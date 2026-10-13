"""`make gen`: translate every in-scope module.

Output per module `build/gen/<module>.ir` (decoded IR listing) and
`build/gen/<module>.s` (68020, Motorola syntax, translator/emit.py), plus
`build/gen/support.s` (flag/BCD helpers) and `build/gen/program.s` (assembly root:
state equates, runtime xrefs, module includes, dispatch table); never edited by hand
(G1). Header: generator version, SHA-256 of the inputs (translator sources,
tools/swotl_model.py, annotations/, the module file) and of the body.
Alignment pads (R8, emit.align) are sized here: the program is assembled
with vasm and each pad set to 0 or 2 bytes until the label after it sits at
its residue mod 4 (a few rounds; a label still off is counted, not fixed).
Prints the audit (spills, flag materializations, dispatcher exits, stop
sites, return checks) against tests/audit.csv, where a count above its
expected value fails, and the coverage report (G6): executed instruction
starts of the trace corpus as translated / self-modified (D16, not yet
lowered) / HLE / unclassified; unclassified ones fail.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import csv
from collections import Counter

from . import cfg, emit, image, support
from .sem import lift

VERSION = "swotl-gen 2 (ir, 68020)"
AUDIT = image.REPO / "tests/audit.csv"
SUPPORT = "support"
POLLS = "poll-points.csv"
PROGRAM = "program"  # assembly root: equates, runtime xrefs, includes, dispatch table
OUT = image.REPO / "build/gen"
M = image.M


def inputs_digest(module: str) -> str:
    h = hashlib.sha256()
    files = sorted((image.REPO / "translator").glob("*.py")) + [image.REPO / "tools/swotl_model.py"]
    files += sorted(image.ANNOTATIONS.glob("*.csv"))
    if module not in (SUPPORT, PROGRAM):
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


VASM = os.environ.get("VASM") or str(Path.home() / ".local/vasmm68k_mot")
PAD_ROUNDS = 4


def symbols(elf: bytes) -> dict[str, int]:
    """Symbol values of a big-endian ELF32 object (section offsets)."""
    shoff, = struct.unpack(">I", elf[32:36])
    shentsize, shnum = struct.unpack(">HH", elf[46:50])
    secs = [struct.unpack(">10I", elf[shoff + k * shentsize:shoff + k * shentsize + 40])
            for k in range(shnum)]
    out = {}
    for sec in (x for x in secs if x[1] == 2):      # SHT_SYMTAB
        strtab = secs[sec[6]][4]
        for k in range(sec[5] // 16):
            name, value = struct.unpack(">II", elf[sec[4] + 16 * k:sec[4] + 16 * k + 8])
            end = elf.index(b"\0", strtab + name)
            out[elf[strtab + name:end].decode()] = value
    return out


def pad(texts: dict[str, list[str]], stats: Counter) -> None:
    """Size the alignment pads (emit.ALIGN) of the module texts in place: assemble,
    set each pad so the label after it lands on its residue, assuming the code
    after it moves with it, and repeat."""
    marks, label = [], {}
    for f, lines in texts.items():
        for k, x in enumerate(lines):
            if x.startswith(emit.ALIGN):
                r, label[(f, k)] = x[len(emit.ALIGN):].split()
                marks.append((f, k, int(r)))
    if not marks:
        return
    size = {(f, k): 0 for f, k, _ in marks}
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(PAD_ROUNDS + 1):
            for f, lines in texts.items():
                (Path(tmp) / f).write_text("\n".join(lines) + "\n")
            subprocess.run([VASM, "-quiet", "-m68020", "-Felf", "-x", "-nowarn=62", "-o", "p.o",
                            "program.s"], cwd=tmp, check=True)
            at = symbols((Path(tmp) / "p.o").read_bytes())
            shift, off = 0, 0
            for f, k, r in sorted(marks, key=lambda m: at[label[m[:2]]]):
                if (at[label[(f, k)]] + shift) % 4 != r:
                    new = size[(f, k)] ^ 2
                    shift += new - size[(f, k)]
                    size[(f, k)] = new
                    texts[f][k] = f"\tds.b\t{new}\t; align {r} {label[(f, k)]}"
                    off += 1
            if not off:
                break
    stats["aligned label"] = len(marks) - off
    stats["alignment missed"] = off


def write(out: Path, file: str, module: str, body: bytes) -> None:
    (out / file).write_bytes(header(module, body) + body)


def generate(out: Path, program: emit.Program | None = None) -> tuple[dict[str, cfg.Unit], Counter, dict[str, Counter]]:
    units = program.units if program is not None else cfg.build()
    out.mkdir(parents=True, exist_ok=True)
    prog = program if program is not None else emit.Program(units)
    total, per = Counter(), {}
    files: list[str] = []
    texts: dict[str, list[str]] = {}
    for name, u in units.items():
        if not u.insns and not u.smc_entries:
            continue  # DATA.OVL: DGROUP, no code
        write(out, f"{name}.ir", name, listing(u))
        lines, stats = prog.module_text(name)
        texts[f"{name}.s"] = lines
        files.append(f"{name}.s")
        per[name] = stats
        total.update(stats)
    files.append("support.s")
    texts["support.s"] = support.HELPERS.rstrip("\n").split("\n")
    texts["program.s"] = (support.equates() + prog.program_text(files)).rstrip("\n").split("\n")
    pads = Counter()
    pad(texts, pads)
    total.update(pads)
    for f in files[:-1]:
        write(out, f, f.removesuffix(".s"), ("\n".join(texts[f]) + "\n").encode())
    write(out, "support.s", SUPPORT, support.HELPERS.encode())
    write(out, "program.s", PROGRAM, (support.equates() + prog.program_text(files)).encode())
    # D8 poll points for the reference tracer (SWOTL_POLLS): DOSBox-X takes
    # hardware interrupts only there, so the host can replay them exactly
    (out / POLLS).write_text("module,offset\n" + "".join(
        f"{m},0x{o:05x}\n" for m, o in sorted(prog.loop_heads)))
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
