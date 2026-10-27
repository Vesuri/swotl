"""FDE0 terrain polygons (irq-plan I10): original x86 is the oracle.

Each captured call runs from FDE0. The eight calls (transform B52D,
projection D5A6, clip 169E:0666, classify BB70, submit BD68) are continuation
exits and run as original x86 to the row's next hook, the re-entry after the
call returns (d7 = 1 + k), or to the endpoint FEA6. From each hook the native
and the generated arm run to the next exit or the endpoint and are compared
with the original there (RC5: registers, live flags, all RAM, code/VRAM write
sets). Variants patch what the original reads to reach the paths the
fixtures may not take: the object-count loop ([9F4Ch] = 0), a polygon slot
already drawn, a full vertex cache, all vertices behind the eye, a polygon id
FFh, and the guards' declines."""
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
FIRST, ENDPOINT = 0xfde0, 0xfea6
EXITS = (0xff65, 0x10066, 0x10086, 0x100b3, 0x10199, 0x101e1, 0x101f1, 0x1020c)
ENTRIES = (0xff6a, 0x1006b, 0x1008b, 0x100b8, 0x1019e, 0x101e6, 0x101f6, 0x10211)
INDEX = {FIRST: 0} | {a: k + 1 for k, a in enumerate(ENTRIES)}
STOPS = tuple(sorted((*EXITS, ENDPOINT)))
RESUME = {a: k + 1 for k, a in enumerate(STOPS)}
LOOPS = (0xfe20, 0xfe5a, 0xfe94, 0xfecb, 0xfef1, 0xff40, 0x10008, 0x1012f)
SOURCE = ROOT/'src/runtime/compute_polygons.s'
# exits whose callee native (transform B52D, classify BB70) the row calls
# directly; taken only when it declines
DIRECT = (0xff65, 0x10066, 0x10199, 0x101f1)
CALLEES = (ROOT/'src/runtime/compute_transform.s', ROOT/'src/runtime/compute_classify.s')


class PolygonsMismatch(AssertionError):
    pass


REACHED = set()


def captured():
    directories = sorted((ROOT/'tmp/pc-runs').glob('native-I10-polygons-*'))
    assert len(directories) == 3, 'three original-game fixtures required'
    for directory in directories:
        paths = sorted((directory/'trace').glob('snap-entry*'))
        assert len(paths) == 3, directory
        for path in paths:
            ram, regs = O.load_entry(path)
            yield f'{directory.name[20:]}/{path.name}', ram, regs


def changed_ds(ram, regs, offset, data):
    memory = bytearray(ram)
    at = regs['ds']*16 + offset
    memory[at:at+len(data)] = data
    return captured_ram(memory, ram)


def at_hit(ram, regs, at, hit=1):
    """The original's state at the hit-th execution of `at`."""
    stop = {(regs['cs'], at - CS_OFF)}
    state, memory = regs, ram
    for _ in range(hit):
        state, memory = run_to(memory, state, stop)
    return state, memory


def variants(entries):
    entries = list(entries)
    yield from entries
    name, ram, regs = entries[0]
    # the object-count loop at FE20 (the fixtures may skip it)
    yield name+'+9f4c=0', changed_ds(ram, regs, 0x9f4c, b'\0'), regs
    # a full vertex cache: [BP-6] and [BP-4] start at 19h (B608, the cached
    # projection without a store)
    state, memory = at_hit(ram, regs, 0xfe11)
    frame = bytearray(memory)
    bp = state['ss']*16 + state['bp']
    frame[bp-6] = frame[bp-4] = 0x19
    yield name+'+full', captured_ram(frame, ram), state
    # a polygon id FFh and a slot already drawn, at the first polygon
    state, memory = at_hit(ram, regs, 0xfefe)
    linear = state['es']*16 + state['di']
    for value, tag in ((0xff, 'id-ff'), (None, 'drawn')):
        frame = bytearray(memory)
        if value is None:
            frame[state['ss']*16 + ((state['bp'] - 0x202 + frame[linear]) & 0xffff)] = 1
        else:
            frame[linear] = value
        yield name+'+'+tag, captured_ram(frame, ram), state
    # every vertex behind the eye: the transform's z sign at C396h (the
    # first transform's result, as the following ones are recomputed)
    for name, ram, regs in entries[1:3]:
        state, memory = at_hit(ram, regs, 0xff6e)
        yield name+'+behind', changed_ds(memory, state, 0xc396, b'\0\x80'), state


