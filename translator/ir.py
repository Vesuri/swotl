"""Per-instruction semantic IR (docs/translator-design.md §IR).

An instruction lifts to a list of `Op`s over temporaries `T(n, w)` (w in
bits: 1, 8, 16, 32). Value arguments are temporaries or int constants
(read at the destination width). Guest registers are 16-bit with explicit
8-bit halves; segment registers are separate; flags are single bits;
`flagsx` holds FLAGS bits 12-15 (IOPL/NT as the CPU keeps them).

Value ops (dst = result):
  const v | get r | flag f | load seg off | in port
  add sub and or xor a b | not neg a | mul a b (operands extended by the
  lifter; result at dst width) | udiv urem sdiv srem a b (truncated to dst)
  shl shr sar a n (n any count; >= width gives 0 / sign fill) | rol ror a n
  rcl rcr a n c (through carry c; n masked count, mod w+1)
  zext sext trunc a (to dst width) | eq ne ltu lts a b (dst w=1)
  select c a b | cond cc (x86 condition from the current flags, w=1)
Effects:
  put r v | setflag f v | store seg off v w | out port v
  flags kind w a b r [c]: define the status flags `kind` writes (FLAG_KINDS)
    for operand width w (mul/imul: r is the double-width product)
  bcd kind [imm]: daa das aaa aas aam aad on AL/AH and flags
Local control: label L | goto L | br c L (taken when c != 0)
Exits (end the instruction; without one it falls through to the next IP):
  jump ip | jumpf seg ip | call ip | callf seg ip | ret ip | retf seg ip |
  iret seg ip | int vector ip | fault vector | halt |
  trap (TF set by POPF/IRET: a loud stop, no single-step delivery)
Call/return exits carry targets only; the stack traffic is explicit ops.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS = ("CF", "PF", "AF", "ZF", "SF", "OF")
FLAGS = STATUS + ("TF", "IF", "DF")
FLAG_BIT = {"CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7, "TF": 8, "IF": 9, "DF": 10, "OF": 11}

# kind -> (flags written with a defined value, flags left undefined)
ALL = set(STATUS)
FLAG_KINDS = {
    "add": (ALL, set()), "adc": (ALL, set()), "sub": (ALL, set()), "sbb": (ALL, set()),
    "inc": (ALL - {"CF"}, set()), "dec": (ALL - {"CF"}, set()), "neg": (ALL, set()),
    "logic": (ALL - {"AF"}, {"AF"}),
    "mul": ({"CF", "OF"}, {"SF", "ZF", "AF", "PF"}), "imul": ({"CF", "OF"}, {"SF", "ZF", "AF", "PF"}),
    "div": (set(), set(ALL)),
    # Shifts and rotates (count != 0, guarded by the lifter); count-dependent
    # parts (OF unless count 1, CF for SHL/SHR counts > width) are refined by
    # the interpreter.
    "shl": (ALL - {"AF"}, {"AF"}), "shr": (ALL - {"AF"}, {"AF"}), "sar": (ALL - {"AF"}, {"AF"}),
    "rol": ({"CF", "OF"}, set()), "ror": ({"CF", "OF"}, set()),
    "rcl": ({"CF", "OF"}, set()), "rcr": ({"CF", "OF"}, set()),
}

EXITS = {"jump", "jumpf", "call", "callf", "ret", "retf", "iret", "int", "fault", "halt", "trap"}


@dataclass(frozen=True)
class T:
    n: int
    w: int

    def __str__(self) -> str:
        return f"t{self.n}"


@dataclass(frozen=True)
class Op:
    op: str
    dst: T | None
    args: tuple

    def __str__(self) -> str:
        a = ", ".join(str(x) if not isinstance(x, int) else f"0x{x:x}" for x in self.args)
        if self.dst is None:
            return f"{self.op} {a}".rstrip()
        return f"{self.dst}:{self.dst.w} = {self.op} {a}".rstrip()


def mask(w: int) -> int:
    return (1 << w) - 1
