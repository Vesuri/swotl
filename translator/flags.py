"""Flag demand (D6): liveness of the six status flags and the per-instruction
store/fuse plan the lowering follows.

An instruction stores the flags it defines that are live after it. When the
next instruction reads flags straight from the CCR (a fusing reader, not a
block leader) and the setter's 68k CCR holds them with x86 meaning, the setter
stores only what is live after the reader and the reader skips the load.
Plain instructions may stand between the two (provenance, speed-plan R3b):
their 68k code keeps the CCR or moves the setter's result last, which leaves
N and Z equal to SF and ZF.
"""

from __future__ import annotations

import re

from . import reglive
from .decode import Reg
from .ir import STATUS
from .lower import (CCR_OK, GREG, HALF, MIRROR, SZ, Ctx, LowerError, Lowering, fuse_reader,
                    lower, reads, writes)

ALL = frozenset(STATUS)
FUSE_KIND = {"add": "add", "adc": "adc", "sub": "sub", "sbb": "sbb", "cmp": "cmp",
             "and": "logic", "or": "logic", "xor": "logic", "test": "logic", "inc": "inc",
             "dec": "dec", "neg": "neg", "shl": "shl", "shr": "shr", "sar": "sar"}
# Provenance (R3b): setters whose SF and ZF are those of the value they leave in
# their destination; x86 instructions a CCR may be carried across (no flags, no
# transfer); 68k instructions that leave the CCR unchanged.
NZ_OPS = frozenset(FUSE_KIND) - {"cmp"}
PLAIN = frozenset({"mov", "push", "pop", "lea", "xchg", "nop", "cbw", "cwd", "lds", "les", "xlat",
                   "not"})
CCR_NEUTRAL = frozenset({"lea", "movea", "adda", "suba", "pea", "nop"})
CONTROL = re.compile(r"(b(?!tst|set|clr|chg|f)|db|j|rt|trap)")


def transfer(i, live_out: set, program: bool = False) -> set:
    must, _ = writes(i)
    return reads(i, program) | (set(live_out) - must)


def seq_lives(insns, live_end=ALL, program: bool = False) -> list[set]:
    """live-out of each instruction of a straight-line run."""
    out = [set()] * len(insns)
    live = set(live_end)
    for k in reversed(range(len(insns))):
        out[k] = set(live)
        live = transfer(insns[k], live, program)
    return out


def ccr_static(i) -> set:
    k = FUSE_KIND.get(i.op)
    if k is None or k in ("shl", "shr", "sar") and not hasattr(i.operands[1], "value"):
        return set()
    return CCR_OK[k]


def result_reg(i) -> tuple[str, int] | None:
    """(68k data register, width) of the result whose N and Z are i's SF and ZF:
    a register destination (`test r,r` reads it; a shift needs a nonzero count)."""
    a = i.operands[0] if i.operands else None
    if i.op not in NZ_OPS or not isinstance(a, Reg):
        return None
    if i.op == "test" and not (isinstance(i.operands[1], Reg) and i.operands[1].name == a.name):
        return None
    if i.op in ("shl", "shr", "sar") and not getattr(i.operands[1], "value", 0) & 31:
        return None
    name, high = HALF.get(a.name, (a.name, 0))
    r = GREG[name]
    return None if high or r[0] != "d" or name in MIRROR else (r, i.width)


def carry_ccr(lines, ccr: set, res, nz: set):
    """The flags the CCR holds with x86 meaning after 68k `lines`, given `ccr`
    before: kept by CCR_NEUTRAL instructions; `nz` after a move of `res` (the
    setter's result register and width, not written since); none after anything
    else. Returns (flags, res), res None once its register may have changed, or
    None for code with labels or transfers."""
    for line in lines:
        if not line.startswith("\t"):
            return None
        op, _, args = line.split(";")[0].strip().partition(" ")
        base = op.split(".")[0]
        if CONTROL.match(base):
            return None
        if base in CCR_NEUTRAL:
            continue
        dst = args.rsplit(",", 1)[-1]
        if res and op == f"move.{SZ[res[1]]}" and args.startswith(res[0] + ",") \
                and not re.fullmatch(r"a[0-7]|ccr|sr", dst):
            ccr = set(nz)
            continue
        ccr = set()
        if res and re.search(rf"\b{res[0]}\b", args):
            res = None
    return ccr, res


