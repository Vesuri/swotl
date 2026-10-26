"""BFD1 scanline rasterizer from C000 (F5): original x86 is the oracle.

Each captured call runs from its BFD1 entry. The prologue and every guest call
(continuation exits) run as original x86 to the next poll; between polls the
x86 oracle runs segment by segment. At every original poll and exit the
generated arm and the native (diagnostic: every poll hands off) are compared,
and each native entry also runs undiagnosed to its exit."""
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
emit.Program.polled_rows = True  # the exact/U5-poll rows, dormant in the game until I9 (irq-plan I8)

CS_OFF = 0x49b0
FIRST, RETURN = 0xc000, 0xc04a
POLLS = (0xc000, 0xc085, 0xc0c5, 0xc0d1, 0xc11a, 0xc129, 0xc1e2, 0xc27c,
         0xc2f2, 0xc306, 0xc32d, 0xc3a4, 0xc3df)
EXITS = (0xc02c, 0xc03a, 0xc040, 0xc043, 0xc2a5, 0xc2b3, 0xc2bd, 0xc3eb)
RESUME = {a: k + 1 for k, a in enumerate(EXITS)} | {a: 9 + k for k, a in enumerate(POLLS)}
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
          'peek': ('\tcmp.w #$fff0,d6\n\tbhi.w \\1\n\tendm\nRASTER_PEEK_C3DF',
                   '\tcmp.w #$fff0,d6\n\tbhi.w \\1\n\tendm\nRASTER_PEEK_C3DF'.replace('$fff0', '$ffff')),
          'carry': ('\taddx.w d2,d7\n', '\tadd.w d2,d7\n'),
          'selector': ('raster_c0d1_entry-.entry,raster_c11a_entry-.entry',
                       'raster_c11a_entry-.entry,raster_c0d1_entry-.entry'),
          'visit': ('dc.w raster_c000_entry-.entry,', 'dc.w raster_c000-.entry,')}


@lru_cache(maxsize=None)
def native_image(diagnostic=False, plant=None, predecessor='direct'):
    p = program()
    source = (ROOT/'src/runtime/compute_raster.s').read_text()
    if plant == 'poll':
        old = '\trt_hle_rasterize_poll_7_local raster_c27c_pending\n'
        assert source.count(old) == 1
        lab = emit.label('SWOTL.EXE', 0xc27c)
        source = source.replace(old, f'{lab}_native_poll:\n\tnop\n{lab}_native_np:\n')
    elif plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    hooks = {('SWOTL.EXE', a): i for i, a in enumerate(POLLS)} if diagnostic else {}
    saved = p.diagnostic_hooks
    p.diagnostic_hooks = hooks
    try:
        macros = p.native_poll_text()
    finally:
        p.diagnostic_hooks = saved
    prefix = {'direct': [], 'jump': ['bra entry'], 'call': ['bsr entry', 'bra done'],
              'taken': ['cmp.w d0,d0', 'beq entry', 'illegal'],
              'fall': ['cmp.w d0,d0', 'bne done'], 'indirect': ['lea entry,a0', 'jmp (a0)'],
              'return': ['pea entry', 'rts']}[predecessor]
    text = [equates(), f'rt_irq equ ${B.STUB_AT["rt_irq"]:x}', macros,
            f'org ${B.SNIP:x}', 'dc.l done,0', *prefix, 'entry:',
            f'move.l ${B.SNIP+4:x},d7', f'move.l #${B.LOADSEG+0x49b:x},d6',
            'jsr rt_hle_rasterize', 'rts' if predecessor == 'call' else 'bra done',
            'done:', 'nop', source]
    for k, poll in enumerate(POLLS):
        text += emit.native_poll_stub(emit.label('SWOTL.EXE', poll), poll-CS_OFF,
                                      f'${B.LOADSEG+0x49b:x}', RESUME[poll])
    # Alias table at the end: each poll's visit and execution aliases.
    text += ['cnop 0,4'] + [f'dc.l {emit.label("SWOTL.EXE", poll)}_native_{kind}'
                            for poll in POLLS for kind in ('poll', 'np')]
    work = ROOT/f'tmp/rasterize-native-{os.getpid()}'
    work.mkdir(exist_ok=True)
    text = [('\t'+line if '\n' not in line and not line.endswith(':')
             and ' equ ' not in line and not line.startswith('\t') else line) for line in text]
    return B.D.assemble('\n'.join(text), work/f'{diagnostic}-{plant}-{predecessor}.bin')


