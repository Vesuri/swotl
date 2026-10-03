"""`make gen`: translate every in-scope module.

Output per module `build/gen/<module>.ir` (decoded IR listing) and
`build/gen/<module>.s` (68020, Motorola syntax, translator/emit.py), plus
`build/gen/support.s` (state equates, flag/BCD helpers); never edited by hand
(G1). Header: generator version, SHA-256 of the inputs (translator sources,
tools/swotl_model.py, annotations/, the module file) and of the body.
Prints the audit (spills, flag materializations, dispatcher exits, stop
sites, return checks) against tests/audit.csv, where a count above its
expected value fails, and the coverage report (G6): executed instruction
starts of the trace corpus as translated / self-modified (D16, not yet
lowered) / HLE / unclassified; unclassified ones fail.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import csv
from collections import Counter

from . import cfg, emit, image, support
from .sem import lift

VERSION = "swotl-gen 2 (ir, 68020)"
AUDIT = image.REPO / "tests/audit.csv"
SUPPORT = "support"
OUT = image.REPO / "build/gen"
M = image.M


def inputs_digest(module: str) -> str:
    h = hashlib.sha256()
    files = sorted((image.REPO / "translator").glob("*.py")) + [image.REPO / "tools/swotl_model.py"]
    files += sorted(image.ANNOTATIONS.glob("*.csv"))
    if module != SUPPORT:
        files.append(M.REF / module)
    for f in files:
        h.update(f.relative_to(image.REPO).as_posix().encode() + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()


def header(module: str, body: bytes) -> bytes:
    return (f"; {VERSION}\n; module {module}\n; inputs {inputs_digest(module)}\n"
            f"; body {hashlib.sha256(body).hexdigest()}\n").encode()


def listing(u: cfg.Unit) -> bytes:
    out = []
    for off in sorted(u.smc_entries):
        out.append(f"; self-modified entry {u.name}+{off:05X} ({u.smc_entries[off]})")
    for off in sorted(u.insns):
        n = u.insns[off]
        out.append(f"{u.name}+{off:05X} {u.cs[off]:04X}:{n.ip:04X} {n.raw.hex():<14} {n}")
        if off in u.manager_calls:
            out.append(f"    ; PLINK manager call, overlay {u.manager_calls[off]}")
            continue
        out.extend(f"    {o}" for o in lift(n))
    return ("\n".join(out) + "\n").encode()


def write(out: Path, file: str, module: str, body: bytes) -> None:
    (out / file).write_bytes(header(module, body) + body)


def generate(out: Path) -> tuple[dict[str, cfg.Unit], Counter, dict[str, Counter]]:
    units = cfg.build()
    out.mkdir(parents=True, exist_ok=True)
    prog = emit.Program(units)
    total, per = Counter(), {}
    for name, u in units.items():
        if not u.insns and not u.smc_entries:
            continue  # DATA.OVL: DGROUP, no code
        write(out, f"{name}.ir", name, listing(u))
        lines, stats = prog.module_text(name)
        write(out, f"{name}.s", name, (support.equates() + "\n".join(lines) + "\n").encode())
        per[name] = stats
        total.update(stats)
    write(out, "support.s", SUPPORT, (support.equates() + support.HELPERS).encode())
    return units, total, per


AUDITED = ("spill", "full-flag materialization", "PF store", "AF store", "dispatcher exit",
           "stop_unknown site")


def audit(total: Counter, per: dict[str, Counter]) -> int:
    with AUDIT.open() as f:
        expected = {r["counter"]: (int(r["expected"]), r["reason"]) for r in csv.DictReader(f)}
    cols = ("guest instructions", "68k lines", "CCR fused", "flag store", "flag merge",
            "flag load", "return check", "dispatcher exit", "stop_unknown site")
    print(f"{'module':13}" + "".join(f"{c.split()[0][:10]:>11}" for c in cols))
    for name, st in per.items():
        print(f"{name:13}" + "".join(f"{st[c]:11}" for c in cols))
    bad = 0
    for c in sorted(set(AUDITED) | set(expected)):
        want, why = expected.get(c, (0, "not in tests/audit.csv"))
        got = total[c]
        mark = "FAIL" if got > want else "ok" if got == want else "below (update tests/audit.csv)"
        bad += got > want
        print(f"audit {c:28} {got:7} expected {want:7} {mark}: {why}")
    return bad


def coverage(units: dict[str, cfg.Unit]) -> int:
    traces = M.runs()
    executed = M.executed(traces)
    smc = image.smc_regions()
    hle = image.rows("hle.csv")
    print(f"{'module':13} {'executed':>9} {'translated':>10} {'self-mod':>9} {'HLE':>5} {'unclass':>8}")
    bad = 0
    for name, u in units.items():
        starts = executed.get(name, set())
        tr = sm = hl = un = 0
        for off in starts:
            if any(lo <= off <= hi for lo, hi in smc.get(name, ())):
                sm += 1
            elif any(r["module"] == name and int(r["first"], 16) <= off <= int(r["last"], 16)
                     for r in hle):
                hl += 1
            elif off in u.insns:
                tr += 1
            else:
                un += 1
        bad += un
        if starts:
            print(f"{name:13} {len(starts):9} {tr:10} {sm:9} {hl:5} {un:8}")
    print(f"HLE table entries: {len(hle)}; traces: {len(traces)} (counts are instruction starts)")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-coverage", action="store_true")
    args = ap.parse_args()
    units, total, per = generate(args.out)
    failed = audit(total, per)
    if args.no_coverage:
        return 1 if failed else 0
    bad = coverage(units)
    if bad:
        print(f"{bad} executed instructions unclassified")
    return 1 if bad or failed else 0


if __name__ == "__main__":
    sys.exit(main())
