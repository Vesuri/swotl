"""IRQ0 handler footprint proof (docs/irq-plan.md I2): gen time, generated code unchanged.

Handler: from the guest handler of IVT 08h (annotations/entries.csv, "INT 08h
handler") over its CFG with callees inlined (a context is the call stack), an
abstract interpretation of the lifted IR (translator/sem.py). Values: constants,
unsigned ranges, the interrupted registers (whole or halves), entry SP plus a
displacement, segment classes, words loaded through a displacement (typed by it).
States per context and instruction are partitioned by the index and segment
registers (SIGNATURES), joined within a partition and widened after WIDEN changes.
Segment classes: the SPAZ link paragraphs its relocated constants name (`188A`
data, `1770` code), `G` (the word at 188A:0162, which SPAZ init stores), `S` (song
segments, words of G's song table), `BDA` (the BIOS tick the BIOS chain runs,
rt_bios_int08), `K` (the interrupted stack). Indexed offsets are ranges; loads of annotations/irq-bounds.csv variables
take its bounds, and accesses of a class with an extent row (`*`) are clamped to it
(I3's monitor checks every handler access against the footprint).
Proved, else Violation: no interrupted register, flag or stack word is read but
to save it (a push or its copy), every exit (IRET, or the chain to the BIOS
handler with the frame in place) has every register, SP and the frame as on entry,
no DF read, every port in PORTS, no software interrupt, recursion or indirect
transfer but the BIOS chain. A possible divide fault is listed (runtime row).

Main code: a forward analysis over emit.Program's graph from the MZ entry with the
DOS state; the IRQ0 handler entry is not main code. States are kept per context
(function entry, entry DS, entry SS): a call enters its targets' contexts, a return
site joins the caller's stack and BP with the callee context's state at its returns
(DS and the rest), so a function entered with several DS values is classified once
per value. State: segment registers, the general registers as constants (byte
halves too), the stack since the function entry (push/pop, `mov bp,sp`/`mov sp,bp`,
SP adjustments), IF and the STI shadow, and code-segment words stored on the path
(`mov cs:[x],ds` ... `mov ds,cs:[x]`; killed by stores that may overlap them, an
indexed writer by its self-modifying.csv region, else all). Unresolved transfers
reach their traced targets (indirect.csv); an untraced call keeps DS (MS C; I3's
monitor checks); INT 21h AH=4Ch ends a path. annotations/irq-ds.csv declares
entries that return the caller's DS where the analysis cannot see it. Constant-
address word stores give memory slots (resolved by iteration; G is the slot
188A:0162 and must resolve). Each access of a reached instruction is masked (IF = 0
or STI shadow in every context: no delivery before it), disjoint (known address
outside the footprint), sync (may meet it: a read of a handler-written byte, a
write of a handler-accessed byte, a handler port; an indexed access whose
displacement lies in a footprint interval of its segment) or monitored (segment or
offset unknown, or not reached; host runs check them, I3; annotations/irq-sync.csv
declares the ones they found meeting it: sync for the declared span); the worst
context counts. Song segments (S) are only located at run time (I3). A sync access to a
handler-written byte must lower to one 68k instruction that touches memory, no
compute row may contain a sync access, and every main write of a bounded G
variable must keep its irq-bounds.csv bound, else Violation.
Output build/gen/irq-footprint.csv: kind (mem, port, if, hook, runtime, exit, extent,
stack, sync), class, first, last, access, where.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import image
from .decode import Far, Imm, Mem, Reg
from .ir import FLAG_KINDS, T, mask
from .lower import CC_READS, LOADSEG
from .sem import lift

M = image.M
PORTS = {0x388: "OPL index (rt_out8)", 0x389: "OPL data (rt_out8)", 0x20: "PIC EOI"}
BIOS_TICK = ("BDA", 0x6C, 0x70)      # rt_bios_int08: tick dword, midnight byte (0040:006C)
BIOS_ENTRY = 0xFFEA5                 # indirect.csv target of the chain (F000:FEA5)
GAME_DS_SLOT = (0x188A, 0x162)       # SPAZ init +026E stores the caller's DS here
SIGNATURES = 64                      # signatures per context and instruction before joining
WIDEN = 6                            # joins that change a joined state before widening
REGS = ("ax", "bx", "cx", "dx", "si", "di", "bp", "sp", "cs", "ds", "es", "ss", "flagsx")
HALF = {"al": ("ax", 0), "ah": ("ax", 1), "bl": ("bx", 0), "bh": ("bx", 1),
        "cl": ("cx", 0), "ch": ("cx", 1), "dl": ("dx", 0), "dh": ("dx", 1)}
FLAGS = ("CF", "PF", "AF", "ZF", "SF", "TF", "IF", "DF", "OF")
X = ("x",)
TAINT = ("e", "h", "p", "x")


class Violation(Exception):
    pass


def bounds() -> dict[tuple[str, int, int], tuple[int, int]]:
    """(class, variable, width) -> (lo, hi): a load through the variable's displacement."""
    return {(r["class"], int(r["variable"], 16), int(r["width"])): (int(r["lo"], 16), int(r["hi"], 16))
            for r in image.rows("irq-bounds.csv") if r["variable"] != "*"}


def extents() -> dict[str, tuple[int, int]]:
    """class -> (lo, hi): the offsets every handler access of the class lies in (variable
    `*`); a wider access range is clamped and listed (extent rows; I3 checks)."""
    return {r["class"]: (int(r["lo"], 16), int(r["hi"], 16))
            for r in image.rows("irq-bounds.csv") if r["variable"] == "*"}


def declared_sync() -> dict[tuple[str, int], list[tuple[str, int, int, str]]]:
    """(module, offset) -> [(class, first, last, access)]: monitored accesses that the
    host runs found meeting the footprint (irq-sync.csv, I3); sync for that span."""
    out = defaultdict(list)
    for r in image.rows("irq-sync.csv"):
        out[(r["module"], int(r["offset"], 16))].append(
            (r["class"], int(r["first"], 16), int(r["last"], 16), r["access"]))
    return dict(out)


# Segment words: (class, displacement) -> class of the segment they hold. A word
# variable is the displacement of the operand that addresses it (indexed: the
# array). Every handler store through one stores a word of the same class.
SEGMENT_WORDS = {
    (f"{GAME_DS_SLOT[0]:04X}", GAME_DS_SLOT[1]): "G",   # SPAZ init +026E
    ("G", 0x613E): "S",         # song table far pointers (FLIGHT +0389B, +038D7)
    ("188A", 0x19C): "S",       # voice segments, copied from the song table (+0B18, +0B99)
}


# -- abstract values -----------------------------------------------------------
def rng(v, w):
    """(lo, hi) of a handler-defined value, else None."""
    k = v[0]
    if k == "c":
        return v[1] & mask(w), v[1] & mask(w)
    if k == "r":
        return (v[1], v[2]) if v[2] <= mask(w) else (0, mask(w))
    if k in ("l", "s"):
        return 0, mask(w)
    return None


def mk(lo, hi, w):
    if lo < 0 or hi > mask(w):
        return ("r", 0, mask(w))
    return ("c", lo) if lo == hi else ("r", lo, hi)


def split(v, k):
    t = v[0]
    if t == "c":
        return ("c", v[1] >> 8 * k & 0xFF)
    if t == "r":
        return mk(v[1] >> 8 * k if k else v[1], v[2] >> 8 * k if k else v[2], 8) if k or v[2] < 256 \
            else ("r", 0, 0xFF)
    if t == "e":
        return ("h", v[1], k)
    if t == "p":
        return v[1 + k]
    if t in ("l", "s"):
        return ("r", 0, 0xFF)
    return X


def combine(lo, hi):
    if lo[0] == "c" and hi[0] == "c":
        return ("c", lo[1] | hi[1] << 8)
    if lo[0] == "h" and hi[0] == "h" and lo[1] == hi[1] and (lo[2], hi[2]) == (0, 1):
        return ("e", lo[1])
    if lo[0] in TAINT or hi[0] in TAINT:
        return ("p", lo, hi)
    a, b = rng(lo, 8), rng(hi, 8)
    return mk(a[0] | b[0] << 8, a[1] | b[1] << 8, 16)


