"""Fail-closed compute-row admission; no guest routine is replaced by this test."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translator import compute
from translator.decode import decode
from translator.lower import LowerError
from translator import emit  # noqa: E402


def differential(plant=None):
    """Generated stand-in for a future native body, versus independent x86.

    Both fallback and handled arms run, with direct/jump/call predecessors.
    The stand-in is translator output; no guest routine is hand-ported.
    """
    import json
    import random
    import tempfile
    import m68k_diff as D
    from tools import compute_oracle as O
    from translator.ir import FLAGS, FLAG_BIT, STATUS
    from translator.support import equates, HELPERS

    raw = bytes.fromhex('89c8 01d8 894000 89ec 89fd 8ec2')  # arithmetic, store, SP/BP, ES
    insns, at = [], 0
    while at < len(raw):
        i = decode(raw, 0x100 + at, at)
        insns.append(i)
        at += i.size
    ram = bytearray(D.X.RAM)
    ram[0x20100:0x20100 + len(raw) + 1] = raw + b'\xc3'
    regs = dict(ax=0x12, bx=0x1234, cx=0x5678, dx=0x9abc,
                sp=0x400, bp=0xfffe, si=0x2345, di=0x6789,
                es=0x3000, cs=0x2000, ss=0x4000, ds=0x5000,
                ip=0x100, flags=0x7203)
    code = frozenset(range(0x20100, 0x20100 + len(raw) + 1))
    count = 0
    with tempfile.TemporaryDirectory(prefix='compute-contract-') as scratch:
        work = Path(scratch)
        for mode in ('decline', 'handle', 'stub'):
            handled = mode == 'handle'
            for predecessor in ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return'):
                fallback, _ = D.lower_case(insns, regs['cs'], 'fallback', 0)
                body, _ = D.lower_case(insns, regs['cs'], 'body', 0)
                # These snippets have no cold paths. Replace only the test exit.
                fallback = fallback[:fallback.index('fallback_end:')] + ['\tbra resume']
                body = body[:body.index('body_end:')] + ['\tmove.l #$10000,d7', '\trts']
                callback = body if handled else ['\tmoveq #0,d7', '\trts']
                callback = ['\tcmp.l #$2000,d6', '\tbne T_HALT'] + callback
                if plant == 'lost-register' and handled:
                    callback.insert(-2, '\tmove.w #0,d2')
                elif plant == 'lost-flag' and handled:
                    callback.insert(-2, '\teori.b #1,G_FL+1(a6)')
                elif plant == 'lost-store' and handled:
                    store = '\tmove.w d0,-1(a3,d7.w)'
                    assert store in callback, 'plant must reach the store template'
                    callback.remove(store)
                elif plant in {'vram-store', 'code-store'} and handled:
                    # RC5: a rewrite of a byte's own value leaves RAM unchanged;
                    # only the code/VRAM written-address sets see it.
                    linear = 0xa0000 if plant == 'vram-store' else 0x20100
                    callback[-2:-2] = ['\tmove.l a0,-(sp)', f'\tlea (-${linear:x},a6),a0',
                                       '\tmove.b (a0),(a0)', '\tmove.l (sp)+,a0']
                intro = {'direct': [], 'jump': ['\tbra entry'],
                         'call': ['\tbsr entry', '\tjmp T_END'],
                         'taken': ['\tcmp.w d0,d0', '\tbeq entry', '\tillegal'],
                         'fall': ['\tcmp.w d0,d0', '\tbne T_END'],
                         'indirect': ['\tlea entry,a0', '\tjmp (a0)'],
                         'return': ['\tpea entry', '\trts']}[predecessor]
                service = 'rt_hle_contract_decline' if mode == 'stub' else 'candidate'
                hook = compute.hook(service, 'resume', '$2000')
                if plant == 'wrong-arm': hook[-1] = '\tbeq resume'
                if plant == 'word-result': hook[-2] = '\ttst.w d7'
                stubs = dict(D.STUB_AT, rt_hle_contract_decline=D.STUB + 4 * len(D.STUB_AT))
                source = [equates()] + [f'{n} equ ${a:x}' for n, a in stubs.items()]
                source += [f'rt_irq_pending equ ${D.PENDING:x}']
                source += [f'\torg ${D.CODE:x}'] + intro + ['entry:'] + hook
                source += fallback + ['resume:', '\tjmp T_END', 'candidate:'] + callback + [HELPERS]
                binary = D.assemble('\n'.join(source), work / 'case.bin')
                for offset in (0, 1, 0x7fff, 0xfffe, 0xffff):
                    for carry in (0, 1):
                        regs.update(bx=offset, si=0, cx=0xffff if carry else 1,
                                    flags=0x7202 | carry)
                        (work / 'ram.bin').write_bytes(ram)
                        (work / 'regs.json').write_text(json.dumps(regs))
                        saved_ram, saved_regs = O.load_entry(work)
                        end = (regs['cs'], 0x100 + len(raw))
                        expected = O.run(saved_ram, saved_regs, end)
                        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                        services = set() if plant == 'legacy-fallback' else {'rt_hle_contract_decline'}
                        m = D.M68k(saved_ram, stubs, services)
                        try:
                            m.load(binary)
                            O.watch_native(m)
                            got, fl, fx, mem, outs, writes, info = m.run(D.CODE,
                                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []),
                                random.Random(33), irq=False)
                            assert not outs and not info['err'] and info['stop'] == 'T_END', info
                            got.update(cs=end[0], ip=end[1])
                            actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                                          writes=writes, ram=m.gread(0, D.X.RAM))
                            errors = O.compare(expected, actual, STATUS, code)
                            assert not errors, (handled, predecessor, offset, carry, errors)
                            assert not info['irq']
                            assert info['segbase'] == {a: D.TOP - got[s] * 16 - 0x7fff
                                for s, a in (('es', 'a1'), ('ss', 'a2'), ('ds', 'a3'))}
                            # Native stack balances across the hook; guest SP is independent.
                            depth = 4 if predecessor == 'call' else 0
                            assert info['a7'] == D.STACK - 0x100 - depth
                            count += 1
                        finally:
                            D.U.uc.uc_close(m.e.h)
    return count


def graph():
    nodes = {n: ('SWOTL.EXE', off) for n, off in enumerate((0, 10, 20, 3, 30, 40, 6, 15, 25))}
    insns = {nodes[n]: decode(bytes.fromhex(code), 0) for n, code in
             ((0, '90'), (1, '90'), (2, 'c3'), (3, 'e80000'),
              (4, '90'), (5, 'c3'), (6, 'eb00'), (7, 'cb'), (8, '90'))}
    p = NS(succ={nodes[0]: [nodes[1]], nodes[1]: [nodes[2]],
                 nodes[2]: ['ret'], nodes[3]: [nodes[4]],
                 nodes[4]: [nodes[5]], nodes[5]: ['ret'],
                 nodes[6]: [nodes[0]], nodes[7]: ['ret'], nodes[8]: [nodes[2]]},
           call_site={nodes[3]: nodes[1]}, loop_heads=set(),
           hle={}, diagnostic_hooks={},
           units={'SWOTL.EXE': NS(manager_calls={})},
           node_insn=lambda n: insns.get(n))
    return p, nodes, insns


def check(validate):
    p, n, insns = graph()
    assert validate(p, n[0], n[2])[:2] == ({n[0], n[1]}, (n[2],))
    assert validate(p, n[3], n[2])[:2] == ({n[3], n[4], n[5], n[1]}, (n[2],))
    count = 2
    # RC5: loops are admitted; a root loop head is a resume, a callee's is not
    p, n, insns = graph()
    p.succ[n[1]] = [n[2], n[3]]
    p.loops = {n[3], n[4]}
    p.succ[n[4]] = [n[5], n[4]]
    row = validate(p, n[3], n[2])
    assert row.body == {n[3], n[4], n[5], n[1]} and row.loops == (n[3],)
    count += 1
    # U8: an early return in the range is another resume; a REP off the poll
    # set is compute; the divide-fault edge is a decline edge; `end` widens
    # the range past the return (compiled C's out-of-line loop bodies)
    p, n, insns = graph()
    p.succ[n[1]] = [n[7]]
    assert validate(p, n[3], n[2]).returns == (n[7], n[2])
    p, n, insns = graph()
    insns[n[4]] = decode(bytes.fromhex('f3aa'), 0)
    assert n[4] in validate(p, n[3], n[2]).body
    p, n, insns = graph()
    insns[n[1]] = decode(bytes.fromhex('f7f1'), 0)   # div cx; n[8] is past the range
    p.succ[n[1]], p.int0 = [n[2], n[8]], n[8]
    assert n[8] not in validate(p, n[3], n[2]).body
    p, n, insns = graph()
    p.succ[n[1]] = [n[8]]
    assert n[8] in validate(p, n[3], n[2], 26).body
    count += 4
    for defect in ('sync-access', 'callee-sync', 'unknown', 'recursion', 'early-return-outside',
                   'wrong-resume', 'io', 'interrupt', 'flags-control',
                   'nested-hook', 'manager', 'empty-successors', 'outside-range',
                   'empty-body', 'rep-diagnostic', 'diagnostic', 'ss-write',
                   'fault-edge-not-divide', 'fault-edge-not-int0', 'end-before-resume'):
        p, n, insns = graph()
        first, resume, end = n[3], n[2], None
        # I2: a row meeting the handler footprint (a non-loop sync point) rejects
        if defect == 'sync-access': p.sync = {n[1]: 'access'}
        elif defect == 'callee-sync': p.sync = {n[4]: 'access'}
        elif defect == 'unknown': p.succ[n[4]] = ['unknown']
        elif defect == 'recursion': p.succ[n[4]] = [n[3]]
        elif defect == 'early-return-outside': resume = n[7]   # n[2] lies past it
        elif defect == 'wrong-resume': resume = n[1]
        elif defect == 'io': insns[n[4]] = decode(b'\xee', 0)
        elif defect == 'interrupt': insns[n[4]] = decode(b'\xcd\x21', 0)
        elif defect == 'flags-control': insns[n[4]] = decode(b'\xfb', 0)
        elif defect == 'nested-hook': p.hle[n[4]] = (n[5], 'nested')
        elif defect == 'manager': p.units['SWOTL.EXE'].manager_calls[n[4][1]] = 'OTHER'
        elif defect == 'empty-successors': p.succ[n[4]] = []
        elif defect == 'outside-range': p.succ[n[1]] = [n[8]]
        elif defect == 'empty-body': first = resume
        elif defect == 'rep-diagnostic':   # a REP slice hook (replays) inside the body
            insns[n[4]] = decode(bytes.fromhex('f3aa'), 0)
            p.diagnostic_reps = {n[4]: 1}
        elif defect == 'fault-edge-not-divide': p.succ[n[1]], p.int0 = [n[2], n[8]], n[8]
        elif defect == 'fault-edge-not-int0':
            insns[n[1]] = decode(bytes.fromhex('f7f1'), 0)
            p.succ[n[1]] = [n[2], n[8]]
        elif defect == 'end-before-resume': end = 19
        elif defect == 'diagnostic': p.diagnostic_hooks[n[4]] = 1
        elif defect == 'ss-write': insns[n[4]] = decode(bytes.fromhex('8ed0'), 0)
        try:
            validate(p, first, resume, end)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'{defect} admitted')
    return count


def emission(plant=False, missing_resume=False, kept_loop=False):
    """A temporary row in memory checks real Program integration, never hle.csv."""
    from unittest.mock import patch
    from translator import emit, image
    p = emit.Program()
    first = ('SWOTL.EXE', 0xb52d)
    rets, escapes = p.reach(first, {})
    assert len(rets) == 1 and not escapes
    resume = next(iter(rets))
    u = p.units[first[0]]
    last = next(o for o, i in u.insns.items() if o + i.size == resume[1])
    original = image.rows
    row = dict(module=first[0], first=hex(first[1]), last=hex(last),
               service='contract_test_only', kind='compute', args='',
               reason='test admission/emission only; no replacement',
               oracle='tests/test_compute_contract.py')

    # A second independent temporary row makes coexistence a positive control,
    # even when no other production compute row is enabled.
    other = ('SWOTL.EXE', 0xb8a1)
    other_rets, other_escapes = p.reach(other, {})
    assert len(other_rets) == 1 and not other_escapes
    other_resume = next(iter(other_rets))
    other_last = next(o for o, i in u.insns.items() if o + i.size == other_resume[1])
    other_row = dict(row, first=hex(other[1]), last=hex(other_last),
                     service='contract_test_other')
    # RC5: a row with loops (BB70, R39's former sync sites) is poll-free; its
    # loop heads leave the sync set and are resumes after the return.
    loop_root = ('SWOTL.EXE', 0xbb70)
    loop_heads = tuple(('SWOTL.EXE', o) for o in
                       (0xbbac, 0xbbb3, 0xbc55, 0xbc73, 0xbcc4, 0xbd14, 0xbd44))
    loop_row = dict(row, first='0xBB70', last='0xBD66', service='contract_test_loops')
    def rows(name):
        # the I10 classify row is replaced by the test's own BB70 row
        kept = [r for r in original(name) if not (name == 'hle.csv' and r['first'] == '0xBB70')]
        return kept + ([row, other_row, loop_row] if name == 'hle.csv' else [])

    real = compute.validate
    def validate(prog, n, *args, **kwargs):
        got = real(prog, n, *args, **kwargs)
        return got._replace(body=got.body - set(got.loops)) if kept_loop and n == loop_root else got
    with patch.object(image, 'rows', rows), patch.object(compute, 'validate', validate):
        candidate = emit.Program(units=p.units)
        if missing_resume:
            candidate.compute_resumes[loop_root].pop()
        lines, _ = candidate.module_text(first[0])
    if plant:
        candidate.compute_rows.remove(other)
    assert candidate.compute_rows == p.compute_rows | {first, other, loop_root}
    for existing in p.compute_rows - {first, other, loop_root}:
        assert candidate.hle[existing] == p.hle[existing]
        assert existing in candidate.leaders
        assert candidate.compute_resumes.get(existing) == p.compute_resumes.get(existing)
    for existing in p.compute_bodies.keys() - {first, other, loop_root}:
        assert candidate.compute_bodies[existing] == p.compute_bodies[existing]
    rows_loops = candidate.compute_bodies[loop_root]
    assert rows_loops.loops == loop_heads and rows_loops.returns == (('SWOTL.EXE', 0xbd67),)
    # production holds the I10 classify row: its loop heads are loops, out of the sync set
    assert set(loop_heads) <= p.loops and not set(loop_heads) & p.loop_heads, 'control: BB70 loop heads'
    assert not set(loop_heads) & candidate.loop_heads, 'body loop head kept in the sync set'
    assert candidate.loop_heads == p.loop_heads - rows_loops.body, 'sync set changed elsewhere'
    targets = [('SWOTL.EXE', 0xbd67), *loop_heads]
    assert set(targets) <= candidate.leaders
    dispatch = compute.resume_dispatch(f'{emit.label(*loop_root)}_cx',
        [emit.label(*t) for t in targets], emit.hx(u.ip_of(loop_root[1])))
    start = lines.index(dispatch[0])
    assert lines[start:start + len(dispatch)] == dispatch, 'resume dispatch'
    loop_hook = compute.hook('rt_hle_contract_test_loops', dispatch[0][:-1],
                             emit.cs_expr(u.cs[loop_root[1]]))
    loop_start = lines.index('\tjsr rt_hle_contract_test_loops') - 1
    assert lines[loop_start:loop_start + len(loop_hook)] == loop_hook
    assert other in candidate.leaders and other_resume in candidate.leaders
    assert candidate.compute_bodies[other] == compute.validate(p, other, other_resume)
    other_hook = compute.hook('rt_hle_contract_test_other', emit.label(*other_resume),
                              emit.cs_expr(u.cs[other[1]]))
    other_start = lines.index('\tjsr rt_hle_contract_test_other') - 1
    assert lines[other_start:other_start + len(other_hook)] == other_hook
    assert first in candidate.leaders and resume in candidate.leaders
    assert candidate.compute_bodies[first] == compute.validate(p, first, resume)
    assert first not in candidate.compute_resumes, 'one return keeps the plain hook'
    hook = compute.hook('rt_hle_contract_test_only', emit.label(*resume), emit.cs_expr(u.cs[first[1]]))
    start = lines.index('\tjsr rt_hle_contract_test_only') - 1
    assert lines[start:start + len(hook)] == hook
    assert any(line.startswith(emit.label(*resume) + ':') for line in lines)
    return 11


def captured_memory():
    """Original and native reads/writes must not invent bytes past a snapshot."""
    import random
    import m68k_diff as D
    from tools import compute_oracle as O
    from translator.ir import FLAG_BIT, FLAGS
    from translator.support import HELPERS, equates
    import tempfile
    count = 0
    with tempfile.TemporaryDirectory(prefix='compute-bounds-') as d:
        root = Path(d)
        for op in ('8b07', '8907'):  # MOV AX,[BX], MOV [BX],AX
            code = bytes.fromhex(op)
            insn = decode(code, 0x100)
            body, _ = D.lower_case([insn], 0x2000, 'bounds', 0x102)
            source = [equates()] + [f'{n} equ ${a:x}' for n, a in D.STUB_AT.items()]
            source += [f'rt_irq_pending equ ${D.PENDING:x}', f'\torg ${D.CODE:x}'] + body + [HELPERS]
            binary = D.assemble('\n'.join(source), root / 'bounds.bin')
            for offset, valid in ((0x0e, True), (0x0f, False), (0x10, False)):
                ram = bytearray(0x100000)
                ram[0x20100:0x20102] = code
                ram[-2:] = b'\x34\x12'
                regs = dict(ax=0xabcd, bx=offset, cx=0, dx=0, sp=0x100, bp=0, si=0, di=0,
                            cs=0x2000, ip=0x100, ss=0x7000, ds=0xffff, es=0x7000, flags=0x202)
                (root / 'ram.bin').write_bytes(ram)
                (root / 'regs.txt').write_text(' '.join(f'{k}={v:04x}' for k, v in regs.items()))
                saved, regs = O.load_entry(root)
                assert saved.captured_bytes == 0x100000 and len(saved) == D.X.RAM
                try:
                    expected = O.run(saved, regs, (0x2000, 0x102))
                except ValueError as e:
                    assert not valid and 'outside captured memory' in str(e), str(e)
                else:
                    assert valid, 'original accepted uncaptured memory'
                m = D.M68k(saved)
                try:
                    m.load(binary)
                    O.watch_native(m)
                    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                    got, fl, fx, mem, outs, writes, info = m.run(D.CODE,
                        (regs, flags, 0, regs['ip'], []), random.Random(33), irq=False)
                    want = 'T_END' if valid else 'compute_uncaptured_memory'
                    assert info['stop'] == want, info
                    if valid:
                        assert not info['err'] and not outs
                        assert info['d7'] == 0x102
                        got.update(cs=regs['cs'], ip=info['d7'])
                        actual = dict(registers=got,
                            flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                            writes=writes, ram=m.gread(0, D.X.RAM))
                        assert not O.compare(expected, actual, FLAGS)
                        if op == '8b07':
                            assert got['ax'] == 0x1234
                        else:
                            assert actual['ram'][0xffffe:0x100000] == b'\xcd\xab'
                finally:
                    D.U.uc.uc_close(m.e.h)
                count += 2
    return count


def main():
    print('compute contract:', check(compute.validate), 'controls pass')
    print('compute differential:', differential(), 'recorded-state controls pass')
    print('compute emission:', emission(), 'controls pass')
    print('captured memory:', captured_memory(), 'controls pass')
    if '--sabotage' in sys.argv:
        try:
            emission(plant=True)
        except AssertionError:
            print('compute emission: lost independent row caught')
        else:
            raise AssertionError('lost independent compute row escaped')
        try:
            emission(missing_resume=True)
        except AssertionError:
            print('compute emission: lost loop-head resume caught')
        else:
            raise AssertionError('lost loop-head resume escaped')
        try:
            emission(kept_loop=True)
        except AssertionError:
            print('compute emission: body loop head kept in the sync set caught')
        else:
            raise AssertionError('kept body loop head escaped')
        original = compute.forbidden
        compute.forbidden = lambda p, n: False
        try:
            check(compute.validate)
        except AssertionError:
            print('compute contract: removed sync/effect admission guard caught')
        else:
            raise AssertionError('missing admission guard escaped')
        finally:
            compute.forbidden = original
        for plant in ('wrong-arm', 'word-result', 'lost-register', 'lost-store', 'vram-store',
                      'code-store', 'lost-flag', 'legacy-fallback'):
            try:
                differential(plant)
            except AssertionError:
                print(f'compute differential: {plant} plant caught')
            else:
                raise AssertionError(f'{plant} escaped')
        from tools import compute_oracle as O
        saved = O.memory_known
        O.memory_known = lambda *args: True
        try:
            captured_memory()
        except AssertionError:
            print('captured memory: uncaptured-byte admission plant caught')
        else:
            raise AssertionError('uncaptured-byte admission escaped')
        finally:
            O.memory_known = saved


if __name__ == '__main__':
    main()
