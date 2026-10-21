#!/usr/bin/env python3
"""Cost of the lowering by x86 instruction form (docs/speed-plan.md).

  lowering_cost.py CAPTURE ELF [--objdump ...] [--gen build/gen] [--top N]

From an FS-UAE profile capture (tools/profile_report.py) of the exact ELF
that ran: every generated guest instruction's self cycles (its label to the
next symbol), semantic executions (ordinary/BP entries plus recovered zero-code aliases) and static 68k instruction
count and encoded byte size (execution-weighted), grouped by x86 form
(mnemonic and operand kinds, from the comment
the translator writes after each label). Also the generated code's cycles
by 68k mnemonic and by role. Cycle units are the capture's (68020 clocks).
"""
import argparse
import bisect
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
            elif line and not line.startswith((".", "\t", ";")) and \
                    not P.INSIDE.search(line.split(":")[0]):
                cur = None  # X_np, X_sr0, X_hr0: inside X
    return text, count


def parse_disassembly(out):
    """Actual encoded lengths, including extension words (not source estimates)."""
    mn, sizes = {}, {}
    for line in out.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\s+((?:[0-9a-f]{4}[ ]*)+)\t(\S+)\s*(.*)$", line)
        if m:
            addr = int(m.group(1), 16)
            sizes[addr] = len(m.group(2).split()) * 2
            mn[addr] = (m.group(3), m.group(4))
    return mn, sizes


def mnemonics(objdump, elf):
    out = subprocess.run([objdump, "-d", "--insn-width=32", elf],
                         capture_output=True, text=True, check=True).stdout
    return parse_disassembly(out)


def static_bytes(syms, sizes):
    """Bytes from each guest symbol to the next distinct symbol address.

    Aliases share a span. Local slow-path labels retain their own spans,
    just as cycle attribution does; these are static, execution-weighted
    sizes, not dynamic fetch traffic or an instruction-cache simulation.
    """
    addrs = sorted({a for a, _ in syms})
    spans = Counter()
    for pc, size in sizes.items():
        i = bisect.bisect_right(addrs, pc) - 1
        if i >= 0:
            spans[addrs[i]] += size
    return {name: spans[addr] for addr, name in syms if P.GUEST.fullmatch(name)}


def is_entry(name):
    g = P.GUEST.fullmatch(name)
    return bool(g and g[3] in ("", "_bp"))


