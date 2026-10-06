"""Lower one decoded 8086 instruction to 68020 (Motorola syntax, vasm) under the
register contract of docs/translator-design.md §Generated code contract.

Registers: d0 AX, d1 CX, d2 DX, d3 BX, d4 SP, d5 BP, a4 SI, a5 DI hold 16-bit
guest values zero-extended to 32 bits (every write keeps the upper word 0, so
any of them indexes guest RAM as `(base,Rn.l)`); a1/a2/a3 = ES/SS/DS base
(a6 + seg*16); a6 = guest RAM (linear 0, little-endian, byte-exact) with the
state block at negative offsets; d6, d7, a0 scratch; a7 native stack.

Guest flags (state block): G_FL low byte = 68k CCR image of CF (C), OF (V),
ZF (Z), SF (N) (X is not guest state); PF = even parity of G_PF; AF = bit 4
of G_AF; DF/IF/TF bytes; G_FX = FLAGS bits 12-15. A flag setter stores the
flags `need` names (live after it, from translator/flags.py) and may leave
them in the CCR for the next instruction (`fuse`), which then reads `ccr_in`
instead of the state block.

Semantics follow translator/sem.py (386 real mode); the tests compare the
output against Unicorn x86-16, independently of the IR.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .decode import Far, Imm, Insn, Mem, Reg, Rel
from .ir import FLAG_KINDS, STATUS

GREG = {"ax": "d0", "cx": "d1", "dx": "d2", "bx": "d3", "sp": "d4", "bp": "d5", "si": "a4",
        "di": "a5"}
HALF = {"al": ("ax", 0), "cl": ("cx", 0), "dl": ("dx", 0), "bl": ("bx", 0),
        "ah": ("ax", 8), "ch": ("cx", 8), "dh": ("dx", 8), "bh": ("bx", 8)}
SEGBASE = {"es": "a1", "ss": "a2", "ds": "a3"}
SEGSLOT = {"es": "G_ES", "ss": "G_SS", "ds": "G_DS"}
SZ = {8: "b", 16: "w"}
CCR_BIT = {"CF": 1, "OF": 2, "ZF": 4, "SF": 8}
CC68 = {"o": "vs", "no": "vc", "b": "cs", "ae": "cc", "e": "eq", "ne": "ne", "be": "ls",
        "a": "hi", "s": "mi", "ns": "pl", "l": "lt", "ge": "ge", "le": "le", "g": "gt"}
CC_READS = {"o": {"OF"}, "no": {"OF"}, "b": {"CF"}, "ae": {"CF"}, "e": {"ZF"}, "ne": {"ZF"},
            "be": {"CF", "ZF"}, "a": {"CF", "ZF"}, "s": {"SF"}, "ns": {"SF"},
            "p": {"PF"}, "np": {"PF"}, "l": {"SF", "OF"}, "ge": {"SF", "OF"},
            "le": {"SF", "OF", "ZF"}, "g": {"SF", "OF", "ZF"}}
ALLC = {"CF", "OF", "ZF", "SF"}
# Flags the 68k CCR holds with x86 meaning right after the lowered operation
# ("X": the X bit equals CF).
CCR_OK = {"add": ALLC | {"X"}, "adc": ALLC | {"X"}, "sub": ALLC | {"X"}, "sbb": ALLC | {"X"},
          "cmp": ALLC, "logic": ALLC, "inc": {"OF", "ZF", "SF"}, "dec": {"OF", "ZF", "SF"},
          "neg": ALLC | {"X"}, "shl": ALLC | {"X"}, "sar": ALLC | {"X"},
          "shr": {"CF", "ZF", "SF", "X"}}
STATE_EQU = (("G_FL", -2), ("G_PF", -3), ("G_AF", -4), ("G_DF", -5), ("G_IF", -6),
             ("G_TF", -7), ("G_IRQ", -8), ("G_FX", -10), ("G_ES", -12), ("G_SS", -14), ("G_DS", -16))
LOADSEG = 0x0822  # load segment of every reference run (docs/source-inventory.md)


class LowerError(Exception):
    pass


def hx(v: int) -> str:
    return f"${v:x}" if v > 9 else str(v)


def swap_expr(e: str) -> str:
    return f"((({e})>>8)&$ff)|((({e})&$ff)<<8)"


@dataclass
class Ctx:
    """What the lowering of one instruction needs from its module (or a test)."""
    cs: str                                   # 68k expression of the run-time CS
    label: str                                # this instruction's label
    need: set = field(default_factory=set)    # status flags to store in the state block
    live: set = field(default_factory=lambda: set(STATUS))  # status flags live after
    ccr_in: set = field(default_factory=set)  # flags valid in the CCR at entry
    fuse: bool = False                        # try to leave `need`-free flags in the CCR
    reloc: frozenset = frozenset()            # byte positions of relocated segment words
    near: object = None                       # ip -> label | None (None: test exit)
    far: object = None                        # (seg, off) -> label | None
    near_targets: tuple = ()                  # known targets of an indirect near transfer
    smc_targets: tuple = ()                   # (first IP, last IP, walk label): D16 regions
    complete: bool = False                    # near_targets is a proved switch table
    far_targets: tuple = ()                   # known (seg, off) targets of an indirect far one
    manager: bool = False                     # PLINK manager call: return skips `dw id`
    program: bool = False                     # program mode (return checks, runtime calls)
    vram: bool = False                        # graphics driver: stores to A000h mark rows (D9)
    driver_call: bool = False                 # PLINK thunk jump into the graphics driver (D9)


class Lowering:
    def __init__(self, insn: Insn, ctx: Ctx):
        self.i, self.c = insn, ctx
        self.out: list[str] = []
        self.ccr: set = set()      # flags valid in the CCR at the end
        self.stats = Counter()
        self.nl = 0
        self.af = insn.op in ("add", "adc", "sub", "sbb", "cmp", "inc", "dec", "neg")

    # -- emission ---------------------------------------------------------
    def e(self, line: str) -> None:
        self.out.append("\t" + line)

    def local(self) -> str:
        self.nl += 1
        return f".{self.nl}"

    def at(self, label: str) -> None:
        self.out.append(f"{label}:")

    # -- constants, registers, memory --------------------------------------
    def imm(self, o: Imm, pos: int | None = None) -> str:
        v = o.value & (0xFF if o.width == 8 else 0xFFFF)
        if pos is not None and pos in self.c.reloc:
            return f"LOADSEG+{hx(v)}"
        return hx(v)

    def reloc_at_end(self) -> bool:
        return self.i.size - 2 in self.c.reloc

    def check_reloc(self, allowed: set[int]) -> None:
        bad = set(self.c.reloc) - allowed
        if bad:
            raise LowerError(f"relocated word at +{sorted(bad)} of {self.i}")

    def seg_base(self, seg: str) -> str:
        if seg == "cs":
            self.e(f"lea (({self.c.cs})*16,a6),a0")
            return "a0"
        return SEGBASE[seg]

    def ea(self, m: Mem, seg: str | None = None):
        """Address of a memory operand: returns mem(k) for the byte at +k (no 64 KiB
        wrap inside a word). Uses d7 for computed offsets and a0 for CS."""
        base = self.seg_base(seg or m.seg)
        regs = [GREG[r] for r in (m.base, m.index) if r]
        if not regs:
            d = m.disp
            return lambda k: f"({hx(d + k)},{base})"
        if len(regs) == 1 and not m.disp:
            r = regs[0]
            return lambda k: f"{k}({base},{r}.l)"
        self.e(f"move.l {regs[0]},d7")
        if len(regs) == 2:
            self.e(f"add.w {regs[1]},d7")
        if m.disp:
            self.e(f"add.w #{hx(m.disp)},d7")
        return lambda k: f"{k}({base},d7.l)"

    def lea(self, m: Mem) -> str:
        """Put the operand's address in a0; returns the base string."""
        mem = self.ea(m)
        self.e(f"lea {mem(0)},a0")
        return "a0"

    def load16(self, mem, dst: str) -> None:
        self.e(f"move.w {mem(0)},{dst}")
        self.e(f"ror.w #8,{dst}")

    def store16(self, mem, src: str) -> None:
        """Store a native word from a data register (rotated in place)."""
        self.e(f"ror.w #8,{src}")
        self.e(f"move.w {src},{mem(0)}")

    def getreg(self, r: str, dst: str) -> None:
        """Guest register into data register `dst`: 16-bit ones zero-extended, 8-bit
        ones in the low byte (other bits unspecified). Keeps X."""
        if r in HALF:
            full, sh = HALF[r]
            if sh:
                self.e(f"move.w {GREG[full]},{dst}")
                self.e(f"ror.w #8,{dst}")
            else:
                self.e(f"move.l {GREG[full]},{dst}")
        else:
            self.e(f"move.l {GREG[r]},{dst}")

    def putreg(self, r: str, src: str) -> None:
        """Data register `src` (low byte/word) into a guest register."""
        if r in HALF:
            full, sh = HALF[r]
            g = GREG[full]
            if sh:
                self.e(f"ror.w #8,{g}")
                self.e(f"move.b {src},{g}")
                self.e(f"rol.w #8,{g}")
            else:
                self.e(f"move.b {src},{g}")
        elif GREG[r][0] == "a":
            self.e(f"and.l #$ffff,{src}")
            self.e(f"movea.l {src},{GREG[r]}")
        else:
            self.e(f"move.w {src},{GREG[r]}")

    def read(self, o, dst: str, pos: int | None = None) -> None:
        """Operand value into the low byte/word of data register `dst` (upper bits
        unspecified except for 16-bit registers)."""
        w = o.width
        if isinstance(o, Reg):
            if o.name in SEGBASE or o.name == "cs":
                self.getseg(o.name, dst)
            else:
                self.getreg(o.name, dst)
        elif isinstance(o, Imm):
            self.e(f"move.l #{self.imm(o, pos)},{dst}")
        elif isinstance(o, Mem):
            mem = self.ea(o)
            if w == 8:
                self.e(f"move.b {mem(0)},{dst}")
            else:
                self.load16(mem, dst)
        else:
            raise LowerError(f"read {o}")

    def write(self, o, src: str) -> None:
        """Data register `src` into a register or memory operand (src clobbered)."""
        if isinstance(o, Reg):
            if o.name in SEGBASE:
                self.putseg(o.name, src)
            else:
                self.putreg(o.name, src)
        elif isinstance(o, Mem):
            if src == "d7" and (o.base or o.index or o.seg == "cs"):
                self.e("move.l d7,d6")
                src = "d6"
            mem = self.ea(o)
            if o.width == 8:
                self.e(f"move.b {src},{mem(0)}")
            else:
                self.store16(mem, src)
        else:
            raise LowerError(f"write {o}")

    def getseg(self, s: str, dst: str) -> None:
        if s == "cs":
            self.e(f"move.l #{self.c.cs},{dst}")
        else:
            self.e(f"moveq #0,{dst}")
            self.e(f"move.w {SEGSLOT[s]}(a6),{dst}")

    def putseg(self, s: str, src: str) -> None:
        self.e(f"and.l #$ffff,{src}")
        self.e(f"move.w {src},{SEGSLOT[s]}(a6)")
        self.e(f"lsl.l #4,{src}")
        self.e(f"lea (a6,{src}.l),{SEGBASE[s]}")

    def push(self, src: str | None = None, const: str | None = None) -> None:
        self.e("subq.w #2,d4")
        if const is not None:
            self.e(f"move.w #{swap_expr(const)},(a2,d4.l)")
        else:
            self.e(f"ror.w #8,{src}")
            self.e(f"move.w {src},(a2,d4.l)")

    def pop(self, dst: str) -> None:
        self.e(f"move.w (a2,d4.l),{dst}")
        self.e(f"ror.w #8,{dst}")
        self.e("addq.w #2,d4")

    # -- flags --------------------------------------------------------------
    def kills(self, kind: str) -> set:
        d, u = FLAG_KINDS[kind]
        return set(d) | set(u)

    def store_ccr(self, flags: set, defined: set) -> None:
        """Store the CCR-held `flags` (subset of ALLC) in G_FL. A full store is
        used when every live CCR flag is redefined here."""
        flags = flags & ALLC
        if not flags:
            return
        keep = {f for f in ALLC if f in self.c.live and f not in defined}
        if not keep:
            self.e("move.w ccr,G_FL(a6)")
            self.stats["flag store"] += 1
            return
        m = sum(CCR_BIT[f] for f in flags)
        self.e("move.w ccr,d7")
        self.e(f"and.b #{hx(m)},d7")
        self.e(f"and.b #{hx(~m & 0xFF)},G_FL+1(a6)")
        self.e("or.b d7,G_FL+1(a6)")
        self.ccr = set()
        self.stats["flag merge"] += 1

    def put_bits(self, bits: int, src: str = "d7") -> None:
        """Merge CCR-image bits `bits` of data register `src` into G_FL."""
        self.e(f"and.b #{hx(bits)},{src}")
        self.e(f"and.b #{hx(~bits & 0xFF)},G_FL+1(a6)")
        self.e(f"or.b {src},G_FL+1(a6)")
        self.ccr = set()
        self.stats["flag merge"] += 1

    def finish_flags(self, kind: str, ok: set, res: str | None = None,
                     extra: set = frozenset()) -> None:
        """After the 68k op: store `need` ∩ defined; leave the CCR as `ok` if fusable.
        `res`: data register holding the result (for PF); `extra`: needed flags the
        caller computes itself."""
        defined = self.kills(kind)
        need = self.c.need & FLAG_KINDS[kind][0]
        self.ccr = set(ok)
        self.store_ccr((need & ok) - set(extra), defined)
        if "PF" in need:
            self.e(f"move.b {res},G_PF(a6)")
            self.ccr = set()
            self.stats["PF store"] += 1
        if need >= set(STATUS):
            self.stats["full-flag materialization"] += 1
        if not self.c.fuse:
            self.ccr = set()

    def af_pre(self, a: str, b: str) -> None:
        """AF of a+b / a-b: G_AF := a ^ b before the op, ^ result after (af_post)."""
        if "AF" in self.c.need and self.af:
            self.e(f"move.b {a},G_AF(a6)")
            if b.startswith("#"):
                self.e(f"eor.b #({b[1:]})&$ff,G_AF(a6)")
            else:
                self.e(f"eor.b {b},G_AF(a6)")
            self.stats["AF store"] += 1

    def af_post(self, r: str) -> None:
        if "AF" in self.c.need and self.af:
            self.e(f"eor.b {r},G_AF(a6)")
            self.ccr = set()

    def load_ccr(self, reads: set) -> None:
        """Make the CCR hold guest CF/OF/ZF/SF for a reader."""
        if not reads <= self.c.ccr_in:
            self.e("move.w G_FL(a6),ccr")
            self.stats["flag load"] += 1

    def set_x(self) -> None:
        """X := CF (for addx/subx/roxl/roxr), Z := 1. Uses d7."""
        if not {"X", "CF"} <= self.c.ccr_in:
            self.e("move.b G_FL+1(a6),d7")
            self.e("lsr.b #1,d7")
            self.stats["flag load"] += 1

    def branch_cc(self, cc: str, target: str) -> None:
        if cc in ("p", "np"):
            self.e("jsr __getpf")
            self.e(f"tst.b d7")
            self.e(f"{'bne' if cc == 'p' else 'beq'} {target}")
        else:
            self.load_ccr(CC_READS[cc])
            self.e(f"b{CC68[cc]} {target}")

    # -- dispatch ------------------------------------------------------------
    def run(self) -> list[str]:
        i = self.i
        op = i.op
        fn = getattr(self, "op_" + op, None)
        if fn is None:
            if op in ("add", "adc", "sub", "sbb", "cmp", "and", "or", "xor", "test"):
                fn = self.alu
            elif op in ("rol", "ror", "rcl", "rcr", "shl", "shr", "sar"):
                fn = self.shift
            elif op in ("movs", "cmps", "stos", "lods", "scas"):
                fn = self.string
            elif op in ("daa", "das", "aaa", "aas"):
                fn = self.bcd
            else:
                raise LowerError(f"no lowering for {i}")
        if op not in ("mov", "push", "callf", "jmpf"):
            self.check_reloc(set())
        if self.c.vram and op not in STRING_OPS:
            for m in mem_dests(i):
                self.vram_mark(m)
        fn()
        return self.out

    # -- D9 display: the graphics driver's stores to video memory ------------
    def vram_mark(self, m: Mem) -> None:
        """Before a store to `m` in the graphics driver: if its segment is
        A000h, rt_vram_mark widens the changed rows (d7 = offset, d6 = bytes)."""
        if m.seg == "cs":
            return
        skip = self.local()
        self.e(f"cmp.w #$a000,{SEGSLOT[m.seg]}(a6)")
        self.e(f"bne.s {skip}")
        regs = [GREG[r] for r in (m.base, m.index) if r]
        if regs:
            self.e(f"move.l {regs[0]},d7")
            if len(regs) == 2:
                self.e(f"add.w {regs[1]},d7")
            if m.disp:
                self.e(f"add.w #{hx(m.disp)},d7")
        else:
            self.e(f"move.l #{hx(m.disp)},d7")
        self.e(f"moveq #{m.width // 8},d6")
        self.e("jsr rt_vram_mark")
        self.at(skip)
        self.stats["video store mark"] += 1

    def vram_mark_string(self, step: int) -> None:
        """Before `stos`/`movs` (ES:DI, CX elements under REP): the bytes the
        instruction will write, in the direction of `step`."""
        skip = self.local()
        self.e("cmp.w #$a000,G_ES(a6)")
        self.e(f"bne.s {skip}")
        n = abs(step)
        if self.i.rep:
            self.e("moveq #0,d6")
            self.e("move.w d1,d6")
            self.e(f"beq.s {skip}")
            if n == 2:
                self.e("add.l d6,d6")
        else:
            self.e(f"moveq #{n},d6")
        self.e("move.l a5,d7")
        if step < 0:            # DF = 1: the lowest byte written is DI + n - bytes
            self.e("sub.l d6,d7")
            self.e(f"addq.l #{n},d7")
        self.e("jsr rt_vram_mark")
        self.at(skip)
        self.stats["video store mark"] += 1

    # -- ALU -----------------------------------------------------------------
    def src_operand(self, o, *, areg: bool, mem: bool, scratch: str = "d7",
                    pos: int | None = None) -> str:
        """Second operand as a 68k source: data register, #imm, an address register
        (`areg`), direct byte memory (`mem`) or `scratch` it was loaded into."""
        if isinstance(o, Imm):
            return f"#{self.imm(o, pos)}"
        if isinstance(o, Reg):
            if o.name in HALF:
                full, sh = HALF[o.name]
                if not sh:
                    return GREG[full]
            elif GREG[o.name][0] == "d" or areg:
                return GREG[o.name]
            self.getreg(o.name, scratch)
            return scratch
        if o.width == 8 and mem:
            return self.ea(o)(0)
        self.read(o, scratch)
        return scratch

    def dest_reg(self, a) -> str | None:
        """68k register operated on in place: 16-bit data register or low byte."""
        if isinstance(a, Reg):
            if a.name in HALF:
                full, sh = HALF[a.name]
                return None if sh else GREG[full]
            if GREG[a.name][0] == "d":
                return GREG[a.name]
        return None

    def load_dest(self, a, dst: str) -> None:
        """Destination operand into `dst` (a0 holds a memory operand's address). Keeps X."""
        if isinstance(a, Mem):
            if a.width == 8:
                self.e(f"move.b (a0),{dst}")
            else:
                self.load16(lambda k: f"{k}(a0)", dst)
        else:
            self.getreg(a.name, dst)

    def store_dest(self, a, src: str) -> None:
        """Write `src` back to the destination; clears self.ccr if that clobbers it."""
        if isinstance(a, Mem):
            if a.width == 8:
                self.e(f"move.b {src},(a0)")
            else:
                self.store16(lambda k: f"{k}(a0)", src)
            self.ccr = set()
        elif a.name in HALF:
            self.putreg(a.name, src)
            self.ccr = set()
        else:
            self.e(f"movea.l {src},{GREG[a.name]}")

    def alu(self) -> None:
        i = self.i
        op, w = i.op, i.width
        a, b = i.operands
        sz = SZ[w]
        kind = {"add": "add", "adc": "adc", "sub": "sub", "sbb": "sbb", "cmp": "cmp",
                "and": "logic", "or": "logic", "xor": "logic", "test": "logic"}[op]
        m68 = {"add": "add", "sub": "sub", "cmp": "cmp", "and": "and", "or": "or", "xor": "eor",
               "test": "and", "adc": "addx", "sbb": "subx"}[op]
        writes = op not in ("cmp", "test")
        need = self.c.need & FLAG_KINDS[{"cmp": "sub"}.get(kind, kind)][0]
        flagkind = {"cmp": "sub"}.get(kind, kind)
        ok = CCR_OK[kind]
        logic = m68 in ("and", "or", "eor")
        af = "AF" in need
        if op in ("adc", "sbb"):
            self.carry_op(m68, kind, a, b, w)
            return
        if op == "cmp" and {"PF", "AF"} & need:
            m68, ok = "sub", CCR_OK["sub"]  # the result is needed: subtract a copy
        r = self.dest_reg(a)
        if r and (writes or m68 == "cmp"):
            # in place on a data register
            s = self.src_operand(b, areg=not (logic or af), mem=m68 != "eor" and not af)
            self.af_pre(r, s)
            self.e(f"{m68}.{sz} {s},{r}")
            self.finish_flags(flagkind, ok, r)
            self.af_post(r)
            return
        if (isinstance(a, Mem) and w == 8 and not ({"AF", "PF"} & need) and op != "test"
                and (writes or isinstance(b, Imm))):
            # in place on a memory byte
            s = self.src_operand(b, areg=False, mem=False, scratch="d6")
            mem = self.ea(a)
            self.e(f"{m68}.b {s},{mem(0)}")
            self.finish_flags(flagkind, ok)
            return
        # on a copy in d6
        if isinstance(a, Mem):
            self.lea(a)
        s = self.src_operand(b, areg=not (logic or af), mem=False)
        self.load_dest(a, "d6")
        self.af_pre("d6", s)
        self.e(f"{m68}.{sz} {s},d6")
        self.finish_flags(flagkind, ok, "d6")
        self.af_post("d6")
        if writes:
            self.store_dest(a, "d6")

    def carry_op(self, m68, kind, a, b, w) -> None:
        """adc sbb: addx/subx need X = CF and Z preset to 1. Order: addresses and the
        source first (they may change X), then X from the state block, then X-safe
        moves of the destination."""
        sz = SZ[w]
        if isinstance(a, Mem):
            self.lea(a)
        s = self.src_operand(b, areg=False, mem=False, scratch="d6")
        if s.startswith("#"):
            self.e(f"move.l {s},d6")
            s = "d6"
        self.e("move.b G_FL+1(a6),d7")
        self.e("lsr.b #1,d7")
        self.stats["flag load"] += 1
        r = self.dest_reg(a)
        if r is None:
            r = "d7"
            self.load_dest(a, "d7")
        self.af_pre(r, s)
        self.e("ori.b #4,ccr")
        self.e(f"{m68}.{sz} {s},{r}")
        self.finish_flags(kind, CCR_OK[kind], r)
        self.af_post(r)
        if r == "d7":
            self.store_dest(a, "d7")

    def unary(self, m68: str, kind: str | None) -> None:
        """inc dec neg not on any operand."""
        i = self.i
        a = i.operands[0]
        sz = SZ[i.width]
        need = self.c.need
        ok = CCR_OK.get(kind, set())
        opnd = {"addq": "#1,", "subq": "#1,", "neg": "", "not": ""}[m68]
        if isinstance(a, Reg) and (a.name in HALF and not HALF[a.name][1]
                                   or a.name in GREG and GREG[a.name][0] == "d"):
            r = GREG[HALF[a.name][0]] if a.name in HALF else GREG[a.name]
            if kind:
                if kind == "neg":
                    if "AF" in need:
                        self.e(f"move.b {r},G_AF(a6)")
                        self.stats["AF store"] += 1
                else:
                    self.af_pre(r, "#1")
            self.e(f"{m68}.{sz} {opnd}{r}")
            if kind:
                self.finish_flags(kind, ok, r)
                self.af_post(r)
            return
        if isinstance(a, Mem) and i.width == 8 and not ({"AF", "PF"} & need):
            mem = self.ea(a)
            self.e(f"{m68}.b {opnd}{mem(0)}")
            if kind:
                self.finish_flags(kind, ok)
            return
        if isinstance(a, Mem):
            self.lea(a)
            if i.width == 8:
                self.e("move.b (a0),d6")
            else:
                self.load16(lambda k: f"{k}(a0)", "d6")
        else:
            self.getreg(a.name, "d6")
        if kind == "neg":
            if "AF" in need:
                self.e("move.b d6,G_AF(a6)")
                self.stats["AF store"] += 1
        elif kind:
            self.af_pre("d6", "#1")
        self.e(f"{m68}.{sz} {opnd}d6")
        if kind:
            self.finish_flags(kind, ok, "d6")
            self.af_post("d6")
        if isinstance(a, Mem):
            if i.width == 8:
                self.e("move.b d6,(a0)")
            else:
                self.store16(lambda k: f"{k}(a0)", "d6")
            self.ccr = set()
        elif a.name in HALF:
            self.putreg(a.name, "d6")
            self.ccr = set()
        else:
            self.e(f"movea.l d6,{GREG[a.name]}")

    def op_inc(self):
        self.unary("addq", "inc")

    def op_dec(self):
        self.unary("subq", "dec")

    def op_neg(self):
        self.unary("neg", "neg")

    def op_not(self):
        self.unary("not", None)

    # -- shifts and rotates --------------------------------------------------
    def shift(self) -> None:
        i = self.i
        op, w = i.op, i.width
        a, cnt = i.operands
        sz = SZ[w]
        m68 = {"shl": "asl", "shr": "lsr", "sar": "asr", "rol": "rol", "ror": "ror",
               "rcl": "roxl", "rcr": "roxr"}[op]
        rot = op in ("rol", "ror", "rcl", "rcr")
        need = self.c.need & FLAG_KINDS[op][0]
        skip = None
        if isinstance(a, Mem):
            self.lea(a)
        if op in ("rcl", "rcr"):
            self.e("move.b G_FL+1(a6),d6")
            self.e("lsr.b #1,d6")  # X := CF; moveq, and.b, move, ror keep X
            self.stats["flag load"] += 1
        if isinstance(cnt, Reg):
            skip = self.local()
            self.e("moveq #$1f,d7")
            self.e("and.b d1,d7")
            self.e(f"beq {skip}")
            count = "d7"
        else:
            count = "#1"
        r = self.dest_reg(a) or "d6"
        if r == "d6":
            self.load_dest(a, "d6")
        self.e(f"{m68}.{sz} {count},{r}")
        computed = {"OF"} & need if op not in ("shl", "sar") else set()
        if rot or computed or isinstance(cnt, Reg):
            self.c.fuse = False
        store = (need - computed) | ({"CF"} if rot and computed else set())
        ok = {"CF"} if rot else CCR_OK[op]
        self.ccr = set(ok)
        self.store_ccr(store & ok, self.kills(op))
        if "PF" in need:
            self.e(f"move.b {r},G_PF(a6)")
            self.stats["PF store"] += 1
        if computed:
            top = w - 1
            if op == "shr":  # count 1: OF = msb(a) = bit w-2 of the result
                self.e(f"btst #{w - 2},{r}")
                self.e("sne d7")
            elif op in ("rol", "rcl"):  # OF = msb(r) ^ CF (CF stored above)
                lab = self.local()
                self.e("move.b G_FL+1(a6),d7")
                self.e(f"btst #{top},{r}")
                self.e(f"beq {lab}")
                self.e("not.b d7")
                self.at(lab)
                self.e("add.b d7,d7")
            else:  # ror rcr: OF = msb(r) ^ bit w-2 of r
                self.e(f"move.{sz} {r},d7")
                self.e(f"add.{sz} d7,d7")
                self.e(f"eor.{sz} {r},d7")
                self.e("smi d7")
            self.put_bits(2)
            self.stats["OF compute"] += 1
        if need >= set(STATUS) - {"AF"}:
            self.stats["full-flag materialization"] += 1
        if not self.c.fuse:
            self.ccr = set()
        if r == "d6":
            self.store_dest(a, "d6")
        if skip:
            self.at(skip)
            self.ccr = set()

    # -- multiply / divide ---------------------------------------------------
    def op_mul(self):
        self.muldiv("mul")

    def op_imul(self):
        self.muldiv("imul")

    def op_div(self):
        self.muldiv("div")

    def op_idiv(self):
        self.muldiv("idiv")

    def mul_flags(self, test: list[str]) -> None:
        """CF = OF = (`test` leaves NE); SF ZF AF PF undefined, so a full store."""
        if not self.c.need & {"CF", "OF"}:
            return
        for t in test:
            self.e(t)
        self.e("sne d7")
        self.e("move.w d7,G_FL(a6)")
        self.stats["flag store"] += 1

    def muldiv(self, op: str) -> None:
        i = self.i
        w = i.width
        self.read(i.operands[0], "d6")
        signed = op in ("imul", "idiv")
        if w == 8:
            self.e("ext.w d6" if signed else "and.w #$ff,d6")
        if op in ("mul", "imul"):
            if w == 8:
                if op == "mul":
                    self.e("and.w #$ff,d0")
                    self.e("mulu.w d6,d0")
                    self.mul_flags(["move.w d0,d7", "lsr.w #8,d7"])
                else:
                    self.e("ext.w d0")
                    self.e("muls.w d6,d0")
                    self.e("and.l #$ffff,d0")
                    self.mul_flags(["move.b d0,d7", "ext.w d7", "cmp.w d0,d7"])
            else:
                self.e(f"{'muls' if signed else 'mulu'}.w d6,d0")
                self.e("move.l d0,d2")
                self.e("clr.w d2")
                self.e("swap d2")
                if op == "mul":
                    self.mul_flags(["tst.w d2"])
                else:
                    self.mul_flags(["move.w d0,d7", "ext.l d7", "cmp.l d0,d7"])
                self.e("and.l #$ffff,d0")
            self.ccr = set()
            return
        fault, end = self.local(), self.local()
        div = "divs" if signed else "divu"
        if w == 8:
            if signed:
                self.e("move.w d0,d7")
                self.e("ext.l d7")
            else:
                self.e("moveq #0,d7")
                self.e("move.w d0,d7")
            self.e("tst.w d6")
            self.e(f"beq {fault}")
            self.e(f"{div}.w d6,d7")
            self.e(f"bvs {fault}")
            if signed:
                self.e("move.b d7,d6")
                self.e("ext.w d6")
                self.e("cmp.w d7,d6")
                self.e(f"bne {fault}")
            else:
                self.e("cmp.w #$ff,d7")
                self.e(f"bhi {fault}")
            self.e("move.b d7,d0")
            self.e("swap d7")
            self.e("lsl.w #8,d7")
            self.e("move.b d0,d7")
            self.e("move.w d7,d0")
        else:
            self.e("move.l d2,d7")
            self.e("swap d7")
            self.e("move.w d0,d7")
            self.e("tst.w d6")
            self.e(f"beq {fault}")
            self.e(f"{div}.w d6,d7")
            self.e(f"bvs {fault}")
            self.e("move.w d7,d0")
            self.e("swap d7")
            self.e("move.w d7,d2")
        self.e(f"bra {end}")
        self.at(fault)
        self.exit_fault(0)
        self.at(end)
        self.ccr = set()

    # -- data movement ---------------------------------------------------------
    def op_mov(self):
        i = self.i
        a, b = i.operands
        w = i.width
        pos = i.size - 2 if isinstance(b, Imm) and w == 16 else None
        self.check_reloc({pos} if pos is not None else set())
        if isinstance(a, Reg) and a.name in SEGBASE:
            self.read(b, "d7")
            self.putseg(a.name, "d7")
            return
        if isinstance(b, Reg) and (b.name in SEGBASE or b.name == "cs"):
            self.getseg(b.name, "d6")
            self.write(a, "d6")
            return
        if isinstance(a, Reg):
            if isinstance(b, Imm):
                v = self.imm(b, pos)
                if a.name in HALF or GREG[a.name][0] == "d":
                    if a.name in HALF and HALF[a.name][1]:
                        self.e(f"move.l #{v},d6")
                        self.putreg(a.name, "d6")
                    else:
                        r = GREG[HALF[a.name][0]] if a.name in HALF else GREG[a.name]
                        self.e(f"move.{SZ[w]} #{v},{r}")
                else:
                    self.e(f"move.l #{v},{GREG[a.name]}")
                return
            if isinstance(b, Mem) and (a.name in GREG and GREG[a.name][0] == "d"):
                mem = self.ea(b)
                self.load16(mem, GREG[a.name])
                return
            if isinstance(b, Mem) and a.name in HALF and not HALF[a.name][1]:
                mem = self.ea(b)
                self.e(f"move.b {mem(0)},{GREG[HALF[a.name][0]]}")
                return
            if isinstance(b, Reg) and w == 16 and GREG[a.name][0] == "d":
                self.e(f"move.w {GREG[b.name]},{GREG[a.name]}")
                return
            if isinstance(b, Reg) and w == 16:
                self.e(f"move.l {GREG[b.name]},{GREG[a.name]}")
                return
            self.read(b, "d6")
            self.write(a, "d6")
            return
        # memory destination
        if isinstance(b, Imm):
            mem = self.ea(a)
            v = self.imm(b, pos)
            self.e(f"move.{SZ[w]} #{swap_expr(v) if w == 16 else v},{mem(0)}")
            return
        if w == 8 and b.name in HALF and not HALF[b.name][1]:
            mem = self.ea(a)
            self.e(f"move.b {GREG[HALF[b.name][0]]},{mem(0)}")
            return
        self.read(b, "d6")
        self.write(a, "d6")

    def op_lea(self):
        i = self.i
        r, m = i.operands
        regs = [GREG[x] for x in (m.base, m.index) if x]
        if not regs:
            self.e(f"move.l #{hx(m.disp)},d7")
        else:
            self.e(f"move.l {regs[0]},d7")
            if len(regs) == 2:
                self.e(f"add.w {regs[1]},d7")
            if m.disp:
                self.e(f"add.w #{hx(m.disp)},d7")
        if GREG[r.name][0] == "d":
            self.e(f"move.w d7,{GREG[r.name]}")
        else:
            self.e(f"movea.l d7,{GREG[r.name]}")

    def op_les(self):
        self.lxs("es")

    def op_lds(self):
        self.lxs("ds")

    def far_pair(self, m: Mem) -> None:
        """Far pointer in memory: offset word -> d6, segment word (at offset+2, 64 KiB
        wrap) -> d7; low words valid."""
        regs = [GREG[x] for x in (m.base, m.index) if x]
        base = self.seg_base(m.seg)
        if not regs:
            self.load16(lambda k: f"({hx(m.disp + k)},{base})", "d6")
            seg = (m.disp + 2) & 0xFFFF
            self.load16(lambda k: f"({hx(seg + k)},{base})", "d7")
            return
        self.e(f"move.l {regs[0]},d7")
        if len(regs) == 2:
            self.e(f"add.w {regs[1]},d7")
        if m.disp:
            self.e(f"add.w #{hx(m.disp)},d7")
        self.load16(lambda k: f"{k}({base},d7.l)", "d6")
        self.e("addq.w #2,d7")
        self.load16(lambda k: f"{k}({base},d7.l)", "d7")

    def lxs(self, seg: str) -> None:
        r, m = self.i.operands
        self.far_pair(m)
        self.putreg(r.name, "d6")
        self.putseg(seg, "d7")

    def op_xchg(self):
        a, b = self.i.operands
        w = self.i.width
        if isinstance(a, Reg) and isinstance(b, Reg) and w == 16:
            if a.name != b.name:
                self.e(f"exg {GREG[a.name]},{GREG[b.name]}")
            return
        if isinstance(a, Mem) or isinstance(b, Mem):
            m, r = (a, b) if isinstance(a, Mem) else (b, a)
            self.lea(m)
            self.load_dest(m, "d6")
            self.getreg(r.name, "d7")
            self.store_dest(m, "d7")
            self.putreg(r.name, "d6")
            return
        self.getreg(a.name, "d6")
        self.getreg(b.name, "d7")
        self.putreg(a.name, "d7")
        self.putreg(b.name, "d6")

    def op_push(self):
        o = self.i.operands[0]
        if isinstance(o, Reg) and o.name == "cs":
            self.push(const=self.c.cs)
        elif isinstance(o, Reg) and o.name == "sp":
            self.e("move.l d4,d7")
            self.push("d7")
        elif isinstance(o, Reg) and o.name in GREG and GREG[o.name][0] == "d":
            self.e(f"move.l {GREG[o.name]},d7")
            self.push("d7")
        else:
            self.read(o, "d7")
            self.push("d7")

    def op_pop(self):
        o = self.i.operands[0]
        if isinstance(o, Reg) and o.name in GREG and GREG[o.name][0] == "d":
            self.e("move.w (a2,d4.l),d7")
            self.e("addq.w #2,d4")
            self.e("ror.w #8,d7")
            self.e(f"move.w d7,{GREG[o.name]}")
            return
        self.e("moveq #0,d6")
        self.e("move.w (a2,d4.l),d6")
        self.e("addq.w #2,d4")
        self.e("ror.w #8,d6")
        self.write(o, "d6")

    def op_cbw(self):
        self.e("ext.w d0")

    def op_cwd(self):
        self.e("move.w d0,d2")
        self.e("ext.l d2")
        self.e("clr.w d2")
        self.e("swap d2")

    def op_xlat(self):
        seg = self.i.seg or "ds"
        base = self.seg_base(seg)
        self.e("moveq #0,d7")
        self.e("move.b d0,d7")
        self.e("add.w d3,d7")
        self.e(f"move.b ({base},d7.l),d0")

    def op_nop(self):
        pass

    # -- flags instructions ------------------------------------------------------
    def op_clc(self):
        if "CF" in self.c.need:
            self.e("and.b #$fe,G_FL+1(a6)")

    def op_stc(self):
        if "CF" in self.c.need:
            self.e("or.b #1,G_FL+1(a6)")

    def op_cmc(self):
        if "CF" in self.c.need:
            self.e("eor.b #1,G_FL+1(a6)")

    def op_cld(self):
        self.e("clr.b G_DF(a6)")

    def op_std(self):
        self.e("move.b #1,G_DF(a6)")

    def op_cli(self):
        self.e("clr.b G_IF(a6)")

    def op_sti(self):
        self.e("move.b #1,G_IF(a6)")

    def op_lahf(self):
        self.e("jsr __flags_word")
        self.putreg("ah", "d7")

    def op_sahf(self):
        self.getreg("ah", "d7")
        self.e("jsr __set_flags_lo")

    def op_pushf(self):
        self.e("jsr __flags_word")
        self.push("d7")

    def op_popf(self):
        self.pop("d7")
        self.e("jsr __set_flags")

    def bcd(self):
        self.e(f"jsr __{self.i.op}")

    def op_aam(self):
        v = self.i.operands[0].value
        if v == 0:
            self.exit_fault(0)
            return
        self.e(f"move.l #{hx(v)},d7")
        self.e("jsr __aam")

    def op_aad(self):
        self.e(f"move.l #{hx(self.i.operands[0].value)},d7")
        self.e("jsr __aad")

    # -- ports --------------------------------------------------------------------
    def op_in(self):
        a, port = self.i.operands
        if isinstance(port, Imm):
            self.e(f"move.l #{hx(port.value)},d7")
        else:
            self.e("move.l d2,d7")
        self.e(f"jsr rt_in{self.i.width}")
        if self.i.width == 8:
            self.e("move.b d6,d0")
        else:
            self.e("move.w d6,d0")

    def op_out(self):
        port, a = self.i.operands
        if isinstance(port, Imm):
            self.e(f"move.l #{hx(port.value)},d7")
        else:
            self.e("move.l d2,d7")
        self.e("move.l d0,d6")
        self.e(f"jsr rt_out{self.i.width}")

    # -- string instructions --------------------------------------------------------
    def string(self):
        """One body per direction (DF), step as immediate; REP tests CX before each
        element, REPE/REPNE test ZF after it (ZF then always stored)."""
        i = self.i
        back, end = self.local(), self.local()
        self.e("tst.b G_DF(a6)")
        self.e(f"bne {back}")
        self.string_body(i.width // 8, end)
        self.e(f"bra {end}")
        self.at(back)
        self.string_body(-(i.width // 8), end)
        self.at(end)
        self.ccr = set()

    def string_body(self, step: int, end: str) -> None:
        i = self.i
        op, w = i.op, i.width
        sz = SZ[w]
        src = self.seg_base(i.seg or "ds") if op in ("movs", "cmps", "lods") else None
        add = f"{'addq' if step > 0 else 'subq'}.w #{abs(step)}"
        top = self.local()
        if self.c.vram and op in ("movs", "stos"):
            self.vram_mark_string(step)
        if i.rep:
            self.at(top)
            self.e("tst.w d1")
            self.e(f"beq {end}")
        if op == "movs":
            if w == 8:
                self.e(f"move.b ({src},a4.l),(a1,a5.l)")
            else:
                self.e(f"move.w ({src},a4.l),d7")
                self.e("move.w d7,(a1,a5.l)")
        elif op == "stos":
            if w == 8:
                self.e("move.b d0,(a1,a5.l)")
            else:
                self.e("move.w d0,d7")
                self.store16(lambda k: f"{k}(a1,a5.l)", "d7")
        elif op == "lods":
            if w == 8:
                self.e(f"move.b ({src},a4.l),d0")
            else:
                self.load16(lambda k: f"{k}({src},a4.l)", "d7")
                self.e("move.w d7,d0")
        else:  # cmps scas: d7 - d6
            if op == "cmps":
                self.load_mem(lambda k: f"{k}({src},a4.l)", w, "d7")
            else:
                self.e(f"move.l d0,d7")
            self.load_mem(lambda k: f"{k}(a1,a5.l)", w, "d6")
            need = (self.c.need | ({"ZF"} if i.rep else set())) & FLAG_KINDS["sub"][0]
            if "AF" in need:
                self.e("move.b d7,G_AF(a6)")
                self.e("eor.b d6,G_AF(a6)")
                self.stats["AF store"] += 1
            self.e(f"cmp.{sz} d6,d7")
            saved = self.c.need
            self.c.need = need - {"PF", "AF"}
            self.store_ccr(self.c.need & ALLC, self.kills("sub"))
            self.c.need = saved
            if {"PF", "AF"} & need:
                self.e(f"sub.{sz} d6,d7")
                if "PF" in need:
                    self.e("move.b d7,G_PF(a6)")
                    self.stats["PF store"] += 1
                if "AF" in need:
                    self.e("eor.b d7,G_AF(a6)")
        if op in ("movs", "cmps", "lods"):
            self.e("move.l a4,d7")
            self.e(f"{add},d7")
            self.e("movea.l d7,a4")
        if op in ("movs", "cmps", "stos", "scas"):
            self.e("move.l a5,d7")
            self.e(f"{add},d7")
            self.e("movea.l d7,a5")
        if i.rep:
            self.e("subq.w #1,d1")
            if op in ("cmps", "scas"):
                self.e("btst #2,G_FL+1(a6)")
                self.e(f"{'beq' if i.rep == 'repe' else 'bne'} {end}")
            self.e(f"bra {top}")

    def load_mem(self, mem, w: int, dst: str) -> None:
        if w == 8:
            self.e(f"move.b {mem(0)},{dst}")
        else:
            self.load16(mem, dst)

    # -- control flow ---------------------------------------------------------------
    def goto_near(self, ip: int, how: str = "bra") -> None:
        lab = self.c.near(ip) if self.c.near else None
        if lab:
            self.e(f"{how} {lab}")
        else:
            if self.c.program:
                raise LowerError(f"near target {ip:04X} unresolved")
            self.e(f"move.l #{hx(ip)},d7")
            self.e(f"{'jsr' if how == 'jsr' else 'jmp'} T_{'CALL' if how == 'jsr' else 'JUMP'}")

    def goto_far(self, seg: str, off: int, how: str) -> None:
        lab = self.c.far((seg, off)) if self.c.far else None
        if lab:
            self.e(f"{how} {lab}")
        else:
            if self.c.program:
                raise LowerError(f"far target {seg}:{off:04X} unresolved")
            self.e(f"move.l #{seg},d6")
            self.e(f"move.l #{hx(off)},d7")
            self.e(f"{how} T_{'CALLF' if how == 'jsr' else 'JUMPF'}")

    def return_check(self, ip: int, cs: str | None) -> None:
        if not self.c.program:
            return
        self.e(f"cmp.w #{hx(ip)},d7")
        self.e("bne.l rt_ret_mismatch")  # external: 32-bit displacement
        if cs is not None:
            self.e(f"cmp.w #{cs},d6")
            self.e("bne.l rt_ret_mismatch")  # external: 32-bit displacement
        self.stats["return check"] += 1

    def dispatch_near(self, how: str) -> None:
        """Target IP in d7: compare with the known targets, else the runtime table."""
        done = self.local() if how == "jsr" else None
        for lo, hi, lab in self.c.smc_targets:
            nxt = self.local()
            self.e(f"cmp.w #{hx(lo)},d7")
            self.e(f"blo {nxt}")
            self.e(f"cmp.w #{hx(hi)},d7")
            self.e(f"bhi {nxt}")
            self.e(f"{how} {lab}")
            if done:
                self.e(f"bra {done}")
            self.at(nxt)
        for ip in self.c.near_targets:
            lab = self.c.near(ip) if self.c.near else None
            if not lab:
                continue
            nxt = self.local()
            self.e(f"cmp.w #{hx(ip)},d7")
            self.e(f"bne {nxt}")
            self.e(f"{how} {lab}")
            if done:
                self.e(f"bra {done}")
            self.at(nxt)
        if self.c.program and self.c.complete:
            self.e(f"move.l #{self.c.cs},d6")
            self.e("jmp rt_stop_unknown")  # outside the proved table
            self.stats["stop_unknown site"] += 1
        elif self.c.program:
            self.e(f"move.l #{self.c.cs},d6")
            self.e(f"{how} rt_dispatch_near")
            self.stats["dispatcher exit"] += 1
        else:
            self.e(f"{how} T_{'CALL' if how == 'jsr' else 'JUMP'}")
        if done:
            self.at(done)

    def dispatch_far(self, how: str) -> None:
        """Target CS:IP in d6:d7."""
        done = self.local() if how == "jsr" else None
        for seg, off in self.c.far_targets:
            lab = self.c.far((seg, off)) if self.c.far else None
            if not lab:
                continue
            nxt = self.local()
            self.e(f"cmp.w #{hx(off)},d7")
            self.e(f"bne {nxt}")
            self.e(f"cmp.w #{seg},d6")
            self.e(f"bne {nxt}")
            self.e(f"{how} {lab}")
            if done:
                self.e(f"bra {done}")
            self.at(nxt)
        if self.c.program:
            self.e(f"{how} rt_dispatch_far")
            self.stats["dispatcher exit"] += 1
        else:
            self.e(f"{how} T_{'CALLF' if how == 'jsr' else 'JUMPF'}")
        if done:
            self.at(done)

    def op_jmp(self):
        t = self.i.operands[0]
        if isinstance(t, Rel):
            self.goto_near(t.target)
            return
        self.read(t, "d7")
        self.dispatch_near("jmp")

    def op_call(self):
        i = self.i
        t = i.operands[0]
        if isinstance(t, Rel):
            self.push(const=hx(i.next_ip))
            self.goto_near(t.target, "jsr")
        else:
            self.read(t, "d7")
            self.push(const=hx(i.next_ip))
            self.dispatch_near("jsr")
        self.return_check(i.next_ip, None)

    def far_operand(self) -> tuple[str, int] | None:
        t = self.i.operands[0]
        if isinstance(t, Far):
            self.check_reloc({self.i.size - 2})
            seg = f"LOADSEG+{hx(t.seg)}" if self.reloc_at_end() else hx(t.seg)
            return seg, t.off
        self.check_reloc(set())
        self.far_pair(t)
        self.e("exg d6,d7")
        return None

    def op_jmpf(self):
        f = self.far_operand()
        if self.c.driver_call:
            # D9: the driver's retf comes back here; its outermost return
            # publishes the frame it drew (rt_vdrv_return), then returns to
            # the thunk's caller
            if not f:
                raise LowerError(f"indirect graphics driver thunk {self.i}")
            self.e("addq.w #1,rt_vdrv_depth")
            self.goto_far(f[0], f[1], "jsr")
            self.e("jmp rt_vdrv_return")
            self.stats["graphics driver call"] += 1
            return
        if f:
            self.goto_far(f[0], f[1], "jmp")
        else:
            self.dispatch_far("jmp")

    def op_callf(self):
        i = self.i
        f = self.far_operand()
        self.push(const=self.c.cs)
        self.push(const=hx(i.next_ip))
        ret = i.next_ip + (2 if self.c.manager else 0)  # the manager skips `dw id`
        if f:
            self.goto_far(f[0], f[1], "jsr")
        else:
            self.dispatch_far("jsr")
        self.return_check(ret, self.c.cs)

    def op_jcc(self):
        t = self.i.operands[0].target
        lab = self.c.near(t) if self.c.near else None
        if lab:
            self.branch_cc(self.i.cc, lab)
        else:
            if self.c.program:
                raise LowerError(f"jcc target {t:04X} unresolved")
            go = self.local()
            nxt = self.local()
            self.branch_cc(self.i.cc, go)
            self.e(f"bra {nxt}")
            self.at(go)
            self.goto_near(t)
            self.at(nxt)
        self.ccr = set()

    def loopish(self, cond: str | None) -> None:
        t = self.i.operands[0].target
        lab = (self.c.near(t) if self.c.near else None) or self.local()
        far = not (self.c.near and self.c.near(t))
        nxt = self.local()
        if self.i.op == "jcxz":
            self.e("tst.w d1")
            self.e(f"beq {lab}")
        else:
            if cond:
                if "ZF" in self.c.ccr_in:
                    self.e(f"s{'eq' if cond == 'e' else 'ne'} d7")
                else:
                    self.e("btst #2,G_FL+1(a6)")
                    self.e(f"s{'ne' if cond == 'e' else 'eq'} d7")
                    self.stats["flag load"] += 1
            self.e("subq.w #1,d1")
            if cond:
                self.e(f"beq {nxt}")
                self.e("tst.b d7")
                self.e(f"bne {lab}")
            else:
                self.e(f"bne {lab}")
        if far:
            self.e(f"bra {nxt}")
            self.at(lab)
            self.goto_near(t)
        self.at(nxt)
        self.ccr = set()

    def op_loop(self):
        self.loopish(None)

    def op_loope(self):
        self.loopish("e")

    def op_loopne(self):
        self.loopish("ne")

    def op_jcxz(self):
        self.loopish(None)

    def op_ret(self):
        self.ret(far=False)

    def op_retf(self):
        self.ret(far=True)

    def ret(self, far: bool) -> None:
        i = self.i
        self.e("moveq #0,d7")
        self.pop("d7")
        if far:
            self.e("moveq #0,d6")
            self.pop("d6")
        if i.operands:
            self.e(f"add.w #{hx(i.operands[0].value)},d4")
        self.e("rts")

    def op_iret(self):
        # flags word at SS:SP+4 first (d6/d7 then carry IP and CS)
        self.e("move.l d4,d7")
        self.e("addq.w #4,d7")
        self.e("move.w (a2,d7.l),d7")
        self.e("ror.w #8,d7")
        self.e("jsr __set_flags")
        self.e("moveq #0,d7")
        self.pop("d7")
        self.e("moveq #0,d6")
        self.pop("d6")
        self.e("addq.w #2,d4")
        self.e("rts")

    def op_int(self):
        self.interrupt(self.i.operands[0].value)

    def op_int3(self):
        self.interrupt(3)

    def vector(self, vec: int) -> str:
        """d6 operand: the vector, in program mode with CS in the upper word."""
        return f"#(({self.c.cs})<<16)|{hx(vec)}" if self.c.program else f"#{hx(vec)}"

    def interrupt(self, vec: int) -> None:
        self.e(f"move.l #{hx(self.i.next_ip)},d7")
        self.e(f"move.l {self.vector(vec)},d6")
        self.e("jsr rt_int" if self.c.program else "jmp T_INT")

    def op_into(self):
        nxt = self.local()
        self.load_ccr({"OF"})
        self.e(f"bvc {nxt}")
        self.interrupt(4)
        self.at(nxt)
        self.ccr = set()

    def exit_fault(self, vec: int) -> None:
        self.e(f"move.l #{hx(self.i.ip)},d7")
        self.e(f"move.l {self.vector(vec)},d6")
        if self.c.program:
            self.e("jsr rt_fault")
            self.e(f"bra {self.c.label}")
        else:
            self.e("jmp T_FAULT")

    def op_hlt(self):
        self.e(f"move.l #{hx(self.i.next_ip)},d7")
        self.e("jsr rt_halt" if self.c.program else "jmp T_HALT")


# Vectors the game installs handlers for (docs/external-surface.md); every other
# software interrupt is a runtime service, which reads no guest flags and leaves
# those it does not define unchanged in the state block.
GUEST_VECTORS = {0x00, 0x05, 0x08, 0x23, 0x24}


def reads(i: Insn, program: bool = False) -> set:
    """Status flags an instruction reads (for liveness and fusion). Test mode
    (`program` false) treats every interrupt/fault exit as reading all flags (the
    harness compares them); program mode applies the runtime contract and leaves
    the divide-error path to an explicit successor (emit.py)."""
    op = i.op
    if program:
        if op == "int":
            return set(STATUS) if i.operands[0].value in GUEST_VECTORS else set()
        if op in ("int3", "hlt", "div", "idiv") or op == "aam" and i.operands[0].value == 0:
            return set()
    if op == "jcc":
        return set(CC_READS[i.cc])
    if op in ("adc", "sbb", "rcl", "rcr", "cmc"):
        return {"CF"}
    if op in ("loope", "loopne"):
        return {"ZF"}
    if op == "into":
        return {"OF"}
    if op in ("daa", "das"):
        return {"CF", "AF"}
    if op in ("aaa", "aas"):
        return {"AF"}
    if op in ("lahf", "pushf", "int", "int3", "hlt"):
        return set(STATUS)
    if op in ("div", "idiv") or op == "aam" and i.operands[0].value == 0:
        return set(STATUS)  # divide error: the handler sees FLAGS
    return set()


STRING_OPS = ("movs", "cmps", "stos", "lods", "scas")
DEST_WRITERS = ("mov", "add", "adc", "sub", "sbb", "and", "or", "xor", "inc", "dec", "neg", "not",
                "rol", "ror", "rcl", "rcr", "shl", "shr", "sar", "pop")


def mem_dests(i: Insn) -> list:
    """Explicit memory operands an instruction writes (string and stack stores aside)."""
    ops = i.operands
    if i.op == "xchg":
        return [o for o in ops if isinstance(o, Mem)]
    if i.op in DEST_WRITERS and ops and isinstance(ops[0], Mem):
        return [ops[0]]
    return []


def fuse_reader(i: Insn) -> bool:
    """Readers that take flags straight from the CCR left by the previous instruction."""
    if i.op == "jcc":
        return i.cc not in ("p", "np")
    return i.op in ("loope", "loopne")


def writes(i: Insn) -> tuple[set, set]:
    """(must-kill, may-define) status flags."""
    op = i.op
    k = None
    if op in ("add", "adc", "sub", "sbb", "cmp", "neg", "inc", "dec"):
        k = {"cmp": "sub"}.get(op, op)
    elif op in ("and", "or", "xor", "test"):
        k = "logic"
    elif op in ("mul", "imul", "div", "idiv"):
        k = {"idiv": "div"}.get(op, op)
    elif op in ("cmps", "scas"):
        d = set(STATUS)
        return (d, d) if not i.rep else (set(), d)
    elif op in ("rol", "ror", "rcl", "rcr", "shl", "shr", "sar"):
        d, u = FLAG_KINDS[op]
        allk = set(d) | set(u)
        return (allk, allk) if isinstance(i.operands[1], Imm) else (set(), allk)
    elif op in ("popf", "sahf", "iret", "daa", "das", "aaa", "aas", "aad") or \
            op == "aam" and i.operands[0].value:
        d = set(STATUS) - ({"OF"} if op == "sahf" else set())
        return d, d
    elif op in ("clc", "stc", "cmc"):
        return {"CF"}, {"CF"}
    if k is None:
        return set(), set()
    d, u = FLAG_KINDS[k]
    return set(d) | set(u), set(d) | set(u)


def lower(insn: Insn, ctx: Ctx) -> Lowering:
    lw = Lowering(insn, ctx)
    lw.run()
    return lw
