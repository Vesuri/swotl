"""SPAZ OPL delay loops (F9): original x86 is the oracle.

Entries come from original-game captures at the loop heads (first, early and
deep visits), plus mutations of CX (1, 2, 0 = 65536 passes) and SP (stack
slot wrapping the 64K index). Per entry: the native to the endpoint, the
diagnostic native (every poll hands off) segment by segment, a posted
interrupt, the generated arm (hook declined), and exact-once visits."""
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

MODULE, SEG = 'SPAZ.OVL', 0x1770
OFF = 0xd03 - 0xac3                     # module offset - IP in SEG
ROWS = {'opl_wait_index': (0xd03, 0xd07, 'index'), 'opl_wait_data': (0xd0f, 0xd17, 'data')}
PLANTS = {'store': ('\tmove.w d0,(a0)\n\tmove.w d0,(a0)\n\tbra.s opl_wait_data_count\n',
                    '\tmove.w d0,(a0)\n\tbra.s opl_wait_data_count\n'),
          'count': ('\tsubq.w #1,d1\n\tbne.s opl_wait_index_poll\n',
                    '\tsubq.w #2,d1\n\tbne.s opl_wait_index_poll\n'),
          'slot': ('\taddq.w #2,d7\n\tlea -1(a2,d7.w),a0\n\tmove.w d0,(a0)\n\tmove.w d0,(a0)\n',
                   '\taddq.w #1,d7\n\tlea -1(a2,d7.w),a0\n\tmove.w d0,(a0)\n\tmove.w d0,(a0)\n'),
          'visit': ('\tmove.w d0,(a0)\n\tbra.s opl_wait_index_count\n', '\tbra.s opl_wait_index_poll\n')}


class DelayMismatch(AssertionError):
    pass


def captured():
    directories = sorted((ROOT/'tmp/pc-runs').glob('native-F9-opl2-*'))
    assert len(directories) == 2, 'two original-game fixtures required'
    for directory in directories:
        paths = sorted((directory/'trace').glob('snap-*'))
        assert len(paths) == 6, directory
        for path in paths:
            ram, regs = O.load_entry(path)
            yield f'{directory.name[-18:]}/{path.name}', ram, regs


def cases(service):
    first, _, tag = ROWS[service]
    entries = [e for e in captured() if f'snap-{tag}' in e[0]]
    yield from entries
    name, ram, regs = entries[0]
    for cx in (1, 2, 0):
        yield f'{name}+cx={cx}', ram, dict(regs, cx=cx)
    for sp in (0, 1, 2, 0xfffe, 0xffff, 0x8000, 0x8001):
        yield f'{name}+sp={sp:x}', ram, dict(regs, sp=sp, cx=3)


@lru_cache(maxsize=1)
def program():
    return emit.Program()


@lru_cache(maxsize=None)
def native_image(service, diagnostic=False, plant=None):
    p = program()
    source = (ROOT/'src/runtime/compute_opl.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    first = ROWS[service][0]
    saved = p.diagnostic_hooks
    p.diagnostic_hooks = {(MODULE, first): 0} if diagnostic else {}
    try:
        macros = p.native_poll_text()
    finally:
        p.diagnostic_hooks = saved
    lab = emit.label(MODULE, first)
    text = [equates(), f'rt_irq equ ${B.STUB_AT["rt_irq"]:x}', macros,
            f'org ${B.SNIP:x}', 'dc.l done', 'moveq #0,d7', f'move.l #${B.LOADSEG+SEG:x},d6',
            f'jsr rt_hle_{service}', 'bra done', 'done:', 'nop', source]
    for other in ROWS.values():
        text += emit.native_poll_stub(emit.label(MODULE, other[0]), other[0]-OFF,
                                      f'${B.LOADSEG+SEG:x}', 2)
    text += ['cnop 0,4', f'dc.l {lab}_native_poll', f'dc.l {lab}_native_np']
    text = [('\t'+line if '\n' not in line and not line.endswith(':')
             and ' equ ' not in line and not line.startswith('\t') else line) for line in text]
    work = ROOT/f'tmp/opl-delay-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.D.assemble('\n'.join(text), work/f'{service}-{diagnostic}-{plant}.bin')


def state(m, got, fl, fx, writes, history, at):
    got.update(cs=at[0], ip=at[1])
    return dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                writes=writes, history=history, ram=m.gread(0, B.X.RAM))