def join8(a, b):
    if a == b:
        return a
    if a[0] in TAINT or b[0] in TAINT:
        return X
    x, y = rng(a, 8), rng(b, 8)
    return mk(min(x[0], y[0]), max(x[1], y[1]), 8)


def join(a, b):
    if a == b:
        return a
    if a[0] == "s" and b[0] == "s":
        return ("s", a[1] | b[1])
    if a[0] in ("e", "p") or b[0] in ("e", "p"):
        return combine(join8(split(a, 0), split(b, 0)), join8(split(a, 1), split(b, 1)))
    if a[0] in TAINT or b[0] in TAINT or a[0] in ("sp", "s") or b[0] in ("sp", "s"):
        return X
    x, y = rng(a, 16), rng(b, 16)
    return mk(min(x[0], y[0]), max(x[1], y[1]), 16)


def widen(v):
    return ("r", 0, 0xFFFF) if v[0] == "r" else v


@dataclass
class Footprint:
    mem: dict = field(default_factory=lambda: defaultdict(set))   # (cls, lo, hi, 'r'|'w') -> sites
    ports: dict = field(default_factory=lambda: defaultdict(set))
    ifs: dict = field(default_factory=lambda: defaultdict(set))   # value -> sites
    hooks: dict = field(default_factory=lambda: defaultdict(set))
    exits: dict = field(default_factory=lambda: defaultdict(set))
    runtime: dict = field(default_factory=lambda: defaultdict(set))
    clamped: dict = field(default_factory=lambda: defaultdict(set))   # class -> sites (extents)
    depth: int = 0
    nodes: set = field(default_factory=set)
    errors: list = field(default_factory=list)

def site(n) -> str:
    return f"{n[0]}+{n[1]:05X}"


# -- handler interpretation ----------------------------------------------------
class _Path:
    """One state while interpreting an instruction's ops."""

    def __init__(self, regs, flags, slots):
        self.regs, self.flags, self.slots = dict(regs), dict(flags), dict(slots)
        self.t = {}

    def freeze(self):
        return (tuple(self.regs[r] for r in REGS), tuple(self.flags.get(f) for f in FLAGS),
                tuple(sorted(self.slots.items())))


def thaw(st):
    regs, flags, slots = st
    return _Path(dict(zip(REGS, regs)), {f: v for f, v in zip(FLAGS, flags) if v is not None},
                 dict(slots))


def join_states(a, b):
    regs = tuple(join(x, y) for x, y in zip(a[0], b[0]))
    flags = tuple(None if x is None or y is None else x if x == y else ("r", 0, 1)
                  for x, y in zip(a[1], b[1]))
    sb = dict(b[2])
    slots = tuple((d, (wa, join(va, sb[d][1]))) for d, (wa, va) in a[2]
                  if d in sb and sb[d][0] == wa)
    return regs, flags, slots


SIG = tuple(REGS.index(r) for r in ("cx", "bx", "si", "di", "sp", "ds", "es"))


def signature(s):
    """States join only with states of equal loop registers (constants) and segments."""
    return tuple(s[0][k] if s[0][k][0] in ("c", "s", "sp") else s[0][k][0] for k in SIG)


def widen_state(old, new):
    """Widen the values that grew."""
    slots = dict(old[2])
    return (tuple(v if v == o else widen(v) for o, v in zip(old[0], new[0])), new[1],
            tuple((d, (w, v if slots.get(d) == (w, v) else widen(v))) for d, (w, v) in new[2]))


