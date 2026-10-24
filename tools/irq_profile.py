#!/usr/bin/env python3
"""Interrupt-path costs of FS-UAE profile captures (docs/irq-plan.md I1).

  irq_profile.py ELF CAPTURE... [--json OUT]

Over consecutive captures of the exact ELF that ran (tools/profile_tree.py
records and scope rule): interrupt poll tests (`tst.b G_IRQ(a6)` and its
bne, tools/cost_meter.py) as a share of all cycle units, per class; and per
call of the interrupt path's scopes the inclusive cycle units (mean, max)
and the native stack depth below the scope's entry A7 (return address
excluded; max). Scopes: rt_irq (one poll's deliveries), deliver_guest (one
guest handler run: SPAZ's IRQ0 tick, its BIOS chain included),
rt_video_refresh, plat_service, present, plat_present, fm_field. A scope
opens at its symbol reached with A7 four below the previous user-mode record
(a tail-called scope, `present`: also with A7 unchanged from outside its
symbol) and closes at the first user-mode record with A7 above it. Supervisor-stack
records (hardware interrupts) are counted in the total only. Net figures
exclude nested rt_irq scopes (a poll inside a guest handler delivering the
next interrupt or running the field work).
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import cost_meter as M
import profile_report as P
import profile_tree as T

SCOPES = ("rt_irq", "deliver_guest", "rt_video_refresh", "plat_service", "present",
          "plat_present", "fm_field")
TAIL = ("present",)     # reached by bra.l from rt_video_refresh and rt_video_publish


def pct(values, q):
    """Nearest-rank percentile; 0 without values."""
    v = sorted(values)
    return v[max(0, -(-q * len(v) // 100) - 1)] if v else 0


def analyse(prog, captures):
    missing = [n for n in SCOPES if n not in prog.by_name]
    if missing:
        raise SystemExit(f"scope symbols missing from the ELF: {missing}")
    starts = {prog.by_name[n]: n for n in SCOPES}
    polls = {pc: prog.cls[pc] for pc in prog.polls}
    total = fields = 0
    poll_cost, poll_tests = Counter(), Counter()
    calls = {n: [] for n in SCOPES}
    net = {n: [] for n in SCOPES}
    depth, net_depth = Counter(), Counter()
    # [name, entry a7, accumulated, lowest a7, net accumulated, net lowest a7]
    stack, prev, prev_pc = [], None, None
    for cap in captures:
        for pcs, costs, a7s in T.records(cap):
            fields += 1
            for pc, cost, a7 in zip(pcs, costs, a7s):
                total += cost
                if pc in polls:
                    poll_cost[polls[pc]] += cost
                    poll_tests[polls[pc]] += prog.mn[pc] == M.POLL_TEST
                if T.SUPERVISOR[0] <= a7 < T.SUPERVISOR[1] or pc == P.IRQ_MARKER:
                    continue
                while stack and a7 > stack[-1][1]:
                    name, entry, acc, low, acc_net, low_net = stack.pop()
                    calls[name].append(acc)
                    net[name].append(acc_net)
                    depth[name] = max(depth[name], entry - low)
                    net_depth[name] = max(net_depth[name], entry - low_net)
                name = starts.get(pc)
                if name and prev is not None and (a7 == prev - 4 or (
                        name in TAIL and a7 == prev and prog.symbol(prev_pc) != name)):
                    stack.append([name, a7, 0, a7, 0, a7])
                inner = max((k for k, s in enumerate(stack) if s[0] == "rt_irq"), default=0)
                for k, s in enumerate(stack):
                    s[2] += cost
                    s[3] = min(s[3], a7)
                    if k >= inner:
                        s[4] += cost
                        s[5] = min(s[5], a7)
                prev, prev_pc = a7, pc
    return dict(total=total, fields=fields,
                polls={k: dict(cost=poll_cost[k], tests=poll_tests[k]) for k in poll_cost},
                scopes={n: dict(calls=len(v), total=sum(v), max=max(v, default=0), depth=depth[n],
                                p50=pct(v, 50), p99=pct(v, 99),
                                net_total=sum(net[n]), net_max=max(net[n], default=0),
                                net_p99=pct(net[n], 99),
                                net_depth=net_depth[n]) for n, v in calls.items()},
                open_scopes=[[s[0], s[2]] for s in stack])


def report(d):
    total = d["total"]
    print(f"{d['fields']} fields, {total:,} cycle units")
    if d["open_scopes"]:
        print("open at the end (not counted):", ", ".join(f"{n} {a:,}" for n, a in d["open_scopes"]))
    for k, c in sorted(d["polls"].items()):
        print(f"poll tests ({k}): {c['tests']:,} visits, {c['cost']:,} units, "
              f"{100 * c['cost'] / total:.2f}% of the total")
    print("scope              calls   share    mean     p50     p99      max  depth |"
          "    mean     p99      max  depth (net)")
    for n, s in d["scopes"].items():
        k = max(s["calls"], 1)
        print(f"{n:<16} {s['calls']:>7} {100 * s['total'] / total:6.2f}% {s['total'] / k:>7,.0f} "
              f"{s['p50']:>7,} {s['p99']:>7,} {s['max']:>8,} {s['depth']:>6} | "
              f"{s['net_total'] / k:>7,.0f} {s['net_p99']:>7,} {s['net_max']:>8,} {s['net_depth']:>6}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf", type=Path)
    ap.add_argument("captures", nargs="+")
    ap.add_argument("--objdump", default=M.OBJDUMP)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    d = analyse(M.Program(args.elf, args.objdump), args.captures)
    if args.json:
        args.json.write_text(json.dumps(d) + "\n")
    report(d)


if __name__ == "__main__":
    main()
