"""109D6 ground-object vertex loops (irq-plan I10): original x86 is the oracle.

Each captured state enters at 10C08. The transform (B52D) and projection
(D5A6) calls, with their 9C20h writes, are continuation exits and run as
original x86 to the row's next hook, the re-entry after POP ES (10CE4, 10F21;
d7 = 1 + k). From each hook the native and the generated arm run to the next
exit or endpoint (10F62, 10F6A, 11131) and are compared with the original
there (RC5: registers, live flags, all RAM, code/VRAM write sets). Variants
move the object origin so that some or all vertices fall behind the eye
(the clipped path and the skip) and mark vertices as midpoints of earlier ones; the guards'
declines are checked separately."""
from pathlib import Path
import argparse
import random
import os
import re
import sys
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from tools import compute_oracle as O
from translator import emit
from translator.support import equates
from translator.ir import FLAGS, FLAG_BIT
from test_rasterize import run_to, captured_ram, actual_state

CS_OFF = 0x109d0
FIRST = 0x10c08
EXITS = (0x10cd1, 0x10f0e)
ENDPOINTS = (0x10f62, 0x10f6a, 0x11131)
ENTRIES = (0x10ce4, 0x10f21)     # hle.csv entries
INDEX = {FIRST: 0} | {a: k + 1 for k, a in enumerate(ENTRIES)}
STOPS = tuple(sorted((*EXITS, *ENDPOINTS)))
RESUME = {a: k + 1 for k, a in enumerate(STOPS)}
LOOPS = (0x10c1d, 0x10df8)
SOURCE = ROOT/'src/runtime/compute_ground.s'


class GroundMismatch(AssertionError):
    pass


REACHED = set()


def captured():
    directories = sorted((ROOT/'tmp/pc-runs').glob('native-I10-ground-*'))
    assert len(directories) == 3, 'three original-game fixtures required'
    for directory in directories:
        paths = sorted((directory/'trace').glob('snap-entry*'))
        assert len(paths) == 3, directory
        for path in paths:
            ram, regs = O.load_entry(path)
            yield f'{directory.name[18:]}/{path.name}', ram, regs


def word(ram, at):
    return int.from_bytes(ram[at:at+2], 'little')


def put(data, at, value):
    data[at:at+2] = (value & 0xffff).to_bytes(2, 'little')


def moved(ram, regs, origin, shift):
    """The object origin's long at DS:origin (C380h X, C384h Y) moved by `shift`."""
    ds = regs['ds']*16
    value = (word(ram, ds+origin) | word(ram, ds+origin+2) << 16) + shift
    data = bytearray(ram)
    put(data, ds+origin, value)
    put(data, ds+origin+2, value >> 16)
    return captured_ram(data, ram)


def midpoints(ram, regs):
    """Vertices after the first two in index order become midpoints (8000h)
    of the first two: the transform and projection midpoint paths."""
    es, di, bp = regs['es']*16, regs['di'], regs['bp']
    table = word(ram, regs['ss']*16 + ((bp - 4) & 0xffff))
    n = ram[regs['ss']*16 + ((bp - 6) & 0xffff)]
    order = [ram[es + ((di + 3 + i) & 0xffff)] for i in range(n)]
    data = bytearray(ram)
    for v in order[2:]:
        at = es + ((table + 6*v) & 0xffff)
        put(data, at, 0x8000)
        put(data, at+2, order[0])
        put(data, at+4, order[1])
    return captured_ram(data, ram)


def table_wrap(ram, regs):
    """The vertex table ([BP-4]) moved so that the first-listed vertex's record
    lies at ES:FFFEh (its words at FFFEh, 0, 2): the ES word-arithmetic path."""
    es, di, ss, bp = regs['es']*16, regs['di'], regs['ss']*16, regs['bp']
    table = word(ram, ss + ((bp - 4) & 0xffff))
    first = ram[es + ((di + 3) & 0xffff)]
    moved = (0xfffe - 6*first) & 0xffff
    data = bytearray(ram)
    for k in range(6*256):
        data[es + ((moved + k) & 0xffff)] = ram[es + ((table + k) & 0xffff)]
    put(data, ss + ((bp - 4) & 0xffff), moved)
    return captured_ram(data, ram)