class Handler:
    def __init__(self, prog, entry=None):
        self.prog = prog
        rows = [r for r in image.rows("entries.csv") if r["reason"].startswith("INT 08h handler")]
        if entry is None:
            if len(rows) != 1:
                raise Violation("entries.csv: one INT 08h handler row expected")
            entry = (rows[0]["module"], int(rows[0]["offset"], 16))
        self.entry = entry
        self.mod = entry[0]
        u = prog.units[self.mod]
        self.code_para = u.cs[entry[1]]
        self.bounds = bounds()
        self.extents = extents()
        self.fp = Footprint()
        self.chains = {(r["module"], int(r["offset"], 16)) for r in image.rows("indirect.csv")
                       if f"-+0x{BIOS_ENTRY:x} (isr)" in r["traced_targets"]}

    def err(self, n, msg):
        self.fp.errors.append(f"{site(n)}: {msg}")

    def para_class(self, n, para):
        if para in (self.code_para,) or self.prog.units[self.mod].module.link_lo <= para * 16 < \
                self.prog.units[self.mod].module.link_hi:
            return ("s", frozenset({f"{para:04X}"}))
        self.err(n, f"relocated segment {para:04X} outside {self.mod}")
        return X

    def run(self) -> Footprint:
        regs = {r: ("e", r) for r in REGS}
        regs["cs"] = ("s", frozenset({f"{self.code_para:04X}"}))
        regs["sp"] = ("sp", 0)
        flags = {"IF": ("c", 0), "TF": ("c", 0)}
        slots = {0: (16, ("e", "ip")), 2: (16, ("e", "cs")), 4: (16, ("e", "fl"))}
        start = _Path(regs, flags, slots).freeze()
        key0 = ((), self.entry)
        states: dict = {key0: {signature(start): start}}
        changes: Counter = Counter()
        done: dict = defaultdict(set)
        work, queued = [key0], {key0}
        while work:
            key = work.pop()
            queued.discard(key)
            ctx, n = key
            for st in [s for s in states[key].values() if s not in done[key]]:
                done[key].add(st)
                for nctx, nn, ns in self.step(ctx, n, st):
                    k2 = (nctx, nn)
                    have = states.setdefault(k2, {})
                    sig = signature(ns)
                    if len(have) >= SIGNATURES and sig not in have:
                        sig = None      # too many: one joined state
                        if None not in have:
                            base = ns
                            for v in have.values():
                                base = join_states(base, v)
                            have.clear()
                            have[None] = base
                    old = have.get(sig)
                    if old is not None:
                        new = join_states(old, ns)
                        if new == old:
                            continue
                        changes[(k2, sig)] += 1
                        if changes[(k2, sig)] > WIDEN:
                            new = widen_state(old, new)
                        ns = new
                    have[sig] = ns
                    if k2 not in queued:
                        queued.add(k2)
                        work.append(k2)
        return self.fp

    # one instruction from one state: [(ctx, node, state)]
    def step(self, ctx, n, st):
        prog = self.prog
        mod, off = n
        u = prog.units[mod]
        i = u.insns.get(off)
        if i is None:
            self.err(n, "flow outside decoded code")
            return []
        self.fp.nodes.add(n)
        if n in prog.hle:
            self.fp.hooks[prog.hle[n][1]].add(site(n))
        fall = (mod, off + i.size)
        p = thaw(st)
        if i.op == "iret":
            return self.iret(n, p)
        if i.op == "jmpf" and isinstance(i.operands[0], Mem):
            return self.chain(n, i, p)
        out = []
        for q, ex in self.ops(n, i, p, u):
            kind = ex[0]
            if kind == "fall":
                out.append((ctx, fall, q.freeze()))
            elif kind == "jump":
                t = ex[1]
                if isinstance(t, int):
                    ip = t
                elif t[0] == "c":
                    ip = t[1]
                else:
                    self.err(n, "indirect jump")
                    continue
                out.append((ctx, (mod, u.off_of(u.cs[off], ip)), q.freeze()))
            elif kind in ("call", "callf"):
                if kind == "call":
                    t = ex[1]
                    if not isinstance(t, int):
                        self.err(n, "indirect call")
                        continue
                    target = (mod, u.off_of(u.cs[off], t))
                elif off in u.far_targets:
                    target = u.far_targets[off]
                else:
                    self.err(n, "far call outside the scope")
                    continue
                if fall in ctx:
                    self.err(n, "recursion")
                    continue
                out.append((ctx + (fall,), target, q.freeze()))
            elif kind == "jumpf" and off in u.far_targets:
                out.append((ctx, u.far_targets[off], q.freeze()))
            elif kind == "fault":
                self.fp.runtime[f"fault {ex[1]:02X}h (divide error: guest INT 00h at interrupt level)"].add(site(n))
            elif kind in ("ret", "retf"):
                if not ctx:
                    self.err(n, "return with an empty call stack")
                    continue
                want = ctx[-1]
                ip = ex[-1]
                if ip != ("c", prog.units[want[0]].ip_of(want[1])):
                    self.err(n, f"return to {ip}, not {site(want)}")
                    continue
                out.append((ctx[:-1], want, q.freeze()))
            else:
                self.err(n, f"{kind} in the handler")
        return out

    def transparent(self, n, p, sp):
        for r in REGS:
            want = ("sp", sp) if r == "sp" else ("s", frozenset({f"{self.code_para:04X}"})) if r == "cs" \
                else ("e", r)
            if p.regs[r] != want:
                self.err(n, f"{r} is {p.regs[r]} at the exit, not as interrupted")

    def iret(self, n, p):
        for d, name in ((0, "ip"), (2, "cs"), (4, "fl")):
            sp = p.regs["sp"]
            if sp[0] != "sp" or p.slots.get(sp[1] + d) != (16, ("e", name)):
                self.err(n, f"IRET pops {p.slots.get(sp[1] + d) if sp[0] == 'sp' else sp}, not the frame's {name}")
                return []
        p.regs["sp"] = ("sp", p.regs["sp"][1] + 6)
        self.transparent(n, p, 6)
        self.fp.exits["iret"].add(site(n))
        return []

    def chain(self, n, i, p):
        m = i.operands[0]
        if n not in self.chains or (m.seg, m.base, m.index) != ("cs", None, None):
            self.err(n, "indirect far jump other than the BIOS chain")
            return []
        self.access(n, p, self.ptr_seg(n, p, "cs"), ("c", m.disp), 16, "r")
        self.access(n, p, self.ptr_seg(n, p, "cs"), ("c", m.disp + 2), 16, "r")
        self.transparent(n, p, 0)
        if p.slots.get(0) != (16, ("e", "ip")) or p.slots.get(4) != (16, ("e", "fl")):
            self.err(n, "BIOS chain without the interrupt frame")
        cls, lo, hi = BIOS_TICK
        self.fp.mem[(cls, lo, hi, "r")].add("rt_bios_int08")
        self.fp.mem[(cls, lo, hi, "w")].add("rt_bios_int08")
        self.fp.runtime["rt_bios_int08 (BIOS tick, IRET)"].add(site(n))
        self.fp.exits["BIOS chain"].add(site(n))
        return []

    def ptr_seg(self, n, p, r):
        return p.regs[r]

    # -- memory --------------------------------------------------------------
    def access(self, n, p, seg, off, w, kind, val=None):
        size = w // 8
        if seg == ("e", "ss"):
            if off[0] != "sp":
                self.err(n, f"stack access at {off}")
                return X
            d = off[1]
            if kind == "w":
                self.fp.depth = max(self.fp.depth, -d)
                for k in range(d - 1, d + size):
                    if k in p.slots and k != d and k + p.slots[k][0] // 8 > d:
                        del p.slots[k]
                for k in list(p.slots):
                    if d < k < d + size:
                        del p.slots[k]
                p.slots[d] = (w, val)
                return None
            got = p.slots.get(d)
            if got is None or got[0] != w:
                self.err(n, f"reads the stack at SP{d:+d} (interrupted or unwritten)")
                return X
            return got[1]
        if seg[0] != "s":
            self.err(n, f"segment {seg}")
            return X
        r = rng(off, 16)
        if r is None:
            self.err(n, f"offset {off} from interrupted state")
            return X
        lo, hi = r[0], r[1] + size - 1
        out = None
        for cls in sorted(seg[1]):
            for a, b in ((lo, min(hi, 0xFFFF)), (0, hi - 0x10000)) if hi > 0xFFFF else ((lo, hi),):
                if cls in self.extents and not (self.extents[cls][0] <= a and b <= self.extents[cls][1]):
                    self.fp.clamped[cls].add(site(n))
                    a, b = max(a, self.extents[cls][0]), min(b, self.extents[cls][1])
                if b >= a:
                    self.fp.mem[(cls, a, b, kind)].add(site(n))
            var = self.disp if self.disp is not None else lo
            if kind == "w":
                if val is not None and val[0] in TAINT + ("sp",):
                    self.err(n, f"stores {val} (interrupted state) to {cls}")
                held = SEGMENT_WORDS.get((cls, var))
                if held and (w != 16 or self.seg_value(n, val) != ("s", frozenset({held}))):
                    self.err(n, f"stores {val} into a segment word of class {held}")
                continue
            got = ("l", cls, var)
            if (cls, var, w) in self.bounds:
                got = mk(*self.bounds[(cls, var, w)], w)
            out = got if out is None else join(out, got)
        return out

    def seg_value(self, n, v):
        """A value written to a segment register."""
        if v[0] in ("s", "e"):
            return v
        if v[0] == "l" and (v[1], v[2]) in SEGMENT_WORDS:
            return ("s", frozenset({SEGMENT_WORDS[(v[1], v[2])]}))
        self.err(n, f"segment register from {v}")
        return X

    # -- IR ------------------------------------------------------------------
    def ops(self, n, i, p, u):
        """Interpret the lifted ops of i on path p: [(path, exit)]."""
        ops = lift(i)
        labels = {o.args[0]: k for k, o in enumerate(ops) if o.op == "label"}
        fix = {f - n[1] for f in u.module.fixups if n[1] <= f < n[1] + i.size}
        reloc = None
        if fix:
            if i.op == "mov" and isinstance(i.operands[0], Reg) and isinstance(i.operands[1], Imm) \
                    and fix == {i.size - 2}:
                reloc = self.para_class(n, i.operands[1].value)
            elif not (i.op in ("callf", "jmpf") and isinstance(i.operands[0], Far)):
                self.err(n, "relocated operand")
                return []
        self.zero = i.op in ("xor", "sub") and isinstance(i.operands[0], Reg) and \
            i.operands[0] == i.operands[1]
        if self.zero:
            reloc = "zero"
        mems = [o for o in i.operands if isinstance(o, Mem)]
        self.disp = mems[0].disp if len(mems) == 1 and i.op not in ("les", "lds") else None
        out, pending = [], [(0, p)]
        guard = 0
        while pending:
            k, q = pending.pop()
            while k < len(ops):
                guard += 1
                if guard > 10000:
                    self.err(n, "op budget")
                    return out
                o = ops[k]
                k += 1
                op, a = o.op, o.args
                if op == "label":
                    continue
                if op == "goto":
                    k = labels[a[0]]
                    continue
                if op == "br":
                    c = self.val(q, a[0], 1)
                    if c[0] == "c":
                        if c[1]:
                            k = labels[a[1]]
                        continue
                    if c[0] in TAINT:
                        self.err(n, "branch on interrupted state")
                    alt = _Path(q.regs, q.flags, q.slots)
                    alt.t = dict(q.t)
                    pending.append((labels[a[1]], alt))
                    continue
                if o.dst is not None:
                    q.t[o.dst.n] = self.value(n, q, o, reloc)
                    continue
                ex = self.effect(n, q, o, reloc)
                if ex is not None:
                    out.append((q, ex))
                    break
            else:
                out.append((q, ("fall",)))
        return out

    def val(self, q, a, w):
        if isinstance(a, T):
            return q.t[a.n]
        return ("c", a & mask(w))

    def get(self, q, r):
        if r in HALF:
            reg, k = HALF[r]
            return split(q.regs[reg], k)
        return q.regs[r]

    def put(self, n, q, r, v):
        if r in HALF:
            reg, k = HALF[r]
            v8 = split(v, 0) if v[0] not in ("h", "c", "r") else v
            if v[0] == "c":
                v8 = ("c", v[1] & 0xFF)
            parts = [split(q.regs[reg], 0), split(q.regs[reg], 1)]
            parts[k] = v8
            q.regs[reg] = combine(*parts)
        elif r in ("ds", "es", "ss"):
            q.regs[r] = self.seg_value(n, v)
        else:
            q.regs[r] = v

    def value(self, n, q, o, reloc):
        op, a, w = o.op, o.args, o.dst.w
        if op == "const":
            return ("c", a[0] & mask(w))
        if op == "get":
            return self.get(q, a[0])
        if op == "flag":
            v = q.flags.get(a[0])
            if v is None:
                self.err(n, f"reads {a[0]} before the handler sets it")
                return X
            return v
        if op == "load":
            return self.access(n, q, self.val(q, a[0], 16), self.val(q, a[1], 16), w, "r")
        if op == "in":
            self.port(n, self.val(q, a[0], 16), "r")
            return ("r", 0, mask(w))
        if op == "cond":
            return self.cond(n, q, a[0])
        vals = [self.val(q, x, w if op not in ("zext", "sext", "trunc", "shl", "shr", "sar", "rol",
                                                 "ror", "eq", "ne", "ltu", "lts", "select")
                         else (x.w if isinstance(x, T) else w)) for x in a]
        if op == "select":
            c = vals[0]
            if c[0] == "c":
                return vals[1] if c[1] else vals[2]
            if c[0] in TAINT:
                self.err(n, "select on interrupted state")
            return join(vals[1], vals[2])
        if op in ("xor", "sub") and reloc == "zero":
            return ("c", 0)     # xor/sub r, r: the result does not depend on r
        if op in ("zext", "trunc"):
            src = vals[0]
            if src[0] in ("e", "h", "p"):
                if op == "zext" or src[0] == "h":
                    self.err(n, f"{op} of interrupted {src}")
                    return X
            if op == "trunc" and w == 8 and src[0] in ("e", "p"):
                self.err(n, f"truncates interrupted {src}")
                return X
        for v in vals:
            if v[0] in TAINT:
                if op in ("zext", "trunc", "sext") or v[0] != "sp":
                    self.err(n, f"{op} reads interrupted {v}")
                    return X
        if any(v[0] == "sp" for v in vals):
            if op in ("add", "sub") and len(vals) == 2 and vals[0][0] == "sp" and vals[1][0] == "c":
                d = vals[1][1] if op == "add" else -vals[1][1]
                d = (d + 0x8000) % 0x10000 - 0x8000
                return ("sp", vals[0][1] + d)
            self.err(n, f"{op} on SP")
            return X
        return arith(op, w, vals, [x.w if isinstance(x, T) else w for x in a])

    def cond(self, n, q, cc):
        need = CC_READS[cc]
        f = {}
        for name in need:
            v = q.flags.get(name)
            if v is None:
                self.err(n, f"reads {name} before the handler sets it")
                return X
            f[name] = v
        if any(v[0] != "c" for v in f.values()):
            return ("r", 0, 1)
        g = {k: v[1] for k, v in f.items()}
        r = {"o": lambda: g["OF"], "b": lambda: g["CF"], "e": lambda: g["ZF"],
             "be": lambda: g["CF"] | g["ZF"], "s": lambda: g["SF"], "p": lambda: g["PF"],
             "l": lambda: g["SF"] ^ g["OF"], "le": lambda: g["ZF"] | (g["SF"] ^ g["OF"])}
        base = cc[1:] if cc.startswith("n") and cc not in ("ne",) and cc[1:] in r else cc
        if cc == "ne":
            return ("c", 1 - g["ZF"])
        if cc in ("ae", "a", "ge", "g"):
            inv = {"ae": "b", "a": "be", "ge": "l", "g": "le"}[cc]
            return ("c", 1 - r[inv]())
        if cc in r:
            return ("c", r[cc]())
        return ("c", 1 - r[base]())

    def port(self, n, v, kind):
        if v[0] != "c" or v[1] not in PORTS:
            self.err(n, f"port {v} not in PORTS")
            return
        self.fp.ports[(v[1], kind)].add(site(n))

    def effect(self, n, q, o, reloc=None):
        op, a = o.op, o.args
        if op == "put":
            if reloc not in (None, "zero") and isinstance(a[1], int):
                self.put(n, q, a[0], reloc)
                return None
            self.put(n, q, a[0], self.val(q, a[1], 8 if a[0] in HALF else 16))
            return None
        if op == "setflag":
            v = self.val(q, a[1], 1)
            if v[0] in TAINT:
                self.err(n, f"sets {a[0]} from interrupted state")
                v = ("r", 0, 1)
            if a[0] == "IF":
                self.fp.ifs[v[1] if v[0] == "c" else "?"].add(site(n))
            q.flags[a[0]] = v
            return None
        if op == "store":
            w = a[3]
            self.access(n, q, self.val(q, a[0], 16), self.val(q, a[1], 16), w, "w",
                        self.val(q, a[2], w))
            return None
        if op == "out":
            port = self.val(q, a[0], 16)
            self.port(n, port, "w")
            self.fp.runtime["rt_out8" if port == ("c", 0x388) or port == ("c", 0x389)
                            else "rt_out8 (PIC: no effect)"].add(site(n))
            v = self.val(q, a[1], 8)
            if v[0] in TAINT:
                self.err(n, f"writes interrupted {v} to a port")
            return None
        if op == "flags":
            self.flags(n, q, a)
            return None
        if op == "bcd":
            self.err(n, "BCD in the handler")
            return None
        return (op,) + tuple(self.val(q, x, 16) if isinstance(x, T) else x for x in a)

    def flags(self, n, q, a):
        kind, w = a[0], a[1]
        vals = [self.val(q, x, w if not isinstance(x, T) else x.w) for x in a[2:]]
        if self.zero:
            vals = [("c", 0)] * 3
        elif any(v[0] in TAINT + ("sp",) for v in vals):
            self.err(n, f"{kind} flags from interrupted state")
        d, undef = FLAG_KINDS[kind]
        unknown = ("r", 0, 1)
        for f in set(d) | set(undef):
            q.flags[f] = unknown
        x, y, r = (rng(v, w) if v[0] not in TAINT + ("sp",) else None for v in vals[:3])
        if r is None:
            return
        top = 1 << (w - 1)
        if r[0] == r[1]:
            q.flags["ZF"] = ("c", int(r[0] == 0)) if "ZF" in d else q.flags["ZF"]
            if "SF" in d:
                q.flags["SF"] = ("c", int(bool(r[0] & top)))
        elif r[0] > 0 and "ZF" in d:
            q.flags["ZF"] = ("c", 0)
        if kind == "logic":
            q.flags["CF"] = q.flags["OF"] = ("c", 0)
        elif kind == "sub" and x is not None and y is not None:
            if x[1] < y[0]:
                q.flags["CF"] = ("c", 1)
            elif x[0] >= y[1]:
                q.flags["CF"] = ("c", 0)
            if x[0] == x[1] and y[0] == y[1]:
                a_, b_, r_ = x[0], y[0], (x[0] - y[0]) & mask(w)
                q.flags["OF"] = ("c", int(bool((a_ ^ b_) & (a_ ^ r_) & top)))
        elif kind == "add" and x is not None and y is not None:
            if x[1] + y[1] <= mask(w):
                q.flags["CF"] = ("c", 0)
            elif x[0] + y[0] > mask(w):
                q.flags["CF"] = ("c", 1)


