#!/usr/bin/env python3
"""Original-x86 oracle for recorded compute-entry states (local files only).

Entry directory: a DOSBox snapshot (ram.bin, regs.txt), or a synthetic test
record (ram.bin, regs.json). All 16-bit registers, IP and FLAGS are required.
The caller supplies the original resume CS:IP and its translator-derived live
flags. No native implementation or expected result is stored in this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import uc as U
import x86_diff as X
from translator.decode import decode
from translator.interp import State, step
from translator.ir import FLAG_BIT, FLAGS


class CapturedRAM(bytes):
    """Mapped test RAM with the recorded extent retained, not inferred from padding."""
    def __new__(cls, data, captured_bytes):
        if not 0 < captured_bytes <= len(data):
            raise ValueError('invalid captured-memory extent')
        ram = super().__new__(cls, data)
        ram.captured_bytes = captured_bytes
        return ram


def memory_known(addr, size, captured_bytes):
    return 0 <= addr and 0 < size and addr + size <= captured_bytes


def load_entry(path):
    ram = (path / 'ram.bin').read_bytes()
    captured_bytes = len(ram)
    if (path / 'regs.json').exists():
        regs = json.loads((path / 'regs.json').read_text())
    else:
        import re
        recorded = dict(re.findall(r'\b([a-z]+)=([0-9a-f]+)', (path / 'regs.txt').read_text()))
        regs = {r: int(recorded[r], 16) for r in X.REGS + X.SEGS + ('ip', 'flags')}
        if len(ram) != 0x100000:
            raise ValueError('DOSBox snapshot requires 1 MiB RAM')
        ram += bytes(X.RAM - len(ram))
    if len(ram) != X.RAM or set(regs) != set(X.REGS + X.SEGS + ('ip', 'flags')):
        raise ValueError('entry requires complete RAM and register state')
    if any(type(v) is not int or not 0 <= v <= 0xffff for v in regs.values()):
        raise ValueError('entry registers must be 16-bit integers')
    return CapturedRAM(ram, captured_bytes), regs


def check_code_writes(written, fetched):
    """A static compute entry may not rewrite instructions it executes."""
    if written & fetched:
        raise ValueError('oracle self-modifying code entry')


class DivideFault(ValueError):
    """The original raised INT 00h (U8): the native must decline before any
mutation in its segment. `state` is the original's at the faulting instruction
(registers with its IP, FLAGS, undefined flags, RAM, write history), where the
declined generated code enters rt_fault."""

    def __init__(self, message, state):
        super().__init__(message)
        self.state = state


def run(ram, registers, resume, limit=100000, stops=(), returns=()):
    """Execute original bytes, stopping *before* the guest return.

`stops` (U5 sync sites, CS:IP): also stop before one of them once at least one
instruction ran, so a chain of runs visits each arrival; `at` names the stop.
`returns` (U8): the row's other root returns, CS:IP, stopped before like
`resume`. A divide error raises DivideFault.

