#!/usr/bin/env python3
"""Choose the forward branches whose fall-through range goes out of line (speed-plan R27).

  outline_sites.py METER_JSON [--elf E] [--gen G] [--min CYCLES] [--write]

`make gen` lists every eligible site in build/gen/outline-sites.csv: a guest
jcc whose target follows its fall-through range F in the same run, or starts
the next one where F ends in a transfer, and the instruction after whose run
F would go (emit.py `outline_cold`). Outlined, the jcc branches, inverted, to
F, which returns with `bra` unless it ends in a transfer. Price from a build
generated with an empty annotations/outline.csv, its meter's exact counts
(cost_meter.py --out of --elf/--gen: `instruction_counts`, `taken_counts`)
and the cost model, per site: the taken branches saved, less F's new taken
branches and return, F's bytes leaving a cached loop, and two bytes per
execution where the branch can no longer be short. Loops are the window's:
a backward branch it takes, within cost_meter.LOOP of its target, matching
the meter's executed-loop rule. Not chosen: a site
whose F would land inside a loop (it grows) or carries a back edge out of
reach. Sites saving at least --min model cycles are
written to annotations/outline.csv. The choice never affects correctness.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import cost_meter as M  # noqa: E402

OUT = REPO / "annotations/outline.csv"
UNCONDITIONAL = re.compile(r"^(bra|jmp|rts|rte)(\.[swl])?$")
COND = re.compile(r"^b(hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le)(\.[swl])?$")
REACH = 126         # a short branch's reach


def counts(prog: M.Program, rows: list) -> dict[int, int]:
    """Meter rows (label, offset, op, args, count) by address; the code must match."""
    out = {}
    for lab, off, op, arg, k in rows:
        pc = prog.by_name[lab] + off
        if tuple(prog.mn.get(pc, ())) != (op, arg):
            raise SystemExit(f"{lab}+{off}: meter has {op} {arg}, the ELF {prog.mn.get(pc)}")
        out[pc] = k
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("meter", type=Path)
    ap.add_argument("--elf", type=Path, default=REPO / "build/host/swotl.elf")
    ap.add_argument("--gen", type=Path, default=REPO / "build/gen")
    ap.add_argument("--min", type=float, default=1000, help="least model cycles saved per site")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    data = json.loads(args.meter.read_text())
    prog = M.Program(args.elf, M.OBJDUMP)
    n, taken = counts(prog, data["instruction_counts"]), counts(prog, data["taken_counts"])
    coef = M.load_model()
    B, LB, W, LW = coef["bytes"], coef["loop_bytes"], coef["taken"], coef["loop_taken"]
    addrs = prog.addrs

    def before(a: int) -> int:
        return int(addrs[bisect.bisect_left(addrs, a) - 1])

    def span(lo: int, hi: int) -> list[int]:
        return [int(a) for a in addrs[bisect.bisect_left(addrs, lo):bisect.bisect_left(addrs, hi)]]

    def target(pc: int, cond: bool = True) -> int | None:
        m = re.match(r"^(?:d[0-7],)?([0-9a-f]+) <", prog.mn[pc][1])
        ok = COND.match(prog.mn[pc][0]) if cond else M.BRANCH.match(prog.mn[pc][0])
        return int(m.group(1), 16) if m and ok else None

    syms = sorted((a, name) for a, name in prog.syms)
    sym_at = [a for a, _ in syms]

    def code_end(name: str) -> int:
        """The address after `name`'s code (its own suffixed labels included)."""
        k = bisect.bisect_right(sym_at, prog.by_name[name])
        while k < len(syms) and (syms[k][1] == name or syms[k][1].startswith(name + "_")):
            k += 1
        return sym_at[k] if k < len(syms) else 1 << 30

    back = []   # loops: (target, taken backward branch) within cost_meter.LOOP
    for pc in taken:
        tg = target(pc, cond=False)
        if tg is not None and tg <= pc and pc + prog.size[pc] - tg <= M.LOOP:
            back.append((tg, pc))
    cached = {int(a) for tg, pc in back for a in span(tg, pc + 1)}

    rows, total, skipped = [], 0.0, {"lands in a cached loop": 0, "moves a back edge out of reach": 0}
    with (args.gen / "outline-sites.csv").open() as f:
        sites = list(csv.DictReader(f))
    if any(s["outlined"] == "1" for s in sites):
        raise SystemExit("price from a build generated with an empty annotations/outline.csv")
    for s in sites:
        f0, t = prog.by_name[s["first"]], prog.by_name[s["target"]]
        p = before(f0)
        if target(p) != t:
            raise SystemExit(f"{s['label']}: branch to {s['target']} not found")
        k = taken.get(p, 0)
        rng = span(f0, t)
        runs = n.get(p, 0)
        if not runs or not rng:
            continue
        loop = p in cached
        fb = sum(prog.size[a] for a in rng)
        ins = code_end(s["place"])
        if any(tg < ins <= pc for tg, pc in back):
            skipped["lands in a cached loop"] += 1
            continue
        if any(f0 <= pc < t and ins - fb + pc - f0 + prog.size[pc] - tg > M.LOOP for tg, pc in back):
            skipped["moves a back edge out of reach"] += 1
            continue
        reach = ins - (p + prog.size[p]) - fb
        grow = 2 if prog.size[p] == 2 and reach > REACH else 0
        w, b = (LW, LB) if loop else (W, B)
        ends = s["ends"] == "1"
        cold = runs - k
        moved = sum(n.get(a, 0) * prog.size[a] * (B - LB) + taken.get(a, 0) * (W - LW)
                    for a in rng if a in cached)
        save = k * w - runs * grow * b - cold * (W + (0 if ends else W + 4 * B)) - moved
        if save >= args.min:
            rows.append((s["label"], k, runs, round(save), p, t))
    # one of two nested sites (a jcc inside another's range): the larger saving
    chosen = []
    for r in sorted(rows, key=lambda r: -r[3]):
        if not any(c[4] <= r[4] < c[5] or r[4] <= c[4] < r[5] for c in chosen):
            chosen.append(r)
    skipped["nested in a larger site"] = len(rows) - len(chosen)
    rows = sorted(r[:4] for r in chosen)
    total = sum(r[3] for r in rows)
    print(f"eligible sites {len(sites)}, chosen {len(rows)} (>= {args.min:g} model cycles each): "
          f"{total:,.0f} model cycles; not chosen {skipped}")
    for lab, k, runs, save in sorted(rows, key=lambda r: -r[3])[:12]:
        print(f"  {save:9,} {lab} taken {k:,}/{runs:,}")
    if args.write:
        OUT.write_text("label,taken,executions,saving\n" +
                       "".join(f"{lab},{k},{runs},{save}\n" for lab, k, runs, save in rows))
        print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
