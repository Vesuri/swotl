#!/usr/bin/env python3
"""Run every milestone in reference/milestones.csv and check its signal.

Each milestone is one tools/pc_run.py run ending at its snapshot. The
signal: the snapshot was reached, the listed modules are resident, and the
BIOS video mode matches. RAM/VRAM/DAC hashes are compared with the previous
run (tmp/reference-hashes.csv) to prove determinism. The instruction count
is reported only: DOSBox-X interleaves host ticks with execution, so the
instruction at which an interrupt lands varies between runs while guest
state at the milestone does not.
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


def main() -> int:
    only = set(sys.argv[1:])
    previous = {}
    if HASHES.exists():
        previous = {r["name"]: r for r in csv.DictReader(HASHES.open())}
    results, failed = [], False
    for m in csv.DictReader((REPO / "reference/milestones.csv").open()):
        if only and m["name"] not in only:
            continue
        name = m["name"]
        cmd = [sys.executable, str(REPO / "tools/pc_run.py"), f"ref-{name}",
               "--time-limit", m["time_limit"], "--snapshots", f"{name}@{m['snapshot']}",
               "--exit-after", name, "--keys", m["keys"].replace(";", ",")]
        status = subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode
        snap = REPO / f"tmp/pc-runs/ref-{name}/trace/snap-{name}"
        problems = []
        if status != 0:
            problems.append(f"run status {status}")
        else:
            missing = set(m["resident"].split()) - resident(snap)
            if missing:
                problems.append(f"not resident: {' '.join(sorted(missing))}")
            regs = dict(kv.split("=") for kv in (snap / "regs.txt").read_text().split())
            if m["vga_mode"] and int(regs["vga_mode"], 16) != int(m["vga_mode"], 16):
                problems.append(f"vga mode {regs['vga_mode']}")
        row = {"name": name, "icount": "", "ram": "", "vram": "", "dac": ""}
        if status == 0:
            row.update(icount=regs["icount"], ram=digest(snap / "ram.bin"),
                       vram=digest(snap / "vram.bin"), dac=digest(snap / "dac.bin"))
            old = previous.get(name)
            if old and any(old[k] != row[k] for k in ("ram", "vram", "dac")):
                problems.append("differs from previous run")
        failed |= bool(problems)
        results.append(row)
        print(f"{name:16} {'FAIL ' + '; '.join(problems) if problems else 'ok'}  "
              f"icount={row['icount']} ram={row['ram']} vram={row['vram']}")
    merged = {**previous, **{r["name"]: r for r in results}}
    with HASHES.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "icount", "ram", "vram", "dac"])
        w.writeheader()
        w.writerows(merged.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
