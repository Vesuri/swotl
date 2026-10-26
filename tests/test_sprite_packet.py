"""Native sprite packet spans: original x86 is the independent oracle."""
import argparse
from functools import lru_cache
from pathlib import Path
import random
import sys
import os
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from tools import compute_oracle as O
from translator import emit, image
from translator.ir import FLAGS, FLAG_BIT, STATUS
from translator.support import equates
emit.Program.polled_rows = True  # the exact-poll row, dormant in the game until I9 (irq-plan I8)

FIRST, END = ('SWOTL.EXE', 0x4ecd), ('SWOTL.EXE', 0x4f09)
PREDECESSORS = ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return')


class SpriteMismatch(AssertionError):
    def __init__(self, cases, detail):
        super().__init__(detail)
        self.cases = cases


def predecessor_cases():
    program.cache_clear()
    count = 0
    try:
        for predecessor in PREDECESSORS:
            count += run(predecessor=predecessor)
    except SpriteMismatch as error:
        return count + error.cases, [str(error)]
    return count, []


def reporting_controls():
    module = sys.modules[__name__]
    with patch.object(module, 'run', return_value=1):
        assert predecessor_cases() == (7, [])
    with patch.object(module, 'run', side_effect=SpriteMismatch(3, 'wrong state')):
        assert predecessor_cases() == (3, ['wrong state'])
    for error in (AssertionError('harness assertion'), RuntimeError('harness failure')):
        with patch.object(module, 'run', side_effect=error):
            try:
                predecessor_cases()
            except type(error) as caught:
                assert caught is error
            else:
                raise AssertionError('harness failure reported as a caught mismatch')


def admitted(regs, ram):
    n = int.from_bytes(ram[regs['ds'] * 16 + 0x88f:regs['ds'] * 16 + 0x891], 'little')
    return (regs['cs'] + 0x1000 <= regs['ds'] <= 0x9000 and n > 0
            and regs['si'] >= 0x891 and regs['si'] + 4 * n <= 0xffff)


def synthetic():
    rng = random.Random(447)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    settings = [(n, si, di, direction, {})
                for n in (1, 2, 17, 255)
                for si in (0x891, 0x8bd, 0xdd8, 0xfa0, 0x10a0, 0x7ffb)
                for di, direction in ((0, -1), (0xffff, 1))]
    settings += [(n, si, 0x1000, 1, extra) for n, si, extra in (
        (0, 0x8bd, {}), (1, 0x890, {}), (1, 0xfffb, {}),
        (1, 0xfffc, {}), (0xffff, 0x8bd, {}),
        (1, 0x8bd, {'ds': B.LOADSEG + 0x49b + 0xfff}),
        (1, 0x8bd, {'ds': B.LOADSEG + 0x49b + 0x1000}),
        (1, 0x8bd, {'ds': 0x9000}), (1, 0x8bd, {'ds': 0x9001}))]
    for index, (n, si, di, direction, extra) in enumerate(settings):
        ram = bytearray(B.X.RAM)
        ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
        regs = dict(ax=0x8001, bx=0xabcd, cx=0xffee, dx=0xffff,
                    si=si, di=di, sp=0xec00, bp=0xf000,
                    cs=B.LOADSEG + 0x49b, ip=0x51d,
                    ds=0x5000, ss=0x7000, es=0x6000,
                    flags=0x7202 | (index & 1) * 0x400)
        regs.update(extra)
        for seg in (regs['ds'], regs['es']):
            ram[seg * 16:seg * 16 + 65536] = rng.randbytes(65536)
        for off, value in ((0x88f, n), (0x86d, direction & 65535)):
            ram[regs['ds'] * 16 + off:regs['ds'] * 16 + off + 2] = value.to_bytes(2, 'little')
        yield f'synthetic-{index}', bytes(ram), regs


def captured():
    for directory in sorted((ROOT / 'tmp/pc-runs').glob('native-N4-sprite-*')):
        for path in sorted((directory / 'trace').glob('snap-entry*')):
            ram, regs = O.load_entry(path)
            yield str(path), ram, regs


