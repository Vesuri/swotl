#!/usr/bin/env python3
"""Sound references (docs/sound-plan.md step 1): DOSBox-X runs with the OPL log
and SPAZ entry probes, rendered to WAV through Nuked OPL.

Runs (tmp/pc-runs/sound-NAME/trace/{opl,probe}.csv, tmp/sound/NAME-fm.wav):
title (no input, 150 s) and the coverage scripts c6, c12, c13 (400 s). Time
in the logs is DOSBox's emulated ms; a run ends at its time limit.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RENDER = REPO / "build/tools/opl_render"
OUT = REPO / "tmp/sound"
# SPAZ.OVL entries (docs/sound-plan.md): name, offset, stack words
PROBES = ",".join(f"SPAZ.OVL+{off:x}:{n}={name}" for name, off, n in (
    ("play", 0x3D5, 1), ("stop", 0x5AF, 1), ("stopall", 0x666, 0),
    ("query", 0x6F9, 0), ("engstop", 0x6D8, 0), ("pitch", 0x713, 3)))
FLIGHTS = ("c6-flight-keys", "c12-b17-bombing", "c13-me262-gunnery")


def record(name: str, keys: str, limit: int) -> str:
    cmd = [sys.executable, str(REPO / "tools/pc_run.py"), f"sound-{name}",
           "--time-limit", str(limit), "--opl", "--probes", PROBES]
    if keys:
        cmd += ["--keys", keys]
    subprocess.run(cmd, stdout=subprocess.DEVNULL)
    trace = REPO / f"tmp/pc-runs/sound-{name}/trace"
    if not (trace / "opl.csv").exists():
        return f"{name}: no opl.csv"
    r = subprocess.run([str(RENDER), str(trace / "opl.csv"), str(OUT / f"{name}-fm.wav")],
                       capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()


def main() -> int:
    if not RENDER.exists():
        print(f"missing {RENDER}: make {RENDER.relative_to(REPO)}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {r["name"]: r for r in csv.DictReader(open(REPO / "reference/coverage.csv"))}
    jobs = [("title", "", 150)] + [(n, rows[n]["keys"].replace(";", ","), 400) for n in FLIGHTS]
    with ThreadPoolExecutor(len(jobs)) as pool:
        for line in pool.map(lambda j: record(*j), jobs):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
