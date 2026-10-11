"""R6 (speed-plan, D2): BP-stable components and their region guards.

A component is the code reachable from the instruction after a BP write
without crossing another one (a call continues at its return site). In its
guarded copy `[bp+d]` is addressed directly as `(-d,aS,d5.w)`: d5.w holds
BP ^ 7FFFh, which sign-extends to 32767 - BP, so the direct address is the
exact (16-bit wrapping) one whenever 0 <= BP + d <= FFFFh. One guard checks
that for every displacement in the component, at its entry and again after
each call or software interrupt in it (guest code may change BP); a failed
guard continues in the exact code. Which components get a copy is a profile
choice (annotations/bp-regions.csv); it never affects correctness.
"""

from __future__ import annotations

from .decode import Reg
from .lower import bp_offsets, far_pair, sx  # noqa: F401 (far_pair: tools)

REGUARD = frozenset({"call", "callf", "int", "int3", "into"})
NOWRITE = frozenset({"cmp", "test", "push"})


def writes_bp(i) -> bool:
    if i.op in ("popa", "enter", "leave"):
        return True
    if i.op == "xchg":
        return any(isinstance(o, Reg) and o.name == "bp" for o in i.operands)
    o = i.operands[0] if i.operands else None
    return isinstance(o, Reg) and o.name == "bp" and i.op not in NOWRITE


def bp_range(insns) -> tuple[int, int] | None:
    """Signed range of d5.w in which every direct access of `insns` is exact."""
    ds = [d for i in insns for d in bp_offsets(i)]
    if not ds:
        return None
    blo, bhi = max(0, -min(ds)), min(0xFFFF, 0xFFFF - max(ds))
    if blo > bhi:
        return None
    return 0x7FFF - bhi, 0x7FFF - blo


def guard(rng: tuple[int, int], fail: str, sz: str = "") -> list[str]:
    """Fall through when d5.w lies in `rng`, else branch to `fail` (CCR clobbered);
    `sz`: the size suffix of the branches."""
    lo, hi = rng
    out = []
    if lo > -0x8000:
        out += [f"\tcmp.w #{sx(lo)},d5", f"\tblt{sz} {fail}"]
    if hi < 0x7FFF:
        out += [f"\tcmp.w #{sx(hi)},d5", f"\tbgt{sz} {fail}"]
    return out


def entry(rng: tuple[int, int], ok: str, fail: str, sz: str = "") -> list[str]:
    """Branch to `ok` when d5.w lies in `rng`, else to `fail`, the next label
    (CCR clobbered)."""
    lo, hi = rng
    if lo > -0x8000 and hi < 0x7FFF:
        return [f"\tcmp.w #{sx(lo)},d5", f"\tblt.s {fail}", f"\tcmp.w #{sx(hi)},d5", f"\tble{sz} {ok}"]
    if lo > -0x8000:
        return [f"\tcmp.w #{sx(lo)},d5", f"\tbge{sz} {ok}"]
    if hi < 0x7FFF:
        return [f"\tcmp.w #{sx(hi)},d5", f"\tble{sz} {ok}"]
    return [f"\tbra{sz} {ok}"]


def writers(p) -> set:
    """Nodes that write BP and fall through into an instruction that does not."""
    out = set()
    for n in p.succ:
        f = p.fall.get(n)
        if writes_bp(p.node_insn(n)) and f and not writes_bp(p.node_insn(f)):
            out.add(n)
    return out


def reach(p, start) -> set:
    """Nodes reachable from `start` in its module without crossing a BP write
    (a call continues at its return site; a divide error is an interrupt)."""
    seen, stack = {start}, [start]
    while stack:
        n = stack.pop()
        i = p.node_insn(n)
        for x in [p.call_site[n]] if n in p.call_site else p.succ[n]:
            if not isinstance(x, tuple) or x == p.int0 and i.op in ("div", "idiv", "aam"):
                continue
            if x[0] == start[0] and x in p.succ and x not in seen \
                    and not writes_bp(p.node_insn(x)):
                seen.add(x)
                stack.append(x)
    return seen


def components(p, ws) -> list[tuple[set, set, set]]:
    """(writers, entries, nodes) of the components after `ws`; overlapping
    ones merge (one copy, one range)."""
    merged: list[tuple[set, set, set]] = []
    for w in sorted(ws):
        c = ({w}, {p.fall[w]}, reach(p, p.fall[w]))
        for m in [m for m in merged if m[2] & c[2]]:
            merged.remove(m)
            c = (c[0] | m[0], c[1] | m[1], c[2] | m[2])
        merged.append(c)
    return merged
