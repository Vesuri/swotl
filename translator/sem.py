"""Lift a decoded 8086 instruction to IR (translator/ir.py).

Real-mode semantics as executed by a 386 in real mode (the reference
DOSBox-X cputype): shift and rotate counts masked to 5 bits, `push sp`
pushes the value before the decrement, `pop sp` loads the popped value,
IDIV accepts the most negative quotient, divide errors fault before any
register changes with IP at the instruction. Effective offsets wrap at 64
KiB; a word access is two consecutive linear bytes (no wrap inside the word).
"""

from __future__ import annotations

from .decode import Far, Imm, Insn, Mem, Reg, Rel
from .ir import Op, T

STRING = ("movs", "cmps", "stos", "lods", "scas")


class LiftError(Exception):
    pass


class _B:
    def __init__(self, insn: Insn):
        self.i = insn
        self.ops: list[Op] = []
        self.n = 0
        self.nl = 0

    # -- emission ---------------------------------------------------------
    def v(self, op, w, *args) -> T:
        self.n += 1
        t = T(self.n, w)
        self.ops.append(Op(op, t, args))
        return t

    def e(self, op, *args) -> None:
        self.ops.append(Op(op, None, args))

    def label(self) -> str:
        self.nl += 1
        return f"L{self.nl}"

    def at(self, label: str) -> None:
        self.e("label", label)

    # -- operands ---------------------------------------------------------
    def get(self, r: str) -> T:
        return self.v("get", Reg(r).width, r)

    def ea(self, m: Mem, seg: bool = True) -> tuple[T | None, T | int]:
        seg = self.get(m.seg) if seg else None
        parts = [self.get(r) for r in (m.base, m.index) if r]
        if not parts:
            return seg, m.disp
        off = parts[0]
        if len(parts) == 2:
            off = self.v("add", 16, off, parts[1])
        if m.disp:
            off = self.v("add", 16, off, m.disp)
        return seg, off

    def read(self, o, w: int | None = None):
        if isinstance(o, Reg):
            return self.get(o.name)
        if isinstance(o, Imm):
            return o.value
        if isinstance(o, Mem):
            seg, off = self.ea(o)
            return self.v("load", w or o.width, seg, off)
        raise LiftError(f"read {o!r}")

    def write(self, o, val) -> None:
        if isinstance(o, Reg):
            self.e("put", o.name, val)
        elif isinstance(o, Mem):
            seg, off = self.ea(o)
            self.e("store", seg, off, val, o.width)
        else:
            raise LiftError(f"write {o!r}")

    def far_ptr(self, m: Mem) -> tuple[T, T]:
        seg, off = self.ea(m)
        lo = self.v("load", 16, seg, off)
        hi = self.v("load", 16, seg, self.v("add", 16, off, 2))
        return hi, lo

    def push(self, val) -> None:
        sp = self.v("sub", 16, self.get("sp"), 2)
        self.e("put", "sp", sp)
        self.e("store", self.get("ss"), sp, val, 16)

    def pop(self) -> T:
        sp = self.get("sp")
        val = self.v("load", 16, self.get("ss"), sp)
        self.e("put", "sp", self.v("add", 16, sp, 2))
        return val

    def flags_word(self) -> T:
        word = self.get("flagsx")  # bits 12-15 as the CPU keeps them
        word = self.v("or", 16, word, 2)
        for f, bit in (("CF", 0), ("PF", 2), ("AF", 4), ("ZF", 6), ("SF", 7), ("TF", 8),
                       ("IF", 9), ("DF", 10), ("OF", 11)):
            b = self.v("zext", 16, self.v("flag", 1, f))
            word = self.v("or", 16, word, self.v("shl", 16, b, bit) if bit else b)
        return word

    def set_flags_word(self, word, names) -> None:
        for f, bit in (("CF", 0), ("PF", 2), ("AF", 4), ("ZF", 6), ("SF", 7), ("TF", 8),
                       ("IF", 9), ("DF", 10), ("OF", 11)):
            if f in names:
                self.e("setflag", f, self.v("trunc", 1, self.v("shr", word.w, word, bit)))
        if word.w == 16:
            self.e("put", "flagsx", self.v("and", 16, word, 0x7000))


ALL_FLAGS = ("CF", "PF", "AF", "ZF", "SF", "TF", "IF", "DF", "OF")


