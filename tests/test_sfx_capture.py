#!/usr/bin/env python3
"""Effect capture (src/runtime/sfx.c, docs/sound-plan.md R1) against the
original SPAZ.

  python3 tests/test_sfx_capture.py [--sabotage]

The host image runs to m2-choose-side with the capture on (host_run.py
--sfx-capture): the milestone must still match the DOSBox-X reference (RAM,
services, interrupts, OPL writes: the capture's state restored, its writes kept
from rt_opl). Each captured id then equals tools/sfx_levels.py's run of the
original SPAZ under Unicorn (stop all, play, the timer handler per tick) write
for write, tick for tick, up to the capture's end, and the original writes
nothing in the quiet second after it. Plants (sfx.c rebuilt):

  restore   SPAZ's data never restored
  tick      handler writes recorded one tick late
  play      the play writes (tick 0) dropped
"""
import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tools")]
import host_run as H  # noqa: E402
import sfx_levels as L  # noqa: E402

MILESTONE = "m2-choose-side"
QUIET = 237                         # sfx.c TICKS_QUIET
PLANTS = {
    "restore": ("    copy(data, spaz_save, SPAZ_DATA_BYTES, restore);",
                "    if (!restore) copy(data, spaz_save, SPAZ_DATA_BYTES, restore);"),
    "tick": ("        rt_sfx_capture[capture_n].tick = capture_tick;",
             "        rt_sfx_capture[capture_n].tick = capture_tick ? capture_tick + 1 : 0;"),
    "play": ("        spaz(cs, SPAZ_PLAY, 0, (uint16_t)(id * 4));\n",
             "        spaz(cs, SPAZ_PLAY, 0, (uint16_t)(id * 4));\n        capture_n = first;\n"),
}


def planted_elf(name):
    old, new = PLANTS[name]
    source = (ROOT / "src/runtime/sfx.c").read_text()
    assert source.count(old) == 1, name
    out = ROOT / "tmp/sfx-capture-plant" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "sfx.c").write_text(source.replace(old, new))
    tools = Path(os.environ.get("AMIGA_TOOLCHAIN") or Path.home() / ".local/opt") / "bin"
    subprocess.run([str(tools / "m68k-amiga-elf-gcc"), "-m68020", "-O2", "-ffreestanding", "-nostdlib",
                    "-fomit-frame-pointer", "-fno-tree-loop-distribute-patterns", "-Wall", "-Wextra",
                    "-Werror", "-I" + str(ROOT / "src/runtime"), "-DSWOTL_SYNC", "-c",
                    "-o", str(out / "sfx.o"), str(out / "sfx.c")], check=True)
    host = ROOT / "build/host"
    objects = [host / n for n in ("host_s.o", "host.o", "rt_entry.o")]
    objects += [out / "sfx.o" if p.stem == "sfx" else host / (p.stem + ".o")
                for p in sorted((ROOT / "src/runtime").glob("*.c"))]
    objects += [host / n for n in ("program.o", "compute_projection.o", "compute_normalise.o",
                                   "compute_scenery.o", "compute_native.o")]
    subprocess.run([str(tools / "m68k-amiga-elf-ld"), "-Ttext=0x10000", "-e", "_start",
                    "-o", str(out / "swotl.elf"), *map(str, objects)], check=True)
    return out / "swotl.elf"


def original(ram, regs, seg, i, ticks, phase):
    """tools/sfx_levels.py's sequence for id i: (tick, reg, value) for ticks,
    SPAZ's effect tick countdown (data [176], reloaded with 4) set to phase."""
    s = L.Spaz(ram, regs, seg)
    s.e.write((seg + 0x11A) * 16 + 0x176, phase.to_bytes(2, "little"))
    s.e.write(regs["ds"] * 16 + L.DELAY, b"\0\0")
    s.call(L.STOP_ALL)
    s.writes.clear()
    s.call(L.PLAY, 4 * i)
    for t in range(ticks):
        s.ms = t + 1                 # the tick number, not milliseconds
        s.tick()
    return [(int(ms), r, v) for ms, r, v in s.writes]


def cases(elf=None):
    out = ROOT / "tmp/sfx-capture.csv"
    problems = H.check(MILESTONE, 600, None, None, sfx_capture=out, elf=elf)
    if problems:
        return [f"host {MILESTONE}: {problems[0]}"]
    got = {}
    lines = out.read_text().splitlines()
    phase = int(lines.pop(1).split()[-1])
    for r in csv.DictReader(lines):
        got.setdefault(int(r["id"]), []).append((int(r["tick"]), int(r["reg"], 16), int(r["value"], 16)))
    if set(got) != set(H.SFX_PRERENDERED):
        return [f"captured ids {sorted(got)}, expected {sorted(H.SFX_PRERENDERED)}"]
    ram, regs, seg = L.snapshot()
    for i in sorted(got):
        end = got[i][-1][0]
        want = original(ram, regs, seg, i, end + QUIET, phase)
        if got[i] != want:
            k = next((k for k, (a, b) in enumerate(zip(got[i], want)) if a != b), min(len(got[i]), len(want)))
            return [f"id {i}: write {k} {got[i][k] if k < len(got[i]) else None}, original "
                    f"{want[k] if k < len(want) else None} ({len(got[i])} vs {len(want)} writes)"]
    print(f"effect capture (countdown {phase}): {len(got)} ids, {sum(map(len, got.values()))} writes equal the original SPAZ")
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sabotage", action="store_true")
    args = ap.parse_args()
    problems = cases()
    print("effect capture:", "ok" if not problems else problems[0])
    if problems:
        return 1
    if args.sabotage:
        missed = []
        for name in PLANTS:
            planted = cases(planted_elf(name))
            print(f"plant {name}: {planted[0] if planted else 'MISSED'}")
            missed += [] if planted else [name]
        if missed:
            print("FAIL: plants missed:", ", ".join(missed))
            return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