@lru_cache(maxsize=1)
def program():
    original = image.rows
    row = dict(module=FIRST[0], first=hex(FIRST[1]), last='0x4f07',
               service='sprite_packet', args='', kind='compute', polls='exact',
               resume='continue', reason='authorized packet differential', oracle=__file__)
    existing = any(r['module'] == FIRST[0] and int(r['first'], 16) == FIRST[1]
                   for r in original('hle.csv'))
    with patch.object(image, 'rows', lambda name: original(name) +
                      ([row] if name == 'hle.csv' and not existing else [])):
        p = emit.Program()
    assert not (p.live_in[FIRST] | p.live_in[END]) & set(STATUS)
    return p


def run(entries=False, plant=None, predecessor='direct'):
    p = program()
    work = ROOT / 'tmp/sprite-packet-differential' / str(os.getpid())
    work.mkdir(parents=True, exist_ok=True)
    implementation = (ROOT / 'src/runtime/compute_sprite.s').read_text()
    if plant == 'store':
        if 'move.b d3,-1(a0)' not in implementation: raise ValueError('missing store plant template')
        implementation = implementation.replace('move.b d3,-1(a0)', 'nop')
    if plant == 'wrap':
        if 'cmp.l #$ffff,d7\n\tbhi.s sprite_packet_decline' not in implementation: raise ValueError('missing wrap plant template')
        implementation = implementation.replace('cmp.l #$ffff,d7\n\tbhi.s sprite_packet_decline', 'nop')
    if plant == 'carry':
        if 'addx.w d6,d2' not in implementation: raise ValueError('missing carry plant template')
        implementation = implementation.replace('addx.w d6,d2', 'add.w d6,d2')
    if plant == 'code-window':
        old = 'cmp.l d6,d7\n\tbcs sprite_packet_decline'
        if old not in implementation: raise ValueError('missing code-window plant template')
        implementation = implementation.replace(old, 'nop')
    # The entry is already after the original poll. This harness checks the
    # uninterrupted native path; separate protocol tests inject interrupts.
    prefix = {'direct': [], 'jump': ['\tbra entry'],
              'call': ['\tbsr entry', '\tbra native_done'],
              'taken': ['\tcmp.w d0,d0', '\tbeq entry', '\tillegal'],
              'fall': ['\tcmp.w d0,d0', '\tbne native_done'],
              'indirect': ['\tlea entry,a0', '\tjmp (a0)'],
              'return': ['\tpea entry', '\trts']}[predecessor]
    source = [equates(), f'rt_irq equ ${B.STUB_AT["rt_irq"]:x}', p.native_poll_text(),
              f'\torg ${B.SNIP:x}', '\tdc.l native_done', *prefix, 'entry:',
              f'\tmove.l #${B.LOADSEG + 0x49b:x},d6',
              '\tjsr rt_hle_sprite_packet',
              '\trts' if predecessor == 'call' else '\tbra native_done',
              'native_done:', '\tnop', implementation,
              '\n'.join(emit.native_poll_stub(emit.label(*FIRST), 0x51d,
                                              f'${B.LOADSEG + 0x49b:x}', 2))]
    binary = B.D.assemble('\n'.join(source), work / f'native-{predecessor}-{plant}.bin')
    cases = list(synthetic()) + (list(captured()) if entries else [])
    count = 0
    for name, ram, regs in cases:
        def check(ok, detail):
            if not ok:
                raise SpriteMismatch(count + 1, (name, detail))
        expected = O.run(ram, regs, (regs['cs'], 0x559)) if admitted(regs, ram) else None
        m = B.D.M68k(ram, B.STUB_AT)
        try:
            m.e.write(B.SNIP, binary)
            m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'native_done'}
            history = O.watch_native(m)
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, fl, fx, mem, outs, writes, info = m.run(B.SNIP + 4,
                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
            check(not info['err'] and not outs and not info['irq'], info)
            check(info['stop'] == 'native_done' and info['a7'] == B.D.STACK - 0x100, info)
            if expected is None:
                check(m.r('d7') == 0, 'guard accepted')
                check(all(got[k] == v for k, v in regs.items() if k in got), got)
                check(not writes and not history and m.gread(0, B.X.RAM) == ram, 'decline mutated')
                # The harness returns modeled flags; architectural bit 1 is
                # constant and is not a member of FLAGS.
                check(2 | fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS) == regs['flags'], 'decline flags')
            else:
                check(m.r('d7') == 1, 'unexpected decline')
                got.update(cs=expected['at'][0], ip=expected['at'][1])
                actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                              writes=writes, history=history, ram=m.gread(0, B.X.RAM))
                errors = O.compare(expected, actual, p.live_in[END])
                check(not errors, errors)
            count += 1
        finally:
            B.U.uc.uc_close(m.e.h)
    return count