# table offsets ([BP-0Ch]) patched in at the 10F21 re-entry: from 8000h the
# DS table words take the word-arithmetic path (FFFCh wraps)
TABLE_AT_10F21 = {'+table-8000': 0x8000, '+table-fffc': 0xfffc}


def variants(entries):
    entries = list(entries)
    yield from entries
    for name, ram, regs in entries[::2]:
        yield name+'+mid', midpoints(ram, regs), regs
    for name, ram, regs in entries[::3]:
        yield name+'+wrap', table_wrap(ram, regs), regs
        for suffix in TABLE_AT_10F21:
            yield name+suffix, ram, regs
    # Y -100000h: every vertex behind (11131); X +40000h or Y -40000h: some
    # behind on c13 (the clipped path 10F6A)
    for name, ram, regs in entries[::3]:
        yield name+'+behind', moved(ram, regs, 0xc384, -0x100000), regs
        yield name+'+clip-x', moved(ram, regs, 0xc380, 0x40000), regs
        yield name+'+clip-y', moved(ram, regs, 0xc384, -0x40000), regs


@lru_cache(maxsize=1)
def program():
    return emit.Program()


@lru_cache(maxsize=None)
def generated_image():
    work = ROOT/f'tmp/ground-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.program_image(program(), work)


PLANTS = {'shift': ('\tasl.l #6,d6\n\tadd.l ($7ffe-$c386,a3),d6\n', '\tasl.l #5,d6\n\tadd.l ($7ffe-$c386,a3),d6\n'),
          'behind': ('\tmove.b #1,($60,a0,d7.w)\n\ttst.w d0\n', '\tmove.b #1,($60,a0,d7.w)\n\ttst.w d1\n'),
          'wrap-shift': ('\tasl.l #6,d0\n\tadd.l ($7ffe-$c386,a3),d0\n', '\tasl.l #5,d0\n\tadd.l ($7ffe-$c386,a3),d0\n'),
          'slow-table': ('\tmove.w ($7ffe-$22e2,a3),d0\n', '\tmove.w ($7ffe-$22e4,a3),d0\n'),
          'mid': ('\tGV_MID $fe92,0,1\n', '\tGV_MID $fe92,0,0\n'),
          'proj': ('\tGV_MID $fda2,0,0\t', '\tGV_MID $fda2,0,1\t'),
          'table': ('\tmove.l ($7ffe-$22e4,a3),d0\n', '\tmove.l ($7ffe-$22e0,a3),d0\n'),
          'push': ('\tmove.l d6,-7(a2,d4.w)\n', '\tmove.l d6,-5(a2,d4.w)\n'),
          'entry': ('\tsubq.w #1,d7\n\tbne.s ground_other_entry\n', '\tsubq.w #1,d7\n\tbeq.s ground_other_entry\n'),
          'cx': ('\tmove.w d3,d1\t\t\t; CX = B3\n', '\n'),
          'seg': ('\tcmp.w #$9000,d7\n', '\tcmp.w #$ffff,d7\n'),
          'frame': ('\tcmp.w #$7fff-$c600,d5\n', '\tcmp.w #$7fff-$0000,d5\n'),
          'stack': ('\tcmp.w #$7fff-14,d4\n', '\tcmp.w #$7fff,d4\n'),
          'pair': ('\tcmp.w G_SS(a6),d7\n\tbne.s .no\n', '\tcmp.w G_SS(a6),d7\n\tnop\n'),
          'index': ('\tcmp.w #$3fc,d6\n', '\tcmp.w #$ffff,d6\n')}


