#!/usr/bin/env python3
"""Headless Ghidra project per module (plan step 2.1).

Runs tools/sweep.py, then for the root and each in-scope code overlay:
writes its link image (root load image; overlay code after the fixup list)
to tmp/ghidra/<module>.bin and an entry CSV (traced instruction starts from
tmp/sweep/<module>.cls; functions at the MZ entry, PLINK thunk targets and
resolved far-call targets), imports it into tools/ghidra-proj/ as program
<module> at its link linear address (x86 real mode, BinaryLoader), seeds the
entries (ghidra_scripts/MarkEntries.java, pre-analysis) and exports
tmp/ghidra/<module>.txt (ExportListing.java). DATA.OVL has no code and is
not imported. Addresses in Ghidra are link addresses (load segment 0).
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict

import swotl_model as M

GHIDRA = M.REPO / "tools/ghidra/ghidra_12.1_PUBLIC/support/analyzeHeadless"
# Ghidra 12.1 needs JDK 21 (AmigaXDev installs Homebrew openjdk@21); GHIDRA_JAVA_HOME overrides.
JAVA_HOME = os.environ.get("GHIDRA_JAVA_HOME") or "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
PROJECT = M.REPO / "tools/ghidra-proj"
OUT = M.REPO / "tmp/ghidra"
CODE_MODULES = [n for n in M.SCOPE if n != "DATA.OVL"]


def functions(mods: dict[str, M.Module]) -> dict[str, dict[int, str]]:
    """Module -> {module offset: name} for function seeds."""
    out: dict[str, dict[int, str]] = defaultdict(dict)
    out[M.ROOT][M.entry()] = "mz_entry"
    for at, mod, off in M.thunks(mods):
        out[mod].setdefault(off, f"thunk_{at:05X}_target")
    with (M.REPO / "tmp/sweep/far-refs.csv").open() as f:
        for r in csv.DictReader(f):
            owner = r["owners"].replace(" (thunk)", "")
            if owner not in mods or " " in owner:
                continue
            m = mods[owner]
            off = m.from_link(int(r["segment"], 16) * 16 + int(r["target"], 16))
            out[owner].setdefault(off, f"far_{int(r['segment'], 16):04X}_{int(r['target'], 16):04X}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("modules", nargs="*", default=CODE_MODULES)
    args = ap.parse_args()
    subprocess.run([sys.executable, str(M.REPO / "tools/sweep.py")], check=True,
                   stdout=subprocess.DEVNULL)
    mods = M.load_modules()
    funcs = functions(mods)
    OUT.mkdir(parents=True, exist_ok=True)
    PROJECT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=JAVA_HOME)
    for name in args.modules:
        m = mods[name]
        image = m.data[m.code_start:]
        binary = OUT / f"{name}.bin"
        binary.write_bytes(image)
        cls = (M.REPO / f"tmp/sweep/{name}.cls").read_bytes()
        entries = OUT / f"{name}-entries.csv"
        with entries.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["linear", "kind", "name"])
            for off, fname in sorted(funcs[name].items()):
                if m.code_start <= off < len(m.data) and cls[off] in (1, 3):
                    w.writerow([f"0x{m.to_link(off):05x}", "func", fname])
            for off, c in enumerate(cls):
                if c == 3:
                    w.writerow([f"0x{m.to_link(off):05x}", "code", ""])
        cmd = [str(GHIDRA), str(PROJECT), "SWOTL", "-import", str(binary), "-overwrite",
               "-processor", "x86:LE:16:Real Mode", "-loader", "BinaryLoader",
               "-loader-baseAddr", f"0x{m.link_lo:x}", "-scriptPath", str(M.REPO / "ghidra_scripts"),
               "-preScript", "MarkEntries.java", str(entries),
               "-postScript", "ExportListing.java", str(OUT / f"{name}.txt")]
        log = OUT / f"{name}.log"
        with log.open("w") as fh:
            status = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
        head = (OUT / f"{name}.txt").read_text().splitlines()[0] if (OUT / f"{name}.txt").exists() else "-"
        print(f"{name:13} {'ok' if status == 0 else f'FAIL {status} (see {log})'}  {head}", flush=True)
        if status:
            return status
    return 0


if __name__ == "__main__":
    sys.exit(main())