def lift(i: Insn) -> list[Op]:
    b = _B(i)
    op, w, ops = i.op, i.width, i.operands
    acc = "al" if w == 8 else "ax"

    if op in ("add", "adc", "sub", "sbb", "cmp", "and", "or", "xor", "test"):
        x = b.read(ops[0])
        y = b.read(ops[1])
        if op in ("adc", "sbb"):
            c = b.v("zext", w, b.v("flag", 1, "CF"))
            r = b.v("add" if op == "adc" else "sub", w, b.v("add" if op == "adc" else "sub", w, x, y), c)
            b.e("flags", op, w, x, y, r, c)
        elif op in ("add", "sub", "cmp"):
            r = b.v("sub" if op == "cmp" else op, w, x, y)
            b.e("flags", "add" if op == "add" else "sub", w, x, y, r)
        else:
            r = b.v("and" if op == "test" else op, w, x, y)
            b.e("flags", "logic", w, x, y, r)
        if op not in ("cmp", "test"):
            b.write(ops[0], r)
    elif op in ("inc", "dec"):
        x = b.read(ops[0])
        r = b.v("add" if op == "inc" else "sub", w, x, 1)
        b.e("flags", op, w, x, 1, r)
        b.write(ops[0], r)
    elif op == "neg":
        x = b.read(ops[0])
        r = b.v("neg", w, x)
        b.e("flags", "neg", w, 0, x, r)
        b.write(ops[0], r)
    elif op == "not":
        b.write(ops[0], b.v("not", w, b.read(ops[0])))
    elif op in ("mul", "imul"):
        ext = "zext" if op == "mul" else "sext"
        x = b.get(acc)
        y = b.read(ops[0])
        p = b.v("mul", 2 * w, b.v(ext, 2 * w, x), b.v(ext, 2 * w, y))
        if w == 8:
            b.e("put", "ax", p)
        else:
            b.e("put", "ax", b.v("trunc", 16, p))
            b.e("put", "dx", b.v("trunc", 16, b.v("shr", 32, p, 16)))
        b.e("flags", op, w, x, y, p)
    elif op in ("div", "idiv"):
        signed = op == "idiv"
        ext = "sext" if signed else "zext"
        y = b.read(ops[0])
        if w == 8:
            n = b.get("ax")
        else:
            hi = b.v("shl", 32, b.v("zext", 32, b.get("dx")), 16)
            n = b.v("or", 32, hi, b.v("zext", 32, b.get("ax")))
        d = b.v(ext, 2 * w, y)
        fault, end = b.label(), b.label()
        b.e("br", b.v("eq", 1, y, 0), fault)
        q = b.v("sdiv" if signed else "udiv", 2 * w, n, d)
        if signed:
            fits = b.v("eq", 1, b.v("sext", 2 * w, b.v("trunc", w, q)), q)
            b.e("br", b.v("eq", 1, fits, 0), fault)
        else:
            b.e("br", b.v("ltu", 1, (1 << w) - 1, q), fault)
        r = b.v("srem" if signed else "urem", w, n, d)
        if w == 8:
            b.e("put", "al", b.v("trunc", 8, q))
            b.e("put", "ah", r)
        else:
            b.e("put", "ax", b.v("trunc", 16, q))
            b.e("put", "dx", r)
        b.e("flags", "div", w, n, d, q)
        b.e("goto", end)
        b.at(fault)
        b.e("fault", 0)
        b.at(end)
    elif op in ("rol", "ror", "rcl", "rcr", "shl", "shr", "sar"):
        x = b.read(ops[0])
        end = None
        if isinstance(ops[1], Imm):
            n = ops[1].value
        else:
            n = b.v("and", 8, b.get("cl"), 0x1F)
            end = b.label()
            b.e("br", b.v("eq", 1, n, 0), end)
        if op in ("rcl", "rcr"):
            c = b.v("flag", 1, "CF")
            r = b.v(op, w, x, n, c)
            b.e("flags", op, w, x, n, r, c)
        else:
            r = b.v(op, w, x, n)
            b.e("flags", op, w, x, n, r)
        b.write(ops[0], r)
        if end:
            b.at(end)
    elif op in STRING:
        string(b, i)
    elif op == "mov":
        b.write(ops[0], b.read(ops[1]))
    elif op == "lea":
        _, off = b.ea(ops[1], seg=False)
        b.e("put", ops[0].name, off)
    elif op in ("les", "lds"):
        hi, lo = b.far_ptr(ops[1])
        b.e("put", ops[0].name, lo)
        b.e("put", "es" if op == "les" else "ds", hi)
    elif op == "xchg":
        x, y = b.read(ops[0]), b.read(ops[1])
        b.write(ops[0], y)
        b.write(ops[1], x)
    elif op == "push":
        b.push(b.read(ops[0]))
    elif op == "pop":
        b.write(ops[0], b.pop())
    elif op == "cbw":
        b.e("put", "ax", b.v("sext", 16, b.get("al")))
    elif op == "cwd":
        b.e("put", "dx", b.v("sar", 16, b.get("ax"), 15))
    elif op == "lahf":
        ah = b.v("const", 8, 2)
        for f, bit in (("CF", 0), ("PF", 2), ("AF", 4), ("ZF", 6), ("SF", 7)):
            x = b.v("zext", 8, b.v("flag", 1, f))
            ah = b.v("or", 8, ah, b.v("shl", 8, x, bit) if bit else x)
        b.e("put", "ah", ah)
    elif op == "sahf":
        b.set_flags_word(b.get("ah"), ("CF", "PF", "AF", "ZF", "SF"))
    elif op == "pushf":
        b.push(b.flags_word())
    elif op == "popf":
        b.set_flags_word(b.pop(), ALL_FLAGS)
    elif op in ("clc", "stc", "cli", "sti", "cld", "std"):
        b.e("setflag", {"c": "CF", "i": "IF", "d": "DF"}[op[2]], 1 if op[0] == "s" else 0)
    elif op == "cmc":
        b.e("setflag", "CF", b.v("xor", 1, b.v("flag", 1, "CF"), 1))
    elif op == "nop":
        pass
    elif op == "xlat":
        seg = b.get(i.seg or "ds")
        off = b.v("add", 16, b.get("bx"), b.v("zext", 16, b.get("al")))
        b.e("put", "al", b.v("load", 8, seg, off))
    elif op == "in":
        port = b.read(ops[1])
        b.e("put", ops[0].name, b.v("in", w, port))
    elif op == "out":
        port = b.read(ops[0])
        b.e("out", port, b.get(ops[1].name))
    elif op in ("daa", "das", "aaa", "aas"):
        b.e("bcd", op)
    elif op in ("aam", "aad"):
        if op == "aam" and ops[0].value == 0:
            b.e("fault", 0)
        else:
            b.e("bcd", op, ops[0].value)
    elif op in ("int", "int3"):
        b.e("int", ops[0].value if op == "int" else 3, i.next_ip)
    elif op == "into":
        go, end = b.label(), b.label()
        b.e("br", b.v("flag", 1, "OF"), go)
        b.e("goto", end)
        b.at(go)
        b.e("int", 4, i.next_ip)
        b.at(end)
    elif op == "iret":
        ip = b.pop()
        cs = b.pop()
        b.set_flags_word(b.pop(), ALL_FLAGS)
        b.e("iret", cs, ip)
    elif op in ("ret", "retf"):
        ip = b.pop()
        cs = b.pop() if op == "retf" else None
        if ops:
            b.e("put", "sp", b.v("add", 16, b.get("sp"), ops[0].value))
        if cs is None:
            b.e("ret", ip)
        else:
            b.e("retf", cs, ip)
    elif op in ("jmp", "call"):
        if isinstance(ops[0], Rel):
            target = ops[0].target
        else:
            target = b.read(ops[0])
        if op == "call":
            b.push(i.next_ip)
        b.e("jump" if op == "jmp" else "call", target)
    elif op in ("jmpf", "callf"):
        if isinstance(ops[0], Far):
            seg, off = ops[0].seg, ops[0].off
        else:
            seg, off = b.far_ptr(ops[0])
        if op == "callf":
            b.push(b.get("cs"))
            b.push(i.next_ip)
        b.e("jumpf" if op == "jmpf" else "callf", seg, off)
    elif op in ("jcc", "loop", "loope", "loopne", "jcxz"):
        if op == "jcc":
            c = b.v("cond", 1, i.cc)
        elif op == "jcxz":
            c = b.v("eq", 1, b.get("cx"), 0)
        else:
            cx = b.v("sub", 16, b.get("cx"), 1)
            b.e("put", "cx", cx)
            c = b.v("ne", 1, cx, 0)
            if op != "loop":
                z = b.v("flag", 1, "ZF")
                if op == "loopne":
                    z = b.v("xor", 1, z, 1)
                c = b.v("and", 1, c, z)
        go, end = b.label(), b.label()
        b.e("br", c, go)
        b.e("goto", end)
        b.at(go)
        b.e("jump", ops[0].target)
        b.at(end)
    elif op == "hlt":
        b.e("halt")
    else:
        raise LiftError(f"no semantics for {i}")
    return b.ops


