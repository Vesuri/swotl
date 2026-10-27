#!/usr/bin/env python3
"""DOSBox entry snapshots for a native row's oracle (native-plan S3).

  native_entries.py TAG MODULE+HEX HITS [--fixtures m4-demo-frames,...]

One tools/pc_run.py run per fixture (a row of reference/milestones.csv or
reference/coverage.csv, its keys, launch and inputs as tools/reference.py
runs it): snapshots entry0, entry1, ... at MODULE+HEX (HITS: comma-separated
execution counts, each counted as pc_run.py counts snapshot triggers: after the
key script, then after the previous snapshot); the run ends at the last. Output:
tmp/pc-runs/native-TAG-FIXTURE/trace/snap-entryK (tools/compute_oracle.py
load_entry). A fixture that never reaches a hit fails the run.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import fixture_inputs

REPO = Path(__file__).resolve().parent.parent
POLLS = REPO / "build/gen/poll-points.csv"  # make gen
TABLES = ("reference/milestones.csv", "reference/coverage.csv")


def fixture(name: str) -> dict:
    for table in TABLES:
        for row in csv.DictReader((REPO / table).open()):
            if row["name"] == name:
                return row
    raise SystemExit(f"no fixture {name}")


def capture(tag: str, target: str, hits: list[int], m: dict) -> int:
    names = [f"entry{k}" for k in range(len(hits))]
    cmd = [sys.executable, str(REPO / "tools/pc_run.py"), f"native-{tag}-{m['name']}",
           "--time-limit", m["time_limit"],
           "--snapshots", ",".join(f"{n}@{target}#{h}" for n, h in zip(names, hits)),
           "--exit-after", names[-1], "--keys", m["keys"].replace(";", ","), "--polls", str(POLLS)]
    for path in fixture_inputs.missing_files(m.get("missing_files") or ""):
        cmd += ["--missing-file", path]
    if m.get("joystick") == "1":
        cmd += ["--joystick"]
    if m["launch"]:
        cmd += ["--launch", m["launch"]]
    if m.get("key_hold"):
        cmd += ["--key-hold", m["key_hold"]]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("target", help="MODULE+HEX")
    ap.add_argument("hits", help="comma-separated execution counts")
    ap.add_argument("--fixtures", default="m4-demo-frames,c13-me262-gunnery,c27-campaign-flight")
    args = ap.parse_args()
    hits = [int(h) for h in args.hits.split(",")]
    assert min(hits) >= 1, "hits are 1-based"
    failed = 0
    for name in args.fixtures.split(","):
        status = capture(args.tag, args.target, hits, fixture(name))
        print(f"native-{args.tag}-{name}: {'ok' if status == 0 else f'run status {status}'}", flush=True)
        failed |= status != 0
    return failed


if __name__ == "__main__":
    sys.exit(main())
