#!/usr/bin/env python3
"""Report an FS-UAE instruction profile of the Amiga build (docs/perf-method.md).

Input: the Barto-format capture written by `monitor profile N "" FILE`
(grahambates/fs-uae remote_debugger_barto; BartmanAbyss/vscode-amiga-debug
src/backend/profile.ts, 17 saved registers; decoder after Vette
tools/report_game_profile.py) and the exact ELF that ran. Every executed
instruction is one record (PC frame if the PC is in the executable or ROM,
emulator cycle units), so per-PC cycles and execution counts are exact for
the window. Shares are self time.

Attribution: generated code to the guest instruction whose label precedes
the PC (`R_xxxxx`, `RPL_xxxxx`, ...: module + offset), grouped into guest
routines at the targets of generated calls; other .text to its C/asm symbol;
Kickstart, the IRQ marker and PCs outside the first hunk by address class.
Generated 68k instructions are also classed by role (poll point, return
check, flag traffic, byte swap, segment base, other) from the disassembly.
"""
import argparse
import bisect
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess

import numpy as np

PREFIX = {"R": "SWOTL.EXE", "SPZ": "SPAZ.OVL", "VGA": "RTSVGA.OVL", "FE": "FRONTEND.OVL",
          "CMP": "CAMPAIGN.OVL", "NCP": "NOTCAMP.OVL", "FLT": "FLIGHT.OVL",
          "RPL": "REPLAY.OVL", "PNL": "PANEL.OVL"}
GUEST = re.compile(r"^(R|SPZ|VGA|FE|CMP|NCP|FLT|RPL|PNL)_([0-9A-F]{5})(\w*)$")
# labels inside their instruction X: after a poll point (emit.poll), a segment
# check, CS store hook, far push (R29), repeated segment load (R30), stack run
# (R31, reuse.stack_runs) or string direction join (lower.py)
INSIDE = re.compile(r"_(np|sr\d+|hr\d+|pr\d+|gr\d+|kr\d+|dfend|dispatchend)$")
# return-check trampolines (translator/emit.py mismatch_stub): generated code
TRAMPOLINE = re.compile(r"^(R|SPZ|VGA|FE|CMP|NCP|FLT|RPL|PNL)_rm\d+$")
DEFAULT_GEN = Path(__file__).resolve().parents[1] / "build/gen"
IRQ_MARKER = 0x7FFFFFFF
NO_PC = -1      # record without a PC frame: code outside the profiled ranges


