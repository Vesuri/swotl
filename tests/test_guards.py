#!/usr/bin/env python3
"""G1/G2 guardrails fail on planted violations (plan step 3.1).

G1: in a copy of build/gen, one body byte edited, one stale header and one
deleted line, each in an IR listing and in a 68020 `.s` file, must each be
rejected; the untouched copy passes, including byte-identical regeneration. G2: planted guest-address names in a
hand-written file are each reported; surface-item names are not.
Run after `make gen`.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from translator import check, gen  # noqa: E402

PLANTED = ["void sub_1369A(void);", "g_SWOTL_EXE_13692:", "int FRONTEND_1A2F;", "seg_1617_034C:",
           "jsr loc_6A4D", "static int flight0x3E8E;"]
CLEAN = ["int21_3Dh:", "port_out_3C8:", "move.w #$7FFF,INTENA", "x = 0xDFF09A;", "stop_unknown:",
         "overlay_load:", "uint16_t value = 0x1234;"]


def main() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "gen"
        shutil.copytree(gen.OUT, base)
        if check.check_gen(True, base):
            fails.append(f"untouched copy rejected: {check.check_gen(True, base)[:2]}")
        for target in (sorted(base.glob("*.ir"))[0], sorted(base.glob("*.s"))[0]):
            original = target.read_bytes()
            cases = {
                "edited body": original[:-3] + bytes([original[-3] ^ 1]) + original[-2:],
                "stale inputs": original.replace(b"; inputs ", b"; inputs 0", 1),
                "deleted line": original.replace(original.split(b"\n")[6] + b"\n", b"", 1),
            }
            for name, data in cases.items():
                target.write_bytes(data)
                if not check.check_gen(False, base):
                    fails.append(f"G1 accepted {name} in {target.name}")
                target.write_bytes(original)
        src = Path(tmp) / "planted.cpp"
        src.write_text("\n".join(PLANTED) + "\n")
        found = check.lint([src])
        if len(found) != len(PLANTED):
            fails.append(f"G2 found {len(found)} of {len(PLANTED)} planted names: {found}")
        src.write_text("\n".join(CLEAN) + "\n")
        if check.lint([src]):
            fails.append(f"G2 flagged clean names: {check.lint([src])}")
    for f in fails:
        print(f)
    print(f"guard tests: {len(fails)} failures (G1 6 plants, G2 {len(PLANTED)} plants)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