@lru_cache(maxsize=1)
def program():
    return emit.Program()


@lru_cache(maxsize=None)
def generated_image():
    work = ROOT/f'tmp/polygons-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.program_image(program(), work)


PLANTS = {'ring': ('\tcmp.w #4,a4\n', '\tcmp.w #3,a4\n'),
          'clear': ('\tlea $203(a0),a5\t', '\tlea $201(a0),a5\t'),
          'cache': ('\tcmp.b #$19,6(a0)\n', '\tcmp.b #$18,6(a0)\n'),
          'cell': ('\tlsl.b #2,d1\n', '\tlsl.b #1,d1\n'),
          'behind': ('\taddq.b #1,$e(a0)\t\t; INC', '\tnop\t\t; INC'),
          'clip': ('\tsub.w $b(a0),d3\n', '\tsub.w $9(a0),d3\n'),
          'entry': ('x_1006b-.entries,x_1008b', 'x_1008b-.entries,x_1008b'),
          'pop': ('-13(a2,d4.w),d7\t\t; ADD SP,0Ch; POP ES\n\tsub.w #14,d4\n\tPG_ES\n\tbra x_100bc',
                  '-11(a2,d4.w),d7\t\t; ADD SP,0Ch; POP ES\n\tsub.w #14,d4\n\tPG_ES\n\tbra x_100bc'),
          'seg': ('\tswap d7\n\tcmp.w #$9000,d7\n', '\tswap d7\n\tcmp.w #$ffff,d7\n'),
          'divisor': ('\tbeq.s .zero\n', '\tnop\n'),
          'frame': ('\tcmp.w #$7aff,d7\n', '\tcmp.w #$7fff,d7\n'),
          'df': ('\ttst.b G_DF(a6)\n\tbne.s polygons_decline\n', '\ttst.b G_DF(a6)\n')}
RUN_PLANTS = ('ring', 'clear', 'cache', 'cell', 'behind', 'clip', 'entry', 'pop')
DECLINE_PLANTS = ('seg', 'frame', 'df')


@lru_cache(maxsize=None)
def native_image(plant=None, direct=True):
    source = SOURCE.read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    source = re.sub(r'^\txref .*$', '', source, flags=re.M)
    # d7 = the entry index (moveq in the hook), patched at SNIP+4 per run;
    # smc_expose drops the cell caches only (no guest state)
    text = [equates(), f'org ${B.SNIP:x}', 'dc.l done,0', 'entry:',
            f'move.l ${B.SNIP+4:x},d7', f'move.l #${B.LOADSEG+0x49b:x},d6',
            'jsr rt_hle_terrain_polygons', 'bra done', 'done:', 'nop',
            'smc_expose:', 'rts', 'smc_seg_limit:', f'dc.w ${program().smc_limit:x}', source]
    if direct:
        text += [c.read_text() for c in CALLEES]
    else:   # the callees decline: the row takes their exits
        text += ['rt_hle_point_transform:', 'rt_hle_polygon_classify:', 'moveq #0,d7', 'rts']
    work = ROOT/f'tmp/polygons-native-{os.getpid()}'
    work.mkdir(exist_ok=True)
    text = [('\t'+line if '\n' not in line and not line.endswith(':')
             and ' equ ' not in line and not line.startswith('\t') else line) for line in text]
    return B.D.assemble('\n'.join(text), work/f'{plant}-{direct}.bin')


