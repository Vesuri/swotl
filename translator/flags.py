"""Flag demand (D6): liveness of the six status flags and the per-instruction
store/fuse plan the lowering follows.

An instruction stores the flags it defines that are live after it. When the
next instruction reads flags straight from the CCR (a fusing reader, not a
block leader) and the setter's 68k CCR holds them with x86 meaning, the setter
stores only what is live after the reader and the reader skips the load.
"""

from __future__ import annotations

from .ir import STATUS
from .lower import CCR_OK, Ctx, Lowering, fuse_reader, lower, reads, writes

ALL = frozenset(STATUS)
FUSE_KIND = {"add": "add", "adc": "adc", "sub": "sub", "sbb": "sbb", "cmp": "cmp",
             "and": "logic", "or": "logic", "xor": "logic", "test": "logic", "inc": "inc",
             "dec": "dec", "neg": "neg", "shl": "shl", "shr": "shr", "sar": "sar"}


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


def plan(insns, lives, leaders, ctx_for, program: bool = False) -> list[Lowering]:
    """Lower a run of instructions in fall-through order. `lives[k]`: live-out of
    insns[k]; `leaders`: indices that other control flow reaches; `ctx_for(k)`: a
    fresh Ctx for insns[k]."""
    out = []
    ccr_in: set = set()
    x_in = False
    for k, i in enumerate(insns):
        if k in leaders:
            ccr_in, x_in = set(), False
        must, may = writes(i)
        lw = None
        nxt = insns[k + 1] if k + 1 < len(insns) else None
        if nxt is not None and k + 1 not in leaders and nxt.op in ("adc", "sbb", "rcl", "rcr"):
            c = ctx_for(k)
            c.live, c.ccr_in, c.x_in = set(lives[k]), ccr_in, x_in
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
        if lw is None:
            c = ctx_for(k)
            c.x_in = x_in
            c.live, c.ccr_in, c.fuse = set(lives[k]), ccr_in, False
            c.need = may & set(lives[k])
            lw = lower(i, c)
            lw.ccr = set()
        ccr_in = lw.ccr
        x_in = lw.cf_result and lw.x_cf
        out.append(lw)
    return out
