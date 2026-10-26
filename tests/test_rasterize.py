"""BFD1 scanline rasterizer from C000 (F5): original x86 is the oracle.

Each captured call runs from its BFD1 entry. The prologue, every guest call
(continuation exits) and the row's code after them run as original x86 to the
next C000 entry, the row's only hook. From each entry the native and the
generated arm run to the next exit and are compared with the original there
(RC5, docs/irq-plan.md: registers, live flags, all RAM, code/VRAM write sets).
A record pointer past FFF0h resumes at its loop head in generated code."""
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
import uc as U
from tools import compute_oracle as O
from translator import compute, emit
from translator.support import equates
from translator.ir import FLAGS, FLAG_BIT

CS_OFF = 0x49b0
FIRST, RETURN = 0xc000, 0xc04a
LOOPS = (0xc000, 0xc085, 0xc0c5, 0xc0d1, 0xc11a, 0xc129, 0xc1e2, 0xc27c,
         0xc2f2, 0xc306, 0xc32d, 0xc3a4, 0xc3df)
EXITS = (0xc02c, 0xc03a, 0xc040, 0xc043, 0xc2a5, 0xc2b3, 0xc2bd, 0xc3eb)
# compute.resume_dispatch ids: the endpoints ascending, then the root loop heads
RESUME = {a: k + 1 for k, a in enumerate(EXITS)} | {a: 9 + k for k, a in enumerate(LOOPS)}
# Wrap peeks (RASTER_PEEK_*): the ES offset this test pokes, a wrapping value,
# and every record word the loop head's peek reads
PEEKS = {0xc0d1: (lambda r: (r['bx'] + 2) & 0xffff, 0xfff8,
                  lambda r: (r['bx'], (r['bx'] + 2) & 0xffff)),
         0xc1e2: (lambda r: r['si'], 0xfff4, lambda r: (r['si'],)),
         0xc3df: (lambda r: (r['si'] + 2) & 0xffff, 0xfffa, lambda r: ((r['si'] + 2) & 0xffff,))}
DS_WORDS = dict(w2581=0x2581, w233e=0x233e, w2531=0x2531, w2533=0x2533, w23ff=0x23ff)


class RasterMismatch(AssertionError):
    pass


REACHED = set()


def captured_ram(data, like):
    return O.CapturedRAM(bytes(data), getattr(like, 'captured_bytes', len(like)))


def run_to(ram, regs, stops, limit=10**7):
    """Original x86 to the first stop (generated-arm stretches: prologue and
    guest calls). Unicorn one instruction per start, as x86_diff (QEMU REP
    after a flag setter); self-modifying code allowed; interrupts and port
    output fail loudly."""
    X = B.X
    e = U.Engine(U.ARCH_X86, U.MODE_16)
    e.map(0, X.RAM)
    e.write(0, bytes(ram[:X.RAM]))
    effects = []

    @U.INTR_CB
    def intr(h, no, user):
        effects.append(no); U.uc.uc_emu_stop(h)

    @U.OUT_CB
    def out(h, port, size, value, user):
        effects.append(('out', port)); U.uc.uc_emu_stop(h)

    e.hook(U.HOOK_INTR, intr)
    e.hook(U.HOOK_INSN, out, U.X86_INS_OUT)
    for r in X.REGS + X.SEGS:
        e.reg_write(U.X86[r], regs[r])
    e.reg_write(U.X86['ip'], regs['ip'])
    e.reg_write(U.X86['flags'], regs['flags'])
    try:
        for n in range(limit):
            cs, ip = e.reg_read(U.X86['cs']), e.reg_read(U.X86['ip']) & 0xffff
            if n and (cs, ip) in stops:
                break
            if e.start(cs*16+ip, 0xFFFFFFFFFFFF, count=1) or effects:
                raise RasterMismatch(('original call', hex(cs), hex(ip), effects))
        else:
            raise RasterMismatch('original call limit')
        out = {r: e.reg_read(U.X86[r]) & 0xffff for r in X.REGS + X.SEGS}
        out.update(ip=ip, flags=e.reg_read(U.X86['flags']) & 0xffff)
        return out, captured_ram(e.read(0, X.RAM), ram)
    finally:
        U.uc.uc_close(e.h)


