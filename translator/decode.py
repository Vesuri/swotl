"""Table-driven 8086 real-mode decoder (D13: own decoder, Capstone cross-check in tests).

Scope: the 8086 instruction set as executed by a 286/386 in real mode. The
classified SWOTL code uses no 186+ opcodes (no 0Fh, C0h/C1h, 68h/6Ah, C8h/C9h)
and no ESC/WAIT/LOCK; those, the 60h–6Fh range, `pop cs`, `mov cs` and the
undefined group aliases raise DecodeError, so they fail loudly.
"""

from __future__ import annotations

from dataclasses import dataclass


class DecodeError(Exception):
    pass


R16 = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
R8 = ("al", "cl", "dl", "bl", "ah", "ch", "dh", "bh")
SREG = ("es", "cs", "ss", "ds")
EA = (("bx", "si"), ("bx", "di"), ("bp", "si"), ("bp", "di"), ("si", None), ("di", None),
      ("bp", None), ("bx", None))
CC = ("o", "no", "b", "ae", "e", "ne", "be", "a", "s", "ns", "p", "np", "l", "ge", "le", "g")
ALU = ("add", "or", "adc", "sbb", "and", "sub", "xor", "cmp")
SHIFT = ("rol", "ror", "rcl", "rcr", "shl", "shr", None, "sar")
PREFIX_SEG = {0x26: "es", 0x2E: "cs", 0x36: "ss", 0x3E: "ds"}


@dataclass(frozen=True)
class Reg:
    name: str

    @property
    def width(self) -> int:
        return 8 if self.name in R8 else 16

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Imm:
    value: int
    width: int

    def __str__(self) -> str:
        return f"0x{self.value:x}"


@dataclass(frozen=True)
class Mem:
    width: int              # 8, 16, or 32 (far pointer)
    seg: str                # effective segment
    base: str | None
    index: str | None
    disp: int               # 16-bit
    override: bool = False

    def __str__(self) -> str:
        parts = [r for r in (self.base, self.index) if r]
        if self.disp or not parts:
            parts.append(f"0x{self.disp:x}")
        size = {8: "byte", 16: "word", 32: "dword"}[self.width]
        return f"{size} {self.seg}:[{'+'.join(parts)}]"


@dataclass(frozen=True)
class Far:
    seg: int
    off: int

    def __str__(self) -> str:
        return f"0x{self.seg:x}:0x{self.off:x}"


@dataclass(frozen=True)
class Rel:
    target: int             # target IP (16-bit, same CS)

    def __str__(self) -> str:
        return f"0x{self.target:x}"


Operand = Reg | Imm | Mem | Far | Rel


@dataclass(frozen=True)
class Insn:
    ip: int
    size: int
    raw: bytes
    op: str                 # canonical mnemonic: add, jcc, movs, call, callf, ...
    width: int              # operand width (8/16); 0 when none
    operands: tuple = ()
    cc: str | None = None   # condition for jcc
    rep: str | None = None  # rep, repe, repne (F3/F2 as written)
    seg: str | None = None  # segment override prefix

    @property
    def next_ip(self) -> int:
        return (self.ip + self.size) & 0xFFFF

    def __str__(self) -> str:
        name = f"j{self.cc}" if self.op == "jcc" else self.op
        if self.op in ("movs", "cmps", "stos", "lods", "scas"):
            name += "b" if self.width == 8 else "w"
        if self.rep:
            name = f"{self.rep} {name}"
        return f"{name} {', '.join(map(str, self.operands))}".rstrip()


class _Reader:
    def __init__(self, code: bytes, pos: int):
        self.code, self.pos = code, pos

    def u8(self) -> int:
        if self.pos >= len(self.code):
            raise DecodeError("truncated")
        v = self.code[self.pos]
        self.pos += 1
        return v

    def s8(self) -> int:
        v = self.u8()
        return v - 256 if v & 0x80 else v

    def u16(self) -> int:
        lo = self.u8()
        return lo | self.u8() << 8


def _modrm(r: _Reader, width: int, seg: str | None):
    """Return (mod, reg, operand) for a ModRM byte; operand is Reg or Mem."""
    b = r.u8()
    mod, reg, rm = b >> 6, (b >> 3) & 7, b & 7
    if mod == 3:
        return mod, reg, Reg((R8 if width == 8 else R16)[rm])
    if mod == 0 and rm == 6:
        base, index, disp = None, None, r.u16()
    else:
        base, index = EA[rm]
        disp = 0 if mod == 0 else (r.s8() & 0xFFFF) if mod == 1 else r.u16()
    default = "ss" if base == "bp" else "ds"
    return mod, reg, Mem(width, seg or default, base, index, disp, seg is not None)


