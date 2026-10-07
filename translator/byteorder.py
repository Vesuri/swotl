"""Block-local word representation through moves, pushes and pops.

Only data registers may hold raw little-endian words. Every other instruction,
leader and runtime boundary sees the original native-register contract. Plans
are independent of profile observations and accept only a net instruction cut.
"""
from dataclasses import dataclass, field

from .decode import Mem, Reg

REGS = frozenset({"ax", "bx", "cx", "dx", "bp"})


@dataclass
class Action:
    raw_load: bool = False
    raw_store: bool = False
    swap_store: bool = False
    before: set = field(default_factory=set)
    after: set = field(default_factory=set)


def eligible(i):
    if i.op in ("push", "pop"):
        return isinstance(i.operands[0], Reg) and i.operands[0].name in REGS
    return (i.op == "mov" and i.width == 16 and
            all(not isinstance(o, Reg) or o.name in REGS for o in i.operands))


def overwritten_before_use(insns, k, reg):
    """The eligible run has no conditional writes, traps or hidden consumers."""
    for i in insns[k + 1:]:
        ops = i.operands
        reads = {r for o in ops if isinstance(o, Mem) for r in (o.base, o.index)}
        if i.op == "push":
            reads.add(ops[0].name)
        elif i.op == "mov" and isinstance(ops[1], Reg):
            reads.add(ops[1].name)
        if reg in reads:
            return False
        if i.op == "pop" and ops[0].name == reg or (
                i.op == "mov" and isinstance(ops[0], Reg) and ops[0].name == reg):
            return True
    return False


def run_actions(insns):
    actions = [Action() for _ in insns]
    raw = set()
    swaps = copies = 0
    for k, (i, a) in enumerate(zip(insns, actions)):
        ops = i.operands
        addresses = {r for o in ops if isinstance(o, Mem) for r in (o.base, o.index)}
        a.before = raw & addresses
        raw -= a.before
        swaps -= len(a.before)
        if i.op == "pop" or (i.op == "mov" and isinstance(ops[0], Reg) and
                             isinstance(ops[1], Mem)):
            a.raw_load = True
            raw.add(ops[0].name)
            swaps += 1
        elif i.op == "mov" and isinstance(ops[0], Reg):
            dest, src = ops
            source_raw = isinstance(src, Reg) and src.name in raw
            raw.discard(dest.name)
            if source_raw:
                raw.add(dest.name)
        else:
            reg = (ops[0].name if i.op == "push" else
                   ops[1].name if isinstance(ops[1], Reg) else None)
            if reg in raw:
                a.raw_store = True
                swaps += 1
                copies += 1
            elif reg and reg not in addresses and overwritten_before_use(insns, k, reg):
                a.raw_store = a.swap_store = True
                raw.add(reg)
                copies += 1
    actions[-1].after = raw
    swaps -= len(raw)
    # Each removed swap/copy is two encoded bytes. Never add net swaps;
    # require a strict instruction/byte reduction independent of profile costs.
    return actions if swaps >= 0 and swaps + copies > 0 else None


def plan(insns, leaders, contexts):
    result = [Action() for _ in insns]
    group = []

    def finish():
        if group:
            actions = run_actions([insns[k] for k in group])
            if actions:
                for k, action in zip(group, actions):
                    result[k] = action
            group.clear()

    for k, i in enumerate(insns):
        ok = eligible(i) and not contexts[k].vram
        if k in leaders or not ok:
            finish()
        if ok:
            group.append(k)
    finish()
    return result
