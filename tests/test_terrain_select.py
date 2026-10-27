"""F290 terrain tile and scenery selection (irq-plan I10): original x86 is the oracle.

Each captured call runs from F290. The object calls (F600, 169E:064E) are
continuation exits and run as original x86 to the row's next hook, the
re-entry after the call returns (F414, F470, F5E8; d7 = 1 + k); the two
unreached paths (exits F484, F4C9) run as original x86 to the next hook or
the endpoint F318. From each hook the native and the generated arm run to the
next exit or the endpoint and are compared with the original there (RC5:
registers, live flags, all RAM, code/VRAM write sets). Variants patch one
byte the original reads (an object's type, its table flags, a near map cell)
to reach the paths no fixture takes, an object table offset that carries
into its segment, and the guards' declines."""
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

CS_OFF = 0x49b0
FIRST, ENDPOINT = 0xf290, 0xf318
EXITS = (0xf40f, 0xf46b, 0xf484, 0xf4c9, 0xf5e3)
ENTRIES = (0xf414, 0xf470, 0xf5e8)     # hle.csv entries
INDEX = {FIRST: 0} | {a: k + 1 for k, a in enumerate(ENTRIES)}
STOPS = tuple(sorted((*EXITS, ENDPOINT)))
RESUME = {a: k + 1 for k, a in enumerate(STOPS)}
LOOPS = (0xf2bd, 0xf30c, 0xf339, 0xf359, 0xf3b4, 0xf45e, 0xf460, 0xf476, 0xf47d, 0xf54c, 0xf598)


class TerrainMismatch(AssertionError):
    pass


REACHED = set()


def captured():
    directories = sorted((ROOT/'tmp/pc-runs').glob('native-I10-terrain-*'))
    assert len(directories) == 3, 'three original-game fixtures required'
    for directory in directories:
        paths = sorted((directory/'trace').glob('snap-entry*'))
        assert len(paths) == 3, directory
        for path in paths:
            ram, regs = O.load_entry(path)
            yield f'{directory.name[19:]}/{path.name}', ram, regs


def patched(ram, regs, at, operand, values, hit=1):
    """The linear address of `operand` (segment, offset registers) at the
    hit-th execution of `at` in the original, set to each value in turn."""
    stop = {(regs['cs'], at - CS_OFF)}
    state, memory = regs, ram
    for _ in range(hit):
        state, memory = run_to(memory, state, stop)
    seg, *offset = operand
    linear = state[seg]*16 + (sum(state[r] if isinstance(r, str) else r for r in offset) & 0xffff)
    for value in values:
        changed = bytearray(ram)
        changed[linear] = value
        yield f'+{at:x}={value:x}', captured_ram(changed, ram)


def variants(entries):
    entries = list(entries)
    yield from entries
    name, ram, regs = entries[0]
    # an object type above 7Fh (F4C9), a type whose flags have bit 3 (F484),
    # object cells in the nearest ring (F566, exit F5E3)
    for tag, changed in patched(ram, regs, 0xf3ee, ('es', 'di'), (0x80, 0x90, 0xc0)):
        yield name+tag, changed, regs
    for tag, changed in patched(ram, regs, 0xf438, ('es', 'bx'), (0x08,)):
        yield name+tag, changed, regs
    for tag, changed in patched(ram, regs, 0xf354, ('es', 'di'), (0xe0, 0xe8, 0xf0, 0xf8, 0xff)):
        yield name+tag, changed, regs
    # the object table offset carries into its segment (ADC AX,0)
    for value in (0xfff0, 0xff00):
        changed = bytearray(ram)
        at = regs['ds']*16 + 0xacb2
        changed[at:at+2] = value.to_bytes(2, 'little')
        yield name+f'+acb2={value:x}', captured_ram(changed, ram), regs
    # the view shifted so that tiles fall off the map (CH or CL >= 32)
    for at, delta in ((0xaa9a, -16), (0xaa9a, -40), (0xaa9a, -64), (0xa9bc, -16), (0xa9bc, 16), (0xa9bc, -64)):
        changed = bytearray(ram)
        linear = regs['ds']*16 + at
        value = (int.from_bytes(changed[linear:linear+2], 'little') + delta) & 0xffff
        changed[linear:linear+2] = value.to_bytes(2, 'little')
        yield name+f'+{at:x}{delta:+d}', captured_ram(changed, ram), regs


