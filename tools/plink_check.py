#!/usr/bin/env python3
"""Check the PLINK overlay model (docs/plink.md) against traced runs (plan 2.2).

Model: a call of the load routine (root +16462, CX = overlay id; reached via
a thunk's manager call or the startup preload) makes the overlay resident;
if it is not, the overlay is read and every overlay whose link range overlaps
it stops being resident; then the same for its parent (flags & 1FFFh) until
the chain ends. Input: the tracer's `plink` events (each load-routine call
that loaded, or broke the model) and DOS opens of `.OVL` files.
Checks: the files opened between two load calls are exactly the predicted
chain; the probe's residency agrees with the model; no call is ever made
from code that the load replaced (caller_intact); every call that found the
overlay resident (plink.csv) loaded nothing.
"""

from __future__ import annotations

import csv
import sys

import swotl_model as M


def predict(mods: dict[str, M.Module], by_id: dict[int, M.Module], resident: set[str], oid: int):
    loads = []
    while oid:
        m = by_id[oid]
        if m.name not in resident:
            for other in list(resident):
                o = mods[other]
                if o.link_seg < m.end_seg and m.link_seg < o.end_seg:
                    resident.discard(other)
            resident.add(m.name)
            loads.append(m.name)
        oid = m.flags & 0x1FFF
    return loads


def main() -> int:
    mods = M.load_modules()
    by_id = {m.index + 1: m for m in mods.values() if m.index >= 0}
    bad, calls, loads = [], 0, 0
    for t in M.runs():
        resident: set[str] = set()
        opened: list[str] = []
        for line in (t / "events.csv").open():
            f = line.rstrip("\n").split(",", 4)
            if len(f) < 5:
                continue
            if f[1] == "open" and f[4].split()[0].endswith(".OVL"):
                opened.append(f[4].split()[0])
            elif f[1] == "plink":
                kv = dict(x.split("=") for x in f[4].split()[1:])
                oid = int(kv["id"])
                was = by_id[oid].name in resident
                want = predict(mods, by_id, resident, oid)
                calls += 1
                loads += len(want)
                where = f"{t.parent.name} @{f[0]} {by_id[oid].name}"
                if opened != want:
                    bad.append(f"{where}: opened {opened}, model {want}")
                if int(kv["resident"]) != was:
                    bad.append(f"{where}: probe resident={kv['resident']}, model {int(was)}")
                if kv["caller_ok"] != "1":
                    bad.append(f"{where}: caller {kv['caller']} replaced by the load")
                opened = []
        if opened:
            bad.append(f"{t.parent.name}: opens after the last load call: {opened}")
        with (t / "plink.csv").open() as fh:
            for r in csv.DictReader(fh):
                if r["resident"] == "1" and r["loaded"] == "1":
                    bad.append(f"{t.parent.name}: resident overlay {r['overlay']} reloaded")
                if r["caller_intact"] != "1":
                    bad.append(f"{t.parent.name}: caller replaced ({r['caller_module']})")
    resident_calls = sum(int(r["count"]) for t in M.runs() for r in csv.DictReader((t / "plink.csv").open())
                         if r["resident"] == "1")
    for b in bad:
        print(b)
    print(f"load calls that loaded {calls} ({loads} files), calls on resident overlays "
          f"{resident_calls}, model violations {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
