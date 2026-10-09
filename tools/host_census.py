#!/usr/bin/env python3
"""Census of the generated program on the host run (docs/perf-method.md: exact
counts, never timing): from the first snapshot of a reference milestone to its
last, with the reference's interrupts replayed (tests/host_run.py).

  host_census.py MILESTONE [--labels L ...] [--strops] [--vram] [--frame LABEL]
                [--whole] [--table reference/coverage.csv]

--labels  executions of each generated label
--strops  elements processed by each `rep`/`repe`/`repne` string instruction
          (CX at the label minus CX at the next label), per execution and
          per frame; top counts
--vram    bytes written to A0000h-AFFFFh by guest instruction label, and
          rows (320 bytes) written per frame
--whole   count from the program entry instead of the first snapshot
--table   milestone table (default reference/milestones.csv)
--frame   label that runs once per drawn frame (default FLT_15E82; m4 census:
          49 per 49 frames, as R_044E2)
"""
import argparse
import bisect
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import host_run  # noqa: E402
from host_run import REPO, TOP, Host, U, image, milestone_script, reference_inputs  # noqa: E402

LABEL = re.compile(r"^[A-Z]+_[0-9A-F]{5}$")
REP = re.compile(r"; [0-9A-F]{4}:[0-9A-F]{4} rep[a-z]* (movs|stos|cmps|scas|lods|ins|outs)[bwd]?$")


def string_ops(gen):
    """{label: next label} for every rep-prefixed string instruction."""
    ops = {}
    for s in Path(gen).glob("*.s"):
        prev = None
        for line in s.read_text().splitlines():
            m = re.match(r"^(\w+):\s*(;.*)?$", line)
            if not m or not LABEL.match(m.group(1)):
                continue
            if prev:
                ops[prev] = m.group(1)
                prev = None
            if m.group(2) and REP.search(m.group(2)):
                prev = m.group(1)
    return ops


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("milestone")
    ap.add_argument("--labels", nargs="*", default=[])
    ap.add_argument("--strops", action="store_true")
    ap.add_argument("--vram", action="store_true")
    ap.add_argument("--frame", default="FLT_15E82")
    ap.add_argument("--whole", action="store_true")
    ap.add_argument("--table", type=Path)
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args()
    if args.table:
        host_run.TABLE = args.table.resolve()

    script = milestone_script(args.milestone)
    trace = REPO / f"tmp/pc-runs/ref-{args.milestone}/trace"
    script["irqs"], script["releases"] = reference_inputs(trace)
    h = Host(image.M.REF, None)
    state = dict(open=args.whole, frames=0)
    hooks = []              # keep the ctypes callbacks alive

    def code(addr, fn):
        cb = U.CODE_CB(fn)
        hooks.append(cb)
        h.e.hook_range(U.HOOK_CODE, cb, addr, addr)

    def snap(e, addr, size, user):
        if h.step >= 1:
            state["open"] = True

    def frame(e, addr, size, user):
        if state["open"]:
            state["frames"] += 1
            rows.append(set())

    code(h.syms[script["snapshots"][0][0]], snap)
    rows = [set()]
    code(h.syms[args.frame], frame)

    counts = Counter()
    for lab in args.labels:
        def hit(e, addr, size, user, lab=lab):
            if state["open"]:
                counts[lab] += 1
        code(h.syms[lab], hit)

    cx, execs, elems, hist = {}, Counter(), Counter(), {}
    if args.strops:
        for op, nxt in string_ops(REPO / "build/gen").items():
            if op not in h.syms or nxt not in h.syms:
                continue
            hist[op] = Counter()

            def enter(e, addr, size, user, op=op):
                if state["open"]:
                    cx[op] = h.r("d1") & 0xFFFF

            def leave(e, addr, size, user, op=op):
                if state["open"] and op in cx:
                    n = cx.pop(op) - (h.r("d1") & 0xFFFF)
                    execs[op] += 1
                    elems[op] += n
                    hist[op][n] += 1
            code(h.syms[op], enter)
            code(h.syms[nxt], leave)

    writers = Counter()
    if args.vram:
        lab = sorted((a, n) for n, a in h.syms.items() if LABEL.match(n))
        addrs = [a for a, _ in lab]

        def wr(e, kind, addr, size, value, user):
            if state["open"]:
                i = bisect.bisect_right(addrs, h.r("pc")) - 1
                writers[lab[i][1] if i >= 0 else "?"] += size
                rows[-1].add(max(TOP - addr - size + 1 - 0xA0000, 0) // 320)
            return True
        cb = U.MEM_CB(wr)
        hooks.append(cb)
        h.e.hook_range(U.HOOK_MEM_WRITE, cb, TOP - 0xAFFFF, TOP - 0xA0000)

    h.run(script, args.timeout)
    f = max(state["frames"], 1)
    print(f"{args.milestone}: stopped at {h.stopped_at}; {state['frames']} frames ({args.frame})")
    for lab in args.labels:
        print(f"{lab} {counts[lab]} ({counts[lab] / f:.1f} per frame)")
    for op in sorted(execs, key=lambda o: -elems[o]):
        print(f"{op}: {execs[op]} runs ({execs[op] / f:.0f}/frame), {elems[op]} elements "
              f"({elems[op] / f:.0f}/frame, {elems[op] / execs[op]:.1f}/run); "
              f"top {hist[op].most_common(4)}")
    if args.vram:
        tot = sum(writers.values())
        print(f"A0000h bytes written {tot} ({tot / f:.0f}/frame)")
        for n, c in writers.most_common(15):
            print(f"{100 * c / max(tot, 1):6.2f}%  {n}")
        sizes = sorted(len(r) for r in rows[1:]) or [0]
        print(f"rows written per frame min/median/max {sizes[0]} {sizes[len(sizes) // 2]} {sizes[-1]}")


if __name__ == "__main__":
    main()