def arith(op, w, vals, widths):
    """Constants exactly, ranges conservatively."""
    rs = [rng(v, ww) for v, ww in zip(vals, widths)]
    m = mask(w)
    if all(r[0] == r[1] for r in rs):
        xs = [r[0] for r in rs]
        try:
            return ("c", exact(op, w, xs, widths) & m)
        except KeyError:
            return ("r", 0, m)
    (a, b), rest = rs[0], rs[1:]
    if op in ("zext",):
        return mk(a, b, w)
    if op == "trunc":
        return mk(a, b, w) if b <= m else ("r", 0, m)
    if op == "add":
        c, d = rest[0]
        return mk(a + c, b + d, w)
    if op == "sub":
        c, d = rest[0]
        return mk(a - d, b - c, w)
    if op == "shl" and rest[0][0] == rest[0][1]:
        return mk(a << rest[0][0], b << rest[0][0], w)
    if op == "shr" and rest[0][0] == rest[0][1]:
        return mk(a >> rest[0][0], b >> rest[0][0], w)
    if op == "and":
        return mk(0, min(b, rest[0][1]), w)
    if op in ("or", "xor"):
        hi = max(b, rest[0][1])
        return mk(0, (1 << hi.bit_length()) - 1, w)
    if op == "mul":
        c, d = rest[0]
        return mk(a * c, b * d, w)
    if op in ("eq", "ne"):
        c, d = rest[0]
        if b < c or d < a:
            return ("c", int(op == "ne"))
        return ("r", 0, 1)
    if op == "ltu":
        c, d = rest[0]
        if b < c:
            return ("c", 1)
        if a >= d:
            return ("c", 0)
        return ("r", 0, 1)
    return ("r", 0, m)