@lru_cache(maxsize=None)
def native_image(plant=None):
    source = SOURCE.read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    # d7 = the entry index (moveq in the hook), patched at SNIP+4 per run
    text = [equates(), f'org ${B.SNIP:x}', 'dc.l done,0', 'entry:',
            f'move.l ${B.SNIP+4:x},d7', f'move.l #${B.LOADSEG+0x109d:x},d6',
            'jsr rt_hle_ground_vertices', 'bra done', 'done:', 'nop', source]
    work = ROOT/f'tmp/ground-native-{os.getpid()}'
    work.mkdir(exist_ok=True)
    text = [('\t'+line if '\n' not in line and not line.endswith(':')
             and ' equ ' not in line and not line.startswith('\t') else line) for line in text]
    return B.D.assemble('\n'.join(text), work/f'{plant}.bin')


def native_run(binary, ram, regs, at, index):
    m = B.D.M68k(ram, B.STUB_AT)
    try:
        m.e.write(B.SNIP, binary[:4] + index.to_bytes(4, 'big') + binary[8:])
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(43), irq=False)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100:
            raise GroundMismatch(('native run', info))
        return actual_state(m, got, fl, fx, writes, at), m.r('d7')
    finally:
        B.U.uc.uc_close(m.e.h)


def generated_run(ram, regs, start):
    binary, addresses = generated_image()
    p = program()
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        # 109D6 runs in its BP-guarded copy (R6): stop at either copy
        m.extra_stops = {addresses[f('SWOTL.EXE', a)]: f'stop-{a:x}' for a in STOPS
                         for f in (emit.label, emit.copy_label) if f('SWOTL.EXE', a) in addresses}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label('SWOTL.EXE', start)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(43), irq=False)
        if info['err'] or outs or info['irq'] or not (info['stop'] or '').startswith('stop-'):
            raise GroundMismatch(('generated run', info))
        stop = int(info['stop'][5:], 16)
        return actual_state(m, got, fl, fx, writes, (regs['cs'], stop-CS_OFF))
    finally:
        B.U.uc.uc_close(m.e.h)


@lru_cache(maxsize=1)
def code():
    return O.code_addresses(program(), B.LOADSEG)


def check(name, expected, actual, stop):
    errors = O.compare(expected, actual, program().live_in['SWOTL.EXE', stop], code())
    if errors:
        raise GroundMismatch((name, hex(stop), errors))


def unchanged(name, ram, regs, actual):
    if actual['writes'] or actual['ram'] != ram or any(
            actual['registers'][k] != v for k, v in regs.items()
            if k in actual['registers'] and k not in ('cs', 'ip')):
        raise GroundMismatch((name, 'decline mutation'))


def chain(name, ram, regs, plant=None, generated=True):
    """Walk one object from 10C08 to an endpoint. Returns the compared hooks."""
    cs = regs['cs']
    hooks = {(cs, a-CS_OFF) for a in (FIRST, *ENTRIES, *ENDPOINTS)}
    stops = tuple((cs, a-CS_OFF) for a in STOPS)
    full = native_image(plant)
    count = 0
    table = next((v for k, v in TABLE_AT_10F21.items() if name.endswith(k)), None)
    while True:
        at = regs['ip'] + CS_OFF
        if at == 0x10f21 and table is not None:
            data = bytearray(ram)
            put(data, regs['ss']*16 + ((regs['bp'] - 0xc) & 0xffff), table)
            ram, table = captured_ram(data, ram), None
        expected = O.run(ram, regs, stops[0], limit=10**6, returns=stops)
        stop = expected['at'][1] + CS_OFF
        if stop not in STOPS:
            raise GroundMismatch((name, 'original left the row without an exit', hex(stop)))
        actual, result = native_run(full, ram, regs, expected['at'], INDEX[at])
        if result != RESUME[stop]:
            raise GroundMismatch((name, 'native', hex(at), hex(stop), result))
        check(f'{name} native {at:x}', expected, actual, stop)
        REACHED.update({stop, at})
        if generated:
            check(f'{name} generated {at:x}', expected, generated_run(ram, regs, at), stop)
        count += 1
        if stop in ENDPOINTS:
            return count
        ram = captured_ram(expected['ram'], ram)
        regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
        regs, ram = run_to(ram, regs, hooks)
        if regs['ip'] + CS_OFF not in INDEX:
            raise GroundMismatch((name, 'exit did not re-enter', hex(regs['ip'] + CS_OFF)))