@lru_cache(maxsize=1)
def program():
    return emit.Program()


@lru_cache(maxsize=None)
def generated_image():
    work = ROOT/f'tmp/terrain-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.program_image(program(), work)


PLANTS = {'ring': ('\taddq.b #4,d1\n', '\taddq.b #5,d1\n'),
          'clip': ('\tclr.b d2\n', '\tnop\n'),
          'carry': ('\taddx.w d7,d0\t\t\t; ADC AX,0\n', '\tnop\n'),
          'cell': ('\tadd.w #$60,d0\n', '\tadd.w #$61,d0\n'),
          'push': ('\tTS_PUSH d0\n\tTS_PUSH d3\n', '\tTS_PUSH d3\n\tTS_PUSH d0\n'),
          'span': ('\tsub.w #$100,d2\n', '\tsub.w #$101,d2\n'),
          'entry': ('\tbcs f414\n', '\tbcs f470\n'),
          'pos': ('\tlsr.w #5,d3\n', '\tlsr.w #4,d3\n'),
          'tile': ('\tclr.b d6\n', '\tnop\n'),
          'skip': ('\taddq.w #5,d7\t\t\t; the last object, skipped\n', '\n'),
          'off': ('\tmove.b d6,d0\n\tmovea.w ($7ffe-$26dd,a3),a5\n', '\taddq.b #1,d6\n\tmove.b d6,d0\n\tmovea.w ($7ffe-$26dd,a3),a5\n'),
          'es': ('\tmove.w d7,G_ES(a6)\n', '\tnop\n'),
          'seg': ('\tcmp.w #$9000,d7\n', '\tcmp.w #$ffff,d7\n'),
          'divisor': ('\tbeq ring_fault\t\t\t; DIV DI would fault: generated from F2BD\n', '\n'),
          'pop': ('\tcmp.w TF_OS(sp),d7\n\tbne terrain_drop\n', '\tcmp.w TF_OS(sp),d7\n\tnop\n')}


@lru_cache(maxsize=None)
def native_image(plant=None):
    source = (ROOT/'src/runtime/compute_terrain.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    source = re.sub(r'^\txref .*$', '', source, flags=re.M)
    # d7 = the entry index (moveq in the hook), patched at SNIP+4 per run;
    # smc_expose drops the cell caches only (no guest state)
    text = [equates(), f'org ${B.SNIP:x}', 'dc.l done,0', 'entry:',
            f'move.l ${B.SNIP+4:x},d7', f'move.l #${B.LOADSEG+0x49b:x},d6',
            'jsr rt_hle_terrain_select', 'bra done', 'done:', 'nop',
            'smc_expose:', 'rts', 'smc_seg_limit:', f'dc.w ${program().smc_limit:x}', source]
    work = ROOT/f'tmp/terrain-native-{os.getpid()}'
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
            raise TerrainMismatch(('native run', info))
        return actual_state(m, got, fl, fx, writes, at), m.r('d7')
    finally:
        B.U.uc.uc_close(m.e.h)


def generated_run(ram, regs, start):
    binary, addresses = generated_image()
    p = program()
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        m.extra_stops = {addresses[f('SWOTL.EXE', a)]: f'stop-{a:x}' for a in STOPS
                         for f in (emit.label, emit.copy_label) if f('SWOTL.EXE', a) in addresses}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label('SWOTL.EXE', start)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(43), irq=False)
        if info['err'] or outs or info['irq'] or not (info['stop'] or '').startswith('stop-'):
            raise TerrainMismatch(('generated run', info))
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
        raise TerrainMismatch((name, hex(stop), errors))


