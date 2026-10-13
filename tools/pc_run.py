#!/usr/bin/env python3
"""Run the original under instrumented DOSBox-X, headless, from a fresh root.

Outputs in tmp/pc-runs/<name>/: root/ (disposable game copy), trace/ (hook
outputs), dosbox-x.log, result.txt. Exit status: 0 success (SWOTL_EXIT_AFTER
snapshot reached), 2 time limit, 3 guest fault, 4 emulator failure.
A time limit is never success.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOSBOX = REPO / "tools/vendor/dosbox-x/src/dosbox-x"
CONF = REPO / "reference/dosbox-x.conf"
LAUNCH = "swotl V S 5 N Y Y 64"

EXIT_SUCCESS, EXIT_LIMIT, EXIT_FAULT, EXIT_EMULATOR = 0, 2, 3, 4


def prepare(run: Path) -> Path:
    if run.exists():
        shutil.rmtree(run)
    root = run / "root"
    subprocess.run(["rsync", "-a", "--exclude", "*.pdf", f"{REPO / 'ref'}/", f"{root}/"],
                   check=True)
    (run / "trace").mkdir()
    return root


def classify(run: Path, returncode: int) -> tuple[int, str]:
    trace = run / "trace"
    exit_file = trace / "exit.txt"
    if exit_file.exists():
        return EXIT_SUCCESS, exit_file.read_text().strip()
    events = trace / "events.csv"
    if events.exists():
        for line in events.read_text(errors="replace").splitlines():
            if ",fault," in line:
                return EXIT_FAULT, f"guest fault: {line}"
    if not (trace / "summary.txt").exists():
        return EXIT_EMULATOR, f"emulator exited {returncode} without trace output"
    return EXIT_LIMIT, "time limit"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--time-limit", type=int, default=60, help="wall-clock seconds")
    parser.add_argument("--cputype", default=None, help="override conf cputype (286, 386)")
    parser.add_argument("--cycles", type=int, default=None)
    parser.add_argument("--snapshots", default="", help="name@MODULE+HEX[#N],...")
    parser.add_argument("--exit-after", default="", help="snapshot name that ends the run")
    parser.add_argument("--keys", default="", help="MODULE+HEX[#N]=key/mx+N/my-N/mb0..7,... (mouse actions are immediate)")
    parser.add_argument("--key-hold", type=int, default=None)
    parser.add_argument("--launch", default=LAUNCH)
    parser.add_argument("--services", action="store_true",
                        help="log every software INT from module code with entry/return registers")
    parser.add_argument("--polls", type=Path,
                        help="translator poll points: hardware interrupts only there, logged")
    args = parser.parse_args()

    run = REPO / "tmp/pc-runs" / args.name
    root = prepare(run)
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy",
               SWOTL_TRACE="1", SWOTL_TRACE_DIR=str(run / "trace"),
               SWOTL_SNAPSHOTS=args.snapshots, SWOTL_EXIT_AFTER=args.exit_after,
               SWOTL_KEYS=args.keys)
    if args.services:
        env["SWOTL_SERVICES"] = "1"
    if args.polls:
        env["SWOTL_POLLS"] = str(args.polls.resolve())
    if args.key_hold is not None:
        env["SWOTL_KEY_HOLD"] = str(args.key_hold)
    command = [str(DOSBOX), "-conf", str(CONF), "-nogui", "-nomenu", "-silent", "-fastlaunch",
               "-time-limit", str(args.time_limit),
               "-set", f"log logfile={run / 'dosbox-x.log'}"]
    if args.cputype:
        command += ["-set", f"cpu cputype={args.cputype}"]
    if args.cycles:
        command += ["-set", f"cpu cycles=fixed {args.cycles}"]
    command += ["-c", f"mount c \"{root}\"", "-c", "c:", "-c", args.launch, "-c", "exit"]
    with open(run / "stdout.txt", "w") as out:
        try:
            proc = subprocess.run(command, cwd=run, env=env, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=args.time_limit + 60)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            returncode = -1
    status, reason = classify(run, returncode)
    (run / "result.txt").write_text(f"{status} {reason}\n")
    print(f"{args.name}: {reason}")
    return status


if __name__ == "__main__":
    sys.exit(main())
