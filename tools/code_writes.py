#!/usr/bin/env python3
"""Classify every CPU write into a module image (plan step 2.6, D16 evidence).

Writes come from the trace corpus (snapshot writes.csv + code-writes.csv,
swotl_model.cpu_writes); byte classes from tools/sweep.py (tmp/sweep/*.cls).
Classes per written byte:
  relocation     PLINK fixup applier (root +16456) on a fixup word
  dos            DOS/BIOS service (writer in the F000 callback area)
  self-modified  byte inside annotations/self-modifying.csv
  data           byte outside any decoded instruction (code-segment data)
A write into decoded code outside the annotated regions fails.
Output: tmp/sweep/code-writes.csv (module, class, writer, first, last,
bytes; runs of consecutive offsets) and a summary. Exit 1 if a relocation
write is not on a fixup word, a writer is unknown, or code is written
outside the annotated regions.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

import swotl_model as M
from sweep import smc_regions

FIXUP_WRITER = "SWOTL.EXE+16456"
CLASS_OF = {0: "data", 1: "static-code", 2: "static-code", 3: "self-modified", 4: "self-modified",
            5: "data"}


def main() -> int:
    mods = M.load_modules()
    writes = M.cpu_writes(M.runs())
    smc = smc_regions()
    bad = []
    runs: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for mod, offs in writes.items():
        if mod not in M.SCOPE:
            continue
        m = mods[mod]
        cls = (M.REPO / f"tmp/sweep/{mod}.cls").read_bytes()
        fix = {b for f in m.fixups for b in (f, f + 1)}
        for off, writers in offs.items():
            for w in writers:
                if w == FIXUP_WRITER:
                    kind = "relocation"
                    if off not in fix:
                        bad.append(f"{mod}+{off:05X}: fixup applier off a fixup word")
                elif w.startswith("-+F"):
                    kind = "dos"
                elif w.startswith("-"):
                    kind = "unknown"
                    bad.append(f"{mod}+{off:05X}: writer {w} outside any module")
                elif any(lo <= off <= hi for lo, hi in smc.get(mod, ())):
                    kind = "self-modified"
                else:
                    kind = CLASS_OF[cls[off]] if off < len(cls) else "data"
                    if kind != "data":
                        bad.append(f"{mod}+{off:05X}: {w} writes code outside "
                                   "annotations/self-modifying.csv")
                runs[(mod, kind, w)].append(off)
    rows = []
    for (mod, kind, w), offs in sorted(runs.items()):
        offs.sort()
        start = prev = offs[0]
        for o in offs[1:] + [None]:
            if o is not None and o == prev + 1:
                prev = o
                continue
            rows.append([mod, kind, w, f"0x{start:05x}", f"0x{prev:05x}", prev - start + 1])
            if o is not None:
                start = prev = o
    with (M.REPO / "tmp/sweep/code-writes.csv").open("w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["module", "class", "writer", "first", "last", "bytes"])
        cw.writerows(rows)
    total = defaultdict(int)
    writers = defaultdict(set)
    for mod, kind, w, _, _, n in rows:
        total[(mod, kind)] += n
        writers[(mod, kind)].add(w)
    for (mod, kind), n in sorted(total.items()):
        ws = sorted(writers[(mod, kind)])
        shown = " ".join(ws[:6]) + (f" (+{len(ws) - 6})" if len(ws) > 6 else "")
        print(f"{mod:13} {kind:13} {n:6}  {shown}")
    for b in bad[:20]:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
