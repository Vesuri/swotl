"""Execute synthetic predecessor graphs against the x86 oracle.

These cases run their predecessors, not just an isolated consumer with an
assumed CCR. Existing register, flags, memory and destination checks apply.
"""
from collections import Counter
import importlib.util

import m68k_diff as D
from translator.decode import decode, Rel, Far
from translator.lower import Ctx, hx


def run():
    real_lower = D.lower_case
    h = D.Harness(7)
    whole = b""

    def lower_graph(_insns, cs, tag, _end_ip):
        insns = []
        at = 0
        while at < len(whole):
            i = decode(whole, 0x100 + at, at)
            insns.append(i)
            at += i.size
        by_ip = {i.ip: k for k, i in enumerate(insns)}
        labels = {ip: f"{tag}_{k}" for ip, k in by_ip.items()}
        succ, leaders = {}, {0}
        for k, i in enumerate(insns):
            target = (i.operands[0].target if i.op in ("jcc", "jmp") and
                      isinstance(i.operands[0], Rel) else
                      i.operands[0].off if i.op == "jmpf" and isinstance(i.operands[0], Far) else None)
            ss = []
            if target in by_ip:
                ss.append(by_ip[target])
                leaders.add(by_ip[target])
            if i.op not in ("jmp", "jmpf") and k + 1 < len(insns):
                ss.append(k + 1)
            succ[k] = ss
        entries = {}

        def ctx(k):
            c = Ctx(cs=hx(cs), label=f"{tag}_{k}", near=labels.get,
                    far=lambda pair: labels.get(pair[1]) if pair[0] == hx(cs) else None)
            c.ccr_entry = entries.get(k, set())
            return c

        lives = [set(D.F.ALL) for _ in insns]
        baseline = D.F.plan(insns, lives, leaders, ctx)
        if importlib.util.find_spec("translator.crossflags"):
            from translator.crossflags import branch_entries
            entries = branch_entries(dict(enumerate(insns)), dict(enumerate(baseline)),
                                     succ, {0}, leaders)
        lowered = D.F.plan(insns, lives, leaders, ctx)
        out, stats = [f"{tag}:"], Counter()
        for k, lw in enumerate(lowered):
            out += [f"{tag}_{k}:"] + lw.out
            stats.update(lw.stats)
        out += [f"{tag}_end:", f"\tmove.l #{hx(insns[-1].next_ip)},d7", "\tjmp T_END"]
        return out, stats

    # Conditional taken/fallthrough, near jump, far jump, EA-setup clobber,
    # two-predecessor joins, and a join with one CCR-clobbering predecessor.
    graphs = (
        ("39d8 7400 7f02", 3, 3),
        ("39d8 7400 eb00 7f02", 4, 4),
        ("39d8 7400 ea09010020 7f02", 4, 4),
        ("39d8 7400 8d36ffff 7f02", 4, 4),
        ("7406 39d8 7400 eb04 39d0 7400 7f02", 5, 4),
        ("7406 39d8 7400 eb06 39d0 7400 89c9 7f02", 5, 5),
    )
    D.lower_case = lower_graph
    try:
        for code, false_count, true_count in graphs:
            whole = bytes.fromhex(code)
            for ax in (0, 1, 0x8000, 0xffff):
                for bx in (0, 1, 0x8000, 0xffff):
                    for zf in (0, 1):
                        h.case(whole, "cross-predecessors", n=true_count if zf else false_count,
                               block=True, overrides={"regs": {"cs": 0x2000, "ax": ax,
                               "bx": bx, "dx": bx ^ 0x8000}, "ip": 0x100, "flags": {"ZF": zf}})
        h.flush()
    finally:
        D.lower_case = real_lower
    return sum(h.count.values()), h.bad, h.lowered


if __name__ == "__main__":
    import sys
    n, bad, stats = run()
    print(f"cross predecessors: {n} cases, {len(bad)} mismatches; {stats}")
    for failure in bad[:5]:
        print(failure)
    sys.exit(bool(bad))