def native_run(binary, ram, regs, at, index):
    m = B.D.M68k(ram, B.STUB_AT)
    try:
        m.e.write(B.SNIP, binary[:4] + index.to_bytes(4, 'big') + binary[8:])
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(47), irq=False)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100:
            raise PolygonsMismatch(('native run', info))
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
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(47), irq=False)
        if info['err'] or outs or info['irq'] or not (info['stop'] or '').startswith('stop-'):
            raise PolygonsMismatch(('generated run', info))
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
        raise PolygonsMismatch((name, hex(stop), errors))


def unchanged(name, ram, regs, actual):
    if actual['writes'] or actual['ram'] != ram or any(
            actual['registers'][k] != v for k, v in regs.items()
            if k in actual['registers'] and k not in ('cs', 'ip')):
        raise PolygonsMismatch((name, 'decline mutation'))


def original(ram, regs, stops, direct):
    """The x86 from a hook to the next taken exit. direct: through the callee
    calls (the oracle stops before each callf; run_to steps callf, callee and
    retf, writing DS only, both callees' own tests cover them)."""
    cs, written = regs['cs'], set()
    calls = tuple((cs, a-CS_OFF) for a in DIRECT) if direct else ()
    while True:
        expected = O.run(ram, regs, (cs, ENDPOINT-CS_OFF), limit=10**7, returns=stops+calls)
        written |= expected['writes']
        if expected['at'] not in calls:
            return dict(expected, writes=written)
        state = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
        regs, ram = run_to(captured_ram(expected['ram'], ram), state, {(cs, expected['at'][1]+5)})


def chain(name, ram, regs, plant=None, generated=True, direct=True):
    """Walk one call from its first hook to FEA6. Returns the compared hooks.
    direct: the callee natives run inside the row (their exits pass through);
    else they decline, and the generated arm runs from every hook too."""
    cs = regs['cs']
    hooks = {(cs, a-CS_OFF) for a in (FIRST, *ENTRIES, ENDPOINT)}
    taken = tuple(a for a in STOPS if not direct or a not in DIRECT)
    stops = tuple((cs, a-CS_OFF) for a in taken)
    generated = generated and not direct
    if regs['ip'] + CS_OFF not in INDEX:
        regs, ram = run_to(ram, regs, hooks)
    full = native_image(plant, direct)
    count = 0
    while regs['ip'] != ENDPOINT-CS_OFF:
        at = regs['ip'] + CS_OFF
        expected = original(ram, regs, stops, direct)
        stop = expected['at'][1] + CS_OFF
        if stop not in taken:
            raise PolygonsMismatch((name, 'original left the row without an exit', hex(stop)))
        actual, result = native_run(full, ram, regs, expected['at'], INDEX[at])
        if result != RESUME[stop]:
            raise PolygonsMismatch((name, 'native', hex(at), hex(stop), result))
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
    """Guards decline before any mutation: DS/SS windows, at FDE0 DF and the
    object count, the frame range at FDE0 (SP) and at a re-entry (BP)."""
    binary = native_image(plant)
    count = 0
    name, ram, regs = next(captured())
    cs = regs['cs']
    cases = [(f'{seg}={value:x}', ram, dict(regs, **{seg: value & 0xffff}), 0)
             for seg in ('ds', 'ss') for value in (0, cs+0xfff, 0x9001, 0xffff)]
    cases += [('df', ram, dict(regs, flags=regs['flags'] | 0x400), 0)]
    cases += [('[befd]=0', changed_ds(ram, regs, 0xbefd, b'\0'), regs, 0)]
    cases += [(f'sp={sp:x}', ram, dict(regs, sp=sp), 0) for sp in (0x500, 0xff04)]
    cases += [(f'bp={bp:x} {index}', ram, dict(regs, bp=bp), index)
              for bp in (0x4ff, 0xff01) for index in (1, 8)]
    for tag, memory, changed, index in cases:
        actual, result = native_run(binary, memory, changed, (cs, regs['ip']), index)
        if result:
            raise PolygonsMismatch((tag, index, 'no decline', result))
        unchanged(tag, memory, changed, actual)
        count += 1
    return count