def handoffs():
    """A pending poll abandons cached pointers and rechecks handler state."""
    p = program()
    work = ROOT / 'tmp/sprite-packet-differential' / str(os.getpid())
    work.mkdir(parents=True, exist_ok=True)
    implementation = (ROOT / 'src/runtime/compute_sprite.s').read_text()
    lab = emit.label(*FIRST)
    source = [equates(), f'rt_irq equ ${B.STUB_AT["rt_irq"]:x}', p.native_poll_text(),
              f'\torg ${B.SNIP:x}', f'\tdc.l done,{lab}_native_poll', 'entry:',
              f'\tmove.l #${B.LOADSEG + 0x49b:x},d6', '\tmoveq #0,d7',
              '\tjsr rt_hle_sprite_packet', '\tcmp.l #2,d7', '\tbeq entry',
              'done:', '\tnop', implementation,
              '\n'.join(emit.native_poll_stub(lab, 0x51d, f'${B.LOADSEG + 0x49b:x}', 2))]
    binary = B.D.assemble('\n'.join(source), work / 'handoff.bin')
    done, poll = (int.from_bytes(binary[k:k + 4], 'big') for k in (0, 4))
    _, ram, regs = list(synthetic())[12]  # two elements, first poll after one
    prefix = O.run(ram, regs, (regs['cs'], 0x559), stops=((regs['cs'], 0x51d),))
    assert prefix['at'] == (regs['cs'], 0x51d)
    for mode in ('move-output', 'decline-output', 'decline-segment'):
        changed = dict(prefix['registers'], cs=regs['cs'], ip=0x51d,
                       flags=prefix['flags'], dx=0x1234)
        changed['si'] = 0xdd8 if mode == 'move-output' else 0x890
        if mode == 'decline-segment': changed['ds'] = 0x9001
        if mode == 'move-output':
            expected = O.run(prefix['ram'], changed, (regs['cs'], 0x559))
            expected['history'] = {a: prefix['history'].get(a, []) + expected['history'].get(a, [])
                                   for a in prefix['history'].keys() | expected['history'].keys()}
            expected['writes'] |= prefix['writes']
        else:
            expected = dict(prefix, registers={k: v for k, v in changed.items() if k != 'flags'},
                            flags=changed['flags'])
        m = B.D.M68k(ram, B.STUB_AT)
        m.irq_calls = []
        visits = []
        @B.U.CODE_CB
        def interrupt(h, address, size, user):
            if address == poll:
                visits.append(address)
                m.e.write(B.D.STATE + 8, b'\1')
                m.e.write(B.D.PENDING, b'\1')
            elif address == B.STUB_AT['rt_irq']:
                m.e.reg_write(B.U.M68K['a4'], changed['si'])
                m.e.reg_write(B.U.M68K['d2'], changed['dx'])
                m.e.reg_write(B.U.M68K['a3'], B.D.TOP - changed['ds'] * 16 - 0x7fff)
                m.e.write(B.D.STATE, changed['ds'].to_bytes(2, 'big'))
        try:
            m.e.write(B.SNIP, binary)
            m.extra_stops = {done: 'done'}
            m.e.hook(B.U.HOOK_CODE, interrupt)
            history = O.watch_native(m)
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, fl, fx, mem, outs, writes, info = m.run(B.SNIP + 8,
                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
            assert not info['err'] and not outs and info['stop'] == 'done', (mode, info)
            assert len(visits) == len(m.irq_calls) == 1, (mode, visits, m.irq_calls)
            assert info['a7'] == B.D.STACK - 0x100, (mode, 'stack')
            assert m.r('d7') == (1 if mode == 'move-output' else 0), (mode, 're-entry guard')
            got.update(cs=expected['at'][0], ip=expected['at'][1])
            actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                          writes=writes, history=history, ram=m.gread(0, B.X.RAM))
            assert not (errors := O.compare(expected, actual, p.live_in[END])), (mode, errors)
        finally:
            B.U.uc.uc_close(m.e.h)
    return 3


