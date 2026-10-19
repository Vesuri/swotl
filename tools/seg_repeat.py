#!/usr/bin/env python3
"""Choose the segment loads that compare first (speed-plan R30).

  seg_repeat.py [--milestone M] [--min CYCLES] [--write]

Census on the meter window (host run of `make host`'s build with the
reference's interrupts, as tools/host_census.py): per guest instruction that
writes ES, DS or SS (mov, les, lds, pop), its executions and how often the new
value equals the one the segment holds (G_xS at its label and at the next),
its R6 `_bp` copy counted with it. Priced with the cost model: a repeat skips
the zero-extension, the G_xS store, the cell-cache check (where the site has
one) and the base, for one compare and an untaken word branch; a change adds
those and two taken word branches. Sites saving at least --min model cycles go
to annotations/seg-repeat.csv. The choice never affects correctness
(lower.putseg_repeat).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))
import cost_meter as M  # noqa: E402
import host_run  # noqa: E402
from host_run import TOP, Host, U, image, milestone_script, reference_inputs  # noqa: E402

OUT = REPO / "annotations/seg-repeat.csv"
GUEST = re.compile(r"^([A-Z]+_[0-9A-F]{5}(?:_bp)?):\s*; [0-9A-F]{4}:[0-9A-F]{4} (.*)$")
WRITES = re.compile(r"^(?:mov (es|ds|ss), (\w+)|l([ed])s |pop (es|ds|ss)$)")
DATA_REGS = {"ax", "bx", "cx", "dx"}         # held in a data register, not mirrored
SLOT = {"es": 5, "ss": 3, "ds": 1}           # G_ES, G_SS, G_DS (lower.py STATE_EQU)


def sites(gen: Path) -> dict:
    """{label or its `_bp` copy: (segment, next label, register source,
    cell-cache check)}. The check is its `_sx` stub (lower.putseg), in line or
    behind a compare."""
    out = {}
    for s in sorted(gen.glob("*.s")):
        text = s.read_text()
        checked = set(re.findall(r"^(\w+)_sx\d+:", text, re.M))
        prev = None
        for line in text.splitlines():
            m = GUEST.match(line)
            if m:
                if prev:
                    out[prev[0]] = (prev[1], m.group(1), prev[2], prev[0] in checked)
                w = WRITES.match(m.group(2))
                prev = [m.group(1), w.group(1) or (w.group(3) + "s" if w.group(3) else w.group(4)),
                        w.group(2) in DATA_REGS] if w else None
    return out


def census(milestone: str, found: dict, timeout: int) -> tuple[Counter, Counter, str]:
    script = milestone_script(milestone)
    trace = REPO / f"tmp/pc-runs/ref-{milestone}/trace"
    script["irqs"], script["releases"] = reference_inputs(trace)
    h = Host(image.M.REF, None)
    state, hooks = dict(open=False), []

    def code(addr, fn):
        cb = U.CODE_CB(fn)
        hooks.append(cb)
        h.e.hook_range(U.HOOK_CODE, cb, addr, addr)

    def snap(e, addr, size, user):
        if h.step >= 1:
            state["open"] = True

    code(h.syms[script["snapshots"][0][0]], snap)
    pending, execs, same = {}, Counter(), Counter()
    for lab, (seg, nxt, _, _) in found.items():
        if lab not in h.syms or nxt not in h.syms:
            continue
        slot = TOP + SLOT[seg]

        def enter(e, addr, size, user, lab=lab, slot=slot):
            if state["open"]:
                pending[lab] = h.mem(slot, 2)

        def leave(e, addr, size, user, lab=lab, slot=slot):
            if state["open"] and lab in pending:
                execs[lab] += 1
                same[lab] += pending.pop(lab) == h.mem(slot, 2)
        code(h.syms[lab], enter)
        code(h.syms[nxt], leave)
    h.run(script, timeout)
    return execs, same, h.stopped_at


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--milestone", default="m4-demo-frames")
    ap.add_argument("--min", type=float, default=1000, help="least model cycles saved per site")
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    found = sites(REPO / "build/gen")
    execs, same, stopped = census(args.milestone, found, args.timeout)
    c = M.load_model()
    B, R, W, T = c["bytes"], c["reads"], c["writes"], c["taken"]
    per = {}                        # guest label: [segment, executions, repeats, saving]
    for lab, n in execs.items():
        seg, _, reg, check = found[lab]
        k = same[lab]
        # removed on a repeat: zero-extension, store, check, base (lsl, lea, suba)
        kept = ((4 if reg else 2) + 4 + (6 if check else 0) + 8) * B + W
        added = 8 * B + R                                   # cmp.w G_xS(a6), bne.w
        # taken there and back (bra.w); and.l #$ffff for moveq #0
        changed = added + 2 * T + 4 * B + (0 if reg else 4 * B)
        row = per.setdefault(lab.removesuffix("_bp"), [seg, 0, 0, 0.0])
        row[1] += n
        row[2] += k
        row[3] += k * (kept - added) - (n - k) * changed
    rows = [(lab, seg, n, k, round(save)) for lab, (seg, n, k, save) in per.items() if save >= args.min]
    total = sum(r[4] for r in rows)
    print(f"{args.milestone}: stopped at {stopped}; segment loads {len(found)}, executed "
          f"{len(execs)}, {sum(execs.values()):,} executions, {sum(same.values()):,} repeats; "
          f"chosen {len(rows)} (>= {args.min:g} each): {total:,} model cycles")
    for lab, seg, n, k, save in sorted(rows, key=lambda r: -r[4])[:12]:
        print(f"  {save:8,} {lab} {seg} {k:,}/{n:,}")
    if args.write:
        OUT.write_text("label,segment,executions,repeats,saving\n" +
                       "".join(f"{lab},{seg},{n},{k},{save}\n" for lab, seg, n, k, save in sorted(rows)))
        print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