class EntryMap:
    """Semantic entries, not hits of arbitrary generated helper symbols.

    At a shared address the assembly's last instruction label owns the body.
    Recover zero-code predecessors from the original IR successors and the
    capture's incoming PC edges. Never multiply every alias by target hits:
    direct entry to the destination did not execute the removed jump.
    """
    def __init__(self, syms, gen, mn=None):
        self.syms = syms
        self.mn = mn or {}
        self.indirect = set()
        emitted = defaultdict(list)
        self.address = dict((n, a) for a, n in syms)
        order = {}
        for path in sorted(gen.glob("*.s")):
            cur = None
            for line in path.read_text().splitlines():
                m = LABEL.match(line)
                if m:
                    order[m[1]] = len(order)
                    cur = m[1]
                elif cur and (target := re.match(r"\t(?:jmp|jsr|bsr(?:\.[swl])?|bra(?:\.[swl])?) ([A-Z]+_[0-9A-F]{5}(?:_bp)?)$", line)):
                    emitted[cur].append(target[1])
        self.groups = defaultdict(list)
        for addr, name in syms:
            if is_entry(name):
                self.groups[addr].append(name)
        for names in self.groups.values():
            if len(names) > 1 and any(n not in order for n in names):
                raise ValueError(f"missing assembly for shared entries {names}")
            names.sort(key=lambda n: order.get(n, -1))
        self.shared = {a: ns for a, ns in self.groups.items() if len(ns) > 1}
        self.next = {}
        far = {}
        locations = defaultdict(list)
        prefixes = {v: k for k, v in P.PREFIX.items()}
        ir = re.compile(r"^(\S+)\+([0-9A-F]{5}) ([0-9A-F]{4}):([0-9A-F]{4}) ([0-9a-fA-F]+)\s+(.*)$")
        for path in gen.glob("*.ir"):
            for line in path.read_text().splitlines():
                m = ir.match(line)
                if not m:
                    continue
                mod, off, cs, ip, data, text = m.groups()
                prefix = prefixes[mod]
                offset, ip = int(off, 16), int(ip, 16)
                base = f"{prefix}_{offset:05X}"
                fall = offset - ip + ((ip + len(data) // 2) & 0xFFFF)
                locations[int(cs, 16), ip].append(base)
                op, *args = text.split(None, 1)
                targets = []
                if op in ("jmpf", "callf") and args and re.fullmatch(r"0x[0-9a-f]+:0x[0-9a-f]+", args[0]):
                    far[base] = tuple(int(v, 16) for v in args[0].split(":"))
                elif op.startswith("j") or op.startswith("loop") or op == "call":
                    if args and re.fullmatch(r"0x[0-9a-f]+", args[0]):
                        targets.append(offset - ip + int(args[0], 16))
                    if op != "jmp":
                        targets.append(fall)
                elif op not in ("ret", "retf", "iret", "jmpf", "callf", "int", "into"):
                    targets.append(fall)
                for suffix in ("", "_bp"):
                    self.next[base + suffix] = [f"{prefix}_{t:05X}{suffix}" for t in targets]
                    if op in ("jmp", "jmpf", "call", "callf") and args and not args[0].startswith("0x"):
                        self.indirect.add(base + suffix)
                        self.next[base + suffix] = emitted[base + suffix]
        for base, target in far.items():
            for suffix in ("", "_bp"):
                self.next[base + suffix] = locations.get(target, [])
        for name, successors in self.next.items():
            self.next[name] = list(dict.fromkeys(
                variant for n in successors
                for variant in (n, n.removesuffix("_bp")) if variant in self.address))
        self.addrs = [a for a, _ in syms]
        self.names = [n for _, n in syms]

    def owner(self, pc):
        i = bisect.bisect_right(self.addrs, pc) - 1
        if i < 0:
            return None
        addr, name = self.syms[i]
        if addr in self.groups:
            return self.groups[addr][-1]
        g = P.GUEST.fullmatch(name)
        if g:
            return f"{g[1]}_{g[2]}" + ("_bp" if g[3].startswith("_bp") else "")
        return None

    def path(self, name, addr):
        names = self.groups[addr]
        path = []
        while name in names and name not in path:
            path.append(name)
            if name == names[-1]:
                return tuple(path)
            successors = [n for n in self.next.get(name, []) if n in names]
            if len(successors) != 1:
                break
            name = successors[0]
        return None

    def count(self, pc_count, edges):
        entries = Counter()
        for addr, names in self.groups.items():
            n = pc_count.get(addr, 0)
            if len(names) == 1 and n:
                entries[names[0]] += n
        incoming = defaultdict(list)
        for (src, dst), n in edges.items():
            if n and dst in self.shared:
                incoming[dst].append((src, n))
        for addr, names in self.shared.items():
            n = pc_count.get(addr, 0)
            if sum(n for _, n in incoming[addr]) != n:
                raise ValueError(f"missing incoming edges for {names}")
            for src, visits in incoming[addr]:
                owner = self.owner(src)
                if owner in self.indirect:
                    op, arg = self.mn.get(src, ("", ""))
                    target = re.match(r"([0-9a-f]+) <", arg)
                    if op.split(".")[0] not in ("jmp", "jsr", "bra", "bsr") or not target or int(target[1], 16) != addr:
                        raise ValueError(f"unknown indirect guest edge from {src:x} ({owner})")
                paths = {p for nxt in self.next.get(owner, [])
                         if (p := self.path(nxt, addr)) is not None}
                if len(paths) != 1:
                    raise ValueError(f"ambiguous/unknown guest edge {src:x} ({owner}) -> {names}")
                for name in paths.pop():
                    entries[name] += visits
        return entries


def incoming_edges(fields, destinations, entry_map=None):
    """Keep field boundaries continuous, but never invent a capture predecessor."""
    edges = Counter()
    previous = -1
    guest = (np.array([bool(P.GUEST.fullmatch(n)) for n in entry_map.names])
             if entry_map is not None else None)
    for _, _, pcs, _ in fields:
        pcs = pcs[pcs != P.IRQ_MARKER]  # timing marker, not an executed PC
        if entry_map is not None:
            # Platform/runtime and hardware interrupt handlers execute no
            # translated guest instructions. Preserve the last guest source
            # across them. NO_PC is code outside the profiled first hunk;
            # all generated code is in that hunk. A missing capture predecessor
            # still stays unknown (previous starts at -1).
            indices = np.searchsorted(entry_map.addrs, pcs, side="right") - 1
            keep = (indices >= 0) & (pcs < 0xF80000) & guest[np.maximum(indices, 0)]
            pcs = pcs[keep]
        indices = np.flatnonzero(np.isin(pcs, list(destinations)))
        before = np.where(indices == 0, previous, pcs[np.maximum(indices - 1, 0)])
        pairs, counts = np.unique(np.column_stack((before, pcs[indices])), axis=0,
                                  return_counts=True)
        for (src, dst), n in zip(pairs.tolist(), counts.tolist()):
            edges[src, dst] += n
        if len(pcs):
            previous = int(pcs[-1])
    return edges


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
    ap.add_argument("--gen", type=Path, default=P.DEFAULT_GEN)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    prof = P.decode(args.capture)
    syms = P.symbols(args.objdump, args.elf)
    addrs = np.array([a for a, _ in syms])
    names = [n for _, n in syms]
    by_name = {n: a for a, n in syms}
    text, nstatic = static_counts(args.gen)
    mn, sizes = mnemonics(args.objdump, args.elf)
    nbytes = static_bytes(syms, sizes)
    entry_map = EntryMap(syms, args.gen, mn)

    pc_cycles, pc_count = Counter(), Counter()
    for _, _, pcs, cost in prof["fields"]:
        uniq, inv = np.unique(pcs, return_inverse=True)
        for u, c, n in zip(uniq.tolist(), np.bincount(inv, weights=cost).tolist(),
                           np.bincount(inv).tolist()):
            pc_cycles[u] += int(c)
            pc_count[u] += n
    total = sum(pc_cycles.values())
    entries = entry_map.count(pc_count, incoming_edges(prof["fields"], entry_map.shared, entry_map))

    lab_cycles, mn_cycles, role_cycles, mn_count = Counter(), Counter(), Counter(), Counter()
    gen_total, gen_insns = 0, 0
    for pc, c in pc_cycles.items():
        if pc < 0 or pc >= 0xF80000:
            continue
        i = int(np.searchsorted(addrs, pc, side="right")) - 1
        if i < 0:
            continue
        name = entry_map.groups.get(int(addrs[i]), [names[i]])[-1]
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

    fcyc, fexec, fstatic, flabels, fbytes = (Counter() for _ in range(5))
    for name in lab_cycles.keys() | entries.keys():
        c = lab_cycles[name]
        t = text.get(name)
        f = form(t) if t else ("walk" if "_walk" in name else "?")
        n = entries.get(name, 0)
        fcyc[f] += c
        fexec[f] += n
        fstatic[f] += nstatic.get(name, 0) * n
        flabels[f] += 1
        fbytes[f] += (0 if name in entry_map.shared.get(by_name.get(name), [])[:-1]
                      else nbytes.get(name, 0)) * n
    guest_exec = sum(fexec.values())
    label_exec = sum(pc_count.get(a, 0) for a in entry_map.groups)

    pct = lambda c: f"{100 * c / total:6.2f}%"
    print(f"{len(prof['fields'])} fields, {total:,} cycles; generated code {pct(gen_total)}, "
          f"{guest_exec:,} guest instructions ({label_exec:,} distinct entry-PC hits, "
          f"{guest_exec - label_exec:,} recovered zero-code entries), {gen_insns:,} 68k instructions "
          f"({gen_insns / max(guest_exec, 1):.1f} per guest instruction, "
          f"{gen_total / max(gen_insns, 1):.2f} cycles each; "
          f"{gen_total / max(guest_exec, 1):.2f} cycles/guest instruction; "
          f"{sum(fbytes.values()) / max(guest_exec, 1):.2f} static bytes/guest instruction)")
    print(f"\n## x86 forms by cycles (top {args.top}): share, executions, cycles/exec, "
          f"68k instructions/exec (static), code bytes/exec (static), sites")
    for f, c in fcyc.most_common(args.top):
        n = fexec[f]
        ratios = (f"{c / n:6.1f}  {fstatic[f] / n:5.1f}  {fbytes[f] / n:6.1f}"
                  if n else "     —      —       —")
        print(f"{pct(c)}  {f:34} {n:>10,}  {ratios}  {flabels[f]}")
    print("\n## Generated 68k instructions by role")
    for k, c in role_cycles.most_common():
        print(f"{pct(c)}  {k}")
    print(f"\n## Generated 68k mnemonics (top {args.top}): share, executions, cycles/exec")
    for k, c in mn_cycles.most_common(args.top):
        print(f"{pct(c)}  {k:10} {mn_count[k]:>11,}  {c / max(mn_count[k], 1):5.2f}")


if __name__ == "__main__":
    main()
