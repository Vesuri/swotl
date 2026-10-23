#!/usr/bin/env python3
"""Self and inclusive costs and the call tree of FS-UAE profile captures
(docs/perf-method.md), over one capture or several consecutive ones.

  profile_tree.py ELF CAPTURE... [--gen build/gen] [--json OUT] [--top N]
                  [--tree-min PERCENT] [--frame LABEL]

Inputs: captures of `monitor profile N "" FILE` (tools/profile_report.py) and
the exact ELF and generated `.s` that ran. A scope opens at a guest routine
entry (generated call target) or a .text symbol start reached with A7 four
below the previous user-mode record (jsr/bsr) and closes at the first
user-mode record with A7 above it. Supervisor-stack records (hardware
interrupts) are not charged to a scope; a guest interrupt delivery (`rt_irq`
scope) is not charged to the routine it interrupted. Scope state carries
across the captures given (the emulator stops between `monitor profile`
commands), so pass consecutive captures in order. Scopes still open at the
end are listed, not counted. Inclusive rows overlap; do not add them.
"""
import argparse
import bisect
from collections import Counter, defaultdict
import json
from pathlib import Path

import numpy as np

import profile_report as P

SUPERVISOR = (0x200000, 0x210000)   # A7 on the supervisor stack


def records(path):
    """Per field: (pcs, costs, a7s), first PC frame of each record."""
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
    word(), word()                          # clock, unit
    for f in range(fields):
        skip(word())
        skip(word())
        for _ in range(2):
            size, count = word(), word()
            skip(size * count)
        _cycles, _idle, count = word(), word(), word()
        t = words(count).tolist()
        pcs, costs, a7s = [], [], []
        i, pc = 0, P.NO_PC
        while i < count:            # [PC frames...] cost marker, 17 registers (A7 16th)
            v = t[i]
            if v < 0xFFFF0000:
                if pc == P.NO_PC:
                    pc = v
                i += 1
            else:
                pcs.append(pc)
                costs.append(0xFFFFFFFF - v)
                a7s.append(t[i + 16])
                pc = P.NO_PC
                i += 18
        if i != count or pc != P.NO_PC:
            raise ValueError(f"{path} field {f}: invalid record boundary")
        yield P.hunk_relative(pcs, sections[0] if sections else 0).tolist(), costs, a7s
        size = word()
        word()
        skip(size)
    if pos != len(raw):
        raise ValueError(f"{path}: trailing data")


def analyse(elf, captures, gen, objdump, frame):
    syms = P.symbols(objdump, elf)
    addrs = np.array([a for a, _ in syms], dtype=np.int64)
    by_name = {n: a for a, n in syms}
    entry_lists = P.routine_entries(gen)
    owner, entry = [], {}
    for a, n in syms:
        g = P.GUEST.match(n)
        if g:
            mod, off = P.PREFIX[g.group(1)], int(g.group(2), 16)
            el = entry_lists.get(mod, [])
            j = bisect.bisect_right(el, off) - 1
            owner.append(f"{mod}+{el[j] if j >= 0 else 0:05X}")
            if j >= 0 and el[j] == off and not g.group(3):
                entry[a] = owner[-1]
        else:
            owner.append(n)
            entry[a] = n
    irq, frame_pc, last = by_name["rt_irq"], by_name[frame], int(addrs[-1]) + 0x10000

    def cls(pc):
        if pc == P.NO_PC:
            return "<no PC>"
        if pc == P.IRQ_MARKER:
            return "<IRQ transition>"
        if 0xF80000 <= pc < 0x1000000:
            return "<Kickstart>"
        if pc > last:
            return "<outside first hunk>"
        return None

    own, incl, calls, edges = Counter(), Counter(), Counter(), Counter()
    total = fields = frames = 0
    stack, prev = [], None              # [name or None (guest irq), a7, accumulated]
    for cap in captures:
        for pcs, costs, a7s in records(cap):
            fields += 1
            idx = np.searchsorted(addrs, np.array(pcs, dtype=np.int64), side="right") - 1
            for pc, cost, a7, i in zip(pcs, costs, a7s, idx.tolist()):
                total += cost
                frames += pc == frame_pc
                own[cls(pc) or owner[i]] += cost
                if SUPERVISOR[0] <= a7 < SUPERVISOR[1] or pc == P.IRQ_MARKER:
                    continue
                while stack and a7 > stack[-1][1]:
                    name, _, acc = stack.pop()
                    if name is None:
                        continue
                    incl[name] += acc
                    calls[name] += 1
                    if stack:
                        stack[-1][2] += acc
                        if stack[-1][0] is not None:
                            edges[(stack[-1][0], name)] += acc
                if prev is not None and a7 == prev - 4:
                    if pc == irq:
                        stack.append([None, a7, 0])
                    elif pc in entry:
                        stack.append([entry[pc], a7, 0])
                if stack:
                    stack[-1][2] += cost
                prev = a7
    return dict(total=total, fields=fields, frames=frames, frame=frame,
                own=own.most_common(), incl=incl.most_common(), calls=dict(calls),
                edges=[[a, b, c] for (a, b), c in edges.most_common()],
                open_scopes=[[n, acc] for n, _, acc in stack])


def report(d, top, tree_min):
    total, calls = d["total"], d["calls"]
    own, incl = dict(d["own"]), dict(d["incl"])
    pct = lambda c: f"{100 * c / total:6.2f}%"
    print(f"{d['fields']} fields, {total:,} cycle units, {d['frames']} executions of {d['frame']}")
    if d["open_scopes"]:
        print("open at the end (not counted):",
              ", ".join(f"{n or '<irq>'} {a:,}" for n, a in d["open_scopes"]))
    print(f"\n## Self (top {top})")
    for n, c in d["own"][:top]:
        print(f"{pct(c)}  {n:<36} calls {calls.get(n, '-')}")
    print(f"\n## Inclusive (top {top}): calls, cycles per call")
    for n, c in d["incl"][:top]:
        print(f"{pct(c)}  {n:<36} {calls[n]:>7} {c / calls[n]:>12,.0f}")
    kids, parents = defaultdict(list), set()
    for a, b, c in d["edges"]:
        kids[a].append((c, b))
        parents.add(b)
    print(f"\n## Call tree (edges of at least {tree_min}%; a node shows its total inclusive cost)")

    def show(n, depth, path):
        print(f"{'  ' * depth}{pct(incl.get(n, 0))} self {pct(own.get(n, 0))}  {n} x{calls.get(n, 0)}")
        for c, b in sorted(kids[n], reverse=True):
            if 100 * c / total >= tree_min and b not in path:
                print(f"{'  ' * (depth + 1)}edge {pct(c)}")
                show(b, depth + 1, path | {b})

    for root in sorted((n for n in incl if n not in parents), key=lambda n: -incl[n]):
        if 100 * incl[root] / total >= tree_min:
            show(root, 0, {root})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf")
    ap.add_argument("captures", nargs="+")
    ap.add_argument("--gen", type=Path, default=P.DEFAULT_GEN, help="generated .s directory (call targets)")
    ap.add_argument("--objdump", default="m68k-amiga-elf-objdump")
    ap.add_argument("--frame", default="R_044E2", help="label counted as drawn frames")
    ap.add_argument("--json", type=Path, help="write self/inclusive/calls/edges")
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--tree-min", type=float, default=0.4)
    args = ap.parse_args()
    d = analyse(args.elf, args.captures, args.gen, args.objdump, args.frame)
    if args.json:
        args.json.write_text(json.dumps(d) + "\n")
    report(d, args.top, args.tree_min)


if __name__ == "__main__":
    main()
