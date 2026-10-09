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


def no_predecessor_store(self, out):
    """T4: skip a predecessor store needed by another successor's reload."""
    if self.i.op == "cmp":
        return [s for s in out if "ccr,G_FL" not in s]
    return out


def trust_dirty_upper_word(self, out):
    """T6: replace every word mask even when its upper word is unknown."""
    return [re.sub(r"^\tand\.l #\$ffff,(d[0-7])$", r"\ttst.l \1", line) for line in out]


def drop_live_dx(self, out):
    """T7: discard every word high/remainder result without a liveness proof."""
    if self.i.width != 16:
        return out
    if self.i.op in ("mul", "imul"):
        return [s for s in out if s not in ("\tmove.l d0,d2", "\tclr.w d2", "\tswap d2")]
    if self.i.op in ("div", "idiv"):
        result = []
        for line in out:
            if line == "\tmove.w d7,d2":
                assert result[-1] == "\tswap d7"
                result.pop()
            else:
                result.append(line)
        return result
    return out


def high_byte_written_low(self, out):
    """T8: corrupt the neighboring byte instead of writing the high byte."""
    result = list(out)
    for reg in ("d0", "d1", "d2", "d3"):
        for src in ("d6", "d7"):
            old = [f"\tror.w #8,{reg}", f"\tmove.b {src},{reg}", f"\trol.w #8,{reg}"]
            k = 0
            while k + 2 < len(result):
                if result[k:k+3] == old:
                    result[k:k+3] = [f"\tmove.b {src},{reg}"]
                k += 1
    return [line.replace("{16:8}", "{24:8}") if line.startswith("\tbfins ") else line for line in result]

def byte_copy_uses_destination(self, out):
    """T10: copy the old destination instead of the source byte."""
    from translator.decode import Reg
    if self.i.op != "mov" or self.i.width != 8:
        return out
    a, b = self.i.operands
    if not all(isinstance(o, Reg) and o.name in L.HALF for o in (a, b)):
        return out
    ar, ah = L.HALF[a.name]
    br, bh = L.HALF[b.name]
    if ah != bh:
        return out
    ar, br = L.GREG[ar], L.GREG[br]
    return [re.sub(r"^(\tmove\.[bwl] )" + br + r",(d6|" + ar + r")$",
                   lambda m: m[1] + ar + "," + m[2], line) for line in out]


def stale_address_offset(self, out):
    """T12: trust scratch d7 without proving its value or address inputs."""
    if self.i.op != "mov" or self.i.width != 16:
        return out
    result = []
    skipping = False
    for line in out:
        if re.fullmatch(r"\tmove.w (d[45]|#\S+),d7", line):
            skipping = True
            continue
        if skipping and re.match(r"\t(sub|subq|addq)\.w .*,d7$", line):
            continue
        skipping = False
        result.append(line)
    return result


def shift_disp(line: str, k: int) -> str:
    """Displacements of direct segment-relative operands (v,aN) plus k."""
    def one(m):
        v = m[1]
        neg = v.startswith("-")
        v = v.lstrip("-")
        n = int(v[1:], 16) if v.startswith("$") else int(v)
        return f"({(-n if neg else n) + k},{m[2]})"
    return re.sub(r"\((-?\$?[0-9a-f]+),(a[1-3])\)", one, line)


def top_off_by_one(self, out):
    """D1: guest linear L read at TOP - L - 1 (direct offsets off by one byte)."""
    return [shift_disp(line, -1) for line in out]


def word_at_byte_address(self, out):
    """D1: a word read or written at its low byte's host address, not one below."""
    return [shift_disp(line, 1).replace("-1(a", "0(a") if line.startswith("\t") and
            line.split()[0].endswith(".w") else line for line in out]


def rmw_word_at_byte_address(self, out):
    """D1: a read-modify-write word operand addressed at its low byte."""
    if self.i.width != 16:
        return out
    return [line.replace("lea -1(a", "lea 0(a") for line in out]


def word_store_swapped(self, out):
    """D1: a register stored to a memory word in swapped byte order."""
    from translator.decode import Mem, Reg
    if self.i.op != "mov" or self.i.width != 16:
        return out
    a, b = self.i.operands
    if not (isinstance(a, Mem) and isinstance(b, Reg)):
        return out
    result = []
    for line in out:
        m = re.fullmatch(r"\tmove\.w (d[0-7]),(.*\(.*)", line)
        if m:
            result += [f"\tror.w #8,{m[1]}", line, f"\tror.w #8,{m[1]}"]
        else:
            result.append(line)
    return result


