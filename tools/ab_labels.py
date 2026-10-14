#!/usr/bin/env python3
"""FS-UAE mix-adjusted A/B per generated label (docs/speed-plan.md M1, §3).

  ab_labels.py CAPTURE_A ELF_A CAPTURE_B ELF_B METER_JSON [--objdump ...]

Each capture (tools/profile_report.py format) gives every generated label's
cycles per execution (its PCs up to the next symbol). Both arms are weighted
by the same executions, the meter's (tools/cost_meter.py --out), so a
different instruction mix in the two capture windows cannot move the result:
delta = sum(w * (cpe_B - cpe_A)) / sum(w * cpe_A). Reported over all labels
executed in both captures and over the changed labels only (instruction text
differs, branch targets compared by symbol, not address).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_meter as M  # noqa: E402
import profile_report as P  # noqa: E402


def canon(name: str) -> str:
    """A guarded copy's label (R6) is its instruction's."""
    return name.removesuffix("_bp")


def label_cycles(capture: Path, syms: list, extra=frozenset()) -> tuple[Counter, Counter]:
    """Per label: cycles of its span and executions of its first PC. A region
    guard (R6) belongs to the instruction it follows."""
    syms = [(a, n) for a, n in syms if not n.endswith(("_bpg", "_bpr"))]
    prof = P.decode(capture)
    addrs = np.array([a for a, _ in syms], dtype=np.int64)
    names = [n for _, n in syms]
    first = {a for a, n in syms}
    cyc, execs = Counter(), Counter()
    for _, _, pcs, cost in prof["fields"]:
        u, inv = np.unique(pcs, return_inverse=True)
        c, n = np.bincount(inv, weights=cost), np.bincount(inv)
        for pc, cc, nn in zip(u.tolist(), c.tolist(), n.tolist()):
            i = int(np.searchsorted(addrs, pc, side="right")) - 1
            if i < 0 or (not P.GUEST.match(names[i]) and "walk" not in names[i]
                         and names[i] not in extra):
                continue
            cyc[canon(names[i])] += cc
            if pc in first and pc == addrs[i]:
                execs[canon(names[i])] += nn
    return cyc, execs


def normalize(insn: str) -> str:
    """An instruction's text with addresses replaced by their symbol names."""
    return re.sub(r"\b[0-9a-f]+ <([^>]*)>", r"<\1>", insn)


def bodies(elf: Path, objdump: str) -> dict[str, tuple]:
    """Label -> its instructions with addresses replaced by symbol names."""
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", str(elf)], capture_output=True,
                         text=True, check=True).stdout
    body, cur = {}, None
    for line in out.splitlines():
        m = re.match(r"^[0-9a-f]+ <(\w+)>:$", line)
        if m:
            cur = m.group(1)
            body[cur] = []
            continue
        m = re.match(r"^\s+[0-9a-f]+:\s+(.*)$", line)
        if m and cur:
            body[cur].append(normalize(m.group(1)))
    return {k: tuple(v) for k, v in body.items()}


def mix_delta(a: tuple, b: tuple, weights: dict, only=None) -> tuple[float, float, float]:
    """(delta fraction, weighted A cycles, share of the weight covered)."""
    (ca, ea), (cb, eb) = a, b
    num = den = covered = total = 0.0
    for lab, w in weights.items():
        if only is not None and lab not in only:
            continue
        total += w
        if ea.get(lab) and eb.get(lab):
            pa, pb = ca[lab] / ea[lab], cb[lab] / eb[lab]
            num += w * (pb - pa)
            den += w * pa
            covered += w
    return (num / den if den else 0.0), den, (covered / total if total else 0.0)


def changed_labels(weights, before, after):
    return {k for k in weights if before.get(k) != after.get(k)
            or before.get(k + "_bp") != after.get(k + "_bp")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture_a", type=Path)
    ap.add_argument("elf_a", type=Path)
    ap.add_argument("capture_b", type=Path)
    ap.add_argument("elf_b", type=Path)
    ap.add_argument("meter", type=Path, help="cost_meter.py --out JSON (the weights)")
    ap.add_argument("--objdump", default=M.OBJDUMP)
    ap.add_argument("--runtime-weight", action="append", default=[], metavar="LABEL=COUNT",
                    help="include a runtime helper with its independently measured host census count")
    args = ap.parse_args(argv)
    meter = json.loads(args.meter.read_text())
    weights = Counter()
    for k, v in meter["labels"].items():
        if v.get("execs"):
            weights[canon(k)] += v["execs"]
    extra = {}
    for spec in args.runtime_weight:
        name, sep, count = spec.partition("=")
        if not sep or not name or not count.isdigit() or int(count) <= 0 or name in weights or name in extra:
            ap.error("runtime weight must be a unique LABEL=positive census count")
        extra[name] = int(count)
    weights.update(extra)
    a = label_cycles(args.capture_a, P.symbols(args.objdump, str(args.elf_a)), extra)
    b = label_cycles(args.capture_b, P.symbols(args.objdump, str(args.elf_b)), extra)
    for name in extra:
        if not a[1].get(name) or not b[1].get(name):
            ap.error(f"runtime helper {name} was not exercised in both captures")
        pa, pb = a[0][name] / a[1][name], b[0][name] / b[1][name]
        if not pa or not pb:
            ap.error(f"runtime helper {name} has no measured cycles")
        print(f"runtime {name}: {a[1][name]} / {b[1][name]} calls; "
              f"{pa:.3f} -> {pb:.3f} cycles/call ({100 * (pb / pa - 1):+.3f}%), "
              f"{extra[name] * (pb - pa):+,.0f} census-weighted cycles")
    ba, bb = bodies(args.elf_a, args.objdump), bodies(args.elf_b, args.objdump)
    changed = changed_labels(weights, ba, bb)
    d, den, cov = mix_delta(a, b, weights)
    print(f"all labels: mix-adjusted delta {100 * d:+.3f}% (weight covered {100 * cov:.1f}%)")
    d, den, cov = mix_delta(a, b, weights, changed)
    print(f"changed labels ({len(changed)}): mix-adjusted delta {100 * d:+.3f}% of their cycles, "
          f"{d * den:+,.0f} weighted cycles (weight covered {100 * cov:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