def actual_state(m, got, fl, fx, writes, history, at):
    got.update(cs=at[0], ip=at[1])
    return dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                writes=writes, history=history, ram=m.gread(0, B.X.RAM))


def aliases(binary):
    """Address -> (poll, kind) from native_image's trailing alias table."""
    table = binary[len(binary)-8*len(POLLS):]
    return {int.from_bytes(table[4*k:4*k+4], 'big'): (POLLS[k//2], ('poll', 'np')[k % 2])
            for k in range(2*len(POLLS))}


def native_run(binary, ram, regs, selector, at, posted=False):
    binary = binary[:4] + selector.to_bytes(4, 'big') + binary[8:]
    m = B.D.M68k(ram, B.STUB_AT)
    m.irq_calls = []
    events = []
    names = aliases(binary)

    @B.U.CODE_CB
    def alias(h, addr, size, user):
        events.append(names[addr])
    try:
        for a in names:
            m.e.hook_range(B.U.HOOK_CODE, alias, a, a)
        m.e.write(B.SNIP, binary)
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        history = O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False,
            posted=posted)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100:
            raise RasterMismatch(('native run', info))
        # Exact-once visits: the caller's hook already executed the entry poll,
        # so an execution alias is reached only straight from its own visit.
        for k, (poll, kind) in enumerate(events):
            if kind == 'np' and (k == 0 or events[k-1] != (poll, 'poll')):
                raise RasterMismatch(('duplicate visit', hex(poll), selector, k))
        return actual_state(m, got, fl, fx, writes, history, at), m.r('d7'), len(m.irq_calls)
    finally:
        B.U.uc.uc_close(m.e.h)


def generated_run(ram, regs, start, stops, plant=False):
    binary, addresses = generated_image(plant)
    p = program()
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        m.extra_stops = {addresses[emit.label('SWOTL.EXE', a)]: f'stop-{a:x}' for a in stops}
        history = O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label('SWOTL.EXE', start)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['irq'] or not (info['stop'] or '').startswith('stop-'):
            raise RasterMismatch(('generated run', info))
        stop = int(info['stop'][5:], 16)
        return actual_state(m, got, fl, fx, writes, history, (regs['cs'], stop-CS_OFF))
    finally:
        B.U.uc.uc_close(m.e.h)


def check(name, expected, actual, stop):
    errors = O.compare(expected, actual, program().live_in['SWOTL.EXE', stop])
    if errors:
        raise RasterMismatch((name, hex(stop), errors))


def merge(total, part):
    """Chain segment results: union writes, concatenated byte histories."""
    if total is None:
        return dict(part, history={a: list(v) for a, v in part['history'].items()})
    total = dict(total, registers=part['registers'], flags=part['flags'], undefined=part['undefined'],
                 ram=part['ram'], at=part['at'], writes=total['writes'] | part['writes'])
    for a, v in part['history'].items():
        total['history'].setdefault(a, []).extend(v)
    return total


def chain(name, ram, regs, plant=None, generated=True, mutate=None, generated_plant=False):
    """Walk one call. Returns the number of compared points."""
    cs = regs['cs']
    polls = {(cs, a-CS_OFF) for a in POLLS}
    stops = tuple(sorted(polls | {(cs, a-CS_OFF) for a in EXITS}))
    regs, ram = run_to(ram, regs, polls | {(cs, RETURN-CS_OFF)})
    diag, full = native_image(True, plant), native_image(False, plant)
    count = 0
    while regs['ip'] != RETURN-CS_OFF:
        at = regs['ip'] + CS_OFF
        if mutate:
            ram, regs = mutate(at, ram, regs)
        actual_full, result_full, irqs_full = native_run(full, ram, regs, POLLS.index(at), (cs, 0))
        accumulated = None
        while True:     # segment by segment to the next exit
            expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, stops=stops)
            stop = expected['at'][1] + CS_OFF
            accumulated = merge(accumulated, expected)
            actual, result, irqs = native_run(diag, ram, regs, POLLS.index(at), expected['at'])
            if result != RESUME[stop] or irqs != int(stop in POLLS):
                raise RasterMismatch((name, 'diagnostic', hex(at), hex(stop), result, irqs))
            check(name+' diagnostic', expected, actual, stop)
            # A posted interrupt: the first poll reached hands off through its tail.
            actual, result, irqs = native_run(full, ram, regs, POLLS.index(at), expected['at'], True)
            if result != RESUME[stop] or irqs != int(stop in POLLS):
                raise RasterMismatch((name, 'posted', hex(at), hex(stop), result, irqs))
            check(name+' posted', expected, actual, stop)
            REACHED.add(stop)
            if generated:
                check(name+' generated', expected,
                      generated_run(ram, regs, at, POLLS+EXITS, generated_plant), stop)
            count += 1
            ram = captured_ram(expected['ram'], ram)
            regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
            if stop in EXITS:
                break
            at = stop
        if result_full != RESUME[stop] or irqs_full:
            raise RasterMismatch((name, 'native', hex(stop), result_full, irqs_full))
        actual_full['registers'].update(cs=cs, ip=accumulated['at'][1])
        check(name+' native', accumulated, actual_full, stop)
        regs, ram = run_to(ram, regs, polls | {(cs, RETURN-CS_OFF)})
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
    """Guards and pointer peeks decline before any mutation."""
    binary = native_image(False, plant)
    name, ram, regs = next(captured())
    cs = regs['cs']
    regs, ram = run_to(ram, regs, {(cs, FIRST-CS_OFF)})
    cases = [(seg, value, 0) for seg in ('ds', 'es', 'ss')
             for value in (0, cs+0xfff, 0x9001, 0xffff)]
    cases += [('es', regs['ss']+0xfff, 0), ('es', regs['ss']-0xfff, 0),
              ('flags', regs['flags'] | 0x400, 0), ('flags', regs['flags'], 13)]
    count = 0
    for key, value, selector in cases:
        changed = dict(regs, **{key: value & 0xffff})
        actual, result, irqs = native_run(binary, ram, changed, selector, (cs, regs['ip']))
        if result or irqs or actual['writes'] or actual['history'] or actual['ram'] != ram:
            raise RasterMismatch((key, value, selector, 'decline mutation'))
        if any(actual['registers'][k] != v for k, v in changed.items() if k in actual['registers']
               and k not in ('cs', 'ip')):
            raise RasterMismatch((key, value, 'decline registers'))
        count += 1
    return count


