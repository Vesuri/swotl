#!/usr/bin/env python3
"""Run every milestone in reference/milestones.csv and check its signal.
`--table reference/coverage.csv` runs the coverage scripts the same way.

Each milestone is one tools/pc_run.py run. Snapshots (space-separated
triggers, taken in order after the key script) are named <name>-0, -1, ...;
the run ends at the last. Checks per milestone: every snapshot reached, the
listed modules resident and the BIOS video mode at the last; consecutive
snapshots differ in RAM and VRAM (the scene advances); every snapshot passes
the gate 1 image proof (tools/load_image.py). RAM/VRAM/DAC hashes of the last
snapshot are compared with the previous run (tmp/reference-hashes.csv) to
prove determinism. The instruction count is reported only: DOSBox-X
interleaves host ticks with execution, so the instruction at which an
interrupt lands varies between runs while guest state at the milestone does
not.
"""

from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HASHES = REPO / "tmp/reference-hashes.csv"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def resident(snapshot: Path) -> set[str]:
    with (snapshot / "residency.csv").open() as f:
        return {r["module"] for r in csv.DictReader(f)}


def run(m: dict) -> tuple[list[str], dict]:
    name = m["name"]
    triggers = m["snapshots"].split()
    names = [f"{name}-{i}" for i in range(len(triggers))]
    cmd = [sys.executable, str(REPO / "tools/pc_run.py"), f"ref-{name}",
           "--time-limit", m["time_limit"],
           "--snapshots", ",".join(f"{n}@{t}" for n, t in zip(names, triggers)),
           "--exit-after", names[-1], "--keys", m["keys"].replace(";", ",")]
    if m["launch"]:
        cmd += ["--launch", m["launch"]]
    row = {"name": name, "icount": "", "ram": "", "vram": "", "dac": ""}
    status = subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode
    if status != 0:
        return [f"run status {status}"], row
    trace = REPO / f"tmp/pc-runs/ref-{name}/trace"
    snaps = [trace / f"snap-{n}" for n in names]
    problems = []
    last = snaps[-1]
    missing = set(m["resident"].split()) - resident(last)
    if missing:
        problems.append(f"not resident: {' '.join(sorted(missing))}")
    regs = dict(kv.split("=") for kv in (last / "regs.txt").read_text().split())
    if m["vga_mode"] and int(regs["vga_mode"], 16) != int(m["vga_mode"], 16):
        problems.append(f"vga mode {regs['vga_mode']}")
    for a, b in zip(snaps, snaps[1:]):
        for part in ("ram.bin", "vram.bin"):
            if digest(a / part) == digest(b / part):
                problems.append(f"{b.name} {part} did not advance")
    for s in snaps:
        if subprocess.run([sys.executable, str(REPO / "tools/load_image.py"), str(s)],
                          stdout=subprocess.DEVNULL).returncode:
            problems.append(f"{s.name} image proof")
    row.update(icount=regs["icount"], ram=digest(last / "ram.bin"),
               vram=digest(last / "vram.bin"), dac=digest(last / "dac.bin"))
    return problems, row


def main() -> int:
    args = sys.argv[1:]
    table = REPO / "reference/milestones.csv"
    if args[:1] == ["--table"]:
        table, args = REPO / args[1], args[2:]
    only = set(args)
    previous = {}
    if HASHES.exists():
        previous = {r["name"]: r for r in csv.DictReader(HASHES.open())}
    results, failed = [], False
    for m in csv.DictReader(table.open()):
        if only and m["name"] not in only:
            continue
        problems, row = run(m)
        old = previous.get(m["name"])
        if row["ram"] and old and any(old[k] != row[k] for k in ("ram", "vram", "dac")):
            problems.append("differs from previous run")
        failed |= bool(problems)
        results.append(row)
        print(f"{m['name']:16} {'FAIL ' + '; '.join(problems) if problems else 'ok'}  "
              f"icount={row['icount']} ram={row['ram']} vram={row['vram']}", flush=True)
    merged = {**previous, **{r["name"]: r for r in results}}
    with HASHES.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "icount", "ram", "vram", "dac"])
        w.writeheader()
        w.writerows(merged.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
