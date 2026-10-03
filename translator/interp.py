"""Host interpreter for the IR: the semantics under test in the x86 differential.

Guest RAM is linear (seg*16 + off, A20 on, no 1 MiB wrap), byte-exact and
little-endian. Flags carry a defined value or are undefined; reading an
undefined flag (cond, flag, pushf, lahf) raises UndefinedFlag, so a program
that depends on one is reported, never given an invented value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .decode import decode
from .ir import FLAG_KINDS, Op, T, mask
from .sem import lift

R16 = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di", "es", "cs", "ss", "ds", "flagsx")
HALF = {"al": ("ax", 0), "ah": ("ax", 8), "bl": ("bx", 0), "bh": ("bx", 8),
        "cl": ("cx", 0), "ch": ("cx", 8), "dl": ("dx", 0), "dh": ("dx", 8)}


class UndefinedFlag(Exception):
    pass


class InterpError(Exception):
    pass


@dataclass
class Exit:
    kind: str               # fallthrough, jump, jumpf, call, callf, ret, retf, iret, int, fault, halt
    vector: int | None = None


@dataclass
class State:
    regs: dict[str, int]
    flags: dict[str, int]
    mem: bytearray
    ip: int = 0
    undef: set[str] = field(default_factory=set)
    outs: list[tuple[int, int, int]] = field(default_factory=list)
    writes: set[int] = field(default_factory=set)
    port_in = staticmethod(lambda port, w: 0)

    def get(self, r: str) -> int:
        if r in HALF:
            full, sh = HALF[r]
            return self.regs[full] >> sh & 0xFF
        return self.regs[r]

    def put(self, r: str, v: int) -> None:
        if r in HALF:
            full, sh = HALF[r]
            self.regs[full] = self.regs[full] & ~(0xFF << sh) & 0xFFFF | (v & 0xFF) << sh
        else:
            self.regs[r] = v & 0xFFFF

    def load(self, seg: int, off: int, w: int) -> int:
        a = seg * 16 + off
        return int.from_bytes(self.mem[a:a + w // 8], "little")

    def store(self, seg: int, off: int, v: int, w: int) -> None:
        a = seg * 16 + off
        self.mem[a:a + w // 8] = (v & mask(w)).to_bytes(w // 8, "little")
        self.writes.update(range(a, a + w // 8))

    def flag(self, f: str) -> int:
        if f in self.undef:
            raise UndefinedFlag(f)
        return self.flags[f]


def signed(v: int, w: int) -> int:
    v &= mask(w)
    return v - (1 << w) if v >> (w - 1) else v


def parity(v: int) -> int:
    return int(bin(v & 0xFF).count("1") % 2 == 0)


def _szp(r: int, w: int) -> dict[str, int]:
    return {"SF": r >> (w - 1) & 1, "ZF": int(r & mask(w) == 0), "PF": parity(r)}


def status(kind: str, w: int, a: int, b: int, r: int, c: int = 0) -> tuple[dict[str, int], set[str]]:
    """Defined status flag values and undefined flags of a flags op."""
    m, top = mask(w), w - 1
    defined, undef = FLAG_KINDS[kind]
    undef = set(undef)
    f: dict[str, int] = {}
    if kind in ("add", "adc", "inc"):
        f = {"CF": int(a + b + c > m), "OF": ((a ^ r) & (b ^ r)) >> top & 1,
             "AF": (a ^ b ^ r) >> 4 & 1, **_szp(r, w)}
    elif kind in ("sub", "sbb", "dec", "neg"):
        f = {"CF": int(a < b + c), "OF": ((a ^ b) & (a ^ r)) >> top & 1,
             "AF": (a ^ b ^ r) >> 4 & 1, **_szp(r, w)}
    elif kind == "logic":
        f = {"CF": 0, "OF": 0, **_szp(r, w)}
    elif kind == "mul":
        f = {"CF": int(r >> w != 0)}
        f["OF"] = f["CF"]
    elif kind == "imul":
        f = {"CF": int(signed(r & m, w) != signed(r, 2 * w))}
        f["OF"] = f["CF"]
    elif kind in ("shl", "shr", "sar"):
        n = b
        f = _szp(r, w)
        if kind == "shl":
            f["CF"] = a >> (w - n) & 1 if n <= w else 0
            f["OF"] = (r >> top & 1) ^ f["CF"]
        elif kind == "shr":
            f["CF"] = a >> (n - 1) & 1 if n <= w else 0
            f["OF"] = a >> top & 1
        else:
            f["CF"] = signed(a, w) >> (n - 1) & 1
            f["OF"] = 0
        if kind != "sar" and n >= w:  # Intel: CF undefined for SHL/SHR counts >= width
            undef.add("CF")
        if n != 1:
            undef.add("OF")
    elif kind in ("rol", "ror"):
        n = b
        if kind == "rol":
            f = {"CF": r & 1}
            f["OF"] = (r >> top & 1) ^ f["CF"]
        else:
            f = {"CF": r >> top & 1}
            f["OF"] = (r >> top & 1) ^ (r >> (top - 1) & 1)
        if n != 1:
            undef.add("OF")
    elif kind in ("rcl", "rcr"):
        n = b
        t = n % (w + 1)
        full = c << w | a
        if kind == "rcl":
            full = (full << t | full >> (w + 1 - t)) & mask(w + 1) if t else full
            f = {"CF": full >> w & 1}
            f["OF"] = (r >> top & 1) ^ f["CF"]
        else:
            full = (full >> t | full << (w + 1 - t)) & mask(w + 1) if t else full
            f = {"CF": full >> w & 1}
            f["OF"] = (r >> top & 1) ^ (r >> (top - 1) & 1)
        if n != 1:
            undef.add("OF")
    elif kind == "div":
        f = {}
    else:
        raise InterpError(f"flags kind {kind}")
    return {k: v for k, v in f.items() if k in defined and k not in undef}, undef


def bcd(s: State, kind: str, imm: int | None) -> None:
    """DAA DAS AAA AAS AAM AAD (Intel SDM pseudocode; AAA/AAS as AX ± 106h, as QEMU)."""
    al, ah, cf, af = s.get("al"), s.get("ah"), s.flag("CF"), s.flag("AF")
    if kind == "daa":
        old, ncf = al, 0
        if al & 0xF > 9 or af:
            ncf, af = cf or al + 6 > 0xFF, 1
            al = (al + 6) & 0xFF
        else:
            af = 0
        if old > 0x99 or cf:
            al, ncf = (al + 0x60) & 0xFF, 1
        else:
            ncf = 0
        s.put("al", al)
        out, undef = {"CF": int(ncf), "AF": af, **_szp(al, 8)}, {"OF"}
    elif kind == "das":
        old, ncf = al, 0
        if al & 0xF > 9 or af:
            ncf, af = cf or al < 6, 1
            al = (al - 6) & 0xFF
        else:
            af = 0
        if old > 0x99 or cf:
            al, ncf = (al - 0x60) & 0xFF, 1
        s.put("al", al)
        out, undef = {"CF": int(ncf), "AF": af, **_szp(al, 8)}, {"OF"}
    elif kind in ("aaa", "aas"):
        if al & 0xF > 9 or af:
            ax = (s.get("ax") + (0x106 if kind == "aaa" else -0x106)) & 0xFFFF
            s.put("ax", ax)
            s.put("al", s.get("al") & 0xF)
            out = {"AF": 1, "CF": 1}
        else:
            s.put("al", al & 0xF)
            out = {"AF": 0, "CF": 0}
        undef = {"OF", "SF", "ZF", "PF"}
    elif kind == "aam":
        s.put("ah", al // imm)
        s.put("al", al % imm)
        out, undef = _szp(s.get("al"), 8), {"OF", "AF", "CF"}
    elif kind == "aad":
        s.put("al", (al + ah * imm) & 0xFF)
        s.put("ah", 0)
        out, undef = _szp(s.get("al"), 8), {"OF", "AF", "CF"}
    else:
        raise InterpError(f"bcd {kind}")
    s.flags.update(out)
    s.undef = (s.undef - set(out)) | undef


CC = {
    "o": lambda f: f("OF"), "no": lambda f: 1 - f("OF"),
    "b": lambda f: f("CF"), "ae": lambda f: 1 - f("CF"),
    "e": lambda f: f("ZF"), "ne": lambda f: 1 - f("ZF"),
    "be": lambda f: f("CF") | f("ZF"), "a": lambda f: 1 - (f("CF") | f("ZF")),
    "s": lambda f: f("SF"), "ns": lambda f: 1 - f("SF"),
    "p": lambda f: f("PF"), "np": lambda f: 1 - f("PF"),
    "l": lambda f: f("SF") ^ f("OF"), "ge": lambda f: 1 - (f("SF") ^ f("OF")),
    "le": lambda f: (f("SF") ^ f("OF")) | f("ZF"), "g": lambda f: 1 - ((f("SF") ^ f("OF")) | f("ZF")),
}


def execute(ops: list[Op], s: State, ip: int, next_ip: int) -> Exit:
    """Run one instruction's IR on `s`; sets s.ip (and CS for far exits)."""
    labels = {o.args[0]: k for k, o in enumerate(ops) if o.op == "label"}
    env: dict[T, int] = {}

    def val(x, w: int) -> int:
        return env[x] if isinstance(x, T) else x & mask(w)

    def width(args, default):
        return next((a.w for a in args if isinstance(a, T)), default)

    pc = 0
    while pc < len(ops):
        o = ops[pc]
        pc += 1
        op, d, a = o.op, o.dst, o.args
        w = d.w if d else 16
        if op == "const":
            env[d] = a[0] & mask(w)
        elif op == "get":
            env[d] = s.get(a[0])
        elif op == "flag":
            env[d] = s.flag(a[0])
        elif op == "load":
            env[d] = s.load(val(a[0], 16), val(a[1], 16), w)
        elif op == "in":
            env[d] = s.port_in(val(a[0], 16), w) & mask(w)
        elif op in ("add", "sub", "and", "or", "xor", "mul"):
            x, y = val(a[0], w), val(a[1], w)
            r = {"add": x + y, "sub": x - y, "and": x & y, "or": x | y, "xor": x ^ y,
                 "mul": x * y}[op]
            env[d] = r & mask(w)
        elif op == "not":
            env[d] = ~val(a[0], w) & mask(w)
        elif op == "neg":
            env[d] = -val(a[0], w) & mask(w)
        elif op in ("udiv", "urem"):
            x, y = val(a[0], width(a[:1], w)), val(a[1], width(a[1:], w))
            env[d] = (x // y if op == "udiv" else x % y) & mask(w)
        elif op in ("sdiv", "srem"):
            wx, wy = width(a[:1], w), width(a[1:], w)
            x, y = signed(val(a[0], wx), wx), signed(val(a[1], wy), wy)
            q = abs(x) // abs(y) * (1 if (x < 0) == (y < 0) else -1)
            env[d] = (q if op == "sdiv" else x - q * y) & mask(w)
        elif op in ("shl", "shr", "sar"):
            x, n = val(a[0], w), val(a[1], 8)
            r = x << n if op == "shl" else x >> n if op == "shr" else signed(x, w) >> n
            env[d] = r & mask(w)
        elif op in ("rol", "ror"):
            x, n = val(a[0], w), val(a[1], 8) % w
            r = (x << n | x >> (w - n)) if op == "rol" else (x >> n | x << (w - n))
            env[d] = r & mask(w)
        elif op in ("rcl", "rcr"):
            x, n, c = val(a[0], w), val(a[1], 8), val(a[2], 1)
            t = n % (w + 1)
            full = c << w | x
            if t:
                if op == "rcl":
                    full = (full << t | full >> (w + 1 - t)) & mask(w + 1)
                else:
                    full = (full >> t | full << (w + 1 - t)) & mask(w + 1)
            env[d] = full & mask(w)
        elif op == "zext":
            env[d] = val(a[0], w) & mask(w)
        elif op == "sext":
            env[d] = signed(env[a[0]], a[0].w) & mask(w)
        elif op == "trunc":
            env[d] = val(a[0], w) & mask(w)
        elif op in ("eq", "ne", "ltu", "lts"):
            ww = width(a, 16)
            x, y = val(a[0], ww), val(a[1], ww)
            if op == "lts":
                x, y = signed(x, ww), signed(y, ww)
            env[d] = int({"eq": x == y, "ne": x != y, "ltu": x < y, "lts": x < y}[op])
        elif op == "select":
            env[d] = val(a[1], w) if val(a[0], 1) else val(a[2], w)
        elif op == "cond":
            env[d] = CC[a[0]](s.flag)
        elif op == "put":
            reg_w = 8 if a[0] in HALF else 16
            s.put(a[0], val(a[1], reg_w))
        elif op == "setflag":
            s.flags[a[0]] = val(a[1], 1)
            s.undef.discard(a[0])
        elif op == "store":
            s.store(val(a[0], 16), val(a[1], 16), val(a[2], a[3]), a[3])
        elif op == "out":
            ow = a[1].w
            s.outs.append((val(a[0], 16), ow, val(a[1], ow)))
        elif op == "flags":
            kind, fw = a[0], a[1]
            rest = [val(x, fw) for x in a[2:4]] + [env[a[4]]] + [val(x, 1) for x in a[5:]]
            if kind in ("shl", "shr", "sar", "rol", "ror", "rcl", "rcr"):
                rest[1] = val(a[3], 8)
            defined, undef = status(kind, fw, *rest)
            s.flags.update(defined)
            s.undef = (s.undef - set(defined)) | undef
        elif op == "bcd":
            bcd(s, a[0], a[1] if len(a) > 1 else None)
        elif op == "label":
            pass
        elif op == "goto":
            pc = labels[a[0]]
        elif op == "br":
            if val(a[0], 1):
                pc = labels[a[1]]
        elif op in ("jump", "call", "ret"):
            s.ip = val(a[0], 16)
            return Exit(op)
        elif op in ("jumpf", "callf", "retf", "iret"):
            s.regs["cs"] = val(a[0], 16)
            s.ip = val(a[1], 16)
            return Exit(op)
        elif op == "int":
            s.ip = a[1]
            return Exit("int", a[0])
        elif op == "fault":
            s.ip = ip
            return Exit("fault", a[0])
        elif op == "halt":
            s.ip = next_ip
            return Exit("halt")
        else:
            raise InterpError(f"op {op}")
    s.ip = next_ip
    return Exit("fallthrough")


def step(s: State) -> tuple[Exit, object]:
    """Fetch, decode, lift and execute the instruction at CS:IP."""
    base = s.regs["cs"] * 16
    i = decode(bytes(s.mem[base + s.ip: base + s.ip + 16]), s.ip)
    return execute(lift(i), s, i.ip, i.next_ip), i