def unchanged(name, ram, regs, actual):
    if actual['writes'] or actual['ram'] != ram or any(
            actual['registers'][k] != v for k, v in regs.items()
            if k in actual['registers'] and k not in ('cs', 'ip')):
        raise TerrainMismatch((name, 'decline mutation'))


def chain(name, ram, regs, plant=None, generated=True):
    """Walk one call from F290 to F318. Returns the number of compared hooks."""
    cs = regs['cs']
    hooks = {(cs, a-CS_OFF) for a in (FIRST, *ENTRIES, ENDPOINT)}
    stops = tuple((cs, a-CS_OFF) for a in STOPS)
    full = native_image(plant)
    count = 0
    while regs['ip'] != ENDPOINT-CS_OFF:
        at = regs['ip'] + CS_OFF
        expected = O.run(ram, regs, (cs, ENDPOINT-CS_OFF), limit=10**7, returns=stops)
        stop = expected['at'][1] + CS_OFF
        if stop not in STOPS:
            raise TerrainMismatch((name, 'original left the row without an exit', hex(stop)))
        actual, result = native_run(full, ram, regs, expected['at'], INDEX[at])
        if result != RESUME[stop]:
            raise TerrainMismatch((name, 'native', hex(at), hex(stop), result))
        check(f'{name} native {at:x}', expected, actual, stop)
        REACHED.update({stop, at})
        if generated:
            check(f'{name} generated {at:x}', expected, generated_run(ram, regs, at), stop)
        count += 1
        ram = captured_ram(expected['ram'], ram)
        regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
        if stop != ENDPOINT:
            regs, ram = run_to(ram, regs, hooks)
    return count


def decline_cases(plant=None):
    """Guards decline before any mutation: DS/SS windows, the tile, map and
    type segments, and at a re-entry the ES to pop and
    the tile window's LES segment."""
    binary = native_image(plant)
    count = 0
    for name, ram, regs in captured():
        cs, ds = regs['cs'], regs['ds']*16

        def word(offset, value, memory=ram):
            changed = bytearray(memory)
            changed[ds+offset:ds+offset+2] = (value & 0xffff).to_bytes(2, 'little')
            return captured_ram(changed, ram)
        cases = [(f'{seg}={value:x}', ram, dict(regs, **{seg: value & 0xffff}), 0)
                 for seg in ('ds', 'ss') for value in (0, cs+0xfff, 0x9001, 0xffff)]
        cases += [(f'[{at:x}]={value:x}', word(at, value), regs, 0)
                  for at in (0x8692, 0x8658, 0xaba2) for value in (0, cs+0xfff)]
        sp = regs['sp']
        tiles = int.from_bytes(ram[ds+0x8692:ds+0x8694], 'little')
        for index, depth in ((1, 2), (2, 4), (3, 2)):
            at = regs['ss']*16 + ((sp + depth) & 0xffff)
            changed = bytearray(word(0x26df, tiles))
            changed[at:at+2] = ((int.from_bytes(ram[ds+0xaba2:ds+0xaba4], 'little') + 1) & 0xffff).to_bytes(2, 'little')
            cases.append((f'pop es {index}', captured_ram(changed, ram), regs, index))
            stale = word(0x26df, int.from_bytes(ram[ds+0x8692:ds+0x8694], 'little') + 1)
            pushed = bytearray(stale)
            pushed[at:at+2] = ram[ds+0xaba2:ds+0xaba4]
            cases.append((f'26df {index}', captured_ram(pushed, ram), regs, index))
        for tag, memory, changed, index in cases:
            actual, result = native_run(binary, memory, changed, (cs, regs['ip']), index)
            if result:
                raise TerrainMismatch((tag, index, 'no decline', result))
            unchanged(tag, memory, changed, actual)
            count += 1
        break
    return count