def captured():
    directories = sorted((ROOT/'tmp/pc-runs').glob('native-F5-raster-BFD1-*'))
    assert len(directories) == 3, 'three original-game fixtures required'
    for directory in directories:
        paths = sorted((directory/'trace').glob('snap-entry*'))
        assert len(paths) == 3, directory
        for path in paths:
            ram, regs = O.load_entry(path)
            yield f'{directory.name[-20:]}/{path.name}', ram, regs


def ds_word(ram, regs, offset, value):
    at = regs['ds']*16 + offset
    changed = bytearray(ram)
    changed[at:at+2] = value.to_bytes(2, 'little')
    return captured_ram(changed, ram)


def variants(entries):
    """Captured calls, then flag variants reaching the other exits."""
    entries = list(entries)
    yield from entries
    # c13 ends through CD99's return, c27 through the scanline head (C03A).
    for name, ram, regs in (entries[0], next(e for e in entries if 'c27' in e[0])):
        yield name+'+2581=0', ds_word(ram, regs, 0x2581, 0), regs
        yield name+'+233e=0', ds_word(ram, regs, 0x233e, 0), regs


@lru_cache(maxsize=1)
def program():
    return emit.Program()


@lru_cache(maxsize=None)
def generated_image(plant=False):
    p = program()
    work = ROOT/f'tmp/rasterize-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    binary, addresses = B.program_image(p, work)
    if plant:   # drop the ordering swap's first store
        changed = bytearray(binary)
        a = addresses[emit.label('SWOTL.EXE', 0xc121)]-B.D.CODE
        z = addresses[emit.label('SWOTL.EXE', 0xc124)]-B.D.CODE
        changed[a:z] = b'\x4e\x71'*((z-a)//2)
        binary = bytes(changed)
    return binary, addresses


PLANTS = {'write': ('\tmove.w a5,-1(a1,d7.w)\n', '\tnop\n'),
          'index': ('\taddq.w #2,d7\t\t; 7FFFh - BX, wrapping like BX\n', '\taddq.w #1,d7\n'),
          'guard': ('\tcmp.w #$1000,d7\n', '\tcmp.w #$0,d7\n'),
          'peek': ('\tcmp.w #$fff0,d7\n', '\tcmp.w #$ffff,d7\n'),
          'carry': ('\taddx.w d2,d7\n', '\tadd.w d2,d7\n'),
          'resume': ('\tmoveq #RZ_C2B3,d7\n', '\tmoveq #RZ_C2BD,d7\n'),
          'bail': ('raster_c0d1_bail:\n\tmoveq #RZ_C0D1,d7\n', 'raster_c0d1_bail:\n\tmoveq #RZ_C1E2,d7\n')}


@lru_cache(maxsize=None)
def native_image(plant=None, predecessor='direct'):
    source = (ROOT/'src/runtime/compute_raster.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    prefix = {'direct': [], 'jump': ['bra entry'], 'call': ['bsr entry', 'bra done'],
              'taken': ['cmp.w d0,d0', 'beq entry', 'illegal'],
              'fall': ['cmp.w d0,d0', 'bne done'], 'indirect': ['lea entry,a0', 'jmp (a0)'],
              'return': ['pea entry', 'rts']}[predecessor]
    # d7 holds garbage on entry: the hook passes no entry index (compute.hook)
    text = [equates(), f'rt_irq equ ${B.STUB_AT["rt_irq"]:x}',
            f'org ${B.SNIP:x}', 'dc.l done,0', *prefix, 'entry:',
            'move.l #$5a5a5a5a,d7', f'move.l #${B.LOADSEG+0x49b:x},d6',
            'jsr rt_hle_rasterize', 'rts' if predecessor == 'call' else 'bra done',
            'done:', 'nop', source]
    work = ROOT/f'tmp/rasterize-native-{os.getpid()}'
    work.mkdir(exist_ok=True)
    text = [('\t'+line if '\n' not in line and not line.endswith(':')
             and ' equ ' not in line and not line.startswith('\t') else line) for line in text]
    return B.D.assemble('\n'.join(text), work/f'{plant}-{predecessor}.bin')


def actual_state(m, got, fl, fx, writes, at):
    got.update(cs=at[0], ip=at[1])
    return dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                writes=writes, ram=m.gread(0, B.X.RAM))


