#!/usr/bin/env python3
"""Deterministic cost meter (docs/speed-plan.md §3-4): the per-step acceptance.

  cost_meter.py [MILESTONE] [--elf E] [--gen G] [--out JSON]
  cost_meter.py --compare A.json B.json
  cost_meter.py --calibrate CAPTURE ELF [--write]
  cost_meter.py --plant-check BASE_JSON

Run: the host run (tests/host_run.py, the reference's interrupts replayed)
from the milestone's first snapshot to its last (default m4-demo-frames: 49
drawn frames of the demo flight). A Unicorn block hook counts executions of
every translated block and every taken transfer (and its target: `targets`,
for R8's alignment); blocks expand to executed
68k instructions over the disassembly of the image that ran. Features per
instruction, all static except taken: encoded bytes and taken transfers,
each split by whether the instruction lies in an innermost loop of <= 256
bytes (the 68020 i-cache); data reads; data writes; mul/div. Model cycles =
the features weighted by tools/cost_model.json. Exact and layout-blind: the
same build gives the same numbers, and moving code changes nothing.

Calibrate: fit the weights (non-negative least squares) on an FS-UAE capture
(tools/profile_report.py format) of the Amiga ELF of the same build: per-PC
cycles against per-PC executions times features, taken counts from the
capture's PC sequence. Compare: per class and per x86 form, the deltas the
speed plan reports. Plant check: every `ror.w #8` tripled (flag-neutral)
must add exactly its instructions and bytes, and their cost.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TOOLS))
import lowering_cost as L  # noqa: E402
import profile_report as P  # noqa: E402

MODEL = TOOLS / "cost_model.json"
# The shared toolchain, as amiga/env.sh.
CROSS = str(Path(os.environ.get("AMIGA_TOOLCHAIN") or Path.home() / ".local/opt") / "bin/m68k-amiga-elf-")
VASM = os.environ.get("VASM") or str(Path.home() / ".local/vasmm68k_mot")
OBJDUMP = CROSS + "objdump"
FEATURES = ("insns", "bytes", "loop_bytes", "reads", "writes", "taken", "loop_taken", "muldiv")
LOOP = 256      # 68020 instruction cache

# --- static features ---------------------------------------------------------

REG = re.compile(r"^(%?[ad][0-7]|sp|fp|pc|ccr|sr|usp|vbr|[ad][0-7]-[ad][0-7].*|[ad][0-7]/.*)$")
ABS = re.compile(r"^[0-9a-f]+( <[^>]*>)?$")
BRANCH = re.compile(r"^(b(ra|hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le|hs|lo)|db\w+)(\.[swl])?$")
CC = ("t", "f", "hi", "ls", "cc", "cs", "ne", "eq", "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le")
READ_ONLY = ("cmp", "cmpa", "cmpi", "tst", "btst", "chk", "chk2", "cmp2", "bftst", "bfextu",
             "bfexts", "bfffo", "mulu", "muls", "divu", "divs", "divul", "divsl")


def split_args(args: str) -> list[str]:
    """Top-level comma split (indexed modes contain commas); symbol notes dropped."""
    out, depth, cur = [], 0, ""
    for ch in re.sub(r" <[^>]*>", "", args):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def is_mem(operand: str) -> bool:
    if operand.startswith("#") or REG.match(operand):
        return False
    return "(" in operand or bool(ABS.match(operand))


def reglist_size(operand: str) -> int:
    n = 0
    for part in operand.split("/"):
        if "-" in part:
            a, b = part.split("-")
            n += int(b[1]) - int(a[1]) + 1 + (8 if a[0] != b[0] else 0)
        else:
            n += 1
    return n


def accesses(op: str, args: str) -> tuple[int, int, int]:
    """(data reads, data writes, mul/div) of one 68k instruction."""
    base = op.split(".")[0]
    if base in ("rts", "rtd"):
        return 1, 0, 0
    if base == "rtr":
        return 2, 0, 0
    if base in ("jsr", "bsr"):
        return 0, 1, 0
    if base in ("jmp", "nop", ".short", ".word", ".long") or BRANCH.match(op) or base.startswith("trap"):
        return 0, 0, 0
    if base == "link":
        return 0, 1, 0
    if base == "unlk":
        return 1, 0, 0
    ops = split_args(args)
    muldiv = int(base in ("mulu", "muls", "divu", "divs", "divul", "divsl"))
    if base == "movem":
        n = reglist_size(ops[0] if REG.match(ops[0]) else ops[1])
        return (0, n, 0) if REG.match(ops[0]) else (n, 0, 0)
    if base == "cmpm":
        return 2, 0, 0
    if base in ("addx", "subx", "abcd", "sbcd") and ops and is_mem(ops[0]):
        return 2, 1, 0
    if base in ("bfextu", "bfexts", "bfffo"):
        # objdump: source,offset,width,destination (unlike BFINS).
        ops = [ops[0], ops[-1]]
    elif base.startswith("bf"):   # offset and width follow the operands
        ops = ops[:-2]
    if base == "pea":
        return 0, 1, 0
    if base == "lea":
        return 0, 0, 0
    mem = [is_mem(o) for o in ops]
    if not any(mem):
        return 0, 0, muldiv
    if base in ("move", "movea", "movep", "move16", "moves"):
        return int(mem[0]), int(len(mem) > 1 and mem[-1]), 0
    if base == "clr" or base in tuple("s" + c for c in CC):
        return 0, int(mem[-1]), 0
    if base in READ_ONLY or base.startswith("cmp"):
        return sum(mem), 0, muldiv
    if base.startswith("bf"):     # bfins, bfset, bfclr, bfchg: read-modify-write
        return 1, 1, 0
    # ALU: a memory source is read; a memory destination is read and written
    reads = sum(mem[:-1]) + int(mem[-1])
    return reads, int(mem[-1]), muldiv


class Program:
    """The disassembly and symbols of one ELF: per-PC static features and the
    class of every PC (generated guest code, cell walk, runtime, platform)."""

    def __init__(self, elf: Path, objdump: str = OBJDUMP, platform_objs: tuple = ()):
        out = subprocess.run([objdump, "-d", "--insn-width=32", str(elf)],
                             capture_output=True, text=True, check=True).stdout
        self.init(out, P.symbols(objdump, str(elf)), self.object_symbols(objdump, platform_objs))

    @staticmethod
    def object_symbols(objdump: str, objs) -> set[str]:
        names = set()
        for o in objs:
            if Path(o).exists():
                out = subprocess.run([objdump, "-t", str(o)], capture_output=True, text=True,
                                     check=True).stdout
                names.update(p.split()[-1] for p in out.splitlines()
                             if len(p.split()) >= 5 and p.split()[-3] == ".text")
        return names

    def init(self, dis: str, syms: list, platform: set[str]):
        mn, sizes = L.parse_disassembly(dis)
        self.addrs = np.array(sorted(mn), dtype=np.int64)
        self.size = {a: sizes[a] for a in mn}
        self.mn = mn
        self.syms = syms
        self.sym_addr = [a for a, _ in syms]
        self.by_name = {n: a for a, n in syms}
        feats = {}
        for a, (op, arg) in mn.items():
            r, w, m = accesses(op, arg)
            feats[a] = [1, sizes[a], 0, r, w, 0, 0, m]
        # innermost loops of <= LOOP bytes: a backward branch and its target
        for a, (op, arg) in mn.items():
            if not (BRANCH.match(op)):
                continue
            t = re.match(r"^(?:d[0-7],)?([0-9a-f]+) <", arg)
            if not t:
                continue
            target = int(t.group(1), 16)
            if target <= a and a + sizes[a] - target <= LOOP:
                i = bisect.bisect_left(self.addrs, target)
                while i < len(self.addrs) and self.addrs[i] <= a:
                    f = feats[int(self.addrs[i])]
                    f[2], f[1] = f[1] + f[2], 0
                    i += 1
        self.feat = feats
        self.cls = {}
        for a in mn:
            self.cls[a] = self.classify(a, platform)

    def symbol(self, pc: int) -> str:
        i = bisect.bisect_right(self.sym_addr, pc) - 1
        return self.syms[i][1] if i >= 0 else "?"

    def classify(self, pc: int, platform: set[str]) -> str:
        name = self.symbol(pc)
        if name.endswith("_walk") or "_walk_" in name:
            return "walk"
        if P.GUEST.match(name) or P.TRAMPOLINE.match(name):
            return "generated"
        if name in platform:
            return "platform"
        return "runtime"


def model_cycles(feat, n, taken, coef) -> float:
    """feat: per-execution features (taken and loop_taken unused: they come
    from the taken count, charged as loop_taken inside a cached loop)."""
    return n * sum(coef[k] * feat[i] for i, k in enumerate(FEATURES) if "taken" not in k) + \
        coef["loop_taken" if feat[2] else "taken"] * taken


def load_model() -> dict:
    return json.loads(MODEL.read_text())["coef"]


# --- the run -------------------------------------------------------------------

def run(milestone: str, elf: Path, gen: Path, timeout: int) -> tuple[Counter, Counter, dict]:
    """Block counts {(addr, size): n}, taken counts {block: n} and taken transfers
    {(block, target): n} (in meta["into"]) over the window."""
    import host_run
    import uc as U
    host_run.ELF = elf
    script = host_run.milestone_script(milestone)
    trace = REPO / f"tmp/pc-runs/ref-{milestone}/trace"
    script["irqs"], script["releases"] = host_run.reference_inputs(trace)
    h = host_run.Host(host_run.image.M.REF, None)
    blocks, taken, into = Counter(), Counter(), Counter()
    state = {"open": False, "prev": None}
    first = h.syms[script["snapshots"][0][0]]

    @U.CODE_CB
    def opener(e, addr, size, user):
        if h.step >= 1:
            state["open"] = True

    @U.CODE_CB
    def block(e, addr, size, user):
        if state["open"]:
            prev = state["prev"]
            if prev is not None and prev[0] + prev[1] != addr:
                taken[prev] += 1
                into[(prev, addr)] += 1
            key = (addr, size)
            blocks[key] += 1
            state["prev"] = key

    h.e.hook_range(U.HOOK_CODE, opener, first, first)
    h.e.hook_range(8, block, 1, 0)          # UC_HOOK_BLOCK, everywhere
    t0 = time.time()
    h.run(script, timeout)
    meta = {"milestone": milestone, "stopped_at": h.stopped_at, "seconds": round(time.time() - t0),
            "irq_lost": h.irq_lost, "label": script["snapshots"][-1][0]}
    if h.stopped_at != meta["label"] or h.irq_lost:
        raise SystemExit(f"meter run failed: {meta}")
    meta["into"] = into
    return blocks, taken, meta


def expand(prog: Program, blocks: Counter, taken_blocks: Counter):
    """Per-PC executions and taken transfers from block counts."""
    n, taken = Counter(), Counter()
    for (addr, size), k in blocks.items():
        i = bisect.bisect_left(prog.addrs, addr)
        end = addr + size
        last = None
        while i < len(prog.addrs) and prog.addrs[i] < end:
            pc = int(prog.addrs[i])
            n[pc] += k
            last = pc
            i += 1
        if last is None:
            raise ValueError(f"block {addr:x}+{size} outside the disassembly")
    for (addr, size), k in taken_blocks.items():
        i = bisect.bisect_left(prog.addrs, addr + size) - 1
        taken[int(prog.addrs[i])] += k
    return n, taken


def targets(prog: Program, into: Counter) -> dict:
    """Taken transfers into generated code from outside a cached loop, per
    target as "LABEL+offset" (tools/align_targets.py, speed-plan R8)."""
    out = Counter()
    for ((addr, size), dst), k in into.items():
        i = bisect.bisect_left(prog.addrs, addr + size) - 1
        if prog.feat[int(prog.addrs[i])][2] or prog.cls.get(dst) not in ("generated", "walk"):
            continue
        lab = prog.symbol(dst)
        out[f"{lab}+{dst - prog.by_name[lab]}"] += k
    return dict(out)


def report(prog: Program, n: Counter, taken: Counter, coef: dict, gen: Path) -> dict:
    text, _ = L.static_counts(gen)
    classes = defaultdict(lambda: Counter())
    labels = defaultdict(lambda: Counter())
    ops = defaultdict(lambda: Counter())
    for pc, k in n.items():
        f = prog.feat[pc]
        c = classes[prog.cls[pc]]
        cyc = model_cycles(f, k, taken[pc], coef)
        c["cycles"] += cyc
        for i, name in enumerate(FEATURES):
            c[name] += (taken[pc] if (name == "loop_taken") == bool(f[2]) else 0) \
                if "taken" in name else f[i] * k
        if prog.cls[pc] in ("generated", "walk"):
            op = prog.mn[pc][0] + (" #8" if prog.mn[pc][1].startswith("#8,") else "")
            ops[op]["execs"] += k
            ops[op]["cycles"] += cyc
            ops[op]["bytes"] += (f[1] + f[2]) * k
            lab = prog.symbol(pc)
            labels[lab]["cycles"] += cyc
            labels[lab]["bytes"] += (f[1] + f[2]) * k
            labels[lab]["reads"] += f[3] * k
            labels[lab]["writes"] += f[4] * k
            labels[lab]["taken"] += taken[pc]
            if pc == prog.by_name.get(lab):
                labels[lab]["execs"] += k
    forms = defaultdict(lambda: Counter())
    for lab, c in labels.items():
        t = text.get(lab)
        form = L.form(t) if t else ("walk" if "walk" in lab else "?")
        forms[form]["cycles"] += c["cycles"]
        forms[form]["execs"] += c["execs"]
        forms[form]["bytes"] += c["bytes"]
    guest = sum(c["execs"] for lab, c in labels.items() if lab in text)
    return {"classes": {k: dict(v) for k, v in classes.items()},
            "labels": {k: dict(v) for k, v in labels.items()},
            "forms": {k: dict(v) for k, v in forms.items()},
            "ops": {k: dict(v) for k, v in ops.items()},
            "guest_instructions": guest}


def static_size(prog: Program) -> dict:
    out = Counter()
    for a, s in prog.size.items():
        out[prog.cls[a]] += s
    return dict(out)


def summary(res: dict) -> str:
    cl = res["classes"]
    tot = sum(c["cycles"] for c in cl.values())
    g = res["guest_instructions"]
    gen = cl.get("generated", {}).get("cycles", 0) + cl.get("walk", {}).get("cycles", 0)
    lines = [f"{res['meta']['milestone']}: model cycles {tot:,.0f}; generated+walk {gen:,.0f} "
             f"({gen / max(g, 1):.3f} per guest instruction, {g:,} guest instructions)"]
    for k in ("generated", "walk", "runtime", "platform"):
        c = cl.get(k, {})
        if c:
            lines.append(f"  {k:9} cycles {c['cycles']:>14,.0f}  insns {c['insns']:>12,}  bytes "
                         f"{c['bytes'] + c['loop_bytes']:>13,} (loop {c['loop_bytes']:,})  reads "
                         f"{c['reads']:>11,}  writes {c['writes']:>11,}  taken {c['taken']:>11,}")
    lines.append("  static bytes: " + ", ".join(f"{k} {v:,}" for k, v in sorted(res["static"].items())))
    return "\n".join(lines)


def compare(a: dict, b: dict, top: int = 25) -> str:
    def tot(r, keys=("generated", "walk", "runtime")):
        return sum(r["classes"].get(k, {}).get("cycles", 0) for k in keys)
    out = []
    ta, tb = tot(a), tot(b)
    out.append(f"model cycles (generated+walk+runtime) {ta:,.0f} -> {tb:,.0f}: "
               f"{tb - ta:+,.0f} ({100 * (tb - ta) / ta:+.4f}%)")
    for k in ("generated", "walk", "runtime"):
        ca, cb = a["classes"].get(k, {}), b["classes"].get(k, {})
        d = {f: cb.get(f, 0) - ca.get(f, 0) for f in ("cycles", "bytes", "loop_bytes", "reads",
                                                         "writes", "taken", "insns")}
        out.append(f"  {k:9} " + "  ".join(f"{f} {v:+,.0f}" for f, v in d.items()))
    sa, sb = a["static"], b["static"]
    out.append("  static bytes " + ", ".join(f"{k} {sb.get(k, 0) - sa.get(k, 0):+,}"
                                              for k in sorted(set(sa) | set(sb))))
    if a["guest_instructions"] != b["guest_instructions"]:
        out.append(f"  WARNING guest instructions {a['guest_instructions']:,} vs "
                   f"{b['guest_instructions']:,}: not the same guest work")
    fa, fb = a["forms"], b["forms"]
    deltas = sorted(((fb.get(f, {}).get("cycles", 0) - fa.get(f, {}).get("cycles", 0), f)
                     for f in set(fa) | set(fb)), key=lambda x: abs(x[0]), reverse=True)
    out.append(f"  x86 forms by |delta cycles| (top {top}):")
    for d, f in deltas[:top]:
        out.append(f"    {d:+14,.0f}  {f}")
    return "\n".join(out)


# --- the doubling plant -------------------------------------------------------

def plant_check(base_json: Path, objdump: str) -> int:
    """Every `ror.w #8,dN` tripled (flag-neutral: same result, N, Z, C; X
    untouched): the meter must see exactly 2 more instructions and 4 more
    bytes per executed `ror.w #8` and the model move by their cost."""
    import shutil
    base = json.loads(base_json.read_text())
    work = REPO / "tmp/meter-plant"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(REPO / "build/gen", work / "gen")
    for s in (work / "gen").glob("*.s"):
        text = s.read_text()
        s.write_text(re.sub(r"^(\tror\.w #8,d[0-7])$", r"\1\n\1\n\1", text, flags=re.M))
    host = REPO / "build/host"
    cross = CROSS
    subprocess.run([VASM, "-quiet", "-m68020", "-Felf", "-x",
                    "-nowarn=62", "-o", str(work / "program.o"), "program.s"],
                   cwd=work / "gen", check=True)
    order = ["host_s.o", "host.o", "rt_entry.o"]
    runtime_c = sorted(p.stem for p in (REPO / "src/runtime").glob("*.c"))
    objs = [host / o for o in order] + [host / f"{c}.o" for c in runtime_c] + [work / "program.o"]
    subprocess.run([cross + "ld", "-Ttext=0x10000", "-e", "_start", "-o", str(work / "swotl.elf")]
                   + [str(o) for o in objs], check=True)
    elf = work / "swotl.elf"
    prog = Program(elf, objdump, (host / "host.o", host / "host_s.o"))
    blocks, taken_blocks, meta = run(base["meta"]["milestone"], elf, work / "gen", 3600)
    meta.pop("into")
    n, taken = expand(prog, blocks, taken_blocks)
    coef = load_model()
    res = report(prog, n, taken, coef, work / "gen")
    rors = base["ops"].get("ror.w #8", {}).get("execs", 0)
    g = lambda r, f: sum(r["classes"].get(k, {}).get(f, 0) for k in ("generated", "walk"))
    ror = lambda r, f: r["ops"].get("ror.w #8", {}).get(f, 0)
    d_insns = g(res, "insns") - g(base, "insns")
    d_bytes, d_cyc = ror(res, "bytes") - ror(base, "bytes"), ror(res, "cycles") - ror(base, "cycles")
    rest = g(res, "cycles") - g(base, "cycles") - d_cyc
    lo, hi = 4 * rors * min(coef["bytes"], coef["loop_bytes"]), 4 * rors * max(coef["bytes"],
                                                                            coef["loop_bytes"])
    ok = ror(res, "execs") == 3 * rors and d_insns == 2 * rors and d_bytes == 4 * rors and \
        lo <= d_cyc <= hi
    print(f"plant: {rors:,} ror.w #8 executed; instructions {d_insns:+,} (want {2 * rors:+,}), "
          f"their bytes {d_bytes:+,} (want {4 * rors:+,}), their model cycles {d_cyc:+,.0f} "
          f"(want {lo:,.0f}..{hi:,.0f}); other instructions {rest:+,.0f} (branch sizes, "
          f"loops past {LOOP} bytes): {'ok' if ok else 'FAIL'}")
    shutil.rmtree(work)
    return 0 if ok else 1


# --- calibration -----------------------------------------------------------------

def capture_counts(prog: Program, capture: Path):
    """Per-PC cycles, executions and taken transfers of an FS-UAE capture."""
    prof = P.decode(capture)
    addrs = prog.addrs
    sizes = np.array([prog.size[int(a)] for a in addrs], dtype=np.int64)
    cyc, cnt, tak = (np.zeros(len(addrs)) for _ in range(3))
    for _, _, pcs, cost in prof["fields"]:
        idx = np.searchsorted(addrs, pcs)
        idx = np.clip(idx, 0, len(addrs) - 1)
        ok = addrs[idx] == pcs
        np.add.at(cyc, idx[ok], cost[ok])
        np.add.at(cnt, idx[ok], 1)
        fall = pcs[:-1] + sizes[idx[:-1]]
        t = ok[:-1] & ok[1:] & (pcs[1:] != fall)
        np.add.at(tak, idx[:-1][t], 1)
    return cyc, cnt, tak, len(prof["fields"])


def fit(X: np.ndarray, y: np.ndarray, names: list[str]) -> dict:
    """Least squares with non-negative weights (drop a negative weight, refit)."""
    keep = list(range(X.shape[1]))
    while True:
        w, *_ = np.linalg.lstsq(X[:, keep], y, rcond=None)
        if (w >= 0).all():
            break
        keep.pop(int(np.argmin(w)))
    coef = {n: 0.0 for n in names}
    for k, v in zip(keep, w):
        coef[names[k]] = float(v)
    return coef


def calibrate(capture: Path, elf: Path, objdump: str, write: bool) -> None:
    prog = Program(elf, objdump)
    cyc, cnt, tak, fields = capture_counts(prog, capture)
    rows, y = [], []
    for i, a in enumerate(prog.addrs.tolist()):
        if cnt[i] and prog.cls[a] in ("generated", "walk"):
            f = prog.feat[a]
            rows.append([cnt[i] * f[0], cnt[i] * f[1], cnt[i] * f[2], cnt[i] * f[3],
                         cnt[i] * f[4], 0 if f[2] else tak[i], tak[i] if f[2] else 0,
                         cnt[i] * f[7]])
            y.append(cyc[i])
    X, y = np.array(rows), np.array(y)
    coef = fit(X, y, list(FEATURES))
    w = np.array([coef[k] for k in FEATURES])
    pred = X @ w
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    total, model = y.sum(), pred.sum()
    print(f"capture {capture.name}: {fields} fields, {len(y):,} generated PCs, "
          f"{int(cnt.sum()):,} executions")
    print("weights: " + ", ".join(f"{k} {v:.3f}" for k, v in coef.items()))
    print(f"R^2 {r2:.3f}; generated code measured {total:,.0f}, model {model:,.0f} "
          f"({100 * (model - total) / total:+.2f}%)")
    for cls in ("runtime",):
        m = sum(model_cycles(prog.feat[a], cnt[i], tak[i], coef)
                for i, a in enumerate(prog.addrs.tolist()) if cnt[i] and prog.cls[a] == cls)
        t = sum(cyc[i] for i, a in enumerate(prog.addrs.tolist()) if cnt[i] and prog.cls[a] == cls)
        print(f"{cls} (not fitted): measured {t:,.0f}, model {m:,.0f}")
    if write:
        MODEL.write_text(json.dumps({"coef": coef, "r2": round(float(r2), 4),
                                     "capture": {"fields": fields, "pcs": len(y),
                                                 "measured": int(total), "model": int(model)}},
                                    indent=1) + "\n")
        print(f"wrote {MODEL.relative_to(REPO)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("milestone", nargs="?", default="m4-demo-frames")
    ap.add_argument("--elf", type=Path, default=REPO / "build/host/swotl.elf")
    ap.add_argument("--gen", type=Path, default=REPO / "build/gen")
    ap.add_argument("--out", type=Path, help="write the full result as JSON")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--objdump", default=OBJDUMP)
    ap.add_argument("--calibrate", nargs=2, type=Path, metavar=("CAPTURE", "ELF"))
    ap.add_argument("--write", action="store_true", help="with --calibrate: write cost_model.json")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    ap.add_argument("--plant-check", type=Path, metavar="BASE_JSON",
                    help="meter a copy of build/gen with every ror.w #8 tripled against BASE_JSON")
    args = ap.parse_args(argv)
    if args.compare:
        a, b = (json.loads(p.read_text()) for p in args.compare)
        print(compare(a, b))
        return 0
    if args.plant_check:
        return plant_check(args.plant_check, args.objdump)
    if args.calibrate:
        calibrate(*args.calibrate, args.objdump, args.write)
        return 0
    host = args.elf.parent
    prog = Program(args.elf, args.objdump, (host / "host.o", host / "host_s.o"))
    blocks, taken_blocks, meta = run(args.milestone, args.elf.resolve(), args.gen, args.timeout)
    n, taken = expand(prog, blocks, taken_blocks)
    res = report(prog, n, taken, load_model(), args.gen)
    res["targets"] = targets(prog, meta.pop("into"))
    res["meta"] = meta
    res["static"] = static_size(prog)
    print(summary(res))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
