#!/usr/bin/env python3
"""Generate/report standalone FS-UAE 68020 probes; no game code or data.

Run through amiga/cost_probe.sh. Costs are per selected instruction, excluding
operand setup, checks and loop control. Both cache-sized and oversized loops
are included. Arithmetic operands are reset before every measured operation.
"""
import argparse
import json
from pathlib import Path
import subprocess


def cases():
    out = [
        ("control_mulu_w", ["move.l #$1234,d0"], "mulu.w d1,d0", 17,
         [("d0", 0x1234 * 17)], None),
        ("control_divu_w", ["move.l #$123456,d0"], "divu.w d1,d0", 257,
         [("d0", ((0x123456 % 257) << 16) | (0x123456 // 257))], None),
        ("control_move_l", ["moveq #0,d0"], "move.l d1,d0", 17,
         [("d0", 17)], None),
    ]
    for bits in (32, 64):
        for name, lhs, rhs in (("zero", 0, 3), ("sparse", 0x12345678, 17),
                               ("dense", 0xffffffff, 0xfffffff1)):
            product = lhs * rhs
            dest = "d2:d0" if bits == 64 else "d0"
            checks = [("d0", product & 0xffffffff)]
            if bits == 64:
                checks.append(("d2", product >> 32))
            out.append((f"mul{bits}_{name}", [f"move.l #${lhs:x},d0"],
                        f"mulu.l d1,{dest}", rhs, checks, None))
        for name, dividend, divisor in (("zero", 0, 3),
                ("sparse", 0x123456789 if bits == 64 else 0x12345678, 17),
                ("dense", 0xfffffffeffffffff if bits == 64 else 0xffffffff,
                 0xffffffff)):
            setup = [f"move.l #${dividend & 0xffffffff:x},d0"]
            if bits == 64:
                setup.append(f"move.l #${dividend >> 32:x},d2")
            # DIVUL is 32/32 -> remainder:quotient; DIVU paired is 64/32.
            op = "divu.l d1,d2:d0" if bits == 64 else "divul.l d1,d2:d0"
            out.append((f"div{bits}_{name}", setup, op, divisor,
                        [("d0", dividend // divisor), ("d2", dividend % divisor)], None))
    for name, setup, op, divisor, checks, residue in list(out):
        if name.startswith("div32_"):
            out.append((name.replace("div32_", "div32q_"), setup, "divu.l d1,d0",
                        divisor, checks[:1], residue))
    for width, value in (("w", 0xa5a5), ("l", 0xa5a5a5a5)):
        for action in ("load", "store"):
            for residue in range(4):
                op = f"move.{width} (a0),d0" if action == "load" else f"move.{width} d0,(a0)"
                checks = [("d0" if action == "load" else "(a0)", value)]
                out.append((f"{action}_{width}_{residue}", [], op, 0, checks, residue))
    return out


def generate(root, plant=False):
    root.mkdir(parents=True, exist_ok=True)
    asm = [" section .text,code", " xdef _start,probe_fail,probe_ready,probe_buffer", "_start:",
           " moveq #0,d7", "probe_ready:"]
    manifest = []
    for shape, repeat in (("hot", 8), ("cold", 128)):
        for name, setup, op, rhs, checks, residue in cases():
            name = f"{shape}_{name}"
            asm += [f" move.l #${rhs:x},d1", " moveq #7,d3"]
            if residue is not None:
                asm += [f" lea probe_buffer+{residue},a0", " move.l #$a5a5a5a5,d0"]
            asm += [" cnop 0,4", f"loop_{name}:"]
            for i in range(repeat):
                asm += [f" {s}" for s in setup]
                asm += [f"target_{name}_{i}:", f" {op}"]
            width = op.split()[0].split(".")[1] if residue is not None else "l"
            for reg, expected in checks:
                asm += [f" cmpi.{width} #${expected:x},{reg}", " bne probe_fail"]
            asm += [f" dbra d3,loop_{name}", f"end_{name}:"]
            manifest.append(dict(name=name, repeat=repeat, instruction=op))
    asm += [" bra probe_ready", "probe_fail:", " moveq #1,d7", " bra probe_fail",
            " cnop 0,4", "probe_buffer:", " dc.l $a5a5a5a5,$a5a5a5a5,$a5a5a5a5,$a5a5a5a5"]
    if plant:
        # Deliberately corrupt the first arithmetic oracle, without changing timing ops.
        index = next(i for i, line in enumerate(asm) if line.startswith(" cmpi.l"))
        asm[index] = " cmpi.l #$ffffffff,d0"
    (root / "probe.s").write_text("\n".join(asm) + "\n")
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def report(root, capture, output):
    import numpy as np
    from profile_report import decode
    prof = decode(capture)
    if len(prof["fields"]) != 50 or prof["clock"] != 28375160 or prof["unit"] != 128:
        raise ValueError("unexpected capture length or 68020/PAL clock metadata")
    syms = {}
    for line in subprocess.check_output(["m68k-amiga-elf-objdump", "-t", str(root / "probe.elf")], text=True).splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[-3] == ".text":
            syms[parts[-1]] = int(parts[0], 16)
    rows = []
    for case in json.loads((root / "manifest.json").read_text()):
        name = case["name"]
        targets = [syms[f"target_{name}_{i}"] for i in range(case["repeat"])]
        n = total = 0
        # Discard the two edge fields, which can be partial.
        for _, _, pcs, cost in prof["fields"][1:-1]:
            hit = np.isin(pcs, targets)
            n += int(hit.sum())
            total += int(cost[hit].sum())
        if n < 1000:
            raise ValueError(f"insufficient coverage: {name}: {n}")
        size = syms[f"end_{name}"] - syms[f"loop_{name}"]
        if (name.startswith("hot_") and size > 256) or (name.startswith("cold_") and size <= 256):
            raise ValueError(f"invalid cache-size arm: {name}: {size}")
        rows.append(dict(**case, loop_bytes=size, executions=n, cycle_units=total, mean=total / n))
    result = dict(clock=prof["clock"], unit=prof["unit"], fields=len(prof["fields"]), rows=rows)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{len(rows)} cases; clock={prof['clock']} unit={prof['unit']}; {len(prof['fields'])-2} complete fields")
    for r in rows:
        print(f"{r['name']:24} {r['mean']:9.3f} units/op  n={r['executions']:7} loop={r['loop_bytes']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--plant", action="store_true", help="deliberately fail the arithmetic oracle")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.capture:
        if not args.output:
            parser.error("--capture requires --output")
        report(args.root, args.capture, args.output)
    else:
        generate(args.root, args.plant)
