"""BD68 edge submission (irq-plan I10): original x86 is the oracle.

Each captured call runs from BD68. The edge setup (C962) and span-record
(CD00) calls are continuation exits and run as original x86 to the row's next
hook, the re-entry after the call returns (BE1B, BEDB, BF97, BFB4; d7 = 1 + k).
From each hook the native and the generated arm run to the next exit or the
endpoint BF04 and are compared with the original there (RC5: registers, live
flags, all RAM, code/VRAM write sets). Variants force the flat-polygon path
(C3F8h low nibble 0Fh), the span-record declines (DF, a DI that would wrap)
and re-entries whose popped SI or BP lies outside the record base's exact
range (resume at the loop head in generated code)."""
from pathlib import Path
import argparse
import random
import os
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
FIRST, ENDPOINT = 0xbd68, 0xbf04
EXITS = (0xbe18, 0xbed8, 0xbf94, 0xbfb1)
ENTRIES = (0xbe1b, 0xbedb, 0xbf97, 0xbfb4)     # hle.csv entries
INDEX = {FIRST: 0} | {a: k + 1 for k, a in enumerate(ENTRIES)}
STOPS = tuple(sorted((*EXITS, ENDPOINT)))
RESUME = {a: k + 1 for k, a in enumerate(STOPS)}
LOOPS = (0xbda5, 0xbdc6, 0xbe66, 0xbe87, 0xbf1b, 0xbf56)
LOOP_RESUME = {a: len(STOPS) + 1 + k for k, a in enumerate(LOOPS)}
AFTER = {0xbe1b: 0xbdc6, 0xbedb: 0xbe87}    # a re-entry's loop head after POP BP, POP SI


class EdgeMismatch(AssertionError):
    pass


REACHED = set()


def captured():
    directories = sorted((ROOT/'tmp/pc-runs').glob('native-I10-edge-*'))
    assert len(directories) == 3, 'three original-game fixtures required'
    for directory in directories:
        paths = sorted((directory/'trace').glob('snap-entry*'))
        assert len(paths) == 3, directory
        for path in paths:
            ram, regs = O.load_entry(path)
            yield f'{directory.name[16:]}/{path.name}', ram, regs


def flat(ram, regs):
    """The caller's [BP+0Ah] argument (stored to C3F8h) with low nibble 0Fh."""
    at = regs['ss']*16 + ((regs['sp'] + 8) & 0xffff)   # [BP+0Ah] after PUSH BP
    changed = bytearray(ram)
    changed[at] |= 0x0f
    return captured_ram(changed, ram)


def variants(entries):
    entries = list(entries)
    yield from entries
    for name, ram, regs in entries[::3]:
        yield name+'+flat', flat(ram, regs), regs


@lru_cache(maxsize=1)
def program():
    return emit.Program()


@lru_cache(maxsize=None)
def generated_image():
    work = ROOT/f'tmp/edge-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.program_image(program(), work)


PLANTS = {'carry': ('\tsubx.w d7,d2\n', '\tsub.w d7,d2\n'),
          'store': ('\tmove.w d0,($7ffe-$23ff,a3)\n\tmove.w -2(a0),d2\n', '\tmove.w -2(a0),d2\n'),
          'push': ('\teori.w #$7fff,d7\n\tEDGE_PUSH d7\n', '\tEDGE_PUSH d7\n'),
          'mark': ('\tor.b #\\1,-5(a1,d7.w)\n', '\tor.b #\\1,-4(a1,d7.w)\n'),
          'record': ('\tadda.w #16,a5\n', '\tadda.w #14,a5\n'),
          'entry': ('\tbeq.w edge_bf97\n', '\tbne.w edge_bf97\n'),
          'bound': ('\tadd.w #$1000,d7\n\tcmp.w #$2000,d7\n', '\tadd.w #$1000,d7\n\tcmp.w #$ffff,d7\n'),
          'wrap': ('\tcmp.w #$fff0,d6\n', '\tcmp.w #$ffff,d6\n')}