def native_run(binary, ram, regs, at):
    """The native from C000; never calls rt_irq (poll-free, RC5)."""
    m = B.D.M68k(ram, B.STUB_AT)
    m.irq_calls = []
    try:
        m.e.write(B.SNIP, binary)
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100 \
                or m.irq_calls:
            raise RasterMismatch(('native run', info, m.irq_calls))
        return actual_state(m, got, fl, fx, writes, at), m.r('d7')
    finally:
        B.U.uc.uc_close(m.e.h)


def generated_run(ram, regs, start, stops, plant=False):
    binary, addresses = generated_image(plant)
    p = program()
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        m.extra_stops = {addresses[emit.label('SWOTL.EXE', a)]: f'stop-{a:x}' for a in stops}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label('SWOTL.EXE', start)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['irq'] or not (info['stop'] or '').startswith('stop-'):
            raise RasterMismatch(('generated run', info))
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
        raise RasterMismatch((name, hex(stop), errors))


def chain(name, ram, regs, plant=None, generated=True, mutate=None, generated_plant=False):
    """Walk one call. Returns the number of compared entries."""
    cs = regs['cs']
    entry = {(cs, FIRST-CS_OFF), (cs, RETURN-CS_OFF)}
    exits = tuple((cs, a-CS_OFF) for a in EXITS)
    regs, ram = run_to(ram, regs, entry)
    full = native_image(plant)
    count = 0
    while regs['ip'] != RETURN-CS_OFF:
        if mutate:
            ram, regs = mutate(FIRST, ram, regs)
        expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, returns=exits)
        stop = expected['at'][1] + CS_OFF
        if stop not in EXITS:
            raise RasterMismatch((name, 'original left the row without an exit', hex(stop)))
        actual, result = native_run(full, ram, regs, expected['at'])
        if result != RESUME[stop]:
            raise RasterMismatch((name, 'native', hex(stop), result))
        check(name+' native', expected, actual, stop)
        REACHED.add(stop)
        if generated:
            check(name+' generated', expected,
                  generated_run(ram, regs, FIRST, EXITS, generated_plant), stop)
        count += 1
        ram = captured_ram(expected['ram'], ram)
        regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
        regs, ram = run_to(ram, regs, entry)
    return count


def head_exit(at, ram, regs):
    """The scanline head's own end test (exit C043) at the last line."""
    if at != FIRST:
        return ram, regs
    ds = regs['ds']*16
    if int.from_bytes(ram[ds+0x23ff:ds+0x2401], 'little'):
        return ram, regs
    ram = ds_word(ram, regs, 0x2531, 0)
    return ds_word(ram, regs, 0x2533, 0xffff), regs


def decline_cases(plant=None):
    """Guards decline before any mutation."""
    binary = native_image(plant)
    name, ram, regs = next(captured())
    cs = regs['cs']
    regs, ram = run_to(ram, regs, {(cs, FIRST-CS_OFF)})
    cases = [(seg, value) for seg in ('ds', 'es', 'ss')
             for value in (0, cs+0xfff, 0x9001, 0xffff)]
    cases += [('es', regs['ss']+0xfff), ('es', regs['ss']-0xfff),
              ('flags', regs['flags'] | 0x400)]
    count = 0
    for key, value in cases:
        changed = dict(regs, **{key: value & 0xffff})
        actual, result = native_run(binary, ram, changed, (cs, regs['ip']))
        if result or actual['writes'] or actual['ram'] != ram:
            raise RasterMismatch((key, value, 'decline mutation'))
        if any(actual['registers'][k] != v for k, v in changed.items() if k in actual['registers']
               and k not in ('cs', 'ip')):
            raise RasterMismatch((key, value, 'decline registers'))
        count += 1
    return count