def decode(code: bytes, ip: int, pos: int = 0) -> Insn:
    """Decode one instruction from code[pos:] at guest IP `ip`."""
    r = _Reader(code, pos)
    seg = rep = None
    while True:
        b = r.u8()
        if b in PREFIX_SEG:
            seg = PREFIX_SEG[b]
        elif b == 0xF3:
            rep = "rep"
        elif b == 0xF2:
            rep = "repne"
        else:
            break
        if r.pos - pos > 8:
            raise DecodeError("prefix run")

    def mk(op, width=0, operands=(), cc=None):
        size = r.pos - pos
        string = op in ("movs", "cmps", "stos", "lods", "scas")
        rp = rep
        if rp and not string:
            raise DecodeError(f"rep prefix on {op}")
        if rp == "rep" and op in ("cmps", "scas"):
            rp = "repe"
        return Insn(ip & 0xFFFF, size, bytes(code[pos:r.pos]), op, width, tuple(operands), cc, rp, seg)

    def rel(n):
        return Rel((ip + (r.pos - pos) + n) & 0xFFFF)

    def gpr(i, w):
        return Reg((R8 if w == 8 else R16)[i])

    if b < 0x40 and (b & 7) < 6:  # ALU block
        op, form = ALU[b >> 3], b & 7
        w = 8 if form in (0, 2, 4) else 16
        if form < 4:
            _, reg, rm = _modrm(r, w, seg)
            ops = (rm, gpr(reg, w)) if form < 2 else (gpr(reg, w), rm)
            return mk(op, w, ops)
        return mk(op, w, (gpr(0, w), Imm(r.u8() if w == 8 else r.u16(), w)))
    if b in (0x06, 0x0E, 0x16, 0x1E):
        return mk("push", 16, (Reg(SREG[b >> 3]),))
    if b in (0x07, 0x17, 0x1F):
        return mk("pop", 16, (Reg(SREG[b >> 3]),))
    if b in (0x27, 0x2F, 0x37, 0x3F):
        return mk({0x27: "daa", 0x2F: "das", 0x37: "aaa", 0x3F: "aas"}[b], 8)
    if 0x40 <= b < 0x50:
        return mk("inc" if b < 0x48 else "dec", 16, (gpr(b & 7, 16),))
    if 0x50 <= b < 0x60:
        return mk("push" if b < 0x58 else "pop", 16, (gpr(b & 7, 16),))
    if 0x70 <= b < 0x80:
        n = r.s8()
        return mk("jcc", 0, (rel(n),), CC[b & 15])
    if b in (0x80, 0x81, 0x82, 0x83):
        w = 8 if b in (0x80, 0x82) else 16
        _, reg, rm = _modrm(r, w, seg)
        imm = r.u16() if b == 0x81 else (r.s8() & 0xFFFF if b == 0x83 else r.u8())
        return mk(ALU[reg], w, (rm, Imm(imm, w)))
    if b in (0x84, 0x85, 0x86, 0x87):
        w = 8 if b in (0x84, 0x86) else 16
        _, reg, rm = _modrm(r, w, seg)
        return mk("test" if b < 0x86 else "xchg", w, (rm, gpr(reg, w)))
    if 0x88 <= b <= 0x8B:
        w = 8 if b in (0x88, 0x8A) else 16
        _, reg, rm = _modrm(r, w, seg)
        return mk("mov", w, (rm, gpr(reg, w)) if b < 0x8A else (gpr(reg, w), rm))
    if b in (0x8C, 0x8E):
        _, reg, rm = _modrm(r, 16, seg)
        if reg > 3 or (b == 0x8E and reg == 1):
            raise DecodeError(f"{b:02X} sreg {reg}")
        return mk("mov", 16, (rm, Reg(SREG[reg])) if b == 0x8C else (Reg(SREG[reg]), rm))
    if b == 0x8D:
        mod, reg, rm = _modrm(r, 16, seg)
        if mod == 3:
            raise DecodeError("lea with register")
        return mk("lea", 16, (gpr(reg, 16), rm))
    if b == 0x8F:
        _, reg, rm = _modrm(r, 16, seg)
        if reg:
            raise DecodeError("8F /r")
        return mk("pop", 16, (rm,))
    if b == 0x90:
        return mk("nop")
    if 0x91 <= b <= 0x97:
        return mk("xchg", 16, (gpr(b & 7, 16), Reg("ax")))
    simple = {0x98: ("cbw", 8), 0x99: ("cwd", 16), 0x9C: ("pushf", 16), 0x9D: ("popf", 16),
              0x9E: ("sahf", 8), 0x9F: ("lahf", 8), 0xC3: ("ret", 0), 0xCB: ("retf", 0),
              0xCC: ("int3", 0), 0xCE: ("into", 0), 0xCF: ("iret", 0), 0xD7: ("xlat", 8),
              0xF4: ("hlt", 0), 0xF5: ("cmc", 0), 0xF8: ("clc", 0), 0xF9: ("stc", 0),
              0xFA: ("cli", 0), 0xFB: ("sti", 0), 0xFC: ("cld", 0), 0xFD: ("std", 0)}
    if b in simple:
        op, w = simple[b]
        return mk(op, w)
    if b in (0x9A, 0xEA):
        off = r.u16()
        return mk("callf" if b == 0x9A else "jmpf", 0, (Far(r.u16(), off),))
    if 0xA0 <= b <= 0xA3:
        w = 8 if b in (0xA0, 0xA2) else 16
        m = Mem(w, seg or "ds", None, None, r.u16(), seg is not None)
        return mk("mov", w, (gpr(0, w), m) if b < 0xA2 else (m, gpr(0, w)))
    if b in (0xA8, 0xA9):
        w = 8 if b == 0xA8 else 16
        return mk("test", w, (gpr(0, w), Imm(r.u8() if w == 8 else r.u16(), w)))
    if 0xA4 <= b <= 0xAF:
        op = {0xA4: "movs", 0xA6: "cmps", 0xAA: "stos", 0xAC: "lods", 0xAE: "scas"}[b & ~1]
        return mk(op, 8 if b % 2 == 0 else 16)
    if 0xB0 <= b < 0xC0:
        w = 8 if b < 0xB8 else 16
        return mk("mov", w, (gpr(b & 7, w), Imm(r.u8() if w == 8 else r.u16(), w)))
    if b in (0xC2, 0xCA):
        return mk("ret" if b == 0xC2 else "retf", 0, (Imm(r.u16(), 16),))
    if b in (0xC4, 0xC5):
        mod, reg, rm = _modrm(r, 32, seg)
        if mod == 3:
            raise DecodeError("les/lds with register")
        return mk("les" if b == 0xC4 else "lds", 16, (gpr(reg, 16), rm))
    if b in (0xC6, 0xC7):
        w = 8 if b == 0xC6 else 16
        _, reg, rm = _modrm(r, w, seg)
        if reg:
            raise DecodeError(f"{b:02X} /{reg}")
        return mk("mov", w, (rm, Imm(r.u8() if w == 8 else r.u16(), w)))
    if b == 0xCD:
        return mk("int", 0, (Imm(r.u8(), 8),))
    if 0xD0 <= b <= 0xD3:
        w = 8 if b in (0xD0, 0xD2) else 16
        _, reg, rm = _modrm(r, w, seg)
        if SHIFT[reg] is None:
            raise DecodeError("shift /6")
        return mk(SHIFT[reg], w, (rm, Imm(1, 8) if b < 0xD2 else Reg("cl")))
    if b in (0xD4, 0xD5):
        return mk("aam" if b == 0xD4 else "aad", 8, (Imm(r.u8(), 8),))
    if 0xE0 <= b <= 0xE3:
        n = r.s8()
        return mk(("loopne", "loope", "loop", "jcxz")[b - 0xE0], 0, (rel(n),))
    if b in (0xE4, 0xE5, 0xEC, 0xED):
        w = 8 if b in (0xE4, 0xEC) else 16
        port = Imm(r.u8(), 8) if b < 0xEC else Reg("dx")
        return mk("in", w, (gpr(0, w), port))
    if b in (0xE6, 0xE7, 0xEE, 0xEF):
        w = 8 if b in (0xE6, 0xEE) else 16
        port = Imm(r.u8(), 8) if b < 0xEE else Reg("dx")
        return mk("out", w, (port, gpr(0, w)))
    if b == 0xE8:
        n = r.u16()
        return mk("call", 0, (rel(n),))
    if b == 0xE9:
        n = r.u16()
        return mk("jmp", 0, (rel(n),))
    if b == 0xEB:
        n = r.s8()
        return mk("jmp", 0, (rel(n),))
    if b in (0xF6, 0xF7):
        w = 8 if b == 0xF6 else 16
        _, reg, rm = _modrm(r, w, seg)
        if reg == 1:
            raise DecodeError("F6/F7 /1")
        if reg == 0:
            return mk("test", w, (rm, Imm(r.u8() if w == 8 else r.u16(), w)))
        return mk(("", "", "not", "neg", "mul", "imul", "div", "idiv")[reg], w, (rm,))
    if b == 0xFE:
        _, reg, rm = _modrm(r, 8, seg)
        if reg > 1:
            raise DecodeError(f"FE /{reg}")
        return mk("inc" if reg == 0 else "dec", 8, (rm,))
    if b == 0xFF:
        save = r.pos
        _, reg, _ = _modrm(r, 16, seg)
        r.pos = save
        far = reg in (3, 5)
        mod, reg, rm = _modrm(r, 32 if far else 16, seg)
        if reg == 7 or (far and mod == 3):
            raise DecodeError(f"FF /{reg}")
        op = ("inc", "dec", "call", "callf", "jmp", "jmpf", "push")[reg]
        return mk(op, 16, (rm,))
    raise DecodeError(f"opcode {b:02X}")