def plan(insns, lives, leaders, ctx_for, program: bool = False) -> list[Lowering]:
    """Lower a run of instructions in fall-through order. `lives[k]`: live-out of
    insns[k]; `leaders`: indices that other control flow reaches; `ctx_for(k)`: a
    fresh Ctx for insns[k]."""
    contexts = [ctx_for(k) for k in range(len(insns))]
    dead_dx = reglive.dead_dx(insns, leaders, contexts)
    original_ctx_for = ctx_for

    def ctx_for(k):
        c = original_ctx_for(k)
        c.dead_dx = dead_dx[k]
        return c

    def plain(m):
        if m >= len(insns) or m in leaders:
            return False
        i = insns[m]
        return i.op in PLAIN and not reads(i, program) and not writes(i)[1]

    def provenance(k, ccr_in, x_in):
        """R3b: the setter insns[k] leaves its flags in the CCR across plain
        instructions to a fusing reader (carry_ccr); its lowering, or None."""
        i = insns[k]
        static, res = set(ccr_static(i)), result_reg(i)
        nz = {"SF", "ZF"} if res else set()
        ccr, r, m, mids = static, res, k + 1, []
        while (ccr or r) and plain(m):
            c = ctx_for(m)
            c.live = set(lives[m])
            mids.append(lower(insns[m], c).out)
            step = carry_ccr(mids[-1], ccr, r, nz)
            if step is None:
                return None
            ccr, r = step
            m += 1
        if not mids or m >= len(insns) or m in leaders or not fuse_reader(insns[m]):
            return None
        rd = reads(insns[m], program)
        if not rd or not rd <= ccr:
            return None
        c = ctx_for(k)
        c.x_in, c.live, c.ccr_in, c.fuse = x_in, set(lives[k]), ccr_in, True
        c.need = writes(i)[1] & (set(lives[m]) - writes(insns[m])[0])
        lw = lower(i, c)
        ccr, r = set(lw.ccr), res
        for lines in mids:
            ccr, r = carry_ccr(lines, ccr, r, nz)
        if not rd <= ccr:
            return None
        lw.stats["CCR provenance"] += 1
        chain.update(end=m, res=res, nz=nz)
        return lw

    out = []
    ccr_in: set = set()
    x_in = False
    chain = {"end": -1}
    for k, i in enumerate(insns):
        if k in leaders:
            ccr_in, x_in = set(), False
        must, may = writes(i)
        lw = None
        nxt = insns[k + 1] if k + 1 < len(insns) else None
        if nxt is not None and k + 1 not in leaders and nxt.op in ("adc", "sbb", "rcl", "rcr"):
            c = ctx_for(k)
            c.live, c.ccr_in, c.x_in, c.keep_x = set(lives[k]), ccr_in, x_in, True
            c.need = may & set(lives[k])
            if "CF" not in set(lives[k + 1]) - writes(nxt)[0]:
                c.need.discard("CF")
            candidate = lower(i, c)
            if candidate.cf_result and candidate.x_cf:
                reader = ctx_for(k + 1)
                reader.live, reader.need = set(lives[k + 1]), writes(nxt)[1] & set(lives[k + 1])
                reader.x_in = True
                # Prove the reader's real EA/source setup preserves incoming X.
                if lower(nxt, reader).stats["carry X reused"]:
                    lw = candidate
                    lw.stats["carry pair"] += 1
        if lw is None and nxt is not None and k + 1 not in leaders and fuse_reader(nxt):
            r = reads(nxt, program)
            if r and r <= ccr_static(i):
                c = ctx_for(k)
                c.x_in = x_in
                c.live, c.ccr_in, c.fuse = set(lives[k]), ccr_in, True
                c.need = may & (set(lives[k + 1]) - writes(nxt)[0])
                lw = lower(i, c)
                if not r <= lw.ccr:
                    lw = None
                else:
                    lw.stats["CCR fused"] += 1
        if lw is None and may and plain(k + 1):
            lw = provenance(k, ccr_in, x_in)
        if lw is None:
            c = ctx_for(k)
            c.x_in = x_in
            c.live, c.ccr_in, c.fuse = set(lives[k]), ccr_in, False
            c.need = may & set(lives[k])
            lw = lower(i, c)
            lw.ccr = set()
            if k < chain["end"]:    # between a provenance setter and its reader
                step = carry_ccr(lw.out, ccr_in, chain["res"], chain["nz"])
                if step is None:
                    raise LowerError(f"{i}: provenance chain broken")
                lw.ccr, chain["res"] = step
            elif k == chain["end"] and not reads(i, program) <= ccr_in:
                raise LowerError(f"{i}: provenance reader without its flags in the CCR")
        ccr_in = lw.ccr
        x_in = lw.cf_result and lw.x_cf
        out.append(lw)
    return out
