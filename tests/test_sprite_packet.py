"""Native sprite row (span count, packet spans, span bounds, walk setup, the
span walk loop): original x86 is the independent oracle (RC5: registers, live
flags, all RAM and code/VRAM/cell write addresses at the endpoint reached;
poll-free since irq-plan I9, widened at I10 and by the user 2026-10-27 to the
walk loop: RET plants through the cell cache's bookkeeping, the generated cell
walk called directly; native-compute "Code writes and the cell walk"). The
cell cache at the endpoint must equal the generated body's for the case."""
import argparse
from functools import lru_cache
from pathlib import Path
import random
import sys
import os
import re
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
ENDPOINTS = (0x4f3c, 0x5036, 0x5153)   # resumes 1..3
HEAD = 0x4fd3                           # the walk loop head: resume 5 (root loop heads 4ECD, 4FD3)
RESUME = {0x4f3c: 1, 0x5036: 2, 0x5153: 3, HEAD: 5}
CELLS = (0x209d, 0x447c)                # the cell walk's IPs (D16), as the native checks DX
WALK = ('smc_walk', 'smc_walk_wb', 'smc_walk_plant', 'smc_walk_cov', 'smc_expose', 'smc_seg_limit')
PREDECESSORS = ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return')
LIMIT = 4000000
PLANTS = {
    'store': ('move.b d3,-1(a0)', 'nop'),
    'carry': ('addx.w d6,d2\n\tmove.w d2,-3(a0)', 'add.w d6,d2\n\tmove.w d2,-3(a0)'),
    'code-window': ('cmp.l #$1000,d7\n\tblt sprite_row_decline', 'nop'),
    'wrap': ('cmp.w #$3dd0,d1\n\tbhi sprite_row_decline', 'nop'),
    'decline': ('sprite_row_decline:\n\tmoveq #0,d7', 'sprite_row_decline:\n\taddq.w #1,a4\n\tmoveq #0,d7'),
    'bounds': ('cmp.w ($7643,a3),d0\n\tbcs', 'cmp.w ($7643,a3),d0\n\tbhi'),
    'push': ('move.w (-$9b33,a0),-1(a2,d4.w)', 'move.w (-$9b37,a0),-1(a2,d4.w)'),
    'pop': ('move.w -1(a2,d4.w),d3\n\tsubq.w #2,d4', 'subq.w #2,d4'),
    'resume': ('sprite_row_clipped:\n\taddq.l #4,sp\n\tmoveq #SR_CLIPPED,d7',
               'sprite_row_clipped:\n\taddq.l #4,sp\n\tmoveq #SR_TAIL,d7'),
    # the walk loop (user 2026-10-27)
    'head': ('cmp.w #$23e0,d7\n\tbcc sprite_span_leave', 'cmp.w #$23e1,d7\n\tbcc sprite_span_leave'),
    'df': ('tst.b G_DF(a6)\n\tbne sprite_span_resume', 'nop'),
    'dx': ('move.w a5,d2\t\t\t; MOV DX,DI', 'nop'),
    'plant': ('move.b #$c3,(a0)', 'nop'),
    'plant-tag': ('move.w d6,smc_walk_plant\nsprite_span_planted:', 'sprite_span_planted:'),
    'restore': ('rol.w #8,d0\n\tmove.b d0,(a0,d7.w)\n\trol.w #8,d0', 'move.b d0,(a0,d7.w)'),
    'restore-tag': ('move.w #-1,smc_walk_plant\nsprite_span_restored:', 'sprite_span_restored:'),
    'bp': ('move.w (sp),d5\t\t\t; MOV BP,DS', 'nop'),
    'push-ds': ('move.w G_DS(a6),-1(a2,d4.w)', 'move.w 2(sp),-1(a2,d4.w)'),
    'ds-base': ('movea.l 4(sp),a3', 'nop'),
    'clip-push': ('move.w (-$9b37,a0),-1(a2,d4.w)\n\tmove.w (-$9b39,a0),d3',
                  'move.w (-$9b33,a0),-1(a2,d4.w)\n\tmove.w (-$9b39,a0),d3'),
    'clip-near': ('tst.w ($5a36,a3)\t\t; [25C8]\n\tbne.s .index', 'tst.w ($5a36,a3)\t\t; [25C8]\n\tbeq.s .index'),
    'tail-pop': ('move.w -1(a2,d4.w),d0\t\t; POP AX, JMP 7A3', 'move.w -3(a2,d4.w),d0\t\t; POP AX, JMP 7A3'),
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


def cells(ram, cs, rng, fill, low=None):
    """The cell walk's bytes (D16 forms): all RET (any span start returns at
    once), or MOV cells on a 4-byte grid with a RET past the last, optionally
    reload cells (BX, DS from CS:9B38/9B36) and, with `low`, one MOV whose store
    rewrites a later cell's operand (the walk's own SMC under a low DS)."""
    base = cs * 16
    if fill == 'ret':
        ram[base + CELLS[0]:base + CELLS[1] + 1] = b'\xc3' * (CELLS[1] + 1 - CELLS[0])
        return [CELLS[0] + k for k in range(0, CELLS[1] - CELLS[0], 37)]
    starts, at = [], CELLS[0]
    while at + 10 <= CELLS[1]:
        starts.append(at)
        if fill == 'reload' and rng.randrange(12) == 0:     # MOV BX,CS:[9B38]; MOV DS,CS:[9B36]
            ram[base + at:base + at + 10] = bytes.fromhex('2e8b1e389b2e8e1e369b')
            at += 10
            continue
        ram[base + at:base + at + 4] = b'\x88\x87' + rng.randrange(0x8000).to_bytes(2, 'little')
        at += 4
    ram[base + at] = 0xc3
    if low is not None:     # cell 5's store (BX 2222h) lands on a later cell's operand
        target = next(a for a in starts if base + a >= low * 16)
        word(ram, base + starts[5] + 2, (base + target + 2 - low * 16 - 0x2222) & 0xffff)
    return starts


@lru_cache(maxsize=1)
def synthetic():
    return tuple(synthetic_cases())


def synthetic_cases():
    """Every path: tail (CX = 0, [9BD] negative), clipped, EGA, both walk
    setups; CX and AX extremes; the DS window and SI wrap guards; the walk loop
    over RET cells, MOV and reload cells, a sprite DS reaching the cells, DF set
    and span starts outside the cells (resume at the loop head)."""
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
    for kind in ('walk', 'walk-near', 'walk-skip', 'walk-reload', 'walk-low', 'walk-outside', 'walk-df'):
        for cx in (1, 2, 9, 40, 200):
            settings.append((kind, cx, 3, 1, {}))
    for index, (kind, cx, ax, direction, extra) in enumerate(settings):
        ram = bytearray(B.X.RAM)
        ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
        regs = dict(ax=ax, bx=0xabcd, cx=cx, dx=0x1234,
                    si=0x5555, di=rng.randrange(65536), sp=0xec00, bp=0xf000,
                    cs=B.LOADSEG + 0x49b, ip=0x4d9,
                    ds=0x5000, ss=0x7000, es=0x6000,
                    flags=0x7202 | (index & 1) * 0x400 * (not kind.startswith('walk'))
                    | 0x400 * (kind == 'walk-df'))
        regs.update(extra)
        for seg in (regs['ds'], regs['es']):
            ram[seg * 16:seg * 16 + 65536] = rng.randbytes(65536)
        low = 0x1000 if kind == 'walk-low' else None
        for k in range(4):      # the walk's DS and BX pairs (cs:9B32..9B39), distinct
            word(ram, regs['cs'] * 16 + 0x9b32 + 2 * k,
                 (low if k % 2 == 0 else 0x2222) if low else 0x1111 * (k + 1))
        walk = kind.startswith('walk')
        fill = {'walk-reload': 'reload', 'walk-outside': 'ret', 'walk-df': 'ret'}.get(
            kind, 'mov' if walk else 'ret')
        starts = cells(ram, regs['cs'], rng, fill, low)
        ds = regs['ds'] * 16
        word(ram, ds + 0x86d, direction)
        if kind != 'random':
            word(ram, ds + 0x9bd, 0x7fff if kind != 'tail' else 0x8000)
            word(ram, ds + 0x9bb, 0)
            word(ram, ds + 0x87a, rng.randrange(0x100))
            for k in range(0x200):          # small span ends: DX stays in bounds
                ram[ds + 0x10a6 + k] = 0
            word(ram, ds + 0x2581, 0 if kind == 'ega' else 1)
            word(ram, ds + 0x25c8, 1 if kind in ('vga-near', 'walk-near')
                 or kind == 'walk-skip' and cx in (2, 40) else 0)
            # walk: the near limit among the packet's span indices, so a clipped
            # span (5005) can switch the DS and BX pair the first span pushed
            word(ram, ds + 0x25c0, rng.randrange(0x20, 0xe0) if walk else rng.randrange(0x200))
            if kind == 'clip':
                word(ram, ds + 0x9bb, 0x7000)
        if walk:    # span ends grow by 0/1 per packet; DI from a table of cell starts
            for k in range(16):
                word(ram, ds + 0x10a6 + 2 * k, k & 1)
            word(ram, ds + 0x8b9, 0x3000)
            word(ram, ds + 0x8ad, 0)
            # AH (0..1Eh, even) equal to [871]: the span is skipped (5005)
            word(ram, ds + 0x871, rng.randrange(0, 0x20, 2) if kind == 'walk-skip'
                 else rng.randrange(0x20, 0x100))
            first = rng.randrange(max(1, len(starts) - 1000))
            for k in range(0x400):      # rising span ends (a few cells), a far one back
                start = starts[min(first + 3 * k + rng.randrange(3), len(starts) - 1)]
                if k % 61 == 30:
                    start = starts[rng.randrange(len(starts))]
                if kind == 'walk-outside' and k % 7 == 3:
                    start = rng.choice((CELLS[0] - 1, CELLS[1] + 1, 0x8000))
                word(ram, ds + 0x3000 + 2 * k, start)
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
    assert not (p.live_in[FIRST] | set().union(*(p.live_in[(MODULE, e)] for e in RESUME))) & set(STATUS)
    assert p.compute_resumes[FIRST] == [(MODULE, e) for e in (*ENDPOINTS, 0x4ecd, HEAD)], \
        p.compute_resumes[FIRST]
    assert p.compute_bodies[FIRST].walks == ((MODULE, 0x4ff7),)
    return p


@lru_cache(maxsize=1)
def cell_bytes():
    return O.cell_addresses(program(), B.LOADSEG)


EXPECTED = {}
CACHE = {}  # the cell cache at the generated body's endpoint, per case


def expected_for(name, ram, regs):
    if name not in EXPECTED:
        EXPECTED[name] = expect(ram, regs)
    return EXPECTED[name]


def expect(ram, regs):
    """The x86 from the entry to an endpoint, or to the walk loop head where the
    native leaves (DF set, DX outside the cells: the generated dispatch). A run
    from the head steps over its first instruction. `visits`: head visits."""
    cs, captured = regs['cs'], getattr(ram, 'captured_bytes', len(ram))
    stops = tuple((cs, e - OFF) for e in ENDPOINTS)
    head, after = (cs, HEAD - OFF), (cs, HEAD + 2 - OFF)
    written, visits = set(), 0
    while True:
        e = O.run(ram, regs, stops[0], limit=LIMIT, returns=stops[1:] + (head,), cells=cell_bytes())
        written |= e['writes']
        ram = O.CapturedRAM(e['ram'], captured)
        if e['at'] != head:
            return dict(e, writes=written, visits=visits)
        visits += 1
        r = e['registers']
        if e['flags'] & 0x400 or not CELLS[0] <= r['di'] <= CELLS[1]:
            return dict(e, writes=written, visits=visits)
        regs = dict(r, cs=cs, ip=HEAD - OFF, flags=e['flags'])
        e = O.run(ram, regs, after, limit=LIMIT, cells=cell_bytes())
        written |= e['writes']
        ram = O.CapturedRAM(e['ram'], captured)
        regs = dict(e['registers'], cs=cs, ip=after[1], flags=e['flags'])


@lru_cache(maxsize=1)
def program_image():
    """The generated program (every compute hook declines) with the walk's labels."""
    p = program()
    work = ROOT / 'tmp/sprite-packet-generated'
    work.mkdir(exist_ok=True)
    stubs = dict(B.STUB_AT)
    for service in sorted({p.hle[n][1] for n in p.compute_rows} - set(stubs)):
        stubs[service] = max(a for n, a in stubs.items() if n != 'rt_irq_pending') + 4
    with patch.dict(B.STUB_AT, stubs):
        binary, addresses = B.program_image(p, work, WALK)
    return binary, addresses, stubs


@lru_cache(maxsize=None)
def native(plant=None, predecessor='direct'):
    binary, addresses, stubs = program_image()
    work = ROOT / 'tmp/sprite-packet-differential' / str(os.getpid())
    work.mkdir(parents=True, exist_ok=True)
    implementation = (ROOT / 'src/runtime/compute_sprite.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        if implementation.count(old) != 1:
            raise ValueError(f'missing {plant} plant template')
        implementation = implementation.replace(old, new)
    implementation = re.sub(r'^\txref .*$', '', implementation, flags=re.M)
    prefix = {'direct': [], 'jump': ['\tbra entry'],
              'call': ['\tbsr entry', '\tbra native_done'],
              'taken': ['\tcmp.w d0,d0', '\tbeq entry', '\tillegal'],
              'fall': ['\tcmp.w d0,d0', '\tbne native_done'],
              'indirect': ['\tlea entry,a0', '\tjmp (a0)'],
              'return': ['\tpea entry', '\trts']}[predecessor]
    source = [equates(), *(f'{n}\tequ\t${a:x}' for n, a in stubs.items() if n not in WALK and n != 'rt_hle_sprite_row'),
              *(f'{n}\tequ\t${addresses[n]:x}' for n in WALK),
              f'\torg ${B.SNIP:x}', '\tdc.l native_done', *prefix, 'entry:',
              f'\tmove.l #${B.LOADSEG + 0x49b:x},d6',
              '\tjsr rt_hle_sprite_row',
              '\trts' if predecessor == 'call' else '\tbra native_done',
              'native_done:', '\tnop', implementation]
    return B.D.assemble('\n'.join(source), work / f'native-{predecessor}-{plant}.bin')


def run(entries=False, plant=None, predecessor='direct'):
    p = program()
    prog, addresses, stubs = program_image()
    binary = native(plant, predecessor)
    cases = list(synthetic()) + (list(captured()) if entries else [])
    count = 0
    for name, ram, regs in cases:
        def check(ok, detail):
            if not ok:
                raise SpriteMismatch(count + 1, (name, detail))
        expected = expected_for(name, ram, regs) if admitted(regs, ram) else None
        m = B.D.M68k(ram, stubs, {p.hle[n][1] for n in p.compute_rows})
        try:
            m.load(prog)
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
                check(m.r('d7') == RESUME[at], ('resume', m.r('d7'), hex(at)))
                got.update(cs=expected['at'][0], ip=expected['at'][1])
                actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                              writes=writes, ram=m.gread(0, B.X.RAM))
                errors = O.compare(expected, actual, p.live_in[(MODULE, at)], code(p))
                check(not errors, errors)
                check(name not in CACHE or cache(m, addresses) == CACHE[name], 'cell cache')
            count += 1
        finally:
            B.U.uc.uc_close(m.e.h)
    return count


def cache(m, addresses):
    """The cell walk's bookkeeping, `_cov` through `_plant`."""
    first = addresses['smc_walk_cov']
    return bytes(m.e.read(first, addresses['smc_walk_plant'] + 2 - first))


@lru_cache(maxsize=None)
def code(p):
    """Decoded instruction bytes and the cells (the plants' addresses)."""
    return O.code_addresses(p, B.LOADSEG) | cell_bytes()


def generated(entries=False):
    """S4: the declined generated body from the entry to the endpoint reached
    (a loop-head leave only at its first visit: the generated code runs on)."""
    p = program()
    binary, addresses, stubs = program_image()
    cases = list(synthetic()) + (list(captured()) if entries else [])
    count = 0
    for index, (name, ram, regs) in enumerate(cases):
        expected = expected_for(name, ram, regs)
        at = expected['at'][1] + OFF
        if at == HEAD and expected['visits'] > 1:
            continue
        m = B.D.M68k(ram, stubs, {p.hle[n][1] for n in p.compute_rows})
        try:
            m.load(binary)
            m.extra_stops = {addresses[emit.label(MODULE, e)]: f'endpoint {e:x}' for e in ENDPOINTS}
            if at == HEAD:
                m.extra_stops[addresses[emit.label(MODULE, HEAD)]] = f'endpoint {HEAD:x}'
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
            CACHE[name] = cache(m, addresses)
            count += 1
        finally:
            B.U.uc.uc_close(m.e.h)
    return count


def paths(entries=False):
    """Every resume is reached by some admitted case, and the walk loop runs
    (two spans or more)."""
    reached, walked = set(), 0
    for name, ram, regs in list(synthetic()) + (list(captured()) if entries else []):
        if admitted(regs, ram):
            e = expected_for(name, ram, regs)
            reached.add(e['at'][1] + OFF)
            walked += e['visits'] > 1
    assert reached == set(RESUME), sorted(map(hex, reached))
    assert walked, "no case walks two spans"


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--entries', action='store_true')
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    ap.add_argument('--generated', action='store_true')
    args = ap.parse_args()
    reporting_controls()
    paths(args.entries)
    if args.generated or args.sabotage:
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