def string(b: _B, i: Insn) -> None:
    """One element per iteration; REP checks CX before each, REPE/REPNE stop on ZF after."""
    w, op = i.width, i.op
    k = w // 8
    src = i.seg or "ds"
    top = end = None
    if i.rep:
        top, end = b.label(), b.label()
        b.at(top)
        b.e("br", b.v("eq", 1, b.get("cx"), 0), end)
    step = b.v("select", 16, b.v("flag", 1, "DF"), (-k) & 0xFFFF, k)
    if op in ("movs", "cmps", "lods"):
        si = b.get("si")
        x = b.v("load", w, b.get(src), si)
        b.e("put", "si", b.v("add", 16, si, step))
    if op in ("movs", "stos", "cmps", "scas"):
        di = b.get("di")
        if op == "movs":
            b.e("store", b.get("es"), di, x, w)
        elif op == "stos":
            b.e("store", b.get("es"), di, b.get("al" if w == 8 else "ax"), w)
        else:
            y = b.v("load", w, b.get("es"), di)
            a = x if op == "cmps" else b.get("al" if w == 8 else "ax")
            b.e("flags", "sub", w, a, y, b.v("sub", w, a, y))
        b.e("put", "di", b.v("add", 16, di, step))
    if op == "lods":
        b.e("put", "al" if w == 8 else "ax", x)
    if i.rep:
        b.e("put", "cx", b.v("sub", 16, b.get("cx"), 1))
        if op in ("cmps", "scas"):
            z = b.v("flag", 1, "ZF")
            # repe stops when ZF = 0, repne when ZF = 1
            b.e("br", b.v("eq", 1, z, 0 if i.rep == "repe" else 1), end)
        b.e("goto", top)
        b.at(end)