def decode(path):
    """Per field: (cycles, idle, pcs array, cost array) with pcs hunk-relative."""
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    pos = 0

    def words(n):
        nonlocal pos
        v = np.frombuffer(raw, dtype="<u4", count=n, offset=pos)
        pos += 4 * n
        return v

    word = lambda: int(words(1)[0])

    def skip(n):
        nonlocal pos
        pos += n

    fields = word()
    sections = [word() for _ in range(word())]
    skip(16)                                # stack bounds
    for _ in range(3):                      # ROM, chip RAM, bogo RAM
        skip(word())
    clock, unit = word(), word()
    out = []
    for f in range(fields):
        skip(word())                        # custom registers
        skip(word())                        # AGA
        for _ in range(2):                  # DMA and graphics-resource records
            size, count = word(), word()
            skip(size * count)
        cycles, idle, count = word(), word(), word()
        trace = words(count).tolist()
        pcs, cost = [], []
        i, pc = 0, NO_PC
        while i < count:            # [PC frames...] cost marker, 17 registers
            v = trace[i]
            if v < 0xFFFF0000:
                if pc == NO_PC:
                    pc = v
                i += 1
            else:
                pcs.append(pc)
                cost.append(0xFFFFFFFF - v)
                pc = NO_PC
                i += 1 + 17
        if i != count or pc != NO_PC:
            raise ValueError(f"field {f}: invalid record boundary")
        pcs, cost = np.array(pcs, dtype=np.int64), np.array(cost, dtype=np.int64)
        if abs(int(cost.sum()) - cycles) > max(100, cycles // 1000):
            raise ValueError(f"field {f}: accounted {cost.sum()} vs {cycles}")
        out.append((cycles, idle, pcs, cost))
        size = word()
        word()                              # screenshot kind
        skip(size)
    if pos != len(raw):
        raise ValueError("trailing data")
    return dict(fields=out, sections=sections, clock=clock, unit=unit)


def symbols(objdump, elf):
    text = subprocess.run([objdump, "-t", elf], capture_output=True, text=True, check=True).stdout
    syms = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[-3] == ".text" and not INSIDE.search(parts[-1]):
            syms.append((int(parts[0], 16), parts[-1]))  # X_np, X_sr0, X_hr0: inside X
    syms.sort()
    return syms


def roles(objdump, elf):
    """68k instruction role per .text address, from the disassembly."""
    text = subprocess.run([objdump, "-d", "--no-show-raw-insn", elf],
                          capture_output=True, text=True, check=True).stdout
    role, insns = {}, []
    stub = False
    for line in text.splitlines():
        label = re.match(r"^[0-9a-f]+ <([^>]+)>:$", line)
        if label:
            stub = bool(GUEST.fullmatch(label.group(1)) and label.group(1).endswith("_irq"))
        m = re.match(r"^\s+([0-9a-f]+):\s+(\S+)\s*(.*)$", line)
        if m:
            addr, op, arg = int(m.group(1), 16), m.group(2), m.group(3)
            insns.append((addr, op, arg, stub))
    mismatch = lambda arg: bool(re.search(r"rt_ret_(?:far_)?mismatch", arg)) or \
                           bool(re.search(r"<\w+_rm\d+>", arg))
    for i, (addr, op, arg, stub) in enumerate(insns):
        if mismatch(arg) or (op.startswith("cmp") and i + 1 < len(insns)
                             and insns[i + 1][1].startswith("bne")
                             and mismatch(insns[i + 1][2])):
            r = "return check"
        elif stub or "rt_irq" in arg or (op == "tst.b" and arg in ("9(a6)", "(9,a6)")) \
                or (op.startswith("bne") and re.search(r"<\w+_irq>", arg)):
            r = "poll point"
        # lower.STATE_EQU: bytes 1..16 above a6, including G_FL's low byte.
        # (a6) itself is guest RAM; negative displacements are guest RAM too.
        elif re.search(r"(?<![0-9-])(?:[1-9]|1[0-6])\(a6\)|\((?:[1-9]|1[0-6]),a6\)", arg):
            r = "state block (flags, segments)"
        elif op in ("ror.w", "rol.w") and arg.startswith("#8"):
            r = "byte swap"
        elif (op == "lsl.l" and arg.startswith("#4")) or arg.startswith("(0,a6,d7.l)"):
            r = "segment base"
        else:
            r = "other"
        role[addr] = r
    return role


def routine_entries(gen):
    """Generated direct call targets; never silently report an empty map."""
    entries = defaultdict(set)
    for source in Path(gen).glob("*.s"):
        for line in source.read_text().splitlines():
            m = re.match(r"^\s*(?:jsr|bsr)(?:\.[swl])?\s+(\w+)\s*(?:;.*)?$", line)
            g = GUEST.fullmatch(m.group(1)) if m else None
            if g:
                entries[PREFIX[g.group(1)]].add(int(g.group(2), 16))
    if not entries:
        raise ValueError(f"no generated guest call targets in {gen}")
    return {k: sorted(v) for k, v in entries.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("elf")
    ap.add_argument("--objdump", default="m68k-amiga-elf-objdump")
    ap.add_argument("--entries", type=Path, default=DEFAULT_GEN, help="generated .s directory (call targets)")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--count", action="append", default=[],
                    help="label whose executions to report per field (e.g. a per-frame routine)")
    args = ap.parse_args()

    prof = decode(args.capture)
    base = prof["sections"][0]
    syms = symbols(args.objdump, args.elf)
    addrs = [a for a, _ in syms]
    role = roles(args.objdump, args.elf)
    by_name = {n: a for a, n in syms}

    entry_lists = routine_entries(args.entries)

    pc_cycles, pc_count = Counter(), Counter()
    field_cycles = []
    counted = {lab: [] for lab in args.count}
    for cycles, idle, pcs, cost in prof["fields"]:
        field_cycles.append((cycles, idle))
        uniq, inv = np.unique(pcs, return_inverse=True)
        cyc = np.bincount(inv, weights=cost)
        cnt = np.bincount(inv)
        for u, c, n in zip(uniq.tolist(), cyc.tolist(), cnt.tolist()):
            pc_cycles[u] += int(c)
            pc_count[u] += n
        for lab in args.count:
            counted[lab].append(int((pcs == by_name[lab]).sum()))

    total = sum(pc_cycles.values())
    cls, module, routine, instr, func, rolec = (Counter() for _ in range(6))
    routine_calls = Counter()
    executed = Counter()        # guest instructions executed (label PCs), per module
    for pc, c in pc_cycles.items():
        if pc == NO_PC:
            cls["no PC (outside the executable and ROM)"] += c
            continue
        if pc == IRQ_MARKER:
            cls["IRQ transition"] += c
            continue
        if 0xF80000 <= pc < 0x1000000:
            cls["Kickstart"] += c
            continue
        if pc > addrs[-1] + 0x10000:
            cls["outside first hunk"] += c
            continue
        i = bisect.bisect_right(addrs, pc) - 1
        name = syms[i][1] if i >= 0 else "?"
        g = GUEST.match(name)
        if g:
            mod, off = PREFIX[g.group(1)], int(g.group(2), 16)
            cls["generated guest code"] += c
            module[mod] += c
            instr[(mod, off, g.group(3))] += c
            el = entry_lists.get(mod, [])
            j = bisect.bisect_right(el, off) - 1
            routine[(mod, el[j] if j >= 0 else 0)] += c
            rolec[role.get(pc, "other")] += c
            # R6's _bp copy executes a guest instruction too; guards, poll
            # stubs and other suffixed helpers do not start another one.
            if pc == syms[i][0] and g.group(3) in ("", "_bp"):
                executed[mod] += pc_count[pc]
            if pc == syms[i][0] and el and j >= 0 and off == el[j] and not g.group(3):
                routine_calls[(mod, off)] += pc_count[pc]
        else:
            kind = "c2p" if name.startswith("c2p") else "runtime/platform"
            cls[kind] += c
            func[name] += c

    pct = lambda c: f"{100 * c / total:6.2f}%"
    print(f"{len(field_cycles)} PAL fields, {total:,} cycle units "
          f"(clock {prof['clock']}, unit {prof['unit']}); idle per field "
          f"{sum(i for _, i in field_cycles) / len(field_cycles):,.0f}")
    print("\n## Class")
    for k, c in cls.most_common():
        print(f"{pct(c)}  {k}")
    print("\n## Generated code by module (guest instructions executed, 68k cycle units per guest instruction)")
    for k, c in module.most_common():
        print(f"{pct(c)}  {k}  {executed[k]:,}  {c / max(executed[k], 1):.1f}")
    print("\n## Generated 68k instructions by role")
    for k, c in rolec.most_common():
        print(f"{pct(c)}  {k}")
    print(f"\n## Guest routines (self, entry = generated call target; top {args.top})")
    for (mod, off), c in routine.most_common(args.top):
        print(f"{pct(c)}  {mod}+{off:05X}  calls {routine_calls.get((mod, off), 0)}")
    print(f"\n## Guest instructions (top {args.top})")
    for (mod, off, suf), c in instr.most_common(args.top):
        print(f"{pct(c)}  {mod}+{off:05X}{suf}")
    print(f"\n## Runtime/platform functions (top {args.top})")
    for k, c in func.most_common(args.top):
        print(f"{pct(c)}  {k}")
    for lab, per in counted.items():
        print(f"\n{lab} executions per field: {per}  total {sum(per)}")


if __name__ == "__main__":
    main()