@lru_cache(maxsize=None)
def native_image(plant=None):
    source = (ROOT/'src/runtime/compute_edge.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    # d7 = the entry index (moveq in the hook), patched at SNIP+4 per run
    text = [equates(), f'org ${B.SNIP:x}', 'dc.l done,0', 'entry:',
            f'move.l ${B.SNIP+4:x},d7', f'move.l #${B.LOADSEG+0x49b:x},d6',
            'jsr rt_hle_edge_submit', 'bra done', 'done:', 'nop',
            'smc_expose:', 'rts', 'smc_seg_limit:', f'dc.w ${program().smc_limit:x}', source]
    work = ROOT/f'tmp/edge-native-{os.getpid()}'
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
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100:
            raise EdgeMismatch(('native run', info))
        return actual_state(m, got, fl, fx, writes, at), m.r('d7')
    finally:
        B.U.uc.uc_close(m.e.h)


def generated_run(ram, regs, start):
    binary, addresses = generated_image()
    p = program()
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        # BD68 runs in its BP-guarded copy (R6): stop at either copy
        m.extra_stops = {addresses[f('SWOTL.EXE', a)]: f'stop-{a:x}' for a in STOPS
                         for f in (emit.label, emit.copy_label) if f('SWOTL.EXE', a) in addresses}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label('SWOTL.EXE', start)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['irq'] or not (info['stop'] or '').startswith('stop-'):
            raise EdgeMismatch(('generated run', info))
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
        raise EdgeMismatch((name, hex(stop), errors))


def unchanged(name, ram, regs, actual):
    if actual['writes'] or actual['ram'] != ram or any(
            actual['registers'][k] != v for k, v in regs.items()
            if k in actual['registers'] and k not in ('cs', 'ip')):
        raise EdgeMismatch((name, 'decline mutation'))


def chain(name, ram, regs, plant=None, generated=True):
    """Walk one call from BD68 to BF04. Returns the number of compared hooks."""
    cs = regs['cs']
    hooks = {(cs, a-CS_OFF) for a in (FIRST, *ENTRIES, ENDPOINT)}
    stops = tuple((cs, a-CS_OFF) for a in STOPS)
    full = native_image(plant)
    count = 0
    while regs['ip'] != ENDPOINT-CS_OFF:
        at = regs['ip'] + CS_OFF
        expected = O.run(ram, regs, (cs, ENDPOINT-CS_OFF), limit=10**6, returns=stops)
        stop = expected['at'][1] + CS_OFF
        if stop not in STOPS:
            raise EdgeMismatch((name, 'original left the row without an exit', hex(stop)))
        actual, result = native_run(full, ram, regs, expected['at'], INDEX[at])
        if result != RESUME[stop]:
            raise EdgeMismatch((name, 'native', hex(at), hex(stop), result))
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
    """The span-record re-entries decline before any mutation: DF set, or a
    DI whose eight STOSW would wrap."""
    binary = native_image(plant)
    count = 0
    name, ram, regs = next(captured())
    cs = regs['cs']
    cases = [(key, value, k) for k in (3, 4)
             for key, value in (('flags', regs['flags'] | 0x400), ('di', 0xfff1), ('di', 0xffff))]
    for key, value, index in cases:
        changed = dict(regs, **{key: value & 0xffff})
        actual, result = native_run(binary, ram, changed, (cs, regs['ip']), index)
        if result:
            raise EdgeMismatch((key, hex(value), index, 'no decline', result))
        unchanged(f'{key}={value:x}', ram, changed, actual)
        count += 1
    return count


def bound_cases(plant=None):
    """A re-entry whose popped SI or BP lies outside +-1000h (SI DBB4h puts the
    record across the signed 16-bit index boundary) resumes at its loop head
    with the original's state there."""
    binary = native_image(plant)
    count = 0
    for name, ram, regs in captured():
        cs = regs['cs']
        hooks = {(cs, a-CS_OFF) for a in (FIRST, *ENTRIES, ENDPOINT)}
        stops = tuple((cs, a-CS_OFF) for a in STOPS)
        need = set(AFTER)
        while need and regs['ip'] != ENDPOINT-CS_OFF:
            at = regs['ip'] + CS_OFF
            if at in need:
                sp = regs['ss']*16
                for slot, value in ((2, 0xdbb4), (0, 0x1008)):     # SI, BP slots
                    changed = bytearray(ram)
                    a = sp + ((regs['sp'] + slot) & 0xffff)
                    changed[a:a+2] = value.to_bytes(2, 'little')
                    memory = captured_ram(changed, ram)
                    want = O.run(memory, regs, (cs, AFTER[at]-CS_OFF), limit=10**6,
                                 returns=((cs, AFTER[at]-CS_OFF),))
                    actual, result = native_run(binary, memory, regs, want['at'], INDEX[at])
                    if result != LOOP_RESUME[AFTER[at]]:
                        raise EdgeMismatch((name, 'bound', hex(at), slot, result))
                    check(f'{name} bound {at:x}', want, actual, AFTER[at])
                    count += 1
                need.discard(at)
            expected = O.run(ram, regs, (cs, ENDPOINT-CS_OFF), limit=10**6, returns=stops)
            ram = captured_ram(expected['ram'], ram)
            regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
            if expected['at'][1] != ENDPOINT-CS_OFF:
                regs, ram = run_to(ram, regs, hooks)
        if not need:
            return count
    raise EdgeMismatch(('bound coverage', sorted(map(hex, need))))


def dispatch_cases():
    p = program()
    row = ('SWOTL.EXE', FIRST)
    want = {r[1]: k + 1 for k, r in enumerate(p.compute_resumes[row])}
    if want != RESUME | LOOP_RESUME:
        raise EdgeMismatch(('resume ids', want))
    if tuple(e[1] for e in p.compute_entries[row]) != ENTRIES:
        raise EdgeMismatch(('entries', p.compute_entries[row]))
    import re
    source = (ROOT/'src/runtime/compute_edge.s').read_text()
    for a, k in re.findall(r'^RZ_([0-9A-F]{4})\tequ (\d+)$', source, re.M):
        if (RESUME | LOOP_RESUME).get(int(a, 16)) != int(k):
            raise EdgeMismatch(('native resume id', a, k))
    return len(want)


def run_all(plant=None, generated=True):
    total = 0
    for name, ram, regs in variants(captured()):
        total += chain(name, ram, regs, plant, generated)
    want = set(STOPS) | {FIRST, *ENTRIES}
    if not plant and not REACHED >= want:
        raise EdgeMismatch(('coverage', sorted(map(hex, want - REACHED))))
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('generated', 'native', 'sabotage'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.native or args.generated:
        print('edge submit:', run_all(generated=args.generated), 'hooks pass at their exits', flush=True)
        print('edge submit:', decline_cases(), 'decline cases pass', flush=True)
        print('edge submit:', bound_cases(), 're-entry bound cases pass', flush=True)
        print('edge submit:', dispatch_cases(), 'resume ids match', flush=True)
    if args.sabotage:
        for plant in ('carry', 'store', 'push', 'mark', 'record', 'entry'):
            try:
                run_all(plant, generated=False)
            except EdgeMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        for plant, probe in (('wrap', decline_cases), ('bound', bound_cases)):
            try:
                probe(plant)
            except EdgeMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