def sgn(v, w):
    return v - (1 << w) if v >> (w - 1) & 1 else v


def exact(op, w, xs, widths):
    a = xs[0]
    b = xs[1] if len(xs) > 1 else 0
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "and":
        return a & b
    if op == "or":
        return a | b
    if op == "xor":
        return a ^ b
    if op == "not":
        return ~a
    if op == "neg":
        return -a
    if op == "mul":
        return a * b
    if op == "shl":
        return a << b if b < w else 0
    if op == "shr":
        return a >> b if b < w else 0
    if op == "sar":
        return sgn(a, widths[0]) >> min(b, w)
    if op == "zext":
        return a
    if op == "sext":
        return sgn(a, widths[0])
    if op == "trunc":
        return a
    if op == "eq":
        return int(a == b)
    if op == "ne":
        return int(a != b)
    if op == "ltu":
        return int(a < b)
    if op == "lts":
        return int(sgn(a, widths[0]) < sgn(b, widths[1]))
    if op in ("udiv", "urem") and b:
        return a // b if op == "udiv" else a % b
    raise KeyError(op)


# -- main code -----------------------------------------------------------------
GPR = ("ax", "bx", "cx", "dx", "si", "di", "bp")
SEGS = ("es", "ds", "ss")
STACK_CAP = 48
READS_DST = {"cmp", "test", "push", "call", "callf", "jmp", "jmpf"}
WRITES_AX = {"mul", "imul", "div", "idiv", "cbw", "lahf", "xlat", "in", "lods", "aaa", "aas",
             "daa", "das", "aam", "aad"}


@dataclass(frozen=True)
class MState:
    regs: tuple          # GPR values: int (16-bit) | ('m', depth) | ('b', lo, hi) | None
    segs: tuple          # es, ds, ss: runtime paragraph | None
    depth: int | None    # words pushed since the function entry
    tail: tuple          # known top of the stack (last = top)
    iflag: int | None
    shadow: bool
    cs_mem: tuple = ()   # ((module, first, last), value) of code-segment words stored on this path


def mjoin(a: MState | None, b: MState) -> MState:
    if a is None:
        return b
    if a == b:
        return a
    regs = tuple(x if x == y else None for x, y in zip(a.regs, b.regs))
    segs = tuple(x if x == y else None for x, y in zip(a.segs, b.segs))
    depth = a.depth if a.depth == b.depth else None
    n = min(len(a.tail), len(b.tail)) if depth is not None else 0
    tail = tuple(x if x == y else None for x, y in zip(a.tail[len(a.tail) - n:], b.tail[len(b.tail) - n:]))
    return MState(regs, segs, depth, tail, a.iflag if a.iflag == b.iflag else None,
                  a.shadow and b.shadow, tuple(x for x in a.cs_mem if x in b.cs_mem))


