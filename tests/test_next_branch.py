#!/usr/bin/env python3
"""Branches to the next line (translator/emit.py `drop_next_branches`): a
`bra`/`jmp` goes only when no code lies between it and its target label;
a chain of them goes (speed-plan R27). --sabotage: the scan also skips instructions; the cases must then fail."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from translator import emit  # noqa: E402

# (lines between the branch to L and L, whether the branch goes, the lines left between)
CASES = [
    ([], True, []),
    (["R_A:"], True, ["R_A:"]),
    (["\t; comment", "", "R_A:\t; alias"], True, ["\t; comment", "", "R_A:\t; alias"]),
    (["\tds.b\t0\t; align 2 L"], False, ["\tds.b\t0\t; align 2 L"]),
    (["\tmove.w d0,d1"], False, ["\tmove.w d0,d1"]),
    (["R_A:\tmove.w d0,d1"], False, ["R_A:\tmove.w d0,d1"]),     # an instruction on a label line
    (["\trts"], False, ["\trts"]),
    (["\tbra M"], False, ["\tbra M"]),
    (["\tbra L"], True, []),                    # a chain: the inner branch goes first
    (["\tbra L", "R_A:", "\tjmp L"], True, ["R_A:"]),
]
BRANCHES = [("\tbra L", True), ("\tbra.w L", True), ("\tjmp L", True), ("\tbra L\t; c", True),
            ("\tbne L", False), ("\tbsr L", False), ("\tjmp (a0)", False), ("\tbra M", False)]


def check() -> list[str]:
    bad = []
    for between, want, left in CASES:
        for branch, kind in BRANCHES:
            lines = ["\tmove.w d1,d0", branch] + between + ["L:", "\tmove.w d0,d1"]
            out = list(lines)
            emit.drop_next_branches(out, Counter())
            got = out[1] != branch
            if got != (want and kind):
                bad.append(f"{branch!r} then {between}: dropped {got}")
            elif out != ["\tmove.w d1,d0"] + [branch] * (not got) + left + ["L:", "\tmove.w d0,d1"]:
                bad.append(f"{branch!r} then {between}: {out}")
    return bad


def main(sabotage: bool = False) -> int:
    if sabotage:
        emit.skippable = lambda line: True
    bad = check()
    print(f"branches to the next line: {len(CASES) * len(BRANCHES)} cases, {len(bad)} failures")
    for b in bad:
        print(" ", b)
    return 0 if bool(bad) == sabotage else 1


if __name__ == "__main__":
    sys.exit(main("--sabotage" in sys.argv[1:]))
