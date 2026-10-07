#!/usr/bin/env python3
"""Cost of the lowering by x86 instruction form (docs/speed-plan.md).

  lowering_cost.py CAPTURE ELF [--objdump ...] [--gen build/gen] [--top N]

From an FS-UAE profile capture (tools/profile_report.py) of the exact ELF
that ran: every generated guest instruction's self cycles (its label to the
next symbol), executions (hits of its label) and static 68k instruction
count, grouped by x86 form (mnemonic and operand kinds, from the comment
the translator writes after each label). Also the generated code's cycles
by 68k mnemonic and by role. Cycle units are the capture's (68020 clocks).
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess

import numpy as np

import profile_report as P

REG8 = {"al", "cl", "dl", "bl", "ah", "ch", "dh", "bh"}
REG16 = {"ax", "cx", "dx", "bx", "sp", "bp", "si", "di"}
SREG = {"es", "cs", "ss", "ds"}
LABEL = re.compile(r"^(\w+):\t; [0-9A-F]{4}:[0-9A-F]{4} (.*)$")


def operand_kind(o: str) -> str:
    o = o.strip()
    if o in REG8:
        return "r8"
    if o in REG16:
        return "r16"
    if o in SREG:
        return "sreg"
    if "[" in o:
        w = "m8" if o.startswith("byte") else "m16" if o.startswith("word") else \
            "m32" if o.startswith("dword") else "m"
        inner = o[o.index("[") + 1:o.index("]")]
        regs = [r for r in re.split(r"[+\-]", inner) if r in REG16]
        return f"{w}[{'+'.join(regs) or 'disp'}]"
    if re.fullmatch(r"-?(0x)?[0-9a-fA-F]+", o):
        return "imm"
    return "far" if ":" in o else "x"


def form(text: str) -> str:
    parts = text.split(None, 1)
    op = parts[0]
    prefix = ""
    if op in ("rep", "repe", "repne", "lock") and len(parts) > 1:
        prefix, parts = op + " ", parts[1].split(None, 1)
        op = parts[0]
    if len(parts) == 1:
        return prefix + op
    ops = [operand_kind(o) for o in parts[1].split(",")]
    if op in ("jmp", "call", "jcxz", "loop", "loope", "loopne") or op.startswith("j"):
        ops = ["near" if k == "imm" else k for k in ops]
    return prefix + op + " " + ", ".join(ops)


def static_counts(gen: Path) -> tuple[dict, dict]:
    """label -> x86 text, and label -> 68k instructions up to the next label."""
    text, count = {}, Counter()
    for s in gen.glob("*.s"):
        cur = None
        for line in s.read_text().splitlines():
            m = LABEL.match(line)
            if m:
                cur = m.group(1)
                text[cur] = m.group(2)
            elif cur and line.startswith("\t") and not line.startswith("\t;"):
                count[cur] += 1
            elif line and not line.startswith((".", "\t", ";")):
                cur = None
    return text, count


def mnemonics(objdump, elf):
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", elf],
                         capture_output=True, text=True, check=True).stdout
    mn = {}
    for line in out.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\s+(\S+)\s*(.*)$", line)
        if m:
            mn[int(m.group(1), 16)] = (m.group(2), m.group(3))
    return mn


def role(op: str, arg: str) -> str:
    if re.search(r"(^|,)-1?[0-9]\(a6\)", arg) or re.search(r"\(-1?[0-9],a6\)", arg):
        return "state block (flags, segments)"
    if op in ("ror.w", "rol.w") and arg.startswith("#8"):
        return "byte swap"
    if op in ("jsr", "bsr", "rts"):
        return "call/return"
    if op.startswith(("b", "db")) and op not in ("btst", "bset", "bclr", "bchg", "bfextu", "bfins"):
        return "branch"
    if "move" in op and "ccr" in arg:
        return "ccr save/restore"
    if re.search(r"\(\d*,?a[1-3],[ad]\d\.l\)|\(a[1-3],[ad]\d\.l\)|\d+\(a[1-3],[ad]\d\.l\)", arg):
        return "guest memory access"
    return "other"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("elf")
    ap.add_argument("--objdump", default="m68k-amiga-elf-objdump")
    ap.add_argument("--gen", type=Path, default=Path("build/gen"))
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    prof = P.decode(args.capture)
    syms = P.symbols(args.objdump, args.elf)
    addrs = np.array([a for a, _ in syms])
    names = [n for _, n in syms]
    by_name = {n: a for a, n in syms}
    text, nstatic = static_counts(args.gen)
    mn = mnemonics(args.objdump, args.elf)

    pc_cycles, pc_count = Counter(), Counter()
    for _, _, pcs, cost in prof["fields"]:
        uniq, inv = np.unique(pcs, return_inverse=True)
        for u, c, n in zip(uniq.tolist(), np.bincount(inv, weights=cost).tolist(),
                           np.bincount(inv).tolist()):
            pc_cycles[u] += int(c)
            pc_count[u] += n
    total = sum(pc_cycles.values())

    lab_cycles, mn_cycles, role_cycles, mn_count = Counter(), Counter(), Counter(), Counter()
    gen_total, gen_insns = 0, 0
    for pc, c in pc_cycles.items():
        if pc < 0 or pc >= 0xF80000:
            continue
        i = int(np.searchsorted(addrs, pc, side="right")) - 1
        if i < 0:
            continue
        name = names[i]
        g = P.GUEST.match(name)
        if not g:
            continue
        gen_total += c
        gen_insns += pc_count[pc]
        lab_cycles[name] += c
        op, arg = mn.get(pc, ("?", ""))
        mn_cycles[op] += c
        mn_count[op] += pc_count[pc]
        role_cycles[role(op, arg)] += c

    fcyc, fexec, fstatic, flabels = Counter(), Counter(), Counter(), Counter()
    for name, c in lab_cycles.items():
        t = text.get(name)
        f = form(t) if t else ("walk" if name.endswith("_walk") else "?")
        n = pc_count.get(by_name.get(name, -1), 0)
        fcyc[f] += c
        fexec[f] += n
        fstatic[f] += nstatic.get(name, 0) * n
        flabels[f] += 1
    guest_exec = sum(fexec.values())

    pct = lambda c: f"{100 * c / total:6.2f}%"
    print(f"{len(prof['fields'])} fields, {total:,} cycles; generated code {pct(gen_total)}, "
          f"{guest_exec:,} guest instructions, {gen_insns:,} 68k instructions "
          f"({gen_insns / max(guest_exec, 1):.1f} per guest instruction, "
          f"{gen_total / max(gen_insns, 1):.2f} cycles each)")
    print(f"\n## x86 forms by cycles (top {args.top}): share, executions, cycles/exec, "
          f"68k instructions/exec (static), sites")
    for f, c in fcyc.most_common(args.top):
        n = fexec[f]
        print(f"{pct(c)}  {f:34} {n:>10,}  {c / max(n, 1):6.1f}  {fstatic[f] / max(n, 1):5.1f}  "
              f"{flabels[f]}")
    print("\n## Generated 68k instructions by role")
    for k, c in role_cycles.most_common():
        print(f"{pct(c)}  {k}")
    print(f"\n## Generated 68k mnemonics (top {args.top}): share, executions, cycles/exec")
    for k, c in mn_cycles.most_common(args.top):
        print(f"{pct(c)}  {k:10} {mn_count[k]:>11,}  {c / max(mn_count[k], 1):5.2f}")


if __name__ == "__main__":
    main()