def wrap_cases(plant=None):
    """Record pointers past FFF0h: entry declines, an internal arrival
    resumes at the poll. Priority searches wrap BX through 0."""
    count = 0
    full = native_image(False, plant)
    name, ram, regs = next(captured())
    cs = regs['cs']
    polls = {(cs, a-CS_OFF) for a in POLLS}
    stops = tuple(sorted(polls | {(cs, a-CS_OFF) for a in EXITS}))
    regs, ram = run_to(ram, regs, polls)
    seen = set()
    for _ in range(4000):
        at = regs['ip'] + CS_OFF
        es, si, bx = regs['es']*16, regs['si'], regs['bx']
        trial = None
        if at == 0xc1e2 and at not in seen:
            trial = ('c1e2', [(es+si, 0xfff4)])
        elif at == 0xc0d1 and at not in seen:
            trial = ('c0d1', [(es+((bx+2) & 0xffff), 0xfff8)])
        elif at == 0xc3df and at not in seen:
            trial = ('c3df', [(es+((si+2) & 0xffff), 0xfffa)])
        elif at in (0xc2f2, 0xc32d) and at not in seen:
            trial = ('bx', None)
        if trial:
            seen.add(at)
            label, pokes = trial
            if pokes:
                changed = bytearray(ram)
                for addr, value in pokes:
                    changed[addr:addr+2] = value.to_bytes(2, 'little')
                memory, state = captured_ram(changed, ram), regs
                actual, result, irqs = native_run(full, memory, state, POLLS.index(at), (cs, regs['ip']))
                if result or actual['writes'] or actual['ram'] != memory:
                    raise RasterMismatch((label, 'peek decline', result))
                count += 1
            else:
                for value in (0x0001, 0x41f2, 0xffff, 0x8001):
                    state = dict(regs, bx=value)
                    expected = O.run(ram, state, (cs, RETURN-CS_OFF), limit=10**7, stops=stops)
                    stop = expected['at'][1] + CS_OFF
                    actual, result, irqs = native_run(native_image(True, plant), ram, state,
                                                      POLLS.index(at), expected['at'])
                    if result != RESUME[stop]:
                        raise RasterMismatch(('bx wrap', hex(value), result, hex(stop)))
                    check(f'bx wrap {value:x}', expected, actual, stop)
                    count += 1
        if seen >= {0xc1e2, 0xc0d1, 0xc3df, 0xc2f2, 0xc32d}:
            break
        expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, stops=stops)
        ram = captured_ram(expected['ram'], ram)
        regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
        if expected['at'][1] + CS_OFF in EXITS:
            regs, ram = run_to(ram, regs, polls)
    if not seen >= {0xc1e2, 0xc0d1, 0xc3df, 0xc2f2, 0xc32d}:
        raise RasterMismatch(('wrap coverage', sorted(map(hex, seen))))
    return count


