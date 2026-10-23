"""Exact native polling: admission controls, independent of any native routine."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_compute_polls import graph, base, text_after
from translator import check, compute, emit, gen, image
from translator.decode import decode
from translator.lower import LowerError


def admission():
    for variant in ('normal', 'shared', 'diagnostic', 'wait'):
        p, n, insns = graph()
        if variant == 'shared':
            p.dispatch.add(n['a1'])
        if variant == 'diagnostic':
            p.diagnostic_hooks[n['a1']] = 7
        if variant == 'wait':
            insns[n['a1']] = decode(bytes.fromhex('833e100000'), 5)
        before = p.loop_heads.copy()
        row = compute.validate_exact(p, n['a0'], n['a6'])
        assert not row.removed, 'exact contract removed a poll'
        assert row.sync == tuple(sorted(before)), 'missing native poll metadata'
        assert p.loop_heads == before, 'admission mutated original poll set'
        assert row.returns == (n['a6'],)
    for defect in ('callee-poll', 'interior-diagnostic', 'rep-poll', 'unresolved',
                   'nested', 'effect', 'endpoint-unreachable'):
        p, n, insns = graph()
        endpoint = defect == 'endpoint-unreachable'
        if defect == 'callee-poll': p.loop_heads.add(n['c0'])
        if defect == 'interior-diagnostic': p.diagnostic_hooks[n['a2']] = 8
        if defect == 'rep-poll': insns[n['a1']] = decode(bytes.fromhex('f3a4'), 5)
        if defect == 'unresolved': p.succ[n['a2']] = ['unknown']
        if defect == 'nested': p.hle[n['a4']] = (n['a6'], 'nested')
        if defect == 'effect': insns[n['a4']] = decode(b'\xee', 20)
        if endpoint:
            insns[n['a6']] = decode(b'\x40', 60)
            p.succ[n['a5']] = [n['a4']]
        try:
            compute.validate_exact(p, n['a0'], n['a6'], endpoint=endpoint)
        except LowerError:
            pass
        else:
            raise AssertionError(f'{defect} admitted')


def emission():
    original = image.rows
    parent = base()
    root, end = ('SWOTL.EXE', 0x4ecd), ('SWOTL.EXE', 0x4f09)
    row = dict(module='SWOTL.EXE', first='0x4ECD', last='0x4F07',
               service='exact_poll_test', args='', kind='compute',
               reason='exact poll protocol test', oracle=__file__,
               resume='continue', polls='exact')
    with patch.object(image, 'rows', lambda name: original(name) +
                      ([row] if name == 'hle.csv' else [])):
        p = emit.Program(units=parent.units)
    assert p.loop_heads == parent.loop_heads, 'exact row changed the poll set'
    assert p.compute_bodies[root].sync == (root,)
    assert not p.compute_bodies[root].removed
    lines, _ = p.module_text(root[0])
    lab = emit.label(*root)
    first = text_after(lines, lab, 7)
    assert first[:3] == emit.poll(lab), 'callback precedes original entry poll'
    assert any('jsr rt_hle_exact_poll_test' in s for s in first)
    assert f'\tjmp {lab}_np' in lines, 'pending handoff must resume after the poll'
    tail = text_after(lines, lab + '_native_irq', 6)
    unit = p.units[root[0]]
    assert tail[:2] == [f'\tmove.l #{emit.hx(unit.ip_of(root[1]))},d7',
                       f'\tmove.l #({emit.cs_expr(unit.cs[root[1]])})<<16,d6']
    assert '\tjsr rt_irq' in tail and '\trts' in tail
    assert '\tmoveq #2,d7' in tail, 'handoff result must identify after-poll resume'
    assert end not in p.loop_heads, 'added an endpoint poll'


def aliases():
    good = dict(R_00010=10, R_00010_np=12, R_00010_native_irq=20,
                R_00010_native_poll=30, R_00010_native_np=32)
    assert compute.poll_aliases(good) == {'R_00010': (30, 32)}
    assert compute.poll_aliases({'R_00010': 10}) == {}
    for key in good:
        bad = {k: v for k, v in good.items() if k != key}
        try:
            compute.poll_aliases(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('incomplete alias metadata accepted: ' + key)


def header_audit():
    """The new generated include receives the same integrity check as code."""
    with tempfile.TemporaryDirectory(prefix='native-poll-metadata-') as directory:
        out = Path(directory)
        gen.write(out, 'program.s', gen.PROGRAM, b'; synthetic code\n')
        gen.write(out, 'native_polls.i', gen.PROGRAM, b'; synthetic poll metadata\n')
        assert not check.check_gen(False, out)
        include = out / 'native_polls.i'
        include.write_bytes(include.read_bytes() + b'; planted edit\n')
        errors = check.check_gen(False, out)
        assert any('native_polls.i: body does not match' in e for e in errors), errors


if __name__ == '__main__':
    admission()
    aliases()
    header_audit()
    print('exact native poll admission: 11 controls pass')
    emission()
    print('exact native poll emission: original polls and after-poll handoff pass')
    if '--sabotage' in sys.argv:
        real = compute.validate_exact
        for name, mutate in (
                ('removed poll', lambda r: r._replace(removed=frozenset(r.sync))),
                ('missing poll metadata', lambda r: r._replace(sync=()))):
            def broken(*args, **kwargs):
                return mutate(real(*args, **kwargs))
            with patch.object(compute, 'validate_exact', broken):
                try:
                    admission()
                except AssertionError:
                    print('exact native polls:', name, 'plant caught')
                else:
                    raise AssertionError(name + ' escaped')
        real_stub = emit.native_poll_stub
        def wrong_poll(lab, ip, cs, result, diagnostic=None):
            return real_stub(lab, ip + 1, cs, result, diagnostic)
        with patch.object(emit, 'native_poll_stub', wrong_poll):
            try:
                emission()
            except AssertionError:
                print('exact native polls: wrong interrupt return IP plant caught')
            else:
                raise AssertionError('wrong interrupt return IP escaped')