def zero_divisor_cases(plant=None):
    """A zero ring divisor: the native stops at the ring loop head FE5A (its
    resume after the endpoints), where the generated DIV faults; compared with
    the original arriving there."""
    binary = native_image(plant)
    p = program()
    resume = [r[1] for r in p.compute_resumes['SWOTL.EXE', FIRST]].index(0xfe5a) + 1
    count = 0
    name, ram, regs = next(captured())
    cs = regs['cs']
    for ring in range(4):
        # the earlier rings without tiles (span 0): no exit before ring `ring`
        memory = changed_ds(changed_ds(ram, regs, 0x54b6 + 2*ring, b'\0\0'), regs, 0x549e, bytes(ring))
        state, expected_ram = regs, memory
        for _ in range(ring + 1):
            state, expected_ram = run_to(expected_ram, state, {(cs, 0xfe5a - CS_OFF)})
        actual, result = native_run(binary, memory, regs, (cs, 0xfe5a - CS_OFF), 0)
        if result != resume:
            raise PolygonsMismatch((f'divisor {ring}', 'resume', result))
        expected = dict(registers={k: v for k, v in state.items() if k != 'flags'},
                        flags=state['flags'], ram=expected_ram, at=(cs, 0xfe5a - CS_OFF),
                        undefined=(), writes=set())
        errors = O.compare(expected, actual, p.live_in['SWOTL.EXE', 0xfe5a], code())
        if errors:
            raise PolygonsMismatch((f'divisor {ring}', errors))
        count += 1
    return count


def dispatch_cases():
    p = program()
    row = ('SWOTL.EXE', FIRST)
    want = {r[1]: k + 1 for k, r in enumerate(p.compute_resumes[row])}
    if want != RESUME | {a: len(STOPS) + 1 + k for k, a in enumerate(LOOPS)}:
        raise PolygonsMismatch(('resume ids', want))
    if tuple(e[1] for e in p.compute_entries[row]) != ENTRIES:
        raise PolygonsMismatch(('entries', p.compute_entries[row]))
    if any(('SWOTL.EXE', a) in p.loop_heads for a in LOOPS):
        raise PolygonsMismatch('body loop head left in the sync set')
    for a, k in re.findall(r'^RP_([0-9A-F]{4,5})\tequ (\d+)$', SOURCE.read_text(), re.M):
        if RESUME.get(int(a, 16)) != int(k):
            raise PolygonsMismatch(('native resume id', a, k))
    return len(want)


def run_all(plant=None, generated=True):
    total = 0
    for name, ram, regs in variants(captured()):
        total += chain(name, ram, regs, plant, generated, direct=True)
        total += chain(name, ram, regs, plant, generated, direct=False)
    want = set(STOPS) | {FIRST, *ENTRIES}
    if not plant and not REACHED >= want:
        raise PolygonsMismatch(('coverage', sorted(map(hex, want - REACHED))))
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('generated', 'native', 'sabotage'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.native or args.generated:
        print('terrain polygons:', run_all(generated=args.generated), 'hooks pass at their exits', flush=True)
        print('terrain polygons:', decline_cases(), 'decline cases pass', flush=True)
        print('terrain polygons:', zero_divisor_cases(), 'zero-divisor resumes pass', flush=True)
        print('terrain polygons:', dispatch_cases(), 'resume ids match', flush=True)
    if args.sabotage:
        for plant in RUN_PLANTS:
            try:
                run_all(plant, generated=False)
            except PolygonsMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        try:
            zero_divisor_cases('divisor')
        except (PolygonsMismatch, AssertionError) as error:
            print('caught divisor', str(error)[:200], flush=True)
        else:
            raise AssertionError('divisor escaped')
        for plant in DECLINE_PLANTS:
            try:
                decline_cases(plant)
            except PolygonsMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
