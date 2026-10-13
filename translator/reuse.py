"""R13: within a run, an index formation in d7 or an a6-based segment base in
a0 that repeats the value the register already holds is dropped.

Formations: `move.w #c,d7` or `move.w Rm,d7`, then `sub.w`/`subq.w`/`add.w`/
`addq.w` of a register or immediate to d7 (the 16-bit mirrored offset an
access indexes with `.w`); bases: `lea …(a6),a0` (a constant: a6 never
changes in generated code). A held value ends at a block leader (another
path enters), at any label (local branch targets, poll and guard labels), at
a call, return or unconditional transfer, and at any line that may write the
held register or a register the formation read. A line's written registers
are taken conservatively: a two-operand instruction from a known set writes
only a register destination (and auto-increment/decrement registers);
compare/test instructions write none; anything else writes every register it
names, and `movem`/`exg` end everything held."""

from __future__ import annotations

import re

SRC = re.compile(r"^\tmove\.w (#[^,]+|[ad][0-7]),d7$")
ADJ = re.compile(r"^\t(?:sub|subq|add|addq)\.w (#[^,]+|[ad][0-7]),d7$")
BASE = re.compile(r"^\tlea (?:\([^()]*(?:\([^()]*\)[^()]*)*,a6\)|[^(),]*\(a6\)),a0$")
REG = re.compile(r"\b([ad][0-7])\b")
AUTO = re.compile(r"-\(([ad][0-7])\)|\(([ad][0-7])\)\+")
READ_ONLY = ("cmp", "cmpa", "cmpi", "cmpm", "tst", "btst", "pea", "chk")
BRANCH_CC = re.compile(r"^b(?:ne|eq|cc|cs|hi|ls|pl|mi|ge|gt|le|lt|vc|vs|hs|lo)$")
ENDS = ("jsr", "bsr", "rts", "rte", "rtr", "rtd", "trap", "jmp", "bra", "illegal", "stop",
        "movem", "exg")
TWO = ("move", "movea", "moveq", "add", "adda", "addi", "addq", "addx", "sub", "suba", "subi",
       "subq", "subx", "and", "andi", "or", "ori", "eor", "eori", "lea", "mulu", "muls",
       "divu", "divs", "lsl", "lsr", "asl", "asr", "rol", "ror", "roxl", "roxr", "bset", "bclr",
       "bchg", "bfins", "bfextu", "bfexts")


def operands(args: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in args:
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur] if args else out


def written(line: str) -> set[str] | None:
    """Registers `line` may write; None: end everything held."""
    op, _, args = line.strip().partition(" ")
    base = op.split(".")[0]
    if base in ENDS:
        return None
    if base in READ_ONLY or BRANCH_CC.match(base):
        return set()
    auto = {a or b for a, b in AUTO.findall(args)}
    ops = operands(args)
    if base in TWO and len(ops) == 2:
        dest = ops[1]
        return auto | (set(REG.findall(dest)) if "(" not in dest else set())
    return auto | set(REG.findall(args))


def reuse(outs: list[list[str]], resets: set[int]) -> int:
    """Drop repeated formations from the lowered lines of a run in place
    (`outs[k]`: instruction k's lines; `resets`: instructions entered other
    than by falling through). Returns the formations dropped."""
    held: dict[str, tuple] = {}     # register -> (lines, registers they read)
    dropped = 0
    for k, out in enumerate(outs):
        if k in resets:
            held.clear()
        res, j = [], 0
        while j < len(out):
            x = out[j]
            if not x.startswith("\t"):
                if x.strip():
                    held.clear()
                res.append(x)
                j += 1
                continue
            if SRC.match(x) and j + 1 < len(out) and ADJ.match(out[j + 1]):
                form = (x, out[j + 1])
                if held.get("d7", (None,))[0] == form:
                    dropped += 1
                else:
                    deps = {r for y in form for r in REG.findall(y.split(",")[0])} - {"d7"}
                    held["d7"] = (form, deps)
                    res += form
                j += 2
                continue
            if BASE.match(x):
                if held.get("a0", (None,))[0] == (x,):
                    dropped += 1
                else:
                    held["a0"] = ((x,), set())
                    res.append(x)
                j += 1
                continue
            w = written(x)
            if w is None:
                held.clear()
            else:
                for r in [r for r, (_, deps) in held.items() if r in w or deps & w]:
                    del held[r]
            res.append(x)
            j += 1
        out[:] = res
    return dropped