IR supplies only the undefined-flag mask. Unicorn supplies all expected values,
flow and writes. Faults and external effects fail closed; their guard/fallback
cases belong in the block differential before a compute row can be enabled.
    """
    x = X.Oracle(ram)
    history = {}
    captured_bytes = getattr(ram, 'captured_bytes', len(ram))
    outside = []

    @U.MEM_CB
    def access(h, kind, addr, size, value, user):
        if not memory_known(addr, size, captured_bytes):
            outside.append((addr, size))
            x.e.stop()
        return True

    @U.MEM_CB
    def write(h, kind, addr, size, value, user):
        for k in range(size):
            history.setdefault(addr + k, []).append((value >> (8 * k)) & 0xff)
        return True

    x.e.hook(U.HOOK_MEM_WRITE, write)
    x.e.hook(U.HOOK_MEM_READ | U.HOOK_MEM_WRITE, access)
    regs = dict(registers)
    word = regs.pop('flags')
    flags = {f: (word >> FLAG_BIT[f]) & 1 for f in FLAGS}
    state = State(dict(regs, flagsx=word & 0xf000), dict(flags), bytearray(ram), regs['ip'])
    written, fetched, count = set(), set(), 0
    # The original return remains generated: modifying it is outside the
    # contract even though this oracle stops immediately before executing it.
    ends = {tuple(resume), *(tuple(r) for r in returns)}
    for cs, ip in ends:
        return_at = cs * 16 + ip
        if memory_known(return_at, 1, captured_bytes) and ram[return_at] in (0xc2, 0xc3, 0xca, 0xcb):
            return_size = 3 if ram[return_at] in (0xc2, 0xca) else 1
            fetched.update(range(return_at, min(return_at + return_size, captured_bytes)))
    stops = {tuple(s) for s in stops}
    try:
        while (regs['cs'], regs['ip']) not in ends and \
                not (count and (regs['cs'], regs['ip']) in stops):
            if count >= limit:
                raise ValueError('oracle instruction limit before resume')
            at = regs['cs'] * 16 + regs['ip']
            check_code_writes(written, {at})
            insn = decode(x.e.read(at, 16), regs['ip'])
            if not memory_known(at, insn.size, captured_bytes):
                raise ValueError('oracle instruction fetch outside captured memory')
            fetched.update(range(at, at + insn.size))
            check_code_writes(written, fetched)
            step(state)  # only state.undef is used as expected-result metadata
            case = (regs, flags, word & 0xf000, regs['ip'], [])
            err, regs, word, mem, ints, outs, writes = x.run(case, 1)
            if outside:
                raise ValueError(f'oracle access outside captured memory: {outside}')
            if ints[:1] == [0] and insn.op in ('div', 'idiv', 'aam') and not outs:
                before = bytearray(ram[:X.RAM])
                for addr, values in history.items():
                    before[addr] = values[-1]
                raise DivideFault(f'oracle divide error at {at:05x}', dict(
                    registers=dict(case[0]), flags=word, undefined=sorted(state.undef), ram=bytes(before),
                    history={a: list(v) for a, v in history.items()}))
            if err or ints or outs or 'trap' in regs or insn.op == 'in':
                raise ValueError(f'oracle external effect/fault at {at:05x}: {err, ints, outs}')
            written.update(writes)
            check_code_writes(written, fetched)
            flags = {f: (word >> FLAG_BIT[f]) & 1 for f in FLAGS}
            state.regs.update(regs, flagsx=word & 0xf000)
            state.ip, state.flags = regs['ip'], dict(flags)
            for addr, value in mem.items():
                state.mem[addr] = value
            count += 1
        if not count:
            raise ValueError('zero-instruction oracle is not coverage')
        return dict(registers=regs, flags=word, undefined=sorted(state.undef),
                    writes=written, history=history, ram=x.e.read(0, X.RAM), instructions=count,
                    at=(regs['cs'], regs['ip']))
    finally:
        U.uc.uc_close(x.e.h)


def compare(expected, actual, live):
    """No register/memory ignore list. Dead/undefined *status* flags only omitted."""
    errors = []
    for r, v in expected['registers'].items():
        if actual['registers'].get(r) != v:
            errors.append(f'register {r}')
    checked = (set(live) | {'DF', 'IF', 'TF'}) - set(expected['undefined'])
    mask = 0x7000 | sum(1 << FLAG_BIT[f] for f in checked)
    if (expected['flags'] ^ actual['flags']) & mask:
        errors.append('live flags')
    if expected['writes'] != actual['writes']:
        errors.append('write addresses')
    if expected['history'] != actual['history']:
        errors.append('write values/history')
    if expected['ram'] != actual['ram']:
        errors.append('RAM')
    return errors


def watch_native(m):
    """Per-byte value histories tolerate only merging/reordering distinct bytes."""
    import m68k_diff as D
    history = {}
    captured_bytes = getattr(m.bg, 'captured_bytes', len(m.bg))

    @U.MEM_CB
    def access(h, kind, addr, size, value, user):
        if D.GUEST_LO <= addr and addr + size - 1 <= D.TOP:
            guest = D.TOP - addr - size + 1
            if not memory_known(guest, size, captured_bytes):
                m.stop = 'compute_uncaptured_memory'
                m.e.stop()
        return True

    @U.MEM_CB
    def write(h, kind, addr, size, value, user):
        if D.GUEST_LO <= addr and addr + size - 1 <= D.TOP:
            for k in range(size):
                # Low host byte is the high guest byte (reversed RAM).
                guest = D.TOP - addr - size + 1 + k
                history.setdefault(guest, []).append((value >> (8 * k)) & 0xff)
        return True

    m.e.hook(U.HOOK_MEM_WRITE, write)
    m.e.hook(U.HOOK_MEM_READ | U.HOOK_MEM_WRITE, access)
    return history


# U5 latency bound (native-compute.md): one PIT period at the game's 236.7 Hz
# in 14.19 MHz model cycles, rounded down.
PIT_PERIOD_CYCLES = 59_900


class PollGaps:
    """Model cycles between poll visits (reads of G_IRQ) on the host 68k core.

    Weights are tools/cost_model.json's, without the i-cache loop discount
    (an upper estimate); every mul/div in `image` (loaded at CODE) is charged
    as one. `gaps` holds each
    stretch from the start or a visit to the next visit; `open` the last one.
    """
    def __init__(self, m, image=b''):
        import m68k_diff as D
        coef = json.loads((ROOT / 'tools/cost_model.json').read_text())['coef']
        self.gaps, self.open = [], 0.0
        self.irq = D.TOP + 9   # G_IRQ(a6)
        last = {'end': None}

        @U.CODE_CB
        def code(h, addr, size, user):
            at = addr - D.CODE  # opcodes from the loaded image (no reads inside the hook)
            op = int.from_bytes(image[at:at + 2], 'big') if 0 <= at < len(image) - 1 else 0
            cost = size * coef['bytes']
            if last['end'] is not None and addr != last['end']:
                cost += coef['taken']
            if op & 0xf1c0 in (0xc0c0, 0xc1c0, 0x80c0, 0x81c0) or op & 0xffc0 in (0x4c00, 0x4c40):
                cost += coef['muldiv']
            self.open += cost
            last['end'] = addr + size

        @U.MEM_CB
        def access(h, kind, addr, size, value, user):
            if kind == 17:  # UC_MEM_WRITE
                self.open += coef['writes']
                return True
            self.open += coef['reads']
            if addr <= self.irq < addr + size:
                self.gaps.append(self.open)
                self.open = 0.0
            return True

        m.e.hook(U.HOOK_CODE, code)
        m.e.hook(U.HOOK_MEM_READ | U.HOOK_MEM_WRITE, access)

    def longest(self):
        return max(self.gaps + [self.open])


def generated(path, module, first, cache, end=None):
    """Exercise the recorder/oracle against current generated code, no HLE row.

    This establishes the harness on original game entries. Future authorized
    native rows must additionally exercise their handled and fallback arms.
    """
    import random
    import m68k_blocks as B
    from translator import compute, emit
    p = emit.Program()
    node = (module, first)
    rets, escapes = p.reach(node, {})
    if escapes or not rets:
        raise ValueError('routine needs proved returns')
    region = compute.validate(p, node, max(rets), end)
    u = p.units[module]
    ram, regs = load_entry(path)
    cs = u.cs[first] + B.LOADSEG
    if (regs['cs'], regs['ip']) != (cs, u.ip_of(first)):
        raise ValueError('snapshot is not at the requested entry')
    ends = {(u.cs[r[1]] + B.LOADSEG, u.ip_of(r[1])): r for r in region.returns}
    expected = run(ram, regs, next(iter(ends)), returns=ends)
    resume = ends[expected['at']]
    end = expected['at']
    cache.mkdir(parents=True, exist_ok=True)
    binary, addresses = B.program_image(p, cache)
    m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
    try:
        m.load(binary)
        history = watch_native(m)
        m.extra_stops = {addresses[emit.label(*r)]: 'compute_resume' if r == resume
                         else 'compute_other_return' for r in region.returns}
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label(*node)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(33), irq=False)
        if info['err'] or info['stop'] != 'compute_resume' or outs or info['irq']:
            raise AssertionError(info)
        got.update(cs=end[0], ip=end[1])
        actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                      writes=writes, history=history, ram=m.gread(0, X.RAM))
        errors = compare(expected, actual, p.live_in[resume])
        if errors:
            raise AssertionError(errors)
        return expected
    finally:
        U.uc.uc_close(m.e.h)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('entry', type=Path)
    ap.add_argument('--resume', help='hex CS:IP, before original return')
    ap.add_argument('--generated', help='compare generated MODULE+hex-offset (no native row)')
    ap.add_argument('--end', help='hex range end past the return (hle.csv end, U8)')
    args = ap.parse_args()
    if args.generated:
        module, first = args.generated.split('+')
        result = generated(args.entry, module, int(first, 16), ROOT / 'tmp/compute-oracle',
                           int(args.end, 16) if args.end else None)
    else:
        if not args.resume:
            ap.error('--resume or --generated is required')
        ram, regs = load_entry(args.entry)
        result = run(ram, regs, tuple(int(n, 16) for n in args.resume.split(':')))
    print(json.dumps(dict(instructions=result['instructions'], writes=len(result['writes']),
                          registers=result['registers'], flags=result['flags'],
                          undefined=result['undefined'],
                          ram_sha256=hashlib.sha256(result['ram']).hexdigest()), sort_keys=True))


if __name__ == '__main__':
    main()
