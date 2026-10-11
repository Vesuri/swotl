#!/usr/bin/env python3
"""Choose the BP-stable components that get a guarded copy (speed-plan R6).

  bp_regions.py METER_JSON [--write]

Prices every component (translator/region.py) from a meter run's label
executions (tools/cost_meter.py --out; a copy's `_bp` labels count with
their instruction): executed bytes the direct `[bp+d]` forms save, minus the
guards run at the entry and after each call or software interrupt. Prints
the components by gain; --write puts those with a positive gain in
annotations/bp-regions.csv. The choice never affects correctness.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from translator import emit, region  # noqa: E402
from translator.lower import bp_offsets  # noqa: E402

OUT = REPO / "annotations/bp-regions.csv"


def sub_bytes(d: int) -> int:
    return 2 if -8 <= d <= 8 else 4


def saving(i) -> int:
    """Executed bytes one execution of `i` saves in a copy (estimate)."""
    n = 0
    for d in bp_offsets(i)[::2 if region.far_pair(i) else 1]:
        far = not -128 <= -d - 1 <= 127
        n += 2 + (sub_bytes(d) if d else 0) + (2 if region.far_pair(i) else 0) - (2 if far else 0)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("meter")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    execs = Counter()
    for lab, v in json.load(open(args.meter))["labels"].items():
        execs[lab.removesuffix("_bp")] += v.get("execs", 0)
    p = emit.Program(components=False)
    rows = []
    for writers, start, nodes in region.components(p, region.writers(p)):
        rng = region.bp_range([p.node_insn(n) for n in nodes])
        if rng is None:
            continue
        gbytes = len(region.guard(rng, "x")) // 2 * 6
        ex = lambda n: execs[emit.label(*n)]  # noqa: E731
        gain = sum(ex(n) * saving(p.node_insn(n)) for n in nodes)
        cost = gbytes * (sum(ex(s) for s in start)
                         + sum(ex(n) for n in nodes if p.node_insn(n).op in region.REGUARD))
        rows.append((gain - cost, gain, cost, sorted(writers), len(nodes)))
    rows.sort(key=lambda r: -r[0])
    chosen = [r for r in rows if r[0] > 0]
    print(f"components {len(rows)}, positive {len(chosen)}: gain {sum(r[0] for r in chosen):,} "
          f"bytes (saved {sum(r[1] for r in chosen):,}, guards {sum(r[2] for r in chosen):,}), "
          f"{sum(r[4] for r in chosen)} instructions copied")
    for r in chosen[:20]:
        print(f"  {r[0]:>10,} {r[1]:>10,} {r[2]:>9,} {r[4]:>5}  "
              + " ".join(f"{m}+{o:05X}" for m, o in r[3]))
    if args.write:
        lines = ["module,writer"] + sorted(f"{m},{o:05X}" for r in chosen for m, o in r[3])
        OUT.write_text("\n".join(lines) + "\n")
        print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
