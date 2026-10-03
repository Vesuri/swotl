#!/usr/bin/env python3
"""Recursive-descent sweep of the root and in-scope overlays (plan step 2.4).

Seeds: MZ entry, PLINK thunk targets, every traced instruction start
(union of tmp/pc-runs/ref-*), traced indirect targets. Follows fall-through,
near/far direct jumps and calls; stops at returns and indirect jumps; never
sweeps linearly. Far targets resolve through the link layout: own module,
root, else the single in-scope overlay owning the link address (ambiguous
targets are listed, not followed).

Outputs in tmp/sweep/: <module>.cls (byte per module offset: 0 unknown,
1 instruction start, 2 instruction body, 3 executed start, 4 executed body),
coverage.csv, conflicts.csv, far-refs.csv, indirect.csv (every static
indirect jump/call site: executed, MS C switch-table targets, traced targets;
"(isr)" marks a target that is also a hardware interrupt entry, which an
interrupt arriving after the site would produce as well). With --annotations, the
indirect sites are also written to annotations/indirect.csv.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import defaultdict
from pathlib import Path

import capstone
from capstone import x86

import swotl_model as M

OUT = M.REPO / "tmp/sweep"
UNKNOWN, START, BODY, TABLE = 0, 1, 2, 5


def smc_regions() -> dict[str, list[tuple[int, int]]]:
    """annotations/self-modifying.csv: module ranges whose code is rewritten at run time."""
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with (M.REPO / "annotations/self-modifying.csv").open() as f:
        for r in csv.DictReader(f):
            out[r["module"]].append((int(r["first"], 16), int(r["last"], 16)))
    return out


class Sweep:
    def __init__(self, mods: dict[str, M.Module], scope: list[str], bases: dict[str, list[int]]):
        self.mods, self.scope, self.bases = mods, scope, bases
        self.segs = {n: set() for n in mods}  # far-referenced code segments per module
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
        self.md.detail = True
        self.cls = {n: bytearray(len(mods[n].data)) for n in scope}
        self.insn: dict[str, dict[int, object]] = {n: {} for n in scope}
        self.work: list[tuple[str, int, str]] = []
        self.conflicts: list[tuple[str, int, str]] = []
        self.far_refs: list[tuple[str, int, int, int, str]] = []
        self.indirect: dict[tuple[str, int], str] = {}
        self.by_index = {m.index: m.name for m in mods.values() if m.index >= 0}
        self.tables: dict[tuple[str, int], list[int]] = {}  # switch site -> targets
        self.switch_sites: list[tuple[str, int, int, object]] = []
        self.far_ptrs: list[tuple[str, int, str, int]] = []  # (module, at, target module, offset)
        self.smc = smc_regions()
        self.smc_conflicts = 0

    def in_smc(self, mod: str, off: int) -> bool:
        return any(lo <= off <= hi for lo, hi in self.smc.get(mod, ()))

    def conflict(self, mod: str, off: int, why: str) -> None:
        """Static bytes of self-modified code differ from what runs: not a conflict."""
        if self.in_smc(mod, off):
            self.smc_conflicts += 1
        else:
            self.conflicts.append((mod, off, why))

    def seed(self, mod: str, off: int, why: str) -> None:
        if mod in self.cls:
            self.work.append((mod, off, why))

    def segment(self, mod: str, off: int) -> int:
        """Code segment (link paragraph) of a module offset: highest known base below."""
        para = self.mods[mod].to_link(off) >> 4
        return max(b for b in self.bases[mod] if b <= para)

    def decode(self, mod: str, off: int, seg: int):
        ip = self.mods[mod].to_link(off) - seg * 16
        return next(self.md.disasm(self.mods[mod].data[off:off + 16], ip), None) if ip < 0x10000 else None

    def far_target(self, mod: str, at: int, seg: int, off: int, ovl: str | None = None) -> None:
        linear = seg * 16 + off
        own = self.mods[mod]
        if ovl:  # jump after a manager call: the target is in the named overlay
            target = self.mods[ovl]
            if not target.link_lo <= linear < target.link_hi:
                self.conflicts.append((mod, at, f"thunk target outside {ovl}"))
            elif ovl in self.scope:
                self.segs[ovl].add(seg)
                self.seed(ovl, target.from_link(linear), f"thunk {mod}+{at:X}")
            self.far_refs.append((mod, at, seg, off, f"{ovl} (thunk)"))
            return
        if own.link_lo <= linear < own.link_hi:
            self.segs[mod].add(seg)
            self.seed(mod, own.from_link(linear), f"far from {mod}+{at:X}")
            return
        owners = [n for n in M.link_owners(self.mods, linear) if n in self.scope]
        if len(owners) == 1:
            self.segs[owners[0]].add(seg)
            self.seed(owners[0], self.mods[owners[0]].from_link(linear), f"far from {mod}+{at:X}")
        self.far_refs.append((mod, at, seg, off, " ".join(owners) or "-"))

    def switch(self, mod: str, off: int, seg: int, i) -> None:
        """MS C switch: cmp ax,N; ja/jbe; add ax,ax; xchg bx,ax; jmp cs:[bx+T]."""
        ops = i.operands
        if i.mnemonic != "jmp" or not ops or ops[0].type != x86.X86_OP_MEM:
            return
        mem = ops[0].mem
        if i.reg_name(mem.segment) != "cs" or i.reg_name(mem.base) != "bx" or mem.index:
            return
        # The bounds check precedes the dispatch in the byte stream, not always on this path.
        before = [self.insn[mod][k] for k in range(off - 1, max(off - 24, 0), -1) if k in self.insn[mod]]
        cmp = next((r for r in before if r.mnemonic == "cmp"
                    and len(r.operands) == 2 and r.operands[1].type == x86.X86_OP_IMM), None)
        if cmp is None:
            return
        m, cls = self.mods[mod], self.cls[mod]
        table = m.from_link(seg * 16 + (mem.disp & 0xFFFF))
        n = (cmp.operands[1].imm & 0xFFFF) + 1
        if not 0 < n <= 512 or table < m.code_start or table + 2 * n > len(m.data):
            self.conflicts.append((mod, off, "switch table out of range"))
            return
        targets = []
        for k in range(n):
            ip, = struct.unpack_from("<H", m.data, table + 2 * k)
            targets.append(m.from_link(seg * 16 + ip))
            for b in (table + 2 * k, table + 2 * k + 1):
                if cls[b] in (START, BODY):
                    self.conflicts.append((mod, b, f"switch table over code ({mod}+{off:X})"))
                cls[b] = TABLE
        self.tables[(mod, off)] = targets
        for t in targets:
            self.seed(mod, t, f"switch {mod}+{off:X}")

    def far_pointers(self, sources: list[str]) -> None:
        """Far pointers outside instructions: fixup segment words not inside decoded code."""
        for n in sources:
            m, cls = self.mods[n], self.cls[n]
            for fx in m.fixups:
                if fx < m.code_start + 2 or cls[fx]:
                    continue
                off, seg = struct.unpack_from("<HH", m.data, fx - 2)
                linear = seg * 16 + off
                owners = [o for o in M.link_owners(self.mods, linear)
                          if o in self.scope and o != "DATA.OVL"]
                if n in owners:
                    owners = [n]
                if len(owners) == 1:
                    self.far_ptrs.append((n, fx - 2, owners[0], self.mods[owners[0]].from_link(linear)))

    def run(self) -> None:
        """Drain the worklist; switch dispatches resolve once their bounds check is decoded."""
        while self.work or self.switch_sites:
            while self.work:
                mod, off, why = self.work.pop()
                self.flow(mod, off, why)
            pending, self.switch_sites = self.switch_sites, []
            for mod, off, seg, i in pending:
                if (mod, off) not in self.tables:
                    self.switch(mod, off, seg, i)

    def flow(self, mod: str, off: int, why: str) -> None:
        cls, data = self.cls[mod], self.mods[mod].data
        ovl = None  # overlay named by the last manager call on this path
        seg = self.segment(mod, off) if off < len(data) else 0
        while 0 <= off < len(data):
            if cls[off] == START:
                return
            if off < self.mods[mod].code_start:
                self.conflict(mod, off, f"flow into fixup list ({why})")
                return
            if cls[off] == BODY:
                self.conflict(mod, off, f"start inside instruction ({why})")
                return
            i = self.decode(mod, off, seg)
            if i is None:
                self.conflict(mod, off, f"undecodable ({why})")
                return
            span = range(off, min(off + i.size, len(data)))
            if any(cls[k] for k in span):
                self.conflict(mod, off, f"overlaps instruction ({why})")
                return
            cls[off] = START
            for k in span[1:]:
                cls[k] = BODY
            self.insn[mod][off] = i
            nxt = off + i.size
            g = set(i.groups)
            ops = i.operands
            if capstone.CS_GRP_RET in g or capstone.CS_GRP_IRET in g or i.mnemonic == "hlt":
                return
            if i.mnemonic in ("ljmp", "lcall") and len(ops) == 2 and ops[0].type == x86.X86_OP_IMM:
                fseg, target = ops[0].imm & 0xFFFF, ops[1].imm & 0xFFFF
                if i.mnemonic == "lcall" and (fseg, target) == M.MANAGER:
                    oid, = struct.unpack_from("<H", data, nxt)
                    ovl = self.by_index[oid - 1]
                    for k in (nxt, nxt + 1):
                        cls[k] = BODY  # inline overlay id, consumed by the manager
                    off = nxt + 2
                    continue
                self.far_target(mod, off, fseg, target, ovl if i.mnemonic == "ljmp" else None)
                if i.mnemonic == "ljmp":
                    return
            elif capstone.CS_GRP_JUMP in g or capstone.CS_GRP_CALL in g:
                if ops and ops[0].type == x86.X86_OP_IMM:
                    target = self.mods[mod].from_link(seg * 16 + (ops[0].imm & 0xFFFF))
                    self.seed(mod, target, f"{mod}+{off:X}")
                else:
                    self.indirect[(mod, off)] = f"{i.mnemonic} {i.op_str}"
                    self.switch_sites.append((mod, off, seg, i))
                if i.mnemonic in ("jmp", "ljmp"):
                    return
            off = nxt


def residue(m: M.Module, cls: bytearray) -> list[int]:
    """Unreached bytes by run: zero fill (>= 90 % zero), text, code-like (MS C prologue `55 8B EC` or a
    fixup-anchored far call `9A`), other data."""
    fix = set(m.fixups)
    out = [0, 0, 0, 0]
    off = m.code_start
    while off < len(cls):
        if cls[off]:
            off += 1
            continue
        end = off
        while end < len(cls) and not cls[end]:
            end += 1
        run = m.data[off:end]
        zeros = run.count(0)
        text = sum(1 for b in run if 32 <= b < 127 or b in (10, 13))
        if zeros >= 0.9 * len(run):
            out[0] += len(run)
        elif text + zeros >= 0.9 * len(run) and text >= 0.5 * len(run) and len(run) >= 4:
            out[1] += len(run)
        elif b"\x55\x8b\xec" in run or any(m.data[k] == 0x9A and k + 3 in fix for k in range(off, end)):
            out[2] += len(run)
        else:
            out[3] += len(run)
        off = end
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="ref-*", help="tmp/pc-runs glob for the trace corpus")
    ap.add_argument("--far-pointers", default="",
                    help="modules whose far pointers (fixups outside code) seed the sweep; '' = none")
    ap.add_argument("--annotations", action="store_true", help="write annotations/indirect.csv")
    args = ap.parse_args()
    mods = M.load_modules()
    scope = M.SCOPE
    traces = M.runs(args.runs)
    exe = M.executed(traces)
    hw = {(r["target_module"], int(r["target_offset"], 16))
          for r in M.csv_rows(traces, "interrupts.csv") if r["type"] == "0"}
    edge_set = M.edges(traces)
    bases = {n: {0 if n == M.ROOT else m.link_seg} for n, m in mods.items()}
    bases[M.ROOT].add(M.entry() >> 4)
    while True:  # segment bases come from decoded far references; iterate to a fixpoint
        sw = Sweep(mods, scope, {n: sorted(b) for n, b in bases.items()})
        sw.seed(M.ROOT, M.entry(), "MZ entry")
        for at, mod, off in M.thunks(mods):
            sw.seed(M.ROOT, at, "thunk")
        for mod, starts in exe.items():
            for off in starts:
                sw.seed(mod, off, "traced")
        sw.run()
        # Traced targets of indirect sites; hardware interrupt entries are not targets.
        targets = defaultdict(set)
        for fm, fo, tm, to in edge_set:
            if (fm, fo) in sw.indirect:
                targets[(fm, fo)].add((tm, to))
        for (fm, fo), ts in targets.items():
            for tm, to in ts:
                if (tm, to) not in hw:
                    sw.seed(tm, to, f"indirect {fm}+{fo:X}")
        sw.run()
        if args.far_pointers:
            sw.far_pointers(args.far_pointers.split(","))
            for n, at, tm, to in sw.far_ptrs:
                sw.seed(tm, to, f"far pointer {n}+{at:X}")
            sw.run()
        grown = {n: bases[n] | sw.segs[n] for n in bases}
        if grown == bases:
            break
        bases = grown

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "coverage.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["module", "code_bytes", "static_code", "executed_code", "unexecuted_code",
                    "switch_tables", "residue", "residue_zero", "residue_text", "residue_codelike",
                    "residue_other", "executed_not_code", "smc_region", "indirect_sites",
                    "indirect_traced"])
        for n in scope:
            cls, m = sw.cls[n], mods[n]
            starts = exe.get(n, set())
            ex = bytearray(len(cls))
            missing = 0
            for s in starts:
                if s >= len(cls) or cls[s] != START:
                    missing += 0 if sw.in_smc(n, s) else 1
                    continue
                for k in range(s, s + sw.insn[n][s].size):
                    ex[k] = 1
            code = sum(1 for c in cls if c in (START, BODY))
            tables = sum(1 for c in cls if c == TABLE)
            res = residue(m, cls)
            body = len(cls) - m.code_start
            exn = sum(ex)
            out = bytearray(c + (2 if ex[k] else 0) if c else 0 for k, c in enumerate(cls))
            (OUT / f"{n}.cls").write_bytes(bytes(out))
            sites = [s for s in sw.indirect if s[0] == n]
            smc = sum(hi - lo + 1 for lo, hi in sw.smc.get(n, ()))
            w.writerow([n, body, code, exn, code - exn, tables, body - code - tables, *res,
                        missing, smc, len(sites),
                        sum(1 for s in sites if targets.get(s))])
    with (OUT / "conflicts.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["module", "offset", "reason"])
        for mod, off, why in sorted(set(sw.conflicts)):
            w.writerow([mod, f"0x{off:05x}", why])
    with (OUT / "far-pointers.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["module", "offset", "target_module", "target_offset", "target_class"])
        for n, at, tm, to in sorted(set(sw.far_ptrs)):
            w.writerow([n, f"0x{at:05x}", tm, f"0x{to:05x}", sw.cls[tm][to]])
    with (OUT / "far-refs.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["module", "offset", "segment", "target", "owners"])
        for mod, at, seg, off, owners in sorted(set(sw.far_refs)):
            w.writerow([mod, f"0x{at:05x}", f"0x{seg:04x}", f"0x{off:04x}", owners])
    rows = []
    for (mod, off), text in sorted(sw.indirect.items()):
        ts = sorted(targets.get((mod, off), ()))
        table = sw.tables.get((mod, off), [])
        rows.append([mod, f"0x{off:05x}", text, int(off in exe.get(mod, ())),
                     " ".join(f"{mod}+0x{t:05x}" for t in sorted(set(table))),
                     " ".join(f"{tm}+0x{to:05x}" + (" (isr)" if (tm, to) in hw else "")
                              for tm, to in ts)])
    for path in [OUT / "indirect.csv"] + ([M.REPO / "annotations/indirect.csv"] if args.annotations else []):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["module", "offset", "instruction", "executed", "switch_targets",
                        "traced_targets"])
            w.writerows(rows)
    with (OUT / "coverage.csv").open() as f:
        print(f.read(), end="")
    print(f"conflicts {len(set(sw.conflicts))} (+{sw.smc_conflicts} in self-modified regions), "
          f"far refs {len(set(sw.far_refs))}, "
          f"traces {len(traces)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