def fault_cases(plant=None):
    """A ring whose divisor is zero (DIV DI faults) continues generated at
    its loop head F2BD (resume 7) in the original's state there: ring 0 from
    F290, and the ring after the first re-entry's."""
    binary = native_image(plant)
    head = (0xf2bd, len(STOPS) + 1)
    count = 0
    for name, ram, regs in captured():
        cs, ds = regs['cs'], regs['ds']*16

        def zero(memory, ring):
            changed = bytearray(memory)
            changed[ds+0x54b6+2*ring:ds+0x54b8+2*ring] = b'\0\0'
            return captured_ram(changed, ram)
        cases = [(zero(ram, 0), regs, 0)]
        stops = tuple((cs, a-CS_OFF) for a in STOPS)
        expected = O.run(ram, regs, (cs, ENDPOINT-CS_OFF), limit=10**7, returns=stops)
        if expected['at'][1]+CS_OFF != ENDPOINT:
            state = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
            state, memory = run_to(captured_ram(expected['ram'], ram), state,
                                   {(cs, a-CS_OFF) for a in (*ENTRIES, ENDPOINT)})
            if state['ip']+CS_OFF in ENTRIES and state['si'] < 7:
                cases.append((zero(memory, state['si']+1), state, INDEX[state['ip']+CS_OFF]))
        for memory, start, index in cases:
            expected = O.run(memory, start, (cs, head[0]-CS_OFF), limit=10**7, returns=stops)
            if expected['at'][1]+CS_OFF != head[0]:
                continue
            actual, result = native_run(binary, memory, start, expected['at'], index)
            if result != head[1]:
                raise TerrainMismatch((name, 'divisor', index, result))
            check(f'{name} divisor {index}', expected, actual, head[0])
            count += 1
    if count < 4:
        raise TerrainMismatch(('divisor coverage', count))
    return count


def dispatch_cases():
    p = program()
    row = ('SWOTL.EXE', FIRST)
    want = {r[1]: k + 1 for k, r in enumerate(p.compute_resumes[row])}
    if want != RESUME | {a: len(STOPS) + 1 + k for k, a in enumerate(LOOPS)}:
        raise TerrainMismatch(('resume ids', want))
    if tuple(e[1] for e in p.compute_entries[row]) != ENTRIES:
        raise TerrainMismatch(('entries', p.compute_entries[row]))
    if any(('SWOTL.EXE', a) in p.loop_heads for a in LOOPS):
        raise TerrainMismatch('body loop head left in the sync set')
    source = (ROOT/'src/runtime/compute_terrain.s').read_text()
    for a, k in re.findall(r'^RT_([0-9A-F]{4})\tequ (\d+)$', source, re.M):
        if RESUME.get(int(a, 16)) != int(k):
            raise TerrainMismatch(('native resume id', a, k))
    return len(want)


def run_all(plant=None, generated=True):
    total = 0
    for name, ram, regs in variants(captured()):
        total += chain(name, ram, regs, plant, generated)
    want = set(STOPS) | {FIRST, *ENTRIES}
    if not plant and not REACHED >= want:
        raise TerrainMismatch(('coverage', sorted(map(hex, want - REACHED))))
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('generated', 'native', 'sabotage'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.native or args.generated:
        print('terrain select:', run_all(generated=args.generated), 'hooks pass at their exits', flush=True)
        print('terrain select:', decline_cases(), 'decline cases pass', flush=True)
        print('terrain select:', fault_cases(), 'zero-divisor resumes pass', flush=True)
        print('terrain select:', dispatch_cases(), 'resume ids match', flush=True)
    if args.sabotage:
        for plant in ('ring', 'clip', 'carry', 'cell', 'push', 'span', 'entry', 'pos', 'tile', 'skip', 'off', 'es'):
            try:
                run_all(plant, generated=False)
            except TerrainMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        try:
            fault_cases('divisor')
        except (TerrainMismatch, AssertionError) as error:
            print('caught divisor', str(error)[:200], flush=True)
        else:
            raise AssertionError('divisor escaped')
        for plant in ('seg', 'pop'):
            try:
                decline_cases(plant)
            except TerrainMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