def generated(entries=False):
    """S4: the declined generated body, including guard-edge continuations.

    Unbounded/overlapping declined loops are compared through one original
    iteration to its next poll; admitted inputs run through the endpoint.
    """
    p = program()
    work = ROOT / 'tmp/sprite-packet-generated'
    work.mkdir(exist_ok=True)
    service = p.hle[FIRST][1]
    stubs = dict(B.STUB_AT)
    if service not in stubs:
        stubs[service] = max(a for n, a in stubs.items() if n != 'rt_irq_pending') + 4
    with patch.dict(B.STUB_AT, stubs):
        binary, addresses = B.program_image(p, work)
    cases = list(synthetic()) + (list(captured()) if entries else [])
    for index, (name, ram, regs) in enumerate(cases):
        stops = () if admitted(regs, ram) else ((regs['cs'], 0x51d),)
        expected = O.run(ram, regs, (regs['cs'], 0x559), stops=stops)
        destination = END if expected['at'][1] == 0x559 else FIRST
        m = B.D.M68k(ram, stubs, {p.hle[n][1] for n in p.compute_rows})
        entered = []
        @B.U.CODE_CB
        def boundary(h, address, size, user):
            if address == addresses[emit.label(*FIRST)]:
                if entered and destination == FIRST:
                    m.stop = 'next_poll'
                    B.U.uc.uc_emu_stop(h)
                entered.append(address)
        try:
            m.load(binary)
            m.extra_stops = {addresses[emit.label(*END)]: 'endpoint'}
            m.e.hook(B.U.HOOK_CODE, boundary)
            history = O.watch_native(m)
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label(*FIRST)],
                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
            want = 'next_poll' if destination == FIRST else 'endpoint'
            if info['err'] or outs or info['irq'] or info['stop'] != want:
                raise SpriteMismatch(index + 1, (name, info))
            got.update(cs=expected['at'][0], ip=expected['at'][1])
            actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                          writes=writes, history=history, ram=m.gread(0, B.X.RAM))
            if errors := O.compare(expected, actual, p.live_in[destination]):
                raise SpriteMismatch(index + 1, (name, errors))
        finally:
            B.U.uc.uc_close(m.e.h)
    return len(cases)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--entries', action='store_true')
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    ap.add_argument('--generated', action='store_true')
    args = ap.parse_args()
    reporting_controls()
    if args.generated:
        print('sprite packet:', generated(args.entries), 'generated original/guard cases pass', flush=True)
    for predecessor in PREDECESSORS if args.predecessors else ('direct',):
        print('sprite packet:', predecessor, run(args.entries, predecessor=predecessor),
              'original/guard cases pass', flush=True)
    print('sprite packet:', handoffs(), 'handler state/re-entry cases pass', flush=True)
    if args.sabotage:
        for plant in ('store', 'wrap', 'carry', 'code-window'):
            try:
                run(plant=plant)
            except SpriteMismatch as error:
                print('sprite packet:', plant, 'caught:', error, flush=True)
            else:
                raise AssertionError(plant + ' escaped')
