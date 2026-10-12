#!/usr/bin/env python3
"""Choose branch-target alignment for generated code (speed-plan R8).

  align_targets.py METER_JSON [--elf E] [--write]
  align_targets.py --check [--elf E]

On the FS-UAE 68020 a taken transfer to a target at an address = 2 mod 4
costs more than one to a longword-aligned target. A chunk is the code from a
label that only transfers reach (the instruction before it is bra, jmp, rts
or rte) to the next such instruction. Padding before the chunk is never
executed, and it shifts every target in the chunk together. Per chunk, the
meter's taken transfers into its targets (cost_meter.py --out: `targets`,
from outside a cached loop) choose the residue mod 4 of the chunk's first
label that aligns the most of them. Written to annotations/align.csv when
the aligned and misaligned counts differ by at least --min. emit.py puts a
pad before each listed label (translator/emit.py `align`) and gen.py sizes
it to 0 or 2 bytes. The choice never affects correctness. --check reports how many of the listed
labels have their residue in the ELF.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import cost_meter as M  # noqa: E402
import profile_report as P  # noqa: E402

OUT = REPO / "annotations/align.csv"
DEAD = re.compile(r"^(bra(\.[swl])?|jmp|rts|rte|rtd|rtr)$")


def load() -> dict[str, int]:
    """Listed label -> residue mod 4 (emit.py)."""
    if not OUT.exists():
        return {}
    rows = OUT.read_text().splitlines()[1:]
    return {lab: int(r) for lab, r, *_ in (x.split(",") for x in rows if x)}


def layout(elf: Path, objdump: str):
    """Instruction addresses and mnemonics, and generated-code symbols."""
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", str(elf)], capture_output=True,
                         text=True, check=True).stdout
    insns = []
    for line in out.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\s+(\S+)", line)
        if m:
            insns.append((int(m.group(1), 16), m.group(2)))
    insns.sort()
    syms = [(a, n) for a, n in P.symbols(objdump, str(elf))
            if P.GUEST.match(n) or P.TRAMPOLINE.match(n) or "walk" in n]
    return insns, syms


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("meter", nargs="?", type=Path)
    ap.add_argument("--elf", type=Path, default=REPO / "build/host/swotl.elf")
    ap.add_argument("--objdump", default=M.OBJDUMP)
    ap.add_argument("--min", type=int, default=64, help="least count difference to align a chunk")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    insns, syms = layout(args.elf, args.objdump)
    by_name = {n: a for a, n in syms}
    if args.check:
        want = load()
        ok = sum(by_name[lab] % 4 == r for lab, r in want.items() if lab in by_name)
        print(f"{ok} of {len(want)} listed labels at their residue "
              f"({sum(lab not in by_name for lab in want)} not in the ELF)")
        return 0 if ok == len(want) else 1
    addrs = [a for a, _ in insns]
    # chunk starts: the address after each bra/jmp/rts/rte
    starts = [addrs[k + 1] for k, (a, mn) in enumerate(insns[:-1]) if DEAD.match(mn)]
    head_at = defaultdict(list)
    for a, n in syms:
        head_at[a].append(n)
    weight = defaultdict(lambda: [0, 0])     # head address -> transfers wanting residue 0, 2
    targets = json.loads(args.meter.read_text())["targets"]
    skipped = 0
    for key, n in targets.items():
        lab, off = key.rsplit("+", 1)
        if lab not in by_name:
            skipped += n
            continue
        t = by_name[lab] + int(off)
        i = bisect.bisect_right(starts, t) - 1
        if i < 0 or starts[i] not in head_at:
            skipped += n
            continue
        head = starts[i]
        weight[head][(head - t) % 4 // 2] += n
    rows = []
    for head, (w0, w2) in weight.items():
        if abs(w0 - w2) >= args.min:
            rows.append((abs(w0 - w2), min(head_at[head]), 0 if w0 > w2 else 2, w0, w2))
    rows.sort(key=lambda r: -r[0])
    total = sum(targets.values())
    gain = sum(r[0] for r in rows)
    print(f"targets {len(targets)}, transfers {total:,} ({skipped:,} outside a chunk with a label); "
          f"chunks {len(weight)}, aligned {len(rows)}: transfers moved to aligned "
          f"(expected, half the difference) {gain // 2:,}")
    for r in rows[:15]:
        print(f"  {r[0]:>8,}  {r[1]} residue {r[2]}  (want 0: {r[3]:,}, want 2: {r[4]:,})")
    if args.write:
        OUT.write_text("label,residue,difference\n"
                       + "".join(f"{r[1]},{r[2]},{r[0]}\n" for r in sorted(rows, key=lambda r: r[1])))
        print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
