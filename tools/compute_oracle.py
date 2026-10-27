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
(registers with its IP, FLAGS, undefined flags, RAM, written addresses), where
the declined generated code enters rt_fault."""

    def __init__(self, message, state):
        super().__init__(message)
        self.state = state


def run(ram, registers, resume, limit=100000, returns=(), cells=frozenset()):
    """Execute original bytes, stopping *before* the guest return.

`returns` (U8): the row's other root returns or endpoints, CS:IP, stopped
before like `resume`; `at` names the one reached. A divide error raises
DivideFault. `cells` (user 2026-10-27, native-compute "Code writes and the cell
walk"): linear addresses of D16 cell caches (`cell_addresses`) whose writes
may meet fetches (the RET plant the walk executes, its restore); every other
code write still fails, and compare checks the cells' write addresses.

IR supplies only the undefined-flag mask. Unicorn supplies all expected values,
flow and writes. Faults and external effects fail closed; their guard/fallback
cases belong in the block differential before a compute row can be enabled.
    """
    x = X.Oracle(ram)
    captured_bytes = getattr(ram, 'captured_bytes', len(ram))
    outside = []

    @U.MEM_CB
    def access(h, kind, addr, size, value, user):
        if not memory_known(addr, size, captured_bytes):
            outside.append((addr, size))
            x.e.stop()
        return True

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
    try:
        while (regs['cs'], regs['ip']) not in ends:
            if count >= limit:
                raise ValueError('oracle instruction limit before resume')
            at = regs['cs'] * 16 + regs['ip']
            check_code_writes(written - cells, {at})
            insn = decode(x.e.read(at, 16), regs['ip'])
            if not memory_known(at, insn.size, captured_bytes):
                raise ValueError('oracle instruction fetch outside captured memory')
            fetched.update(range(at, at + insn.size))
            check_code_writes(written - cells, fetched)
            step(state)  # only state.undef is used as expected-result metadata
            case = (regs, flags, word & 0xf000, regs['ip'], [])
            err, regs, word, mem, ints, outs, writes = x.run(case, 1)
            if outside:
                raise ValueError(f'oracle access outside captured memory: {outside}')
            if ints[:1] == [0] and insn.op in ('div', 'idiv', 'aam') and not outs:
                raise DivideFault(f'oracle divide error at {at:05x}', dict(
                    registers=dict(case[0]), flags=word, undefined=sorted(state.undef),
                    ram=bytes(state.mem[:X.RAM]), writes=set(written)))
            if err or ints or outs or 'trap' in regs or insn.op == 'in':
                raise ValueError(f'oracle external effect/fault at {at:05x}: {err, ints, outs}')
            written.update(writes)
            check_code_writes(written - cells, fetched)
            flags = {f: (word >> FLAG_BIT[f]) & 1 for f in FLAGS}
            state.regs.update(regs, flagsx=word & 0xf000)
            state.ip, state.flags = regs['ip'], dict(flags)
            for addr, value in mem.items():
                state.mem[addr] = value
            count += 1
        if not count:
            raise ValueError('zero-instruction oracle is not coverage')
        return dict(registers=regs, flags=word, undefined=sorted(state.undef),
                    writes=written, ram=x.e.read(0, X.RAM), instructions=count,
                    at=(regs['cs'], regs['ip']))
    finally:
        U.uc.uc_close(x.e.h)


VRAM = range(0xa0000, 0xc0000)


def code_addresses(p, loadseg):
    """Linear addresses of every decoded guest instruction byte (compare's `code`)."""
    return frozenset((loadseg + u.cs[o]) * 16 + u.ip_of(o) + k
                     for u in p.units.values() for o, i in u.insns.items() for k in range(i.size))


def cell_addresses(p, loadseg):
    """Linear addresses of the D16 cell caches' bytes (run's `cells`; compare's
`code` for a row that calls the walk)."""
    return frozenset(a for _, seg, first, n in p.cells
                     for a in range((loadseg + seg) * 16 + first, (loadseg + seg) * 16 + first + n))


def compare(expected, actual, live, code=frozenset()):
    """No register/memory ignore list. Dead/undefined *status* flags only omitted.

RC5: all RAM at the resume; written-address sets only for code (`code`, linear
addresses: SMC) and VRAM. Nothing observes the order or count of other writes."""
    errors = []
    for r, v in expected['registers'].items():
        if actual['registers'].get(r) != v:
            errors.append(f'register {r}')
    checked = (set(live) | {'DF', 'IF', 'TF'}) - set(expected['undefined'])
    mask = 0x7000 | sum(1 << FLAG_BIT[f] for f in checked)
    if (expected['flags'] ^ actual['flags']) & mask:
        errors.append('live flags')
    def watched(writes):
        return {a for a in writes if a in VRAM or a in code}
    if watched(expected['writes']) != watched(actual['writes']):
        errors.append('code/VRAM write addresses')
    if expected['ram'] != actual['ram']:
        errors.append('RAM')
    return errors


def watch_native(m):
    """Stop the native run at any access outside the captured memory."""
    import m68k_diff as D
    captured_bytes = getattr(m.bg, 'captured_bytes', len(m.bg))

    @U.MEM_CB
    def access(h, kind, addr, size, value, user):
        if D.GUEST_LO <= addr and addr + size - 1 <= D.TOP:
            guest = D.TOP - addr - size + 1
            if not memory_known(guest, size, captured_bytes):
                m.stop = 'compute_uncaptured_memory'
                m.e.stop()
        return True

    m.e.hook(U.HOOK_MEM_READ | U.HOOK_MEM_WRITE, access)


def generated(path, module, first, cache, end=None):
    """Exercise the recorder/oracle against generated code (native hooks decline).

    This establishes the harness on original game entries. Future authorized
    native rows must additionally exercise their handled and fallback arms.
    """
    import random
    import m68k_blocks as B
    from translator import compute, emit
    p = emit.Program()
    node = (module, first)
    if node in p.compute_bodies:
        if end is not None:
            raise ValueError('declared compute row cannot extend its range')
        region = p.compute_bodies[node]  # Program proved the row
    else:
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
        watch_native(m)
        m.extra_stops = {addresses[emit.label(*r)]: 'compute_resume' if r == resume
                         else 'compute_other_return' for r in region.returns}
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(addresses[emit.label(*node)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(33), irq=False)
        if info['err'] or info['stop'] != 'compute_resume' or outs or info['irq']:
            raise AssertionError(info)
        got.update(cs=end[0], ip=end[1])
        actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                      writes=writes, ram=m.gread(0, X.RAM))
        errors = compare(expected, actual, p.live_in[resume], code_addresses(p, B.LOADSEG))
        if errors:
            raise AssertionError(errors)
        return expected
    finally:
        U.uc.uc_close(m.e.h)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('entry', type=Path)
    ap.add_argument('--resume', help='hex CS:IP, before original return')
    ap.add_argument('--generated', help='compare generated MODULE+hex-offset (native hooks decline)')
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