def native_run(binary, ram, regs, at, posted=False):
    poll_pc, np_pc = (int.from_bytes(binary[k:k+4], 'big') for k in (len(binary)-8, len(binary)-4))
    m = B.D.M68k(ram, B.STUB_AT)
    m.irq_calls = []
    events = []

    @B.U.CODE_CB
    def alias(h, addr, size, user):
        events.append('np' if addr == np_pc else 'poll')
    try:
        for a in (poll_pc, np_pc):
            m.e.hook_range(B.U.HOOK_CODE, alias, a, a)
        m.e.write(B.SNIP, binary)
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        history = O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+4,
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False,
            posted=posted)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100:
            raise DelayMismatch(('native run', info))
        # Exact-once visits: the hook already executed the entry poll.
        for k, event in enumerate(events):
            if event == 'np' and (k == 0 or events[k-1] != 'poll'):
                raise DelayMismatch(('duplicate visit', k))
        return state(m, got, fl, fx, writes, history, at), m.r('d7'), len(m.irq_calls)
    finally:
        B.U.uc.uc_close(m.e.h)


@lru_cache(maxsize=1)
def generated_image():
    work = ROOT/f'tmp/opl-delay-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.program_image(program(), work)


def generated_run(ram, regs, start, stop):
    binary, addresses = generated_image()
    p = program()
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        m.extra_stops = {addresses[emit.label(MODULE, stop)]: 'stop'}
        history = O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label(MODULE, start)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['irq'] or info['stop'] != 'stop':
            raise DelayMismatch(('generated run', info))
        return state(m, got, fl, fx, writes, history, (regs['cs'], stop-OFF))
    finally:
        B.U.uc.uc_close(m.e.h)


def check(name, expected, actual, stop):
    errors = O.compare(expected, actual, program().live_in[MODULE, stop])
    if errors:
        raise DelayMismatch((name, hex(stop), errors))


def merge(total, part):
    if total is None:
        return dict(part, history={a: list(v) for a, v in part['history'].items()})
    total = dict(total, registers=part['registers'], flags=part['flags'], undefined=part['undefined'],
                 ram=part['ram'], at=part['at'], writes=total['writes'] | part['writes'])
    for a, v in part['history'].items():
        total['history'].setdefault(a, []).extend(v)
    return total


def run_case(service, name, ram, regs, plant=None, generated=True, segments=8):
    first, end, _ = ROWS[service]
    cs = regs['cs']
    assert (cs, regs['ip']) == (B.LOADSEG+SEG, first-OFF), (name, hex(regs['ip']))
    full = native_image(service, False, plant)
    expected = O.run(ram, regs, (cs, end-OFF), limit=10**7)
    actual, result, irqs = native_run(full, ram, regs, expected['at'])
    if result != 1 or irqs:
        raise DelayMismatch((name, 'native', result, irqs))
    check(name+' native', expected, actual, end)
    if generated:
        check(name+' generated', expected, generated_run(ram, regs, first, end), end)
    # Segments: every poll hands off (diagnostic) or takes a posted interrupt.
    diag, count, total = native_image(service, True, plant), 0, None
    stops = ((cs, first-OFF),)
    while count < segments:
        part = O.run(ram, regs, (cs, end-OFF), limit=10**7, stops=stops)
        stop = part['at'][1] + OFF
        want = 1 if stop == end else 2
        for label, binary, posted in (('diagnostic', diag, False), ('posted', full, True)):
            got, result, irqs = native_run(binary, ram, regs, part['at'], posted)
            if result != want or irqs != int(want == 2):
                raise DelayMismatch((name, label, count, result, irqs))
            check(f'{name} {label} {count}', part, got, stop)
        total = merge(total, part)
        count += 1
        if stop == end:
            break
        ram = O.CapturedRAM(bytes(part['ram']), getattr(ram, 'captured_bytes', len(ram)))
        regs = dict(part['registers'], cs=cs, ip=part['at'][1], flags=part['flags'])
    return count + 1 + generated


def run_all(plant=None, generated=True):
    total = 0
    for service in ROWS:
        for name, ram, regs in cases(service):
            total += run_case(service, name, ram, regs, plant, generated)
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    print('opl delay:', run_all(), 'native, generated and poll-segment points pass', flush=True)
    if args.sabotage:
        for plant in PLANTS:
            try:
                run_all(plant, generated=False)
            except DelayMismatch as error:
                print('caught', plant, str(error)[:200], flush=True)
            else:
                raise AssertionError(plant+' escaped')