def first_bail(ram, regs):
    """Original x86 from C000 to the first arrival at a peeking loop head whose
    record word wraps (the native resumes there), or None at an exit or return.
    Returns (head, whether it is that head's first arrival)."""
    cs = regs['cs']
    stops = {(cs, a-CS_OFF) for a in (*PEEKS, *EXITS, RETURN)}
    seen = set()
    while True:
        regs, ram = run_to(ram, regs, stops)
        head = regs['ip'] + CS_OFF
        if head not in PEEKS:
            return None
        es = regs['es']*16
        if any(int.from_bytes(ram[es+w:es+w+2], 'little') > 0xfff0 for w in PEEKS[head][2](regs)):
            return head, head not in seen
        seen.add(head)


def wrap_cases(plant=None):
    """A record pointer past FFF0h at a peeking loop head reached from C000:
    the native resumes at the first such arrival in generated code with the
    original's state there. From C000 the merge (C0D1) reads every active
    record pointer before C1E2 (unless one record is active) and C1E2 every one
    before C3DF, so the fixtures reach the C0D1 resume; the C1E2/C3DF peeks
    were reached by re-entry at their polls (retired, RC5), as were the
    priority searches' BX wraps through 0 (C2F2/C32D: the row sets DS:2535
    before it reads it)."""
    count = 0
    full = native_image(plant)
    need = {0xc0d1}
    for name, ram, regs in captured():
        cs = regs['cs']
        entry = {(cs, FIRST-CS_OFF), (cs, RETURN-CS_OFF)}
        exits = tuple((cs, a-CS_OFF) for a in EXITS)
        regs, ram = run_to(ram, regs, entry)
        while need and regs['ip'] != RETURN-CS_OFF:
            for head in sorted(need):
                ends = ((cs, head-CS_OFF),) + exits
                probe = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, returns=ends)
                if probe['at'][1] + CS_OFF != head:
                    continue
                offset, value, _ = PEEKS[head]
                es = probe['registers']['es']*16
                addr = es + offset(probe['registers'])
                # The row copies record words (the add stage's REP MOVSW), so
                # also try the entry RAM's other copies of the arriving word.
                word = probe['ram'][addr:addr+2]
                segment = bytes(ram[es:es+0x10000])
                copies = [es + k for k in range(0x10000 - 1) if segment[k:k+2] == word]
                for poke in [addr] + [a for a in copies if a != addr][:8]:
                    changed = bytearray(ram)
                    changed[poke:poke+2] = value.to_bytes(2, 'little')
                    memory = captured_ram(changed, ram)
                    # oracle stop: the first arrival at `head` must be the first wrap
                    if first_bail(memory, regs) == (head, True):
                        break
                else:
                    continue
                want = O.run(memory, regs, (cs, RETURN-CS_OFF), limit=10**7, returns=ends)
                actual, result = native_run(full, memory, regs, want['at'])
                if want['at'][1] + CS_OFF != head or result != RESUME[head]:
                    raise RasterMismatch((name, 'wrap', hex(head), result))
                check(f'wrap {head:x}', want, actual, head)
                need.discard(head)
                count += 1
            expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, returns=exits)
            ram = captured_ram(expected['ram'], ram)
            regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
            regs, ram = run_to(ram, regs, entry)
    if need:
        raise RasterMismatch(('wrap coverage', sorted(map(hex, need))))
    return count


