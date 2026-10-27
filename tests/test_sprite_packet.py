"""Native sprite row (span count, packet spans, span bounds, walk setup):
original x86 is the independent oracle (RC5: registers, live flags, all RAM
and code/VRAM write addresses at the endpoint reached; poll-free since
irq-plan I9, widened at I10)."""
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

MODULE = 'SWOTL.EXE'
FIRST = (MODULE, 0x4e89)
OFF = 0x4e89 - 0x4d9                    # module offset - IP in CS
ENDPOINTS = (0x4f3c, 0x4fd3, 0x5036, 0x5153)   # resumes 1..4
PREDECESSORS = ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return')
LIMIT = 4000000
PLANTS = {
    'store': ('move.b d3,-1(a0)', 'nop'),
    'carry': ('addx.w d6,d2\n\tmove.w d2,-3(a0)', 'add.w d6,d2\n\tmove.w d2,-3(a0)'),
    'code-window': ('cmp.l #$1000,d7\n\tblt sprite_row_decline', 'nop'),
    'wrap': ('cmp.w #$3dd0,d1\n\tbhi sprite_row_decline', 'nop'),
    'decline': ('sprite_row_decline:\n\tmoveq #0,d7', 'sprite_row_decline:\n\taddq.w #1,a4\n\tmoveq #0,d7'),
    'bounds': ('cmp.w ($7643,a3),d0\n\tbcs.s', 'cmp.w ($7643,a3),d0\n\tbhi.s'),
    'push': ('move.w (-$9b33,a0),-1(a2,d4.w)', 'move.w (-$9b37,a0),-1(a2,d4.w)'),
    'pop': ('move.w -1(a2,d4.w),d3\n\tsubq.w #2,d4', 'subq.w #2,d4'),
    'resume': ('sprite_row_clipped:\n\taddq.l #4,sp\n\tmoveq #3,d7', 'sprite_row_clipped:\n\taddq.l #4,sp\n\tmoveq #4,d7'),
}


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
    return regs['cs'] + 0x1000 <= regs['ds'] <= 0x9000 and regs['cx'] <= 0x3dd0


def word(ram, at, value):
    ram[at:at + 2] = (value & 0xffff).to_bytes(2, 'little')


def synthetic():
    """Every path: tail (CX = 0, [9BD] negative), clipped, EGA, both walk
    setups; CX and AX extremes; the DS window and SI wrap guards."""
    rng = random.Random(447)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    settings = []
    for kind in ('vga', 'vga-near', 'ega', 'clip', 'random'):
        for cx in (1, 2, 17, 255):
            for ax in (0, 1, 0x8001):
                for direction in (1, 0xffff, 0x140):
                    settings.append((kind, cx, ax, direction, {}))
    settings += [('vga', cx, 3, 1, extra) for cx, extra in (
        (0, {}), (0x3dd0, {}), (0x3dd1, {}), (0xffff, {}),
        (1, {'ds': B.LOADSEG + 0x49b + 0xfff}),
        (1, {'ds': B.LOADSEG + 0x49b + 0x1000}),
        (1, {'ds': 0x9000}), (1, {'ds': 0x9001}))]
    settings += [('tail', 5, 3, 1, {}), ('vga', 64, 3, 1, {}), ('vga', 0x150, 3, 1, {}),
                 ('vga', 0x1c0, 9, 1, {}), ('vga', 3, 3, 1, {'sp': 0}), ('vga', 3, 3, 1, {'sp': 1})]
    for index, (kind, cx, ax, direction, extra) in enumerate(settings):
        ram = bytearray(B.X.RAM)
        ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
        regs = dict(ax=ax, bx=0xabcd, cx=cx, dx=0x1234,
                    si=0x5555, di=rng.randrange(65536), sp=0xec00, bp=0xf000,
                    cs=B.LOADSEG + 0x49b, ip=0x4d9,
                    ds=0x5000, ss=0x7000, es=0x6000,
                    flags=0x7202 | (index & 1) * 0x400)
        regs.update(extra)
        for seg in (regs['ds'], regs['es']):
            ram[seg * 16:seg * 16 + 65536] = rng.randbytes(65536)
        for k in range(4):      # the walk's DS and BX pairs (cs:9B32..9B39), distinct
            word(ram, regs['cs'] * 16 + 0x9b32 + 2 * k, 0x1111 * (k + 1))
        ds = regs['ds'] * 16
        word(ram, ds + 0x86d, direction)
        if kind != 'random':
            word(ram, ds + 0x9bd, 0x7fff if kind != 'tail' else 0x8000)
            word(ram, ds + 0x9bb, 0)
            word(ram, ds + 0x87a, rng.randrange(0x100))
            for k in range(0x200):          # small span ends: DX stays in bounds
                ram[ds + 0x10a6 + k] = 0
            word(ram, ds + 0x2581, 0 if kind == 'ega' else 1)
            word(ram, ds + 0x25c8, 1 if kind == 'vga-near' else 0)
            word(ram, ds + 0x25c0, rng.randrange(0x200))
            if kind == 'clip':
                word(ram, ds + 0x9bb, 0x7000)
        yield f'synthetic-{index}-{kind}-cx{cx:x}', bytes(ram), regs


def captured():
    for directory in sorted((ROOT / 'tmp/pc-runs').glob('native-I10-sprite-*')):
        for path in sorted((directory / 'trace').glob('snap-entry*')):
            ram, regs = O.load_entry(path)
            yield str(path), ram, regs
            for cx in (0, 1, 0x3dd0):
                yield f'{path}+cx={cx:x}', ram, dict(regs, cx=cx)


