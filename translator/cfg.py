"""Recursive descent over the in-scope modules with the translator's own decoder.

Seeds (all from annotations/ and the images, no traces): MZ entry, PLINK
thunks, `entries.csv`, `runtime.csv`, the switch and traced targets of
`indirect.csv`. Follows fall-through and direct near/far transfers; a manager
call (`call far 1617:034C; dw id`) skips its inline id and names the overlay
of the following `jmp far`. A far target in several overlays' link ranges
resolves to the caller's PLINK parent chain. Code segments (CS link paragraphs) come from far
transfers: a far transfer sets it, fall-through and near transfers keep it
(an MS C frame paragraph can start up to 15 bytes before its segment, inside
the previous function). Entries seeded without a CS take the highest
far-referenced frame at or below them, iterated to a fixpoint. Self-modified
regions are not decoded statically: flow into one is recorded as an entry of
the region (D16). Overlaps, flow into a fixup list, undecodable bytes and
ambiguous far targets raise CfgError (all of them, after the fixpoint).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import image
from .decode import DecodeError, Far, Insn, Rel, decode

M = image.M


class CfgError(Exception):
    pass


@dataclass
class Unit:
    name: str
    module: M.Module
    bases: list[int]
    insns: dict[int, Insn] = field(default_factory=dict)
    cs: dict[int, int] = field(default_factory=dict)          # offset -> CS link paragraph
    manager_calls: dict[int, str] = field(default_factory=dict)  # offset -> overlay named
    smc_entries: dict[int, str] = field(default_factory=dict)  # region entry -> reason
    seeds: dict[int, str] = field(default_factory=dict)

    def segment(self, off: int) -> int:
        """CS of an entry seeded without one: the highest far-referenced frame at or below."""
        para = self.module.to_link(off) >> 4
        return max(b for b in self.bases if b <= para)

    def ip_of(self, off: int) -> int:
        seg = self.cs[off] if off in self.cs else self.segment(off)
        return self.module.to_link(off) - seg * 16

    def off_of(self, seg: int, ip: int) -> int:
        return self.module.from_link(seg * 16 + ip)


def seeds(mods: dict[str, M.Module]) -> list[tuple[str, int, str]]:
    out = [(M.ROOT, M.entry(), "MZ entry")]
    out += [(M.ROOT, at, "PLINK thunk") for at, _, _ in M.thunks(mods)]
    for r in image.rows("entries.csv"):
        out.append((r["module"], int(r["offset"], 16), r["reason"]))
    for r in image.rows("runtime.csv"):
        out.append((r["module"], int(r["offset"], 16), f"runtime {r['name']}"))
    for r in image.rows("indirect.csv"):
        site = f"{r['module']}+{r['offset']}"
        for col in ("switch_targets", "traced_targets"):
            for t in r[col].split():
                if t == "(isr)":
                    continue
                mod, off = t.split("+")
                out.append((mod, int(off, 16), f"{col[:-8]} {site}"))
    return [s for s in out if s[0] in image.SCOPE]


class _Descent:
    def __init__(self, mods, bases):
        self.mods = mods
        self.units = {n: Unit(n, mods[n], sorted(bases[n])) for n in image.SCOPE}
        self.by_index = {m.index: m.name for m in mods.values() if m.index >= 0}
        self.smc = image.smc_regions()
        self.far_segs = {n: set() for n in image.SCOPE}
        self.work: list[tuple[str, int, str]] = []
        self.body: dict[str, dict[int, int]] = {n: {} for n in image.SCOPE}  # byte -> start
        self.errors: list[str] = []

    def seed(self, mod, off, why, cs=None):
        if mod in self.units:
            self.work.append((mod, off, why, cs))
            self.units[mod].seeds.setdefault(off, why)

    def ancestors(self, mod):
        out, m = [], self.mods[mod]
        while m.flags & 0x1FFF:
            m = self.mods[self.by_index[(m.flags & 0x1FFF) - 1]]
            out.append(m.name)
        return out

    def in_smc(self, mod, off):
        return any(lo <= off <= hi for lo, hi in self.smc.get(mod, ()))

    def far(self, mod, at, f: Far, ovl):
        linear = f.seg * 16 + f.off
        if ovl:
            t = self.mods[ovl]
            if not t.link_lo <= linear < t.link_hi:
                raise CfgError(f"{mod}+{at:05X}: thunk target outside {ovl}")
            if ovl in self.units:
                self.far_segs[ovl].add(f.seg)
                self.seed(ovl, t.from_link(linear), f"thunk {mod}+{at:05X}", f.seg)
            return
        own = self.mods[mod]
        if own.link_lo <= linear < own.link_hi:
            owners = [mod]
        else:
            owners = [n for n in M.link_owners(self.mods, linear) if n in self.units]
            # PLINK keeps a child's parent chain resident (plink.md): resolve to it.
            chain = [n for n in self.ancestors(mod) if n in owners]
            if len(owners) > 1 and chain:
                owners = chain[:1]
        if len(owners) > 1:
            raise CfgError(f"{mod}+{at:05X}: far target {f} ambiguous: {owners}")
        if owners:
            self.far_segs[owners[0]].add(f.seg)
            self.seed(owners[0], self.mods[owners[0]].from_link(linear), f"far {mod}+{at:05X}",
                      f.seg)

    def run(self):
        while self.work:
            try:
                self.flow(*self.work.pop())
            except CfgError as e:
                self.errors.append(str(e))

    def flow(self, mod, off, why, cs):
        u = self.units[mod]
        data = u.module.data
        ovl = None
        while True:
            if not u.module.code_start <= off < len(data):
                raise CfgError(f"{mod}+{off:05X}: flow outside code ({why})")
            if off in u.insns:
                if cs is not None and u.cs[off] != cs:
                    raise CfgError(f"{mod}+{off:05X}: reached with CS {cs:04X} and {u.cs[off]:04X} ({why})")
                return
            if self.in_smc(mod, off):
                u.smc_entries.setdefault(off, why)
                return
            if off in self.body[mod]:
                raise CfgError(f"{mod}+{off:05X}: start inside {mod}+{self.body[mod][off]:05X} ({why})")
            seg = cs = u.segment(off) if cs is None else cs
            ip = u.module.to_link(off) - seg * 16
            if not 0 <= ip < 0x10000:
                raise CfgError(f"{mod}+{off:05X}: outside CS {seg:04X} ({why})")
            try:
                n = decode(data, ip, off)
            except DecodeError as e:
                raise CfgError(f"{mod}+{off:05X}: {e} ({why})") from None
            for k in range(off + 1, off + n.size):
                if k in u.insns or k in self.body[mod]:
                    raise CfgError(f"{mod}+{off:05X}: overlaps {mod}+{k:05X} ({why})")
                self.body[mod][k] = off
            u.insns[off], u.cs[off] = n, seg
            nxt = off + n.size
            why = f"{mod}+{off:05X}"
            if n.op in ("ret", "retf", "iret", "hlt"):
                return
            if n.op in ("callf", "jmpf") and isinstance(n.operands[0], Far):
                f = n.operands[0]
                if n.op == "callf" and (f.seg, f.off) == M.MANAGER:
                    oid, = struct.unpack_from("<H", data, nxt)
                    ovl = self.by_index[oid - 1]
                    u.manager_calls[off] = ovl
                    self.seed(M.ROOT, self.mods[M.ROOT].from_link(f.seg * 16 + f.off),
                              f"PLINK manager {mod}+{off:05X}", f.seg)
                    for k in (nxt, nxt + 1):
                        self.body[mod][k] = off
                    off = nxt + 2
                    continue
                self.far(mod, off, f, ovl if n.op == "jmpf" else None)
                if n.op == "jmpf":
                    return
            elif n.operands and isinstance(n.operands[0], Rel):
                self.seed(mod, u.off_of(seg, n.operands[0].target), why, seg)
                if n.op == "jmp":
                    return
            elif n.op in ("jmp", "jmpf"):
                return
            off = nxt


def build(mods: dict[str, M.Module] | None = None) -> dict[str, Unit]:
    mods = mods or image.load()
    bases = {n: {0 if n == M.ROOT else mods[n].link_seg} for n in image.SCOPE}
    bases[M.ROOT].add(M.mz(M.REF / M.ROOT)[2][0])  # MZ entry CS (the PLINK manager segment)
    start = seeds(mods)
    while True:
        d = _Descent(mods, bases)
        for s in start:
            d.seed(*s)
        d.run()
        grown = {n: bases[n] | d.far_segs[n] for n in bases}
        if grown == bases:
            if d.errors:  # only the fixpoint pass knows every code segment
                raise CfgError("\n".join(sorted(set(d.errors))))
            return d.units
        bases = grown
