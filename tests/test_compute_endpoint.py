"""Approved non-return compute endpoint: admission and generated continuation."""
import sys
import inspect
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_compute_polls import graph, base, text_after
from translator import compute, emit, image
from translator.decode import decode
from translator.lower import LowerError
emit.Program.polled_rows = True  # the exact/U5-poll rows, dormant in the game until I9 (irq-plan I8)


def admission():
    count = 0
    for defect in (None, 'implicit', 'early-return', 'outside', 'unreachable', 'nested', 'shared'):
        p, n, insns = graph()
        insns[n['a6']] = decode(b'\x40', 60)  # continuation remains generated
        if defect == 'early-return': p.succ[n['a2']] = [n['a3'], n['a7']]
        if defect == 'outside': p.succ[n['a2']] = [n['a1'], n['x1']]
        if defect == 'unreachable': p.succ[n['a5']] = [n['a4']]
        if defect == 'nested': p.hle[n['a4']] = (n['a6'], 'nested')
        if defect == 'shared': p.dispatch.add(n['a1'])
        try:
            row = compute.validate_polled(p, n['a0'], n['a6'], endpoint=defect != 'implicit')
        except LowerError:
            assert defect is not None, 'valid endpoint rejected'
        else:
            assert defect is None, (defect, 'accepted')
            assert row.returns == (n['a6'],)
            assert n['a6'] not in row.body
            assert row.removed == {n['a1'], n['a4']}
        count += 1
    p, n, insns = graph()
    try:
        compute.validate_polled(p, n['a0'], n['a6'], endpoint=True)
    except LowerError:
        count += 1
    else:
        raise AssertionError('return-endpoint admitted')
    # User 2026-10-24 (F5): `end` widens a continuation row's range past its
    # endpoint, for a loop body after the endpoint; escaping flow still rejects.
    for end, escape in ((None, False), (70, False), (70, True)):
        p, n, insns = graph()
        insns[n['a6']] = decode(b'\x40', 60)
        after = ('M', 64)
        insns[after] = decode(b'\x40', 64)
        p.succ[n['a5']], p.succ[after] = [n['a4'], after], [n['a6'] if not escape else n['x1']]
        try:
            row = compute.validate_polled(p, n['a0'], n['a6'], end=end, endpoint=True)
        except LowerError:
            assert end is None or escape, 'range extension rejected'
        else:
            assert end is not None and not escape, (end, escape, 'admitted')
            assert after in row.body and row.returns == (n['a6'],)
        count += 1
    return count


def emission():
    original = image.rows
    row = dict(module='SWOTL.EXE', first='0xD5DA', last='0xD5F6',
               service='endpoint_test', kind='compute', args='',
               reason='approved endpoint protocol test, not a native routine',
               oracle='tests/test_compute_endpoint.py', polls='return', resume='continue')
    def rows(name):
        return original(name) + ([row] if name == 'hle.csv' else [])
    with patch.object(image, 'rows', rows):
        p = emit.Program(units=base().units)
    first, end = ('SWOTL.EXE', 0xd5da), ('SWOTL.EXE', 0xd5f8)
    r = p.compute_bodies[first]
    assert r.returns == (end,) and r.removed == {first}
    assert first not in p.loop_heads and end in p.loop_heads
    assert end in p.leaders and end in p.hle_resumes
    assert p.live_in[end] <= p.live_in[first]
    lines, _ = p.module_text('SWOTL.EXE')
    assert text_after(lines, emit.label(*end), len(emit.poll(''))) == emit.poll(emit.label(*end))
    assert not any('R_0D5DA_irq' in line for line in lines)
    assert any('jsr R_0B017' in line for line in lines), 'projection call lost'
    for bad in ({'resume': 'unknown'}, {'polls': ''}, {'kind': 'hook'}):
        invalid = {**row, **bad}
        def invalid_rows(name):
            return original(name) + ([invalid] if name == 'hle.csv' else [])
        with patch.object(image, 'rows', invalid_rows):
            try:
                emit.Program(units=base().units)
            except LowerError as error:
                assert 'continuation' in str(error) or 'resume' in str(error), error
            else:
                raise AssertionError(('invalid endpoint metadata accepted', bad))
    return 10


if __name__ == '__main__':
    print('compute endpoint admission:', admission(), 'controls pass')
    print('compute endpoint emission:', emission(), 'controls pass')
    if '--sabotage' in sys.argv:
        real = compute.validate_polled
        def missing_poll(*args, **kwargs):
            row = real(*args, **kwargs)
            return row._replace(returns=()) if kwargs.get('endpoint') or len(args) == 6 and args[5] else row
        def retained_poll(*args, **kwargs):
            row = real(*args, **kwargs)
            return row._replace(removed=frozenset()) if kwargs.get('endpoint') or len(args) == 6 and args[5] else row
        for name, broken in (('missing endpoint poll', missing_poll),
                             ('retained loop poll', retained_poll)):
            with patch.object(compute, 'validate_polled', broken):
                try:
                    emission()
                except AssertionError:
                    print('compute endpoint:', name, 'plant caught')
                else:
                    raise AssertionError(name + ' plant escaped')
        source = inspect.getsource(real)
        for name, before, after in (
                ('early return admitted', 'if endpoint:\n', 'if False:\n'),
                ('unreachable endpoint admitted', 'if endpoint and not reached_endpoint:', 'if False:')):
            assert before in source
            namespace = dict(vars(compute))
            namespace['wait'] = lambda *args: None
            exec(source.replace(before, after), namespace)
            # Isolate endpoint reachability from the independent pure-wait
            # rejection, so that rejection cannot conceal this missing check.
            with patch.object(compute, 'validate_polled', namespace['validate_polled']), \
                    patch.object(compute, 'wait', lambda *args: None):
                try:
                    admission()
                except AssertionError:
                    print('compute endpoint:', name, 'plant caught')
                else:
                    raise AssertionError(name + ' plant escaped')
