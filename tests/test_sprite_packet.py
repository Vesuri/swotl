"""Native sprite packet spans: original x86 is the independent oracle (RC5:
registers, live flags, all RAM and code/VRAM write addresses at the endpoint;
poll-free since irq-plan I9)."""
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
               service='sprite_packet', args='', kind='compute',
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
    if plant == 'decline':
        old = 'sprite_packet_decline:\n\tmoveq #0,d7'
        if old not in implementation: raise ValueError('missing decline plant template')
        implementation = implementation.replace(old, 'sprite_packet_decline:\n\taddq.w #1,a4\n\tmoveq #0,d7')
    prefix = {'direct': [], 'jump': ['\tbra entry'],
              'call': ['\tbsr entry', '\tbra native_done'],
              'taken': ['\tcmp.w d0,d0', '\tbeq entry', '\tillegal'],
              'fall': ['\tcmp.w d0,d0', '\tbne native_done'],
              'indirect': ['\tlea entry,a0', '\tjmp (a0)'],
              'return': ['\tpea entry', '\trts']}[predecessor]
    source = [equates(), f'\torg ${B.SNIP:x}', '\tdc.l native_done', *prefix, 'entry:',
              f'\tmove.l #${B.LOADSEG + 0x49b:x},d6',
              '\tjsr rt_hle_sprite_packet',
              '\trts' if predecessor == 'call' else '\tbra native_done',
              'native_done:', '\tnop', implementation]
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
            O.watch_native(m)
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, fl, fx, mem, outs, writes, info = m.run(B.SNIP + 4,
                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
            check(not info['err'] and not outs and not info['irq'], info)
            check(info['stop'] == 'native_done' and info['a7'] == B.D.STACK - 0x100, info)
            if expected is None:
                check(m.r('d7') == 0, 'guard accepted')
                check(all(got[k] == v for k, v in regs.items() if k in got), got)
                check(not writes and m.gread(0, B.X.RAM) == ram, 'decline mutated')
                # The harness returns modeled flags; architectural bit 1 is
                # constant and is not a member of FLAGS.
                check(2 | fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS) == regs['flags'], 'decline flags')
            else:
                check(m.r('d7') == 1, 'unexpected decline')
                got.update(cs=expected['at'][0], ip=expected['at'][1])
                actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                              writes=writes, ram=m.gread(0, B.X.RAM))
                errors = O.compare(expected, actual, p.live_in[END], code(p))
                check(not errors, errors)
            count += 1
        finally:
            B.U.uc.uc_close(m.e.h)
    return count


@lru_cache(maxsize=None)
def code(p):
    return O.code_addresses(p, B.LOADSEG)


def next_entry(p, ram, regs):
    """Declined inputs: the original through one iteration, back to the entry
    (the oracle stops before its first instruction, so step that one first)."""
    cs = regs['cs']
    second = 0x51d + p.units[FIRST[0]].insns[FIRST[1]].size
    first = O.run(ram, regs, (cs, second))
    state = dict(first['registers'], cs=cs, ip=second, flags=first['flags'])
    rest = O.run(O.CapturedRAM(bytes(first['ram']), getattr(ram, 'captured_bytes', len(ram))),
                 state, (cs, 0x559), returns=((cs, 0x51d),))
    return dict(rest, writes=first['writes'] | rest['writes'],
                undefined=sorted(set(first['undefined']) | set(rest['undefined'])))


def generated(entries=False):
    """S4: the declined generated body, including guard-edge continuations.

    Unbounded/overlapping declined loops are compared through one original
    iteration back to the entry; admitted inputs run through the endpoint.
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
        expected = (O.run(ram, regs, (regs['cs'], 0x559)) if admitted(regs, ram)
                    else next_entry(p, ram, regs))
        destination = END if expected['at'][1] == 0x559 else FIRST
        m = B.D.M68k(ram, stubs, {p.hle[n][1] for n in p.compute_rows})
        entered = []
        @B.U.CODE_CB
        def boundary(h, address, size, user):
            if address == addresses[emit.label(*FIRST)]:
                if entered and destination == FIRST:
                    m.stop = 'next_entry'
                    B.U.uc.uc_emu_stop(h)
                entered.append(address)
        try:
            m.load(binary)
            m.extra_stops = {addresses[emit.label(*END)]: 'endpoint'}
            m.e.hook(B.U.HOOK_CODE, boundary)
            O.watch_native(m)
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label(*FIRST)],
                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
            want = 'next_entry' if destination == FIRST else 'endpoint'
            if info['err'] or outs or info['irq'] or info['stop'] != want:
                raise SpriteMismatch(index + 1, (name, info))
            got.update(cs=expected['at'][0], ip=expected['at'][1])
            actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                          writes=writes, ram=m.gread(0, B.X.RAM))
            if errors := O.compare(expected, actual, p.live_in[destination], code(p)):
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
    if args.sabotage:
        for plant in ('store', 'wrap', 'carry', 'code-window', 'decline'):
            try:
                run(plant=plant)
            except SpriteMismatch as error:
                print('sprite packet:', plant, 'caught:', error, flush=True)
            else:
                raise AssertionError(plant + ' escaped')
