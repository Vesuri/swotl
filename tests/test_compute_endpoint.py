"""Approved non-return compute endpoint: admission and generated continuation."""
import sys
import inspect
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_compute_loops import graph, base, text_after
from translator import compute, emit, image
from translator.decode import decode
from translator.lower import LowerError


def admission():
    count = 0
    for defect in (None, 'implicit', 'early-return', 'outside', 'unreachable', 'nested',
                   'sync-access', 'diagnostic'):
        p, n, insns = graph()
        insns[n['a6']] = decode(b'\x40', 60)  # continuation remains generated
        if defect == 'early-return': p.succ[n['a2']] = [n['a3'], n['a7']]
        if defect == 'outside': p.succ[n['a2']] = [n['a1'], n['x1']]
        if defect == 'unreachable': p.succ[n['a5']] = [n['a4']]
        if defect == 'nested': p.hle[n['a4']] = (n['a6'], 'nested')
        if defect == 'sync-access': p.sync = {n['a2']: 'access'}   # I2: meets the footprint
        if defect == 'diagnostic': p.diagnostic_hooks[n['a2']] = 1
        try:
            row = compute.validate(p, n['a0'], n['a6'], endpoint=defect != 'implicit')
        except LowerError:
            assert defect is not None, 'valid endpoint rejected'
        else:
            assert defect is None, (defect, 'accepted')
            assert row.returns == (n['a6'],)
            assert n['a6'] not in row.body
            assert row.loops == (n['a1'], n['a4'])   # root loop heads: resumes after the endpoint
        count += 1
    # RC5: an internal entry no longer needs a kept poll; the row stays admitted
    p, n, insns = graph()
    insns[n['a6']] = decode(b'\x40', 60)
    p.dispatch.add(n['a1'])
    compute.validate(p, n['a0'], n['a6'], endpoint=True)
    count += 1
    p, n, insns = graph()
    try:
        compute.validate(p, n['a0'], n['a6'], endpoint=True)
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
            row = compute.validate(p, n['a0'], n['a6'], end=end, endpoint=True)
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
               oracle='tests/test_compute_endpoint.py', resume='continue')
    def rows(name):
        return [r for r in original(name) if not (name == 'hle.csv' and r['first'] == row['first'])] + \
            ([row] if name == 'hle.csv' else [])
    with patch.object(image, 'rows', rows):
        p = emit.Program(units=base().units)
    first, end = ('SWOTL.EXE', 0xd5da), ('SWOTL.EXE', 0xd5f8)
    r = p.compute_bodies[first]
    assert r.returns == (end,) and r.loops == (first,)
    # RC5: the body's loop head leaves the sync set; the endpoint gets no poll
    assert first in p.loops and first not in p.loop_heads and end not in p.loop_heads
    assert p.compute_resumes[first] == [end, first], 'resumes: endpoints, then root loop heads'
    assert end in p.leaders and end in p.hle_resumes
    assert p.live_in[end] <= p.live_in[first]
    lines, _ = p.module_text('SWOTL.EXE')
    assert text_after(lines, emit.label(*first), 4)[-1] == '\tbne R_0D5DA_cx'
    assert not any(line.startswith('R_0D5DA_irq') or line.startswith('R_0D5F8_irq') for line in lines)
    assert not any('G_IRQ' in x for x in text_after(lines, emit.label(*end), 3)), 'endpoint poll'
    dispatch = text_after(lines, 'R_0D5DA_cx', 8)
    assert dispatch[2] == '\tjmp R_0D5F8' and dispatch[6] == '\tjmp R_0D5DA', dispatch
    assert any('jsr R_0B017' in line for line in lines), 'projection call lost'
    for bad in ({'resume': 'unknown'}, {'polls': 'return'}, {'kind': 'hook'}):
        invalid = {**row, **bad}
        def invalid_rows(name):
            return original(name) + ([invalid] if name == 'hle.csv' else [])
        with patch.object(image, 'rows', invalid_rows):
            try:
                emit.Program(units=base().units)
            except LowerError as error:
                assert 'continuation' in str(error) or 'resume' in str(error) \
                    or 'polls retired' in str(error), error
            else:
                raise AssertionError(('invalid endpoint metadata accepted', bad))
    return 13


if __name__ == '__main__':
    print('compute endpoint admission:', admission(), 'controls pass')
    print('compute endpoint emission:', emission(), 'controls pass')
    if '--sabotage' in sys.argv:
        real = compute.validate
        def endpoint_row(args, kwargs):
            return kwargs.get('endpoint') or len(args) > 4 and args[4]
        def missing_endpoint(*args, **kwargs):
            row = real(*args, **kwargs)
            return row._replace(returns=()) if endpoint_row(args, kwargs) else row
        def kept_loop_head(*args, **kwargs):
            row = real(*args, **kwargs)
            return row._replace(body=row.body - set(row.loops)) if endpoint_row(args, kwargs) else row
        def no_loop_resume(*args, **kwargs):
            row = real(*args, **kwargs)
            return row._replace(loops=()) if endpoint_row(args, kwargs) else row
        for name, broken in (('missing endpoint resume', missing_endpoint),
                             ('body loop head kept in the sync set', kept_loop_head),
                             ('root loop head not a resume', no_loop_resume)):
            with patch.object(compute, 'validate', broken):
                try:
                    emission()
                except AssertionError:
                    print('compute endpoint:', name, 'plant caught')
                else:
                    raise AssertionError(name + ' plant escaped')
        real_forbidden = compute.forbidden
        with patch.object(compute, 'forbidden',
                          lambda p, n: n in p.diagnostic_hooks or compute.effect(p, n)):
            try:
                admission()
            except AssertionError:
                print('compute endpoint: body sync access admitted plant caught')
            else:
                raise AssertionError('body sync access plant escaped')
        source = inspect.getsource(real)
        for name, before, after in (
                ('early return admitted', 'if endpoint:\n', 'if False:\n'),
                ('unreachable endpoint admitted', 'if endpoint and reached != endpoints:', 'if False:')):
            assert source.count(before) == 1
            namespace = dict(vars(compute))
            exec(source.replace(before, after), namespace)
            with patch.object(compute, 'validate', namespace['validate']):
                try:
                    admission()
                except AssertionError:
                    print('compute endpoint:', name, 'plant caught')
                else:
                    raise AssertionError(name + ' plant escaped')