def dispatch_cases(plant=False):
    """The generated resume table (21 ids) on the 68k core: every id reaches
    its own target, 0 and out-of-range ids stop loudly; the native's RZ ids
    are the row's compute_resumes."""
    resumes = program().compute_resumes[('SWOTL.EXE', FIRST)]
    want_ids = {r[1]: k + 1 for k, r in enumerate(resumes)}
    if want_ids != RESUME:
        raise RasterMismatch(('resume ids', want_ids))
    source = (ROOT/'src/runtime/compute_raster.s').read_text()
    for a, k in re.findall(r'^RZ_C([0-9A-F]{3})\tequ (\d+)$', source, re.M):
        if want_ids.get(int('C' + a, 16)) != int(k):
            raise RasterMismatch(('native resume id', a, k))
    lines = compute.resume_dispatch('cx', [f'target{k}' for k in range(len(RESUME))], '$1234')
    if plant:
        lines = [line.replace('(cxt,pc,d7.w', '(cxt-4,pc,d7.w') for line in lines]
    text = [equates(), f'org ${B.SNIP:x}', 'dc.l done,0', f'move.l ${B.SNIP+4:x},d7',
            'bra.w cx', *lines]
    for k in range(len(RESUME)):
        text += [f'target{k}:', f'move.w #{k+1},d0', 'bra.w done']
    text += ['rt_stop_unknown:', 'move.w #$ffff,d0', 'done:', 'nop']
    text = ['\t'+line if not line.endswith(':') and ' equ ' not in line and not line.startswith('\t')
            and '\n' not in line else line for line in text]
    work = ROOT/f'tmp/rasterize-native-{os.getpid()}'
    work.mkdir(exist_ok=True)
    binary = B.D.assemble('\n'.join(text), work/f'dispatch-{plant}.bin')
    _, ram, regs = next(captured())
    count = 0
    for selector in range(len(RESUME)+3):
        image_ = binary[:4] + selector.to_bytes(4, 'big') + binary[8:]
        m = B.D.M68k(ram, B.STUB_AT)
        try:
            m.e.write(B.SNIP, image_)
            m.extra_stops = {B.SNIP + len(image_) - 2: 'done'}
            flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
            got, *_, info = m.run(B.SNIP+8, (regs, flags, regs['flags'] & 0xf000, regs['ip'], []),
                                  random.Random(41), irq=False)
            want = selector if 1 <= selector <= len(RESUME) else 0xffff
            if info['err'] or info['stop'] != 'done' or got['ax'] != want:
                raise RasterMismatch(('dispatch', selector, got['ax'], info['stop']))
            count += 1
        finally:
            B.U.uc.uc_close(m.e.h)
    return count


def predecessor_cases():
    total = 0
    name, ram, regs = next(captured())
    cs = regs['cs']
    regs, ram = run_to(ram, regs, {(cs, FIRST-CS_OFF)})
    exits = tuple((cs, a-CS_OFF) for a in EXITS)
    expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, returns=exits)
    stop = expected['at'][1] + CS_OFF
    for predecessor in ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return'):
        try:
            actual, result = native_run(native_image(None, predecessor), ram, regs, expected['at'])
            if result != RESUME[stop]:
                raise RasterMismatch((predecessor, result))
            check(predecessor, expected, actual, stop)
        except RasterMismatch as error:
            return total+1, [str(error)]
        total += 1
    return total, []


def run_all(plant=None, generated=True):
    total = 0
    for name, ram, regs in variants(captured()):
        total += chain(name, ram, regs, plant, generated)
    name, ram, regs = next(captured())
    total += chain(name+'+head-exit', ram, regs, plant, False, head_exit)
    if not plant and REACHED != set(EXITS):
        raise RasterMismatch(('coverage', sorted(map(hex, set(EXITS) - REACHED))))
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('generated', 'native', 'predecessors', 'sabotage'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.native or args.generated:
        print('rasterize:', run_all(generated=args.generated), 'entries pass at their exits', flush=True)
        print('rasterize:', decline_cases(), 'decline cases pass', flush=True)
        print('rasterize:', wrap_cases(), 'wrap cases pass', flush=True)
        print('rasterize:', dispatch_cases(), 'resume table cases pass', flush=True)
    if args.predecessors:
        n, failures = predecessor_cases()
        assert not failures, failures
        print('rasterize:', n, 'predecessor cases pass', flush=True)
    if args.sabotage:
        for plant in ('write', 'index', 'carry', 'resume'):
            try:
                run_all(plant, generated=False)
            except RasterMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        for plant, probe in (('guard', decline_cases), ('peek', wrap_cases), ('bail', wrap_cases)):
            try:
                probe(plant)
            except RasterMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        try:
            dispatch_cases(plant=True)
        except RasterMismatch as error:
            print('caught resume table offset', str(error)[:200], flush=True)
        else:
            raise AssertionError('resume table plant escaped')
        name, ram, regs = next(captured())
        try:
            chain(name, ram, regs, generated_plant=True)
        except RasterMismatch as error:
            print('caught missing swap write (generated)', str(error)[:200], flush=True)
        else:
            raise AssertionError('generated plant escaped')
