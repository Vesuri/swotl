"""Approved multiple continuations: proved exits, retained calls and dispatch.

Test-only rows; no native implementation. RC5 (irq-plan I9): poll-free, a
native may also continue at a root loop head.
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_compute_loops import graph, base, text_after
from translator import compute, emit, image
from translator.decode import decode
from translator.lower import LowerError


def admission():
    count = 0
    for defect in (None, 'unreachable', 'duplicate', 'entry', 'return',
                   'missing', 'foreign', 'sync-access', 'implicit', 'callee', 'undeclared'):
        p, n, insns = graph()
        insns[n['a6']] = decode(b'\x40', 60)
        p.succ[n['a2']] = [n['a3'], n['a4']]
        exits = (n['a3'],)  # stop before a generated CALL; its return a4 is an interior entry
        if defect == 'unreachable': p.succ[n['a2']] = [n['a4']]
        if defect == 'duplicate': exits *= 2
        if defect == 'entry': exits = (n['a0'],)
        if defect == 'return': exits = (n['a7'],)
        if defect == 'missing': exits = (('M', 999),)
        if defect == 'foreign': exits = (('OTHER', 10),)
        if defect == 'sync-access': p.sync = {n['a4']: 'access'}   # I2: meets the footprint
        if defect == 'callee':
            exits = (n['c0'],)
        if defect == 'undeclared': p.succ[n['a4']] = [n['x1']]
        try:
            row = compute.validate(p, n['a0'], n['a6'],
                                   endpoint=defect != 'implicit', exits=exits)
        except LowerError:
            assert defect is not None, 'valid multiple exits rejected'
        else:
            assert defect is None, (defect, 'admitted')
            assert row.returns == (n['a3'], n['a6'])
            assert not set(row.returns) & row.body
            assert n['c0'] not in row.body, 'endpoint CALL was executed'
            assert row.loops == (n['a1'], n['a4']) and set(row.loops) <= row.body
        count += 1
    return count


FIRST = ('SWOTL.EXE', 0x135ee)
ENDS = (('SWOTL.EXE', 0x1360a), ('SWOTL.EXE', 0x1360d))


def rows_with(extra=None):
    original = image.rows
    row = dict(module=FIRST[0], first=hex(FIRST[1]), last='0x1360A',
               service='point_transform', kind='compute', args='',
               reason='test-only multiple endpoints', oracle=__file__,
               resume='continue', exits='0x1360A')
    row.update(extra or {})
    return lambda name: original(name) + ([row] if name == 'hle.csv' else [])


def emission():
    with patch.object(image, 'rows', rows_with()):
        p = emit.Program(units=base().units)
    row = p.compute_bodies[FIRST]
    assert row.returns == ENDS and row.loops == (FIRST,)
    assert not set(ENDS) & row.body
    assert p.compute_resumes[FIRST] == [*ENDS, FIRST]
    assert FIRST not in p.loop_heads, 'body loop head kept in the sync set'
    assert set(ENDS) <= p.leaders and not set(ENDS) & p.loop_heads
    assert set.union(*(p.live_in[n] for n in ENDS)) <= p.live_in[FIRST]
    lines, _ = p.module_text(FIRST[0])
    for end in ENDS:
        assert not any('G_IRQ' in x for x in text_after(lines, emit.label(*end), 3)), 'endpoint poll'
    dispatch = compute.resume_dispatch(emit.label(*FIRST)+'_cx',
                                       [emit.label(*n) for n in (*ENDS, FIRST)], '$1e0e')
    at = lines.index(dispatch[0])
    assert lines[at:at+len(dispatch)] == dispatch
    for bad in ({'resume': ''}, {'kind': 'hook'}, {'polls': 'return'},
                {'exits': '0x1360b'}, {'exits': '0x1360d'}, {'exits': 'xyz'}):
        with patch.object(image, 'rows', rows_with(bad)):
            try:
                emit.Program(units=base().units)
            except LowerError:
                pass
            else:
                raise AssertionError(('invalid exits admitted', bad))
    return 9


def track_writes(m, D):
    """Guest addresses the 68k code writes (the double's writes are added by hand)."""
    import uc as U
    written = set()

    @U.MEM_CB
    def write(h, kind, addr, size, value, user):
        if D.GUEST_LO <= addr and addr + size - 1 <= D.TOP:
            written.update(range(D.TOP - addr - size + 1, D.TOP - addr + 1))
        return True

    m.e.hook(U.HOOK_MEM_WRITE, write)
    m.keep = write
    return written


def differential(plant=None, first=FIRST):
    """Original x86 versus generated decline and an oracle-driven protocol double.

    The double verifies dispatch/state transport only, never native arithmetic.
    From FIRST it covers the whole row and resumes at the endpoint reached; from
    135E0 it covers the prefix up to the root loop head 135EE and resumes there
    (RC5), the generated code finishing the row. Plants: 'endpoint' resumes at
    the first endpoint, 'loop' at an endpoint instead of the loop head.
    """
    import random
    import m68k_blocks as B
    from tools import compute_oracle as O
    from translator.ir import FLAGS, FLAG_BIT
    from test_compute_loops import guest_state, put_state
    with patch.object(image, 'rows', rows_with({'first': hex(first[1])})):
        p = emit.Program(units=base().units)
    cache = ROOT / 'tmp/compute-multi-endpoint'
    cache.mkdir(exist_ok=True)
    binary, addresses = B.program_image(p, cache)
    unit = p.units[first[0]]
    ram = bytearray(B.X.RAM)
    raw = B.relocated(image.load()[first[0]])
    ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
    regs = dict(ax=0x1234, bx=0x5678, cx=0x9abc, dx=0xdef0, si=0,
                di=0x4321, sp=0xf000, bp=0x8000, cs=B.LOADSEG+unit.cs[first[1]],
                ip=unit.ip_of(first[1]), ds=0x5000, ss=0x5000, es=0x6000,
                flags=0x7603)
    ends = {(regs['cs'],unit.ip_of(n[1])):n for n in ENDS}
    resumes = p.compute_resumes[first]
    assert resumes == [*ENDS, FIRST], resumes
    code = O.code_addresses(p, B.LOADSEG)
    service = B.STUB_AT['rt_hle_point_transform']
    count = 0
    for selected in (False, True):
        data = bytearray(ram)
        data[0x5691a] = int(selected)
        data[0x5ba22:0x5ba24] = b'\x01\x00'
        data[0x56c64:0x56c66] = b'\x03\x04'
        data[0x59bd6] = 1
        expected = O.run(bytes(data), regs, next(iter(ends)), returns=ends)
        if first != FIRST:
            assert expected['writes'], 'store-bearing entry wrote nothing'
        destination = ends[expected['at']]
        assert destination == ENDS[0 if selected else 1]
        for handled in (False, True):
            m = B.D.M68k(bytes(data), {n:a for n,a in B.STUB_AT.items()
                                     if n != 'rt_hle_point_transform'})
            try:
                m.load(binary)
                m.e.write(service, bytes.fromhex('7e004e75'))
                O.watch_native(m)
                written = track_writes(m, B.D)
                stops = {addresses[emit.label(*n)]:str(n) for n in ENDS}
                m.extra_stops = dict(stops)
                if handled: m.extra_stops[service] = 'double'
                flags = {f:regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                *_, info = m.run(addresses[emit.label(*first)],
                    (regs,flags,regs['flags'] & 0xf000,regs['ip'],[]),
                    random.Random(40),irq=False)
                assert not info['err'] and not m.outs, info
                if handled:
                    assert info['stop'] == 'double', info
                    if first == FIRST:
                        segment, target = expected, destination
                    else:   # the prefix only: the row's loop head is the resume
                        segment = O.run(bytes(data), regs, (regs['cs'], unit.ip_of(FIRST[1])))
                        target = FIRST
                    for address in segment['writes']:
                        m.gwrite(address, segment['ram'][address:address+1])
                    written |= segment['writes']
                    put_state(m,B.D,segment['registers'],segment['flags'])
                    if plant == 'endpoint' or plant == 'loop' and target == FIRST:
                        target = ENDS[0]
                    m.e.reg_write(B.U.M68K['d7'],resumes.index(target)+1)
                    m.extra_stops = stops
                    m.stop = None
                    error = m.e.start(service+2,0xffffffff,4_000_000)
                    assert not error, error
                assert m.stop == str(destination), ('wrong endpoint',m.stop,destination)
                got, word = guest_state(m,B.D)
                got.update(cs=expected['at'][0],ip=expected['at'][1])
                actual = dict(registers=got,flags=word,writes=written,ram=m.gread(0,B.X.RAM))
                errors = O.compare(expected,actual,p.live_in[destination],code)
                assert not errors, ('state at the endpoint', errors)
                count += 1
            finally:
                B.U.uc.uc_close(m.e.h)
    return count


if __name__ == '__main__':
    print('multiple endpoint admission:', admission(), 'controls pass', flush=True)
    print('multiple endpoint emission:', emission(), 'controls pass', flush=True)
    print('multiple endpoint differential:', differential() + differential(first=('SWOTL.EXE', 0x135e0)), 'cases pass', flush=True)
    if '--sabotage' in sys.argv:
        real = compute.validate
        def missing(*args, **kwargs):
            row = real(*args, **kwargs)
            return row._replace(returns=row.returns[-1:]) if kwargs.get('exits') or len(args) > 5 and args[5] else row
        with patch.object(compute,'validate',missing):
            try: emission()
            except AssertionError: print('missing endpoint caught',flush=True)
            else: raise AssertionError('missing endpoint escaped')
        try: differential(plant='endpoint')
        except AssertionError as error:
            assert 'wrong endpoint' in str(error), error
            print('wrong endpoint dispatch caught',flush=True)
        else: raise AssertionError('wrong endpoint escaped')
        try: differential(plant='loop', first=('SWOTL.EXE', 0x135e0))
        except AssertionError as error:
            assert 'wrong endpoint' in str(error) or 'state at the endpoint' in str(error), error
            print('endpoint instead of loop-head resume caught',flush=True)
        else: raise AssertionError('wrong loop-head resume escaped')