def wrong_mirror(self, out):
    """D1: SP/BP converted with a wrong mirror constant."""
    return [line.replace("eori.w #$7fff,", "eori.w #$7ffe,") for line in out]


def no_native_conversion(self, out):
    """D1: SP/BP used as a value (moves, flag-live arithmetic) without conversion."""
    return [line for line in out if not re.fullmatch(r"\teori\.w #\$7fff,d[67]", line)]


def mirror_not_restored(self, out):
    """D1: a value written to SP/BP left native (the mirror not re-applied)."""
    return [line for line in out if not re.fullmatch(r"\teori\.w #\$7fff,d[45]", line)]


def unbiased_segment_base(self, out):
    """D1: a segment base loaded as a6 - seg*16 without the 7FFFh bias."""
    return [line.replace("lea -$7fff(a6),", "lea (a6),") for line in out]


def native_index_added(self, out):
    """D1: a native index register added to the mirrored offset."""
    return [re.sub(r"^\tsub\.w (d3|a4|a5),d7$", r"\tadd.w \1,d7", line) for line in out]


def linear_retf_stack(self, out):
    """Independent-oracle plant: lose 16-bit SP wrap between RETF pops."""
    if self.i.op == "retf":
        return [line.replace("subq.w #2,d4", "subq.l #2,d4") for line in out]
    return out


def address_copy_from_stale_scratch(self, out):
    """T15: copy the address/result scratch instead of the restored word."""
    return [re.sub(r"^\tmovea\.l d6,(a[45])$", r"\tmovea.l d7,\1", line) for line in out]


SABOTAGE = [
    ("jb/jae swapped", sub(r"\bbcs\b", "bcc"), "forms,boundary"),
    ("TOP off by one", top_off_by_one, "boundary"),
    ("word at its byte address", word_at_byte_address, "boundary"),
    ("adc/rcl ignore CF", drop_after("move.b G_FL+1(a6),d7", "lsr.b #1,d7"), "boundary"),
    ("SP not 16-bit", sub(r"(add|sub)q\.w #2,d4", r"\1q.l #2,d4"), "boundary"),
    ("DF ignored", sub(r"^\ttst\.b G_DF\(a6\)$", "\tcmp.b d0,d0"), "boundary"),
    ("partial flag merge as full store", no_merge, "boundary"),
    ("shift count mod 16", sub(r"moveq #\$1f,d7", "moveq #$f,d7"), "boundary"),
    ("fused setter stores nothing", drop_fused_store, "program"),
    ("RMW word at its byte address", rmw_word_at_byte_address, "forms"),
    ("sti does not re-arm G_IRQ", sub(r"^\tmove\.b rt_irq_pending,G_IRQ\(a6\)$", "\tnop"), "boundary"),
    ("popf/iret do not re-arm G_IRQ", "helpers", "boundary"),
    ("REP fast path without wrap guard", no_wrap_guard, "boundary"),
    ("REPE/REPNE run-out leaves CX FFFFh", no_runout_fix, "boundary"),
    ("carry X trusted across EA clobber", trust_x_across_ea, "boundary"),
    ("word store in swapped byte order", word_store_swapped, "boundary"),
    ("predecessor drops successor flag store", no_predecessor_store, "cross-block"),
    ("mask trusts dirty upper word", trust_dirty_upper_word, "boundary"),
    ("DX result dropped while live", drop_live_dx, "boundary"),
    ("high-byte write corrupts low byte", high_byte_written_low, "boundary"),
    ("byte copy uses destination", byte_copy_uses_destination, "boundary"),
    ("wrong mirror constant", wrong_mirror, "boundary"),
    ("SP/BP value without native conversion", no_native_conversion, "boundary"),
    ("wrapped offset trusted without proof", stale_address_offset, "boundary"),
    ("native index added", native_index_added, "boundary"),
    ("SP/BP mirror not restored", mirror_not_restored, "boundary"),
    ("unbiased segment base", unbiased_segment_base, "boundary"),
    ("RETF CS pop uses linear SP", linear_retf_stack, "boundary"),
    ("address restoration copies stale scratch", address_copy_from_stale_scratch, "boundary"),
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
