"""Execute synthetic predecessor graphs against the x86 oracle.

These cases run their predecessors, not just an isolated consumer with an
assumed CCR. Existing register, flags, memory and destination checks apply.
"""
from collections import Counter
import importlib.util

import m68k_diff as D
from translator.decode import decode, Rel, Far
from translator.interp import State, step
from translator.ir import FLAGS, STATUS
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

        lives, taken = [set(D.F.ALL) for _ in insns], None
        if real_lives:
            lives, live_in = graph_lives(insns, succ, by_ip)
            taken = [(live_in[by_ip[i.operands[0].target]] if i.operands[0].target in by_ip
                      else set(D.F.ALL)) if i.op == "jcc" else None for i in insns]
        baseline = D.F.plan(insns, lives, leaders, ctx, taken=taken)
        if importlib.util.find_spec("translator.crossflags"):
            from translator.crossflags import branch_entries
            entries = branch_entries(dict(enumerate(insns)), dict(enumerate(baseline)),
                                     succ, {0}, leaders)
        lowered = D.F.plan(insns, lives, leaders, ctx, taken=taken)
        out, cold, stats = [f"{tag}:"], [], Counter()
        for k, lw in enumerate(lowered):
            out += [f"{tag}_{k}:"] + lw.out
            cold += lw.cold
            stats.update(lw.stats)
        out += [f"{tag}_end:", f"\tmove.l #{hx(insns[-1].next_ip)},d7", "\tjmp T_END"]
        return out + cold, stats

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
    real_lives = False
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
        real_lives = True
        for code in chain_graphs():
            whole = bytes.fromhex(code)
            for k, (ax, bx) in enumerate((a, b) for a in VALUES for b in VALUES):
                flags = {f: int((k * 7 + j) % 3 == 0) for j, f in enumerate(STATUS)}
                flags.update(DF=0, IF=1, TF=0)
                regs = {"cs": 0x2000, "ds": 0x5000, "ax": ax, "bx": bx, "cx": bx ^ 0x00ff,
                        "dx": (ax & 0xff) << 8 | bx & 0xff, "si": ax ^ 0x8000, "di": bx}
                mem = [(0x50000 + bx, bytes((ax & 0xff, ax >> 8)))]
                h.case(whole, "chain", n=steps(whole, regs, flags, mem), block=True,
                       overrides={"regs": regs, "ip": 0x100, "flags": flags, "mem": mem})
        h.flush()
    finally:
        D.lower_case = real_lower
    return sum(h.count.values()), h.bad, h.lowered


VALUES = (0, 1, 0x7f, 0x80ff, 0x8000, 0xffff)


def chain_graphs():
    """Graphs whose flags die after a join (CMP SI,SI), lowered with their real
    liveness: R14a/c/g setters fused with a jump over MOV DX,CX to the join;
    R14b chains of jumps (each falls through to the next, targets the join or
    the end), after a fused setter, after a load (INC; JB) and before ADC."""
    out = []
    join = "39f6"
    for setter in ("28e4", "30ed", "08f6", "20ff", "84e4", "80e40f", "f60780", "f7070080", "f607ff",
                   "3807", "3827", "3907", "09f6", "21ff", "85f6"):
        for jcc in ("74", "78", "72", "70", "7c", "7f", "76"):
            out.append(setter + jcc + "02" + "89ca" + join)
    for chain in ("7c04 7502 89ca", "7206 7404 7f02 89ca", "7404 7c02 89ca", "7704 7202 89ca"):
        for setter in ("39d8", "29d8", "84c0", "40", "fec4"):
            out.append(setter + chain.replace(" ", "") + join)
            out.append(setter + chain.replace(" ", ""))
    out += ["4072047402" "89ca", "4074047202" "89ca", "29d87503" "83d100" "89ca"]
    # R14d: the chain's jumps reach a join that kills the flags (or one that
    # reads CF, or the end), so a later jump's flags live only in the CCR
    for setter in ("39d8", "29d8", "40", "84c0"):
        for chain in ("7c06 7504 7f02 89ca", "7206 7404 7802 89ca", "7404 7202 89ca",
                      "7204 7402 89ca"):
            for tail in (join, "720289ca" + join, ""):
                out.append(setter + chain.replace(" ", "") + tail)
        # an earlier jump leaves the graph (every flag live), the last reaches the join
        for chain in ("7c06 7502 89ca", "7208 7404 7802 89ca"):
            out.append(setter + chain.replace(" ", "") + join)
    return out


def steps(code: bytes, regs: dict, flags: dict, mem) -> int:
    """x86 instructions run from 2000:0100 until IP leaves the graph."""
    image = bytearray(0x60000)
    image[0x20100:0x20100 + len(code)] = code
    for a, data in mem:
        image[a:a + len(data)] = data
    full = {r: 0 for r in ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di", "es", "ss", "ds")}
    s = State(dict(full, **regs, flagsx=0), {f: int(flags.get(f, 0)) for f in FLAGS}, image, 0x100)
    n = 0
    while 0x100 <= s.ip < 0x100 + len(code):
        step(s)
        n += 1
    return n


def graph_lives(insns, succ, by_ip) -> tuple[list[set], list[set]]:
    """Live-out and live-in of each node; transfers out of the graph and its end
    see every flag."""
    live_in = [set() for _ in insns]
    out = [set() for _ in insns]
    changed = True
    while changed:
        changed = False
        for k in reversed(range(len(insns))):
            i = insns[k]
            o = set()
            for t in succ[k]:
                o |= live_in[t]
            leaves = (i.op == "jcc" and i.operands[0].target not in by_ip
                      or i.op not in ("jmp", "jmpf") and k + 1 == len(insns))
            if leaves:
                o |= D.F.ALL
            new = D.F.transfer(i, o)
            if o != out[k] or new != live_in[k]:
                out[k], live_in[k], changed = o, new, True
    return out, live_in


if __name__ == "__main__":
    import sys
    n, bad, stats = run()
    print(f"cross predecessors: {n} cases, {len(bad)} mismatches; {stats}")
    for failure in bad[:5]:
        print(failure)
    sys.exit(bool(bad))
