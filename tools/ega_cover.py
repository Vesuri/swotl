#!/usr/bin/env python3
"""Routine EGA host gate (docs/ecs-plan.md D7, E7): a greedy cover of EGA-only
executed code by the EGA reference rows.

EGA-only code: instruction starts (module, offset) executed in the EGA corpus
(`reference/milestones-ega.csv`, `reference/coverage-ega.csv`; traces
tmp/pc-runs/ref-<name>) and in no VGA reference (`reference/milestones.csv`,
`reference/coverage.csv`): RTSEGA, the game's EGA arms, the and/or cells. The cover
starts from the seed rows (default: the milestones `make test-host-ega` always ran)
and adds the row with the most uncovered starts until none is left; ties go to the
shorter time limit. `--check NAMES` exits 1 unless NAMES cover every EGA-only start
(the Makefile's HOST_EGA: `make t-ega-cover`).
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import swotl_model as M  # noqa: E402

EGA_TABLES = ("reference/milestones-ega.csv", "reference/coverage-ega.csv")
VGA_TABLES = ("reference/milestones.csv", "reference/coverage.csv")
SEED = "ega-m1-mode0eh ega-m1b-logo ega-m2-choose-side ega-m4-demo-frames ega-m5-player-flight"


def rows(tables) -> dict[str, dict]:
    return {r["name"]: r for t in tables for r in csv.DictReader((REPO / t).open())}


def starts(name: str) -> set[tuple[str, int]]:
    trace = M.RUNS / f"ref-{name}" / "trace"
    if not (trace / "summary.txt").exists():
        raise SystemExit(f"no trace for {name}: record it (tools/reference.py)")
    return {(mod, off) for mod, offs in M.executed([trace]).items() for off in offs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=SEED, help="rows the cover starts from ('' = none)")
    ap.add_argument("--check", metavar="NAMES", help="space-separated rows that must cover EGA-only code")
    args = ap.parse_args()
    ega, vga = rows(EGA_TABLES), rows(VGA_TABLES)
    vga_code = set().union(*(starts(n) for n in vga))
    only = {n: starts(n) - vga_code for n in ega}
    target = set().union(*only.values())
    print(f"EGA-only instruction starts: {len(target)} over {len(ega)} rows", flush=True)
    if args.check is not None:
        names = args.check.split()
        unknown = [n for n in names if n not in ega]
        left = target - set().union(set(), *(only[n] for n in names if n in ega))
        for mod in sorted({m for m, _ in left}):
            print(f"  uncovered {mod}: {sum(1 for m, _ in left if m == mod)}")
        if unknown:
            print("  unknown rows:", " ".join(unknown))
        print("cover ok" if not left and not unknown else "cover FAIL")
        return 1 if left or unknown else 0
    chosen, covered = [], set()
    for n in args.seed.split():
        chosen.append(n)
        gain = only[n] - covered
        covered |= gain
        print(f"  {n:36} seed  +{len(gain):6} {len(covered):6}")
    while covered != target:
        n = max((n for n in ega if n not in chosen),
                key=lambda n: (len(only[n] - covered), -int(ega[n]["time_limit"])))
        gain = only[n] - covered
        chosen.append(n)
        covered |= gain
        print(f"  {n:36} {ega[n]['time_limit']:>5} +{len(gain):6} {len(covered):6}")
    print("HOST_EGA =", " ".join(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
