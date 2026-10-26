#!/usr/bin/env python3
"""Paired measurement runs of frozen build arms (docs/speed-plan.md §3-4).

  ab_runs.py freeze ARM
  ab_runs.py bench  SESSION ARM... [--runs 3] [--ram SHA256]
  ab_runs.py frames SESSION ARM... [--runs 3] [--count LABEL]
  ab_runs.py flyby  SESSION ARM... [--runs 1] [--keep]
  ab_runs.py meter  SESSION ARM... [--runs 3]

An arm is a directory frozen from the current build by `freeze`: gen/
(build/gen), swotl.elf (build/host), amiga/Swotl.elf and amiga/Swotl.exe
(amiga/out) and, when built (`make amiga-sync`), amiga-sync/ (build/amiga-sync/
out: the sync image the bench runs, docs/irq-plan.md I8; an arm without it,
from before I8, polls in its production image). Build each arm's commit, then
freeze it; never measure a live build directory.

Runs interleave the arms (run 1 of every arm, then run 2, ...) on the 68020
+ 8 MB Fast model (AMIGA_CPU and CPU unset), each FS-UAE on its own port.
Results go to SESSION/<arm>/<kind>-<n>/ and SESSION/<kind>-summary.json;
an existing run directory is never overwritten. The first command records
the measurement tools' fingerprints in SESSION/tools.json; every later run
checks them before and after, so one session never mixes tool versions.
Captures are deleted once reported (flyby: --keep retains them).

bench   amiga/bench_frames.gdb: frames 4-11 line sums, RAM hash at frame 12
        (all runs must agree, or equal --ram), profile_report of the window.
frames  amiga/perf_frames.gdb: frames 4-11 field intervals, median ms,
        profile_report (with --count) of the 100-field window.
flyby   amiga/perf_flyby.gdb: frames 0-11 fields, five 100-field captures,
        profile_tree report and JSON, profile_report of each capture.
meter   tools/cost_meter.py on the arm's host ELF and gen.
Claims: speed-plan §3-4 (ranges must not overlap for a frame-rate claim).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
AMIGA = ROOT / "amiga"
SHARE = Path.home() / ".local/share/amiga"
TOOLS = ("m68k-amiga-elf-gdb", "m68k-amiga-elf-objdump", "m68k-amiga-elf-ld")
FILES = (SHARE / "env.sh", SHARE / "fsuae_common.sh", AMIGA / "debug.sh",
         AMIGA / "bench_frames.gdb", AMIGA / "perf_frames.gdb", AMIGA / "perf_flyby.gdb",
         ROOT / "tools/profile_report.py", ROOT / "tools/profile_tree.py",
         ROOT / "tools/cost_meter.py", ROOT / "tools/cost_model.json")


def fingerprints():
    emulator = os.environ.get("FSUAE") or "fs-uae"     # amiga/env.sh selects it
    paths = [Path(shutil.which(t) or t) for t in (emulator, *TOOLS)] + list(FILES) + [AMIGA / "env.sh"]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        sys.exit(f"measurement tools missing: {missing} (source amiga/env.sh)")
    return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def check_tools(session):
    path = session / "tools.json"
    now = fingerprints()
    if not path.exists():
        session.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(now, indent=2) + "\n")
    elif json.loads(path.read_text()) != now:
        sys.exit("measurement tools changed during the session; keep its results, start a new session")


def freeze(arm):
    arm = Path(arm)
    if arm.exists():
        sys.exit(f"{arm} exists; freeze into a new directory")
    (arm / "amiga").mkdir(parents=True)
    shutil.copytree(ROOT / "build/gen", arm / "gen")
    shutil.copy2(ROOT / "build/host/swotl.elf", arm / "swotl.elf")
    sync = ROOT / "build/amiga-sync/out"
    for name in ("Swotl.elf", "Swotl.exe"):
        shutil.copy2(AMIGA / "out" / name, arm / "amiga" / name)
        if sync.is_dir():
            (arm / "amiga-sync").mkdir(exist_ok=True)
            shutil.copy2(sync / name, arm / "amiga-sync" / name)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (arm / "swotl.elf", *sorted(arm.glob("amiga*/Swotl.*")))}
    (arm / "arm.json").write_text(json.dumps(dict(head=head, dirty=bool(dirty), sha256=sums), indent=2) + "\n")
    print(f"froze {arm} at {head}{' (dirty tree)' if dirty else ''}")


def run_dir(session, arm, kind, n):
    d = session / Path(arm).name / f"{kind}-{n}"
    if (d / "run.log").exists():
        sys.exit(f"{d} already measured; never overwrite a measurement")
    d.mkdir(parents=True, exist_ok=True)
    return d


def fsuae(session, arm, d, fixture, replace, args="", image="amiga"):
    """Run one gdb fixture on the arm's Amiga build (image: amiga, or amiga-sync
    with a fallback to amiga before I8); output paths moved into d."""
    check_tools(session)
    rel = os.path.relpath(d, AMIGA)
    text = fixture.read_text()
    for old, new in replace.items():
        if old not in text:
            sys.exit(f"{fixture}: output path {old} not found")
        text = text.replace(old, f"{rel}/{new}")
    (d / "fixture.gdb").write_text(text)
    env = {k: v for k, v in os.environ.items() if k not in ("AMIGA_CPU", "CPU")}
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    arm = Path(arm).resolve()
    if not (arm / image).is_dir():
        image = "amiga"
    env.update(SWOTL_ARGS=args, SWOTL_ELF=str(arm / image / "Swotl.elf"), FSUAE_RUN=f"{rel}/uae",
               DEBUG_PORT=str(port), FSUAE_PORT_PINNED="1", FSUAE_CLAIM_STRICT="1")
    with (d / "run.log").open("w") as log:
        subprocess.run(["bash", str(AMIGA / "debug.sh"), "", str(d / "fixture.gdb"),
                        str(arm / image / "Swotl.exe")], env=env, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    shutil.rmtree(d / "uae", ignore_errors=True)
    check_tools(session)
    return (d / "run.log").read_text()


def tool(script, *args, out=None):
    cmd = [sys.executable, str(ROOT / "tools" / script), *map(str, args)]
    if out is None:
        subprocess.run(cmd, check=True)
    else:
        with open(out, "w") as f:
            subprocess.run(cmd, stdout=f, check=True)


def profile(d, arm, capture, count=(), image="amiga"):
    extra = [x for c in count for x in ("--count", c)]
    if not (Path(arm) / image).is_dir():
        image = "amiga"
    tool("profile_report.py", capture, Path(arm) / image / "Swotl.elf", "--entries", Path(arm) / "gen",
         *extra, out=d / "profile.txt")
    if not (d / "profile.txt").read_text().startswith("100 PAL fields"):
        sys.exit(f"{d}: incomplete capture")
    capture.unlink()


def spread(values):
    return dict(median=statistics.median(values), span=[min(values), max(values)])


def bench(a):
    out = {Path(arm).name: [] for arm in a.arms}
    for n in range(1, a.runs + 1):
        for arm in a.arms:
            d = run_dir(a.session, arm, "bench", n)
            log = fsuae(a.session, arm, d, AMIGA / "bench_frames.gdb",
                        {"../tmp/bench/ram.bin": "ram.bin", "../tmp/bench/frames.bin": "frames.bin"}, "BENCH",
                        "amiga-sync")
            profile(d, arm, d / "frames.bin", image="amiga-sync")
            pts = {int(k): int(f) * 312 + int(line) for k, f, line in
                   re.findall(r"^FRAME (\d+) field (\d+) line (\d+)$", log, re.M)}
            lines = [pts[k] - pts[k - 1] for k in range(4, 12)]
            ram = hashlib.sha256((d / "ram.bin").read_bytes()).hexdigest()
            row = dict(run=n, intervals=lines, sum=sum(lines), ram=ram)
            out[Path(arm).name].append(row)
            print(Path(arm).name, row, flush=True)
    hashes = {r["ram"] for rows in out.values() for r in rows}
    if len(hashes) != 1 or (a.ram and hashes != {a.ram}):
        sys.exit(f"final guest RAM differs: {sorted(hashes)}")
    return {k: dict(runs=v, **spread([r["sum"] for r in v])) for k, v in out.items()}


def frames(a):
    out = {Path(arm).name: [] for arm in a.arms}
    for n in range(1, a.runs + 1):
        for arm in a.arms:
            d = run_dir(a.session, arm, "frames", n)
            log = fsuae(a.session, arm, d, AMIGA / "perf_frames.gdb", {"../tmp/prof/frames.bin": "frames.bin"})
            profile(d, arm, d / "frames.bin", a.count)
            pts = {int(k): int(f) for k, f in re.findall(r"^FRAME (\d+) field (\d+)$", log, re.M)}
            fields = [pts[k] - pts[k - 1] for k in range(4, 12)]
            row = dict(run=n, fields=fields, median_ms=20 * statistics.median(fields))
            out[Path(arm).name].append(row)
            print(Path(arm).name, row, flush=True)
    return {k: dict(runs=v, **spread([r["median_ms"] for r in v])) for k, v in out.items()}


def flyby(a):
    out = {Path(arm).name: [] for arm in a.arms}
    for n in range(1, a.runs + 1):
        for arm in a.arms:
            d = run_dir(a.session, arm, "flyby", n)
            files = {f"../tmp/prof/flyby-%d.{x}": f"flyby-%d.{x}" for x in ("bin", "vram", "dac")}
            log = fsuae(a.session, arm, d, AMIGA / "perf_flyby.gdb", files)
            caps = [d / f"flyby-{k}.bin" for k in range(5)]
            tool("profile_tree.py", Path(arm) / "amiga/Swotl.elf", *caps, "--gen", Path(arm) / "gen",
                 "--json", d / "tree.json", out=d / "tree.txt")
            for k, c in enumerate(caps):
                tool("profile_report.py", c, Path(arm) / "amiga/Swotl.elf", "--entries", Path(arm) / "gen",
                     out=d / f"profile-{k}.txt")
                if not a.keep:
                    c.unlink()
            tree = json.loads((d / "tree.json").read_text())
            windows = [int(f) for f in re.findall(r"^WINDOW \d+ field (\d+)$", log, re.M)]
            row = dict(run=n, fields=tree["fields"], frames=tree["frames"], window_fields=windows,
                       ms_per_frame=20 * tree["fields"] / max(tree["frames"], 1))
            out[Path(arm).name].append(row)
            print(Path(arm).name, row, flush=True)
    return out


def meter(a):
    out = {Path(arm).name: [] for arm in a.arms}
    for n in range(1, a.runs + 1):
        for arm in a.arms:
            check_tools(a.session)
            path = a.session / Path(arm).name / f"meter-{n}.json"
            if path.exists():
                sys.exit(f"{path} already measured")
            path.parent.mkdir(parents=True, exist_ok=True)
            tool("cost_meter.py", "--elf", Path(arm) / "swotl.elf", "--gen", Path(arm) / "gen", "--out", path)
            check_tools(a.session)
            out[Path(arm).name].append(str(path))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="kind", required=True)
    sub.add_parser("freeze").add_argument("arm")
    for kind, runs in (("bench", 3), ("frames", 3), ("flyby", 1), ("meter", 3)):
        p = sub.add_parser(kind)
        p.add_argument("session", type=Path)
        p.add_argument("arms", nargs="+")
        p.add_argument("--runs", type=int, default=runs)
        if kind == "bench":
            p.add_argument("--ram", help="required final RAM SHA-256")
        if kind == "frames":
            p.add_argument("--count", action="append", default=[], help="profile_report --count label")
        if kind == "flyby":
            p.add_argument("--keep", action="store_true", help="retain the captures (1 GB each)")
    a = ap.parse_args()
    if a.kind == "freeze":
        return freeze(a.arm)
    a.session = a.session.resolve()
    a.arms = [str(Path(arm).resolve()) for arm in a.arms]
    for arm in a.arms:
        need = [Path(arm) / p for p in ("gen", "swotl.elf", "amiga/Swotl.elf", "amiga/Swotl.exe")]
        if not all(p.exists() for p in need):
            sys.exit(f"{arm}: not a frozen arm (ab_runs.py freeze)")
    result = dict(bench=bench, frames=frames, flyby=flyby, meter=meter)[a.kind](a)
    summary = a.session / f"{a.kind}-summary.json"
    n = 2
    while summary.exists():
        summary = a.session / f"{a.kind}-summary-{n}.json"
        n += 1
    summary.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: {x: y for x, y in v.items() if x != "runs"} if isinstance(v, dict) else v
                      for k, v in result.items()}))


if __name__ == "__main__":
    main()
