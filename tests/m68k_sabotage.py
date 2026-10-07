#!/usr/bin/env python3
"""Sabotage the 68020 differential (translation-lessons #42): each planted fault in
the lowering's output must produce mismatches. Exit 1 if one passes unnoticed.
Corpus "program" runs the generated-program block differential (m68k_blocks).
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m68k_blocks as B  # noqa: E402
import m68k_diff as D  # noqa: E402
from translator import lower as L  # noqa: E402

real_run = L.Lowering.run
real_helpers = D.HELPERS


def text(fn):
    def run(self):
        out = real_run(self)
        self.out = fn(self, out)
        return self.out
    return run


def sub(pattern, repl):
    rx = re.compile(pattern)
    return lambda self, out: [rx.sub(repl, line) for line in out]


def drop_after(first, second):
    def f(self, out):
        res, k = [], 0
        while k < len(out):
            res.append(out[k])
            if out[k].strip() == first and k + 1 < len(out) and out[k + 1].strip() == second:
                k += 1
            k += 1
        return res
    return f


def no_merge(self, out):
    """Partial flag merges become full CCR stores (inc/dec lose CF)."""
    res, k = [], 0
    while k < len(out):
        if out[k].strip() == "move.w ccr,d7" and k + 3 < len(out) and "G_FL+1" in out[k + 3]:
            res.append("\tmove.w ccr,G_FL(a6)")
            k += 4
            continue
        res.append(out[k])
        k += 1
    return res


def no_wrap_guard(self, out):
    """REP fast path taken whatever SI/DI (the 16-bit wrap guard removed)."""
    return [x for k, x in enumerate(out)
            if not (x.startswith("\tbcc ") and k and out[k - 1].startswith("\tcmp.l #$10000,"))]


def no_runout_fix(self, out):
    """REPE/REPNE fast path: CX left at FFFFh when the count runs out."""
    return [x for k, x in enumerate(out)
            if not (x == "\taddq.w #1,d1" and k and out[k - 1].startswith(("\tbne.s ", "\tbeq.s ")))]


def drop_fused_store(self, out):
    """A setter that leaves flags in the CCR stores nothing (flags lost across blocks)."""
    if self.ccr:
        return [x for x in out if "ccr,G_FL" not in x]
    return out


def trust_x_across_ea(self, out):
    """T4: bypass the proof that operand setup preserves incoming carry in X."""
    if getattr(self.c, "x_in", False):
        for reg in ("d6", "d7"):
            out = drop_after(f"move.b G_FL+1(a6),{reg}", f"lsr.b #1,{reg}")(self, out)
            out = [s for s in out if s != f"\tmove.b G_FL+1(a6),{reg}"]
    return out


def no_native_store_swap(self, out):
    """T3: a native word source is wrongly stored as raw memory byte order."""
    from translator.decode import Mem, Reg
    if self.i.op == "mov" and self.i.width == 16:
        a, b = self.i.operands
        if isinstance(a, Mem) and isinstance(b, Reg):
            return [s for s in out if s != "\tror.w #8,d6"]
    return out


def no_predecessor_store(self, out):
    """T4: skip a predecessor store needed by another successor's reload."""
    if self.i.op == "cmp":
        return [s for s in out if "ccr,G_FL" not in s]
    return out


SABOTAGE = [
    ("jb/jae swapped", sub(r"\bbcs\b", "bcc"), "forms,boundary"),
    ("word loads not byte-swapped", drop_after("move.w (a2,d4.l),d7", "ror.w #8,d7"), "boundary"),
    ("adc/rcl ignore CF", drop_after("move.b G_FL+1(a6),d7", "lsr.b #1,d7"), "boundary"),
    ("SP not 16-bit", sub(r"subq\.w #2,d4", "subq.l #2,d4"), "boundary"),
    ("DF ignored", sub(r"^\ttst\.b G_DF\(a6\)$", "\tcmp.b d0,d0"), "boundary"),
    ("partial flag merge as full store", no_merge, "boundary"),
    ("shift count mod 16", sub(r"moveq #\$1f,d7", "moveq #$f,d7"), "boundary"),
    ("fused setter stores nothing", drop_fused_store, "program"),
    ("ror for ror.w on memory dest", sub(r"^\tror\.w #8,d6$", "\trol.b #8,d6"), "forms"),
    ("sti does not re-arm G_IRQ", sub(r"^\tmove\.b rt_irq_pending,G_IRQ\(a6\)$", "\tnop"), "boundary"),
    ("popf/iret do not re-arm G_IRQ", "helpers", "boundary"),
    ("REP fast path without wrap guard", no_wrap_guard, "boundary"),
    ("REPE/REPNE run-out leaves CX FFFFh", no_runout_fix, "boundary"),
    ("carry X trusted across EA clobber", trust_x_across_ea, "boundary"),
    ("native word store skips byte swap", no_native_store_swap, "boundary"),
    ("predecessor drops successor flag store", no_predecessor_store, "cross-block"),
]


def main() -> int:
    missed = []
    for name, fn, corpus in SABOTAGE:
        if fn == "helpers":     # __set_flags (translator/support.py)
            D.HELPERS = real_helpers.replace("\tmove.b\trt_irq_pending,G_IRQ(a6)", "\tnop")
            assert D.HELPERS != real_helpers
        else:
            L.Lowering.run = text(fn)
        try:
            if corpus == "cross-block":
                total, failures = B.cross_entry_cases()
                bad = len(failures)
            elif corpus == "program":
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    B.main(["--blocks", "1500", "--states", "1"])
                bad = int(re.search(r"(\d+) mismatches", out.getvalue()).group(1))
                total = int(re.search(r"cases (\d+)", out.getvalue()).group(1))
            else:
                h = D.X.run(["--only", corpus, "--states", "1", "--space", "2", "--blocks", "1500"],
                            quiet=True, harness=D.Harness)
                h.flush()
                bad, total = len(h.bad), sum(h.count.values())
        finally:
            L.Lowering.run = real_run
            D.HELPERS = real_helpers
        print(f"{name:36} {corpus:15} mismatches {bad} of {total}")
        if not bad:
            missed.append(name)
    if missed:
        print("not caught:", ", ".join(missed))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