@lru_cache(maxsize=1)
def program():
    p = emit.Program()
    assert FIRST in p.compute_rows, 'sprite_row row missing from hle.csv'
    assert not (p.live_in[FIRST] | set().union(*(p.live_in[(MODULE, e)] for e in ENDPOINTS))) & set(STATUS)
    return p


def expect(ram, regs):
    cs = regs['cs']
    stops = tuple((cs, e - OFF) for e in ENDPOINTS)
    return O.run(ram, regs, stops[0], limit=LIMIT, returns=stops[1:])


def run(entries=False, plant=None, predecessor='direct'):
    p = program()
    work = ROOT / 'tmp/sprite-packet-differential' / str(os.getpid())
    work.mkdir(parents=True, exist_ok=True)
    implementation = (ROOT / 'src/runtime/compute_sprite.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        if implementation.count(old) != 1:
            raise ValueError(f'missing {plant} plant template')
        implementation = implementation.replace(old, new)
    prefix = {'direct': [], 'jump': ['\tbra entry'],
              'call': ['\tbsr entry', '\tbra native_done'],
              'taken': ['\tcmp.w d0,d0', '\tbeq entry', '\tillegal'],
              'fall': ['\tcmp.w d0,d0', '\tbne native_done'],
              'indirect': ['\tlea entry,a0', '\tjmp (a0)'],
              'return': ['\tpea entry', '\trts']}[predecessor]
    source = [equates(), f'\torg ${B.SNIP:x}', '\tdc.l native_done', *prefix, 'entry:',
              f'\tmove.l #${B.LOADSEG + 0x49b:x},d6',
              '\tjsr rt_hle_sprite_row',
              '\trts' if predecessor == 'call' else '\tbra native_done',
              'native_done:', '\tnop', implementation]
    binary = B.D.assemble('\n'.join(source), work / f'native-{predecessor}-{plant}.bin')
    cases = list(synthetic()) + (list(captured()) if entries else [])
    count = 0
    for name, ram, regs in cases:
        def check(ok, detail):
            if not ok:
                raise SpriteMismatch(count + 1, (name, detail))
        expected = expect(ram, regs) if admitted(regs, ram) else None
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
                at = expected['at'][1] + OFF
                check(m.r('d7') == ENDPOINTS.index(at) + 1, ('resume', m.r('d7'), hex(at)))
                got.update(cs=expected['at'][0], ip=expected['at'][1])
                actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                              writes=writes, ram=m.gread(0, B.X.RAM))
                errors = O.compare(expected, actual, p.live_in[(MODULE, at)], code(p))
                check(not errors, errors)
            count += 1
        finally:
            B.U.uc.uc_close(m.e.h)
    return count


@lru_cache(maxsize=None)
def code(p):
    return O.code_addresses(p, B.LOADSEG)


def generated(entries=False):
    """S4: the declined generated body from the entry to the endpoint reached."""
    p = program()
    work = ROOT / 'tmp/sprite-packet-generated'
    work.mkdir(exist_ok=True)
    stubs = dict(B.STUB_AT)
    for service in sorted({p.hle[n][1] for n in p.compute_rows} - set(stubs)):
        stubs[service] = max(a for n, a in stubs.items() if n != 'rt_irq_pending') + 4
    with patch.dict(B.STUB_AT, stubs):
        binary, addresses = B.program_image(p, work)
    cases = list(synthetic()) + (list(captured()) if entries else [])
    for index, (name, ram, regs) in enumerate(cases):
        expected = expect(ram, regs)
        at = expected['at'][1] + OFF
        m = B.D.M68k(ram, stubs, {p.hle[n][1] for n in p.compute_rows})
        try:
            m.load(binary)
            m.extra_stops = {addresses[emit.label(MODULE, e)]: f'endpoint {e:x}' for e in ENDPOINTS}
            O.watch_native(m)
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label(*FIRST)],
                (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
            if info['err'] or outs or info['irq'] or info['stop'] != f'endpoint {at:x}':
                raise SpriteMismatch(index + 1, (name, info))
            got.update(cs=expected['at'][0], ip=expected['at'][1])
            actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                          writes=writes, ram=m.gread(0, B.X.RAM))
            if errors := O.compare(expected, actual, p.live_in[(MODULE, at)], code(p)):
                raise SpriteMismatch(index + 1, (name, errors))
        finally:
            B.U.uc.uc_close(m.e.h)
    return len(cases)


def paths(entries=False):
    """Every endpoint is reached by some admitted case."""
    reached = {expect(ram, regs)['at'][1] + OFF
               for _, ram, regs in list(synthetic()) + (list(captured()) if entries else [])
               if admitted(regs, ram)}
    assert reached == set(ENDPOINTS), sorted(map(hex, reached))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--entries', action='store_true')
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    ap.add_argument('--generated', action='store_true')
    args = ap.parse_args()
    reporting_controls()
    paths(args.entries)
    if args.generated:
        print('sprite row:', generated(args.entries), 'generated original cases pass', flush=True)
    for predecessor in PREDECESSORS if args.predecessors else ('direct',):
        print('sprite row:', predecessor, run(args.entries, predecessor=predecessor),
              'original/guard cases pass', flush=True)
    if args.sabotage:
        for plant in PLANTS:
            try:
                run(plant=plant)
            except SpriteMismatch as error:
                print('sprite row:', plant, 'caught:', error, flush=True)
            else:
                raise AssertionError(plant + ' escaped')