def decline_cases(plant=None):
    """Guards decline before any mutation: DS, SS (and DS = SS), BP, SP, and
    SI at the re-entries."""
    binary = native_image(plant)
    count = 0
    for name, ram, regs in captured():
        cs = regs['cs']
        cases = [(seg, value, 0) for seg in ('ds', 'ss') for value in (0, cs+0xfff, 0x9001, 0xffff)]
        cases += [('ss', regs['ds'] + 0x10, k) for k in (0, 1, 2)]
        cases += [('bp', value, k) for value in (0x2ff, 0xc5ff, 0xfc01, 0xffff) for k in (0, 1, 2)]
        cases += [('sp', value, k) for value in (0, 0xd) for k in (0, 1, 2)]
        cases += [('si', 0x100, 1), ('si', 0x3fd, 2), ('si', 0xffff, 2)]
        cases += [('ds+ss', value, k) for value in (cs+0xfff, 0x9001) for k in (0, 1, 2)]
        for key, value, index in cases:
            changed = dict(regs, **{k: value & 0xffff for k in key.split('+')})
            actual, result = native_run(binary, ram, changed, (cs, regs['ip']), index)
            if result:
                raise GroundMismatch((key, hex(value), index, 'no decline', result))
            unchanged(f'{key}={value:x}', ram, changed, actual)
            count += 1
        break
    return count


def dispatch_cases():
    p = program()
    row = ('SWOTL.EXE', FIRST)
    want = {r[1]: k + 1 for k, r in enumerate(p.compute_resumes[row])}
    if want != RESUME | {a: len(STOPS) + 1 + k for k, a in enumerate(LOOPS)}:
        raise GroundMismatch(('resume ids', want))
    if tuple(e[1] for e in p.compute_entries[row]) != ENTRIES:
        raise GroundMismatch(('entries', p.compute_entries[row]))
    if any(('SWOTL.EXE', a) in p.loop_heads for a in LOOPS):
        raise GroundMismatch(('loop heads still sync points', LOOPS))
    for a, k in re.findall(r'^RZ_([0-9A-F]{5})\tequ (\d+)$', SOURCE.read_text(), re.M):
        if RESUME.get(int(a, 16)) != int(k):
            raise GroundMismatch(('native resume id', a, k))
    return len(want)


def run_all(plant=None, generated=True):
    total = 0
    for name, ram, regs in variants(captured()):
        total += chain(name, ram, regs, plant, generated)
    want = set(STOPS) | {FIRST, *ENTRIES}
    if not plant and not REACHED >= want:
        raise GroundMismatch(('coverage', sorted(map(hex, want - REACHED))))
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('generated', 'native', 'sabotage'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.native or args.generated:
        print('ground vertices:', run_all(generated=args.generated), 'hooks pass at their exits', flush=True)
        print('ground vertices:', decline_cases(), 'decline cases pass', flush=True)
        print('ground vertices:', dispatch_cases(), 'resume ids match', flush=True)
    if args.sabotage:
        for plant in ('shift', 'behind', 'mid', 'proj', 'table', 'push', 'entry', 'cx', 'wrap-shift', 'slow-table'):
            try:
                run_all(plant, generated=False)
            except GroundMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        for plant in ('seg', 'frame', 'stack', 'pair', 'index'):
            try:
                decline_cases(plant)
            except GroundMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