class Main:
    """Segment registers, IF and memory slots of main code (module docstring)."""

    def __init__(self, prog, handler_entry):
        self.prog = prog
        self.handler = handler_entry
        self.fixups = {n: set(u.module.fixups) for n, u in prog.units.items()}
        self.slots: dict[int, int | None] = {}
        self.stores: dict[int, int | None] = {}
        self.state: dict = {}
        self.rets_to = defaultdict(set)
        for r, sites in prog.ret_of.items():
            for s in sites:
                self.rets_to[s].add(r)
        self.rows = sorted(e for e in prog.dispatch if e in prog.succ and e != self.handler)
        self.smc = {}
        for r in image.rows("self-modifying.csv"):
            for w in r["writers"].replace("/", " ").split():
                self.smc[(r["module"], int(w[1:], 16))] = (r["module"], int(r["first"], 16),
                                                          int(r["last"], 16))

    # -- one instruction ---------------------------------------------------------
    def site_after(self, n):
        u = self.prog.units[n[0]]
        i = u.insns[n[1]]
        return (n[0], n[1] + i.size + (2 if n[1] in u.manager_calls else 0))

    @staticmethod
    def terminates(i, st: MState) -> bool:
        """INT 21h AH=4Ch (exit) does not return."""
        ax = st.regs[0]
        hi = ax >> 8 if isinstance(ax, int) else ax[2] if isinstance(ax, tuple) and ax[0] == "b" else None
        return i.op == "int" and i.operands[0].value == 0x21 and hi == 0x4C

    def cs_key(self, n, m: Mem):
        """A code-segment word: (module, first, last) module offsets; an indexed writer
        its self-modifying.csv region, else '*'."""
        u = self.prog.units[n[0]]
        if m.base or m.index:
            return self.smc.get(n, "*")
        off = u.off_of(u.cs[n[1]], m.disp)
        return (n[0], off, off + 1)

    def cs_write(self, n):
        """The code-segment word n writes through a CS override, else None."""
        i = self.prog.node_insn(n)
        dst = i.operands[0] if i.operands else None
        if isinstance(dst, Mem) and dst.seg == "cs" and i.op not in READS_DST:
            return self.cs_key(n, dst)
        return None

    @staticmethod
    def kill(cs_mem, keys):
        """cs_mem without the words keys overlap ('*': all)."""
        if "*" in keys:
            return ()
        return tuple(x for x in cs_mem if not any(
            m == x[0][0] and lo <= x[0][2] and x[0][1] <= hi for m, lo, hi in keys))

    def mem_lin(self, st: MState, m: Mem):
        seg = st.segs[SEGS.index(m.seg)] if m.seg in SEGS else None
        if not isinstance(seg, int) or m.base or m.index:
            return None
        return seg * 16 + m.disp

    def value(self, n, i, st: MState, o):
        if isinstance(o, Reg):
            if o.name in GPR:
                v = st.regs[GPR.index(o.name)]
                return v if not isinstance(v, tuple) else None
            if o.name in SEGS:
                return st.segs[SEGS.index(o.name)]
            if o.name == "cs":
                return LOADSEG + self.prog.units[n[0]].cs[n[1]]
            return None
        if isinstance(o, Imm):
            v = o.value
            if o.width == 16 and n[1] + i.size - 2 in self.fixups[n[0]]:
                v = (v + LOADSEG) & 0xFFFF
            return v
        if isinstance(o, Mem):
            if o.seg == "cs" and not (o.base or o.index) and o.width == 16:
                saved = dict(st.cs_mem)
                if self.cs_key(n, o) in saved:
                    return saved[self.cs_key(n, o)]
            lin = self.mem_lin(st, o)
            return self.slots.get(lin) if lin is not None and o.width == 16 else None
        return None

    def transfer(self, n, st: MState, record: bool = False) -> MState:
        """The state after n (calls and returns: before their transfer)."""
        u = self.prog.units[n[0]]
        i = u.insns[n[1]]
        op, ops = i.op, i.operands
        regs, segs = list(st.regs), list(st.segs)
        depth, tail = st.depth, list(st.tail)
        iflag, shadow = st.iflag, False
        cs_mem = st.cs_mem

        def setr(r, v):
            nonlocal depth, tail
            if r in GPR:
                regs[GPR.index(r)] = v
            elif r in SEGS:
                segs[SEGS.index(r)] = v
            elif r == "sp":
                depth, tail = None, []
            elif r in HALF:
                full, k = HALF[r]
                old = regs[GPR.index(full)]
                b = ([old & 0xFF, old >> 8] if isinstance(old, int) else
                     list(old[1:]) if isinstance(old, tuple) and old[0] == "b" else [None, None])
                b[k] = v if isinstance(v, int) else None
                regs[GPR.index(full)] = (b[0] | b[1] << 8 if None not in b else
                                         None if b == [None, None] else ("b", *b))

        def push(v):
            nonlocal depth
            tail.append(v)
            if len(tail) > STACK_CAP:
                del tail[0]
            depth = None if depth is None else depth + 1

        def pop():
            nonlocal depth
            depth = None if depth is None else depth - 1
            return tail.pop() if tail else None

        dst = ops[0] if ops else None
        key = self.cs_write(n)
        if key is not None:
            cs_mem = self.kill(cs_mem, {key})
            if op == "mov" and key != "*" and not (dst.base or dst.index) and dst.width == 16:
                v = self.value(n, i, st, ops[1])
                if v is not None:
                    cs_mem = tuple(sorted(cs_mem + ((key, v),)))
        if op == "mov" and isinstance(dst, Reg):
            src = ops[1]
            if dst.name == "sp" and src == Reg("bp") and isinstance(regs[6], tuple):
                d = regs[6][1]
                if depth is not None and d <= depth:
                    tail = tail[:max(len(tail) - (depth - d), 0)]
                    depth = d
                else:
                    depth, tail = None, []
            elif dst.name == "bp" and src == Reg("sp"):
                regs[6] = ("m", depth) if depth is not None else None
            elif isinstance(src, Reg) and src.name in GPR and dst.name in GPR:
                setr(dst.name, st.regs[GPR.index(src.name)])
            else:
                setr(dst.name, self.value(n, i, st, src))
        elif op == "mov" and isinstance(dst, Mem):
            lin = self.mem_lin(st, dst)
            if record and lin is not None and dst.width == 16:
                v = self.value(n, i, st, ops[1])
                v = v if isinstance(v, int) else None
                self.stores[lin] = v if self.stores.get(lin, v) == v else None
        elif op in ("xor", "sub") and isinstance(dst, Reg) and ops[1] == dst:
            setr(dst.name, 0)
        elif op == "push":
            push(self.value(n, i, st, dst) if dst != Reg("sp") else None)
        elif op == "pop":
            v = pop()
            if isinstance(dst, Reg):
                setr(dst.name, v)
        elif op == "pushf":
            push(None)
        elif op == "popf":
            pop()
            iflag = None
        elif op in ("les", "lds"):
            setr(dst.name, None)
            lin = self.mem_lin(st, ops[1])
            setr("es" if op == "les" else "ds", self.slots.get(lin + 2) if lin is not None else None)
        elif op == "xchg" and all(isinstance(o, Reg) and o.name in GPR for o in ops):
            a, b = (GPR.index(o.name) for o in ops)
            regs[a], regs[b] = st.regs[b], st.regs[a]
        elif op in ("add", "sub") and dst == Reg("sp") and isinstance(ops[1], Imm):
            v = sgn(ops[1].value & 0xFFFF, 16)
            words = v // 2 if op == "add" else -v // 2
            if v % 2 or abs(words) > 0x400:
                depth, tail = None, []
            elif words > 0:
                for _ in range(words):
                    pop()
            else:
                for _ in range(-words):
                    push(None)
        elif op == "cli":
            iflag = 0
        elif op == "sti":
            iflag, shadow = 1, True
        elif op == "int":
            for r in ("ax", "bx", "cx", "dx", "si", "di", "es"):
                setr(r, None)
        elif op in ("call", "callf", "ret", "retf", "iret", "jmp", "jmpf", "jcc", "jcxz", "cmp",
                    "test", "out", "nop", "clc", "stc", "cmc", "cld", "std", "hlt"):
            pass
        else:
            if op in WRITES_AX:
                setr("ax", None)
            if op in ("mul", "imul", "div", "idiv", "cwd") or op in ("mul", "imul") and i.width == 16:
                setr("dx", None)
            if op in ("movs", "cmps", "stos", "lods", "scas"):
                setr("si", None)
                setr("di", None)
                if i.rep:
                    setr("cx", None)
            if op in ("loop", "loope", "loopne"):
                setr("cx", None)
            if op == "lea" or op in ("in", "xlat", "lahf", "cbw", "cwd"):
                pass
            for o in (ops if op == "xchg" else ops[:1]):
                if isinstance(o, Reg):
                    setr(o.name, None)
        return MState(tuple(regs), tuple(segs), depth, tuple(tail), iflag, shadow, cs_mem)

    def call_entry(self, n, new: MState) -> MState:
        """The callee's entry state (return address pushed: depth 0 below it)."""
        i = self.prog.node_insn(n)
        push = (LOADSEG + self.prog.units[n[0]].cs[n[1]], None) if i.op == "callf" else (None,)
        return MState(new.regs, new.segs, 0, (new.tail + push)[-STACK_CAP:], new.iflag, False,
                      new.cs_mem)

    def ret_words(self, rets) -> int | None:
        words = {(self.prog.node_insn(r).operands[0].value // 2 if self.prog.node_insn(r).operands else 0)
                 for r in rets}
        return words.pop() if len(words) == 1 else None

    def after(self, caller: MState, callee: MState | None, words: int | None, ds) -> MState:
        """State at a return site: the caller's stack, BP and SS, DS from the callees'
        summaries (ds_after), the callee's other registers."""
        depth, tail = caller.depth, list(caller.tail)
        if words is None:
            depth, tail = None, []
        for _ in range(words or 0):
            depth = None if depth is None else depth - 1
            if tail:
                tail.pop()
        if callee is None:
            regs = tuple(caller.regs[k] if g == "bp" else None for k, g in enumerate(GPR))
            segs = (None, ds, caller.segs[2])
            iflag = None
        else:
            regs = tuple(caller.regs[k] if g == "bp" else callee.regs[k] for k, g in enumerate(GPR))
            segs = (callee.segs[0], ds, caller.segs[2])
            iflag = callee.iflag
        return MState(regs, segs, depth, tuple(tail), iflag, False,
                      () if callee is None else callee.cs_mem)

    # -- whole program -------------------------------------------------------------
    def targets(self, n):
        """Successors; an unresolved transfer reaches its traced targets (indirect.csv;
        others are not reached: monitored), None for a self-modified walk."""
        out = []
        for t in self.prog.succ.get(n, []):
            if t == "unknown":
                sw, tr = self.prog.indirect.get(n, ([], []))
                found = [x for x in sw + tr if x in self.prog.succ and x != self.handler]
                out += found or [None]
            elif t == "smc":
                out.append(None)
            elif isinstance(t, tuple):
                out.append(t)
        return out

    def run(self):
        """States per context (function entry, entry DS, entry SS): a call enters its
        targets' contexts; a return site joins the caller's stack and BP with the
        callee context's state at its returns. Iterated until the memory slots (word
        stores of constant addresses) are stable."""
        prog = self.prog
        self.declared = {(r["module"], int(r["offset"], 16)) for r in image.rows("irq-ds.csv")}
        root = (M.ROOT, M.entry())
        psp = LOADSEG - 0x10
        start = MState((None,) * len(GPR), (psp, psp, None), 0, (), 1, False)
        for _ in range(8):
            before = dict(self.slots)
            self.state, self.stores = {}, {}
            self.rets, self.callers = {}, defaultdict(set)
            first = ((root, psp, None), root)
            self.state[first] = start
            work, queued = [first], {first}
            while work:
                key = work.pop()
                queued.discard(key)
                for k, s in self.step(key[0], key[1], self.state[key]):
                    new = mjoin(self.state.get(k), s) if s is not None else self.state[k]
                    if new != self.state.get(k) or s is None:
                        self.state[k] = new
                        if k not in queued:
                            queued.add(k)
                            work.append(k)
            self.slots = self.stores
            if self.slots == before:
                break
        else:
            raise Violation("main-code slots did not converge")
        called = {c[0] for c in self.rets} | {c[0] for c in self.callers}
        for d in self.declared - called:
            raise Violation(f"irq-ds.csv: {site(d)} is no called entry")
        self.at = defaultdict(list)
        for (ctx, n), st in self.state.items():
            self.at[n].append(st)
        return self

    def states(self, n) -> list:
        return self.at.get(n, [])

    def step(self, ctx, n, st: MState):
        """(key, state) successors; state None re-runs a key (a callee's returns grew)."""
        prog = self.prog
        i = prog.node_insn(n)
        new = self.transfer(n, st, record=True)
        out = []
        if self.terminates(i, st):
            return out
        if i.op in ("call", "callf"):
            entry = self.call_entry(n, new)
            site = self.site_after(n)
            words = self.ret_words(self.rets_to.get(site, ()))
            for t in self.targets(n):
                if t is None:   # never traced: MS C keeps DS (I3 checks the accesses)
                    if site in prog.succ:
                        out.append(((ctx, site), self.after(st, None, words, st.segs[1])))
                    continue
                if t == self.handler:
                    continue
                c = (t, entry.segs[1], entry.segs[2])
                out.append(((c, t), entry))
                self.callers[c].add((ctx, n))
                r = self.rets.get(c)
                if r is not None and site in prog.succ:
                    ds = st.segs[1] if t in self.declared else r.segs[1]
                    out.append(((ctx, site), self.after(st, r, words, ds)))
            return out
        if i.op in ("ret", "retf"):
            r = mjoin(self.rets.get(ctx), st)
            if r != self.rets.get(ctx):
                self.rets[ctx] = r
                out += [((cc, c), None) for cc, c in self.callers[ctx]]
            return out
        for t in self.targets(n):
            if t is not None and t != self.handler:
                out.append(((ctx, t), new))
        return out


# -- classification --------------------------------------------------------------
MEMLINE = re.compile(r"\((?:[^()]*,)?a[0-3](?:[,)])")


def accesses(i):
    """(memory operand or None for the stack/string side, 'r'|'w'|'rw') of i."""
    from .lower import mem_dests
    out = []
    dests = mem_dests(i)
    for o in i.operands:
        if isinstance(o, Mem) and i.op != "lea":
            if o in dests:
                kind = "w" if i.op in ("mov", "pop") else "rw"
            else:
                kind = "r"
            out.append((o, kind))
    return out


RANK = ("sync", "monitored", "disjoint")


class Proof:
    def __init__(self, prog, compute_rows=None):
        self.prog = prog
        self.handler = Handler(prog)
        self.fp = self.handler.run()
        self.main = Main(prog, self.handler.entry).run()
        self.compute_rows = prog.compute_rows if compute_rows is None else compute_rows
        self.errors = list(self.fp.errors)
        self.classify()

    def lin_class(self):
        """Footprint class -> runtime paragraph (None: located at run time)."""
        out = {"BDA": 0x40}
        for (cls, *_rest) in self.fp.mem:
            if re.fullmatch(r"[0-9A-F]{4}", cls):
                out[cls] = int(cls, 16) + LOADSEG
        slot = (GAME_DS_SLOT[0] + LOADSEG) * 16 + GAME_DS_SLOT[1]
        g = self.main.slots.get(slot)
        if g is None:
            self.errors.append(f"G: the word at {GAME_DS_SLOT[0]:04X}:{GAME_DS_SLOT[1]:04X} has no single stored value")
        out["G"] = g
        return out

    def classify(self):
        paras = self.lin_class()
        self.paras = paras
        written, accessed = [], []
        for (cls, lo, hi, kind) in self.fp.mem:
            para = paras.get(cls)
            if para is None:
                continue
            span = (para * 16 + lo, para * 16 + hi, cls, lo)
            accessed.append(span)
            if kind == "w":
                written.append(span)
        self.written, self.accessed = written, accessed
        self.counts = Counter()
        self.sync = set()
        declared = declared_sync()
        prog = self.prog
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                states = self.main.states(n)
                if n in self.fp.nodes and not states:
                    continue
                acc = accesses(i)
                port = i.op in ("in", "out")
                if not acc and not port:
                    continue
                if not states:
                    self.counts["monitored (not reached)"] += 1
                    continue
                live = [st for st in states if not (st.iflag == 0 or st.shadow)]
                if not live:
                    self.counts["masked (IF = 0)"] += 1
                    continue
                found = {self.classify_insn(n, i, st, acc) for st in live}
                if n in declared:
                    if "monitored" not in found:
                        self.errors.append(f"irq-sync.csv: {site(n)} is no monitored access ({found})")
                    for cls, lo, hi, kind in declared.pop(n):
                        para = paras.get(cls)
                        w_hit = para is not None and self.meets(para * 16 + lo, para * 16 + hi, written)
                        self.sync.add((n, cls, lo, hi, kind, bool(w_hit)))
                    found = {"sync"}
                self.counts[min(found, key=RANK.index)] += 1
        for n in declared:
            self.errors.append(f"irq-sync.csv: {site(n)} is not reached")
        self.check_atomic()
        self.check_rows()
        self.check_bounds()

    def meets(self, lo, hi, spans):
        return [s for s in spans if s[0] <= hi and lo <= s[1]]

    def classify_insn(self, n, i, st, acc):
        out = "disjoint"
        if i.op in ("in", "out"):
            p = i.operands[1 if i.op == "in" else 0]
            port = p.value if isinstance(p, Imm) else st.regs[GPR.index("dx")] if p == Reg("dx") else None
            if not isinstance(port, int):
                out = "monitored"
            elif port in PORTS:
                self.sync.add((n, "port", port, port, "w" if i.op == "out" else "r", False))
                return "sync"
        for m, kind in acc:
            seg = st.segs[SEGS.index(m.seg)] if m.seg in SEGS else LOADSEG + self.prog.units[n[0]].cs[n[1]]
            if seg is None:
                out = "monitored"
                continue
            size = m.width // 8 if m.width != 32 else 4
            if m.base or m.index:
                # indexed: sync when its displacement lies in a footprint span; the
                # row covers the spans it may reach (I3 checks the address)
                at = seg * 16 + m.disp
                hits = [s for s in self.accessed if s[0] <= at <= s[1]]
                if not hits:
                    out = "monitored" if out != "sync" else out
                    continue
                w_hit = [s for s in self.written if s[0] <= at <= s[1]]
                if ("r" in kind and w_hit) or "w" in kind:
                    for s in hits if "w" in kind else w_hit:
                        self.sync.add((n, s[2], s[3], s[3] + s[1] - s[0], kind, bool(w_hit)))
                    return "sync"
                continue
            lo, hi = seg * 16 + m.disp, seg * 16 + m.disp + size - 1
            w_hit = self.meets(lo, hi, self.written)
            a_hit = self.meets(lo, hi, self.accessed)
            if ("r" in kind and w_hit) or ("w" in kind and a_hit):
                cls = (w_hit or a_hit)[0]
                self.sync.add((n, cls[2], lo - (cls[0] - cls[3]), hi - (cls[0] - cls[3]), kind,
                                  bool(w_hit)))
                return "sync"
        return out

    def check_atomic(self):
        """A sync access to a handler-written byte lowers to one memory-touching 68k line."""
        from .lower import lower
        prog = self.prog
        for n, cls, lo, hi, kind, written in self.sync:
            if not written or cls == "port":
                continue
            i = prog.node_insn(n)
            try:
                lines = lower(i, prog.ctx(n[0], n[1], Counter())).out
            except Exception as e:  # noqa: BLE001 - reported, not hidden
                self.errors.append(f"{site(n)}: lowering for the atomicity check failed: {e}")
                continue
            mem = [x for x in lines if MEMLINE.search(x) and not x.strip().startswith("lea")]
            if len(mem) != 1:
                self.errors.append(f"{site(n)}: {i} meets handler-written {cls}:{lo:04X}..{hi:04X} "
                                   f"in {len(mem)} 68k memory accesses ({'; '.join(m.strip() for m in mem)})")

    def check_bounds(self):
        """Main-code writes of a bounded G variable (irq-bounds.csv): an immediate within
        the bound, or the restore of a frame copy taken in the same module
        (mov r,[v]; mov [bp+d],r ... mov r,[bp+d]; mov [v],r). Other classes are
        SPAZ-private; I3 monitors every handler access."""
        from .lower import mem_dests
        g = self.paras.get("G")
        rows = {var: (w, lo, hi) for (cls, var, w), (lo, hi) in bounds().items() if cls == "G"}
        if not rows or g is None:
            return
        prog = self.prog
        prev = {}
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                prev[(mod, off + i.size)] = (mod, off)

        def is_g(n, m):
            return m.seg in SEGS and any(st.segs[SEGS.index(m.seg)] == g for st in self.main.states(n))

        def plain(m, var):
            return isinstance(m, Mem) and not (m.base or m.index) and m.disp == var

        def frame(m):
            return isinstance(m, Mem) and m.seg == "ss" and m.base == "bp" and not m.index

        copies = set()
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                p = prev.get(n)
                if i.op == "mov" and frame(i.operands[0]) and isinstance(i.operands[1], Reg) and p:
                    j = prog.node_insn(p)
                    src = j.operands[1] if j.op == "mov" else None
                    if isinstance(src, Mem) and j.operands[0] == i.operands[1] and src.disp in rows \
                            and plain(src, src.disp) and is_g(p, src):
                        copies.add((mod, j.operands[1].disp, i.operands[0].disp, i.operands[1].name))
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                for m in mem_dests(i):
                    var = next((v for v in rows if isinstance(m, Mem) and not (m.base or m.index)
                                and v <= m.disp + m.width // 8 - 1 and m.disp <= v + rows[v][0] // 8 - 1), None)
                    if var is None or not is_g(n, m):
                        continue
                    w, lo, hi = rows[var]
                    src = i.operands[1] if len(i.operands) > 1 else None
                    ok = i.op == "mov" and m.disp == var and m.width == w
                    if ok and isinstance(src, Imm):
                        ok = lo <= src.value <= hi
                    elif ok and isinstance(src, Reg) and n in prev:
                        j = prog.node_insn(prev[n])
                        ok = (j.op == "mov" and j.operands[0] == src and frame(j.operands[1])
                              and (mod, var, j.operands[1].disp, src.name) in copies)
                    else:
                        ok = False
                    if not ok:
                        self.errors.append(f"{site(n)}: {i} writes G:{var:04X} outside its irq-bounds.csv "
                                           f"bound {lo:#x}..{hi:#x} (immediate or frame-copy restore)")

    def check_rows(self):
        """No compute row's range or proved body (callees included) holds a sync access;
        a row with exits: its proved body (the exit stretches stay generated)."""
        syncs = {n for n, *_ in self.sync}
        bodies = getattr(self.prog, "compute_bodies", {})
        for row in sorted(self.compute_rows):
            resume = self.prog.hle.get(row, ((None, None), None))[0]
            mod, first = row
            u = self.prog.units[mod]
            end = self.prog.compute_end.get(row)
            last = max(o for o in u.insns if o < resume[1]) if resume[1] else first
            hi = max(last, end or 0)
            nodes = {(mod, off) for off in u.insns if first <= off <= hi}
            if row in bodies and row in getattr(self.prog, "compute_exits", {}):
                # exits and re-entries: the stretches between them run generated
                nodes = set(bodies[row].body)
            elif row in bodies:
                nodes |= bodies[row].body
            for n in sorted(nodes & syncs):
                self.errors.append(f"compute row {site(row)} contains sync access {site(n)}")

    def sync_points(self) -> dict:
        """I8 sync points, (module, offset) -> kind: where tests and the reference
        deliver posted interrupts, before the instruction. `access`: a sync access;
        `int`: a software interrupt (a service); `clear`: CLI, POPF or IRET (IF may
        go 1→0: a tick due before it is taken there, as without polling, not after the
        masked accesses that follow); `if`: the instruction after an IF 0→1, i.e.
        after POPF or after STI's shadow (a RET there: its return sites).
        Accesses and interrupts that only run with IF = 0 never deliver; reached
        or not, every other one counts (I3 checks what the analysis missed)."""
        prog = self.prog
        out = {n: "access" for n, *_ in self.sync}

        def live(n):
            states = self.main.states(n)
            return not states or any(not (st.iflag == 0 or st.shadow) for st in states)

        def after(n):
            ss = [s for s in prog.succ.get(n, ()) if isinstance(s, tuple) and s in prog.succ]
            if prog.node_insn(n).op in ("ret", "retf"):
                ss += sorted(prog.ret_of.get(n, ()))
            return ss

        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                if (n in self.fp.nodes and not self.main.states(n)) or n not in prog.succ:
                    continue
                if i.op == "int" and live(n):
                    out.setdefault(n, "int")
                if i.op in ("cli", "popf", "iret") and live(n):
                    out.setdefault(n, "clear")
                if i.op in ("sti", "popf"):
                    states = self.main.states(n)
                    if states and all(st.iflag == 1 for st in states):
                        continue
                    for m in after(n) if i.op == "popf" else [x for s in after(n) for x in after(s)]:
                        out[m] = "if"   # checked in every build: wins over the other kinds
        return out

    def raise_errors(self):
        if self.errors:
            raise Violation("IRQ0 footprint:\n" + "\n".join(sorted(set(self.errors))[:60]))

    def rows(self) -> list[str]:
        out = []
        fp = self.fp

        def merged(cls, kind):
            spans = sorted((lo, hi, sites) for (c, lo, hi, k), sites in fp.mem.items()
                           if c == cls and k == kind)
            acc = []
            for lo, hi, sites in spans:
                if acc and lo <= acc[-1][1] + 1:
                    acc[-1] = (acc[-1][0], max(acc[-1][1], hi), acc[-1][2] | sites)
                else:
                    acc.append((lo, hi, set(sites)))
            return acc

        for cls in sorted({c for c, *_ in fp.mem}):
            for kind in ("r", "w"):
                for lo, hi, sites in merged(cls, kind):
                    out.append(f"mem,{cls},0x{lo:04x},0x{hi:04x},{kind},{' '.join(sorted(sites))}")
        for (port, kind), sites in sorted(fp.ports.items()):
            out.append(f"port,{PORTS[port].split(' ')[0]},0x{port:03x},0x{port:03x},{kind},{' '.join(sorted(sites))}")
        out.append(f"stack,K,-0x{fp.depth:x},-0x1,rw,{site(self.handler.entry)}")
        for v, sites in sorted(fp.ifs.items(), key=str):
            out.append(f"if,,{v},{v},w,{' '.join(sorted(sites))}")
        for name, sites in sorted(fp.hooks.items()):
            out.append(f"hook,{name},,,,{' '.join(sorted(sites))}")
        for name, sites in sorted(fp.runtime.items()):
            out.append(f"runtime,{name},,,,{' '.join(sorted(sites))}")
        for name, sites in sorted(fp.exits.items()):
            out.append(f"exit,{name},,,,{' '.join(sorted(sites))}")
        for cls, sites in sorted(fp.clamped.items()):
            lo, hi = self.handler.extents[cls]
            out.append(f"extent,{cls},0x{lo:04x},0x{hi:04x},rw,{' '.join(sorted(sites))}")
        for n, cls, lo, hi, kind, written in sorted(self.sync):
            out.append(f"sync,{cls},0x{lo:04x},0x{hi:04x},{kind},{site(n)}")
        return out

    def summary(self) -> str:
        c = self.counts
        return ("irq footprint: handler " + f"{len(self.fp.nodes)} instructions, stack {self.fp.depth} bytes; "
                + "main accesses " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))


def prove(prog) -> Proof:
    p = Proof(prog)
    p.raise_errors()
    return p
