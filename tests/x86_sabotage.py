#!/usr/bin/env python3
"""Sabotage the x86 differential (translation-lessons #42): each planted fault in
the IR semantics or the decoder must produce mismatches on a small corpus.
Exit 1 if any sabotage passes unnoticed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import x86_diff as X  # noqa: E402
from translator import decode as D, interp as I  # noqa: E402

real_status, real_decode, real_execute = I.status, D.decode, I.execute


def adc_ignores_carry(kind, w, a, b, r, c=0):
    return real_status(kind, w, a, b, r, 0 if kind == "adc" else c)


def of_from_carry(kind, w, a, b, r, c=0):
    d, u = real_status(kind, w, a, b, r, c)
    if kind == "sub" and "OF" in d:
        d["OF"] = d["CF"]
    return d, u


def rcl_mod16(kind, w, a, b, r, c=0):
    return real_status(kind, w, a, b % 16 if kind == "rcl" else b, r, c)


def disp8_unsigned(code, ip, pos=0):
    n = real_decode(code, ip, pos)
    ops = tuple(D.Mem(o.width, o.seg, o.base, o.index, o.disp & 0xFF, o.override)
                if isinstance(o, D.Mem) and o.disp >= 0xFF80 else o for o in n.operands)
    return D.Insn(n.ip, n.size, n.raw, n.op, n.width, ops, n.cc, n.rep, n.seg)


def df_ignored(ops, s, ip, next_ip):
    df = s.flags["DF"]
    s.flags["DF"] = 0
    try:
        return real_execute(ops, s, ip, next_ip)
    finally:
        s.flags["DF"] = df


def sp_no_wrap(ops, s, ip, next_ip):
    ex = real_execute(ops, s, ip, next_ip)
    if s.regs["sp"] < 2:
        s.regs["sp"] += 0x10000
    return ex


SABOTAGE = [
    ("adc ignores carry", "status", adc_ignores_carry, "boundary"),
    ("sub OF = CF", "status", of_from_carry, "forms"),
    ("rcl count mod 16", "status", rcl_mod16, "boundary"),
    ("disp8 not sign-extended", "decode", disp8_unsigned, "forms"),
    ("DF ignored", "execute", df_ignored, "boundary"),
    ("SP not 16-bit", "execute", sp_no_wrap, "boundary"),
]


def main() -> int:
    missed = []
    for name, target, fake, corpus in SABOTAGE:
        mod = I if target in ("status", "execute") else D
        setattr(mod, target, fake)
        if target == "decode":
            I.decode = fake
        try:
            h = X.run(["--only", corpus, "--states", "2", "--space", "4"], quiet=True)
        finally:
            I.status, I.execute, D.decode, I.decode = real_status, real_execute, real_decode, real_decode
        caught = len(h.bad)
        print(f"{name:28} {corpus:9} mismatches {caught}")
        if not caught:
            missed.append(name)
    if missed:
        print("not caught:", ", ".join(missed))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
