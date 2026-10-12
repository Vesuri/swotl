#!/usr/bin/env python3
"""R8 alignment pads (translator/emit.py `align`): a pad goes only where no
instruction falls into it, since an executed pad (zero bytes, `ori.b #0,d0`)
would change the flags. --sabotage: the guard accepts any instruction before
the label; the cases must then fail."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from translator import emit  # noqa: E402

# (lines before the listed label L, whether L gets a pad)
CASES = [
    (["\tbra R_1"], True),
    (["\tbra.w R_1"], True),
    (["\tbra.s .x"], True),
    (["\tjmp rt_stop_unknown"], True),
    (["\trts"], True),
    (["\trte"], True),
    (["\trts", "R_A:\t; alias", "\t; comment", ""], True),
    (["\tbne R_1"], False),
    (["\tbne.s .x"], False),
    (["\tdbra d6,.m0"], False),
    (["\tjsr rt_irq"], False),
    (["\tbsr.w R_1"], False),
    (["\tmove.w d0,d1"], False),
    (["\tbra R_1", "R_A:\tmove.w d0,d1"], False),     # an instruction on a label line
    (["\tbra R_1", "R_A:", "\tmove.w d0,d1"], False),
    ([], False),
]


def check() -> list[str]:
    bad = []
    for before, want in CASES:
        lines = before + ["L:\t; listed", "\tmove.w d0,d1"]
        stats = Counter()
        emit.align(lines, {"L": 2}, stats)
        pads = [k for k, x in enumerate(lines) if x.startswith(emit.ALIGN)]
        got = bool(pads)
        if got != want:
            bad.append(f"{before}: pad {got}, want {want}")
        elif got:
            # the pad sits right after the unconditional instruction, before every label
            k = pads[0]
            if not emit.UNCONDITIONAL.match(lines[k - 1]) or lines[k] != emit.ALIGN + "2 L":
                bad.append(f"{before}: pad at line {k}: {lines}")
    return bad


def main(sabotage: bool = False) -> int:
    if sabotage:
        emit.UNCONDITIONAL = re.compile(r"^\t\S")
    bad = check()
    print(f"alignment pads: {len(CASES)} cases, {len(bad)} failures")
    for b in bad:
        print(" ", b)
    return 0 if bool(bad) == sabotage else 1


if __name__ == "__main__":
    sys.exit(main("--sabotage" in sys.argv[1:]))