def internal_bail(plant=None):
    """An internal arrival at C1E2 with a wrapping record resumes there."""
    full = native_image(False, plant)
    name, ram, regs = next(captured())
    cs = regs['cs']
    polls = {(cs, a-CS_OFF) for a in POLLS}
    exits = tuple((cs, a-CS_OFF) for a in EXITS)
    stops = tuple(sorted(polls)) + exits
    regs, ram = run_to(ram, regs, polls)
    for _ in range(4000):
        at = regs['ip'] + CS_OFF
        expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, stops=stops)
        stop = expected['at'][1] + CS_OFF
        if stop == 0xc1e2 and at != 0xc1e2:
            es, si = regs['es']*16, expected['registers']['si']
            changed = bytearray(ram)
            changed[es+si:es+si+2] = (0xfff4).to_bytes(2, 'little')
            memory = captured_ram(changed, ram)
            want = O.run(memory, regs, (cs, RETURN-CS_OFF), limit=10**7,
                         stops=((cs, 0xc1e2-CS_OFF),) + exits)
            actual, result, irqs = native_run(full, memory, regs, POLLS.index(at), want['at'])
            if want['at'][1] + CS_OFF != 0xc1e2 or result != RESUME[0xc1e2] or irqs:
                raise RasterMismatch(('internal bail', hex(at), result))
            check('internal bail', want, actual, 0xc1e2)
            return 1
        ram = captured_ram(expected['ram'], ram)
        regs = dict(expected['registers'], cs=cs, ip=expected['at'][1], flags=expected['flags'])
        if stop in EXITS:
            regs, ram = run_to(ram, regs, polls)
    raise RasterMismatch('no internal arrival at C1E2')


def dispatch_cases(plant=False):
    """The generated resume table (21 ids) on the 68k core: every id reaches
    its own target, 0 and out-of-range ids stop loudly."""
    lines = compute.polled_dispatch('cx', [f'target{k}' for k in range(len(RESUME))], '$1234')
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
    stops = tuple((cs, a-CS_OFF) for a in POLLS+EXITS)
    expected = O.run(ram, regs, (cs, RETURN-CS_OFF), limit=10**7, stops=stops)
    stop = expected['at'][1] + CS_OFF
    for predecessor in ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return'):
        try:
            actual, result, irqs = native_run(native_image(True, None, predecessor), ram, regs, 0,
                                              expected['at'])
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
    if not plant and REACHED != set(POLLS+EXITS):
        raise RasterMismatch(('coverage', sorted(map(hex, set(POLLS+EXITS) - REACHED))))
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('generated', 'native', 'predecessors', 'polls', 'sabotage'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.native or args.generated or args.polls:
        print('rasterize:', run_all(generated=args.generated), 'original poll/exit points pass', flush=True)
        print('rasterize:', decline_cases(), 'decline cases pass', flush=True)
        print('rasterize:', wrap_cases(), 'wrap cases pass', flush=True)
        print('rasterize:', internal_bail(), 'internal bail-out passes', flush=True)
        print('rasterize:', dispatch_cases(), 'resume table cases pass', flush=True)
    if args.predecessors:
        n, failures = predecessor_cases()
        assert not failures, failures
        print('rasterize:', n, 'predecessor cases pass', flush=True)
    if args.sabotage:
        for plant in ('write', 'index', 'carry', 'poll', 'selector', 'visit'):
            try:
                run_all(plant, generated=False)
            except RasterMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
        for plant, probe in (('guard', decline_cases), ('peek', wrap_cases)):
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
