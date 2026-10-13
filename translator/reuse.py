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


# R14f: a formation that differs from the one d7 holds only in its constant is
# dropped; the accesses until d7 is next written take the difference in their
# displacement. One guard per sign after the first formation proves no access
# wraps at 64 KiB; when it fails, an exact copy of the lines runs out of line.
INDEX = re.compile(r"(-?\d+)\((a[0-7]),d7\.w\)")
D7 = re.compile(r"\bd7\b")
LOCAL = re.compile(r"(?<![\w.])\.\d+\b")
CONST = re.compile(r"^\t(sub|subq|add|addq)\.w #(\$[0-9a-f]+|\d+),d7$")
PURE_WRITE = re.compile(r"^\t(?:move\.[wl]|moveq) ([^,]+),d7$")


def number(s: str) -> int:
    return int(s[1:], 16) if s.startswith("$") else int(s)


def formation(out: list[str], j: int) -> tuple[int, tuple, set, int] | None:
    """The formation starting at out[j]: (lines, base, registers read, constant)."""
    m = SRC.match(out[j])
    if not m or j + 1 >= len(out) or not ADJ.match(out[j + 1]):
        return None
    src, base, const = m.group(1), [], 0
    if src.startswith("#"):
        try:
            src, const = "#", number(src[1:])
        except ValueError:
            return None
    n = j + 1
    while n < len(out) and ADJ.match(out[n]):
        c = CONST.match(out[n])
        if c:
            const += number(c.group(2)) * (1 if c.group(1).startswith("add") else -1)
        else:
            base.append(out[n])
        n += 1
    regs = {r for y in [src] + base for r in REG.findall(y.split(",")[0])} - {"d7"}
    return n - j, (src, tuple(base)), regs, const & 0xFFFF


def signed16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def fold(outs: list[list[str]], resets: set[int], labels: list[str],
         colds: list[list[str]]) -> int:
    """Fold formations in the lowered lines of a run in place (after `reuse`);
    out-of-line copies go to `colds[k]`, labelled from `labels[k]`. Returns the
    formations dropped."""
    flat = [(k, j) for k, out in enumerate(outs) for j in range(len(out))]
    edits: list = []        # per group: (start, guards, drops, rewrites, last)
    g = None                # open group

    def close(kill: bool) -> None:
        nonlocal g
        if g is None:
            return
        folds = g["folds"]
        if not kill and folds and g["d"]:
            pos, n, d = folds.pop()     # the last formation stays: d7 is right after it
            g["rewrites"] = {p: x for p, x in g["rewrites"].items() if p < pos}
        g["frozen"] = True
        ds = [d for _, _, d in folds]
        guards = 2 * ((max(ds, default=0) > 0) + (min(ds, default=0) < 0))
        saved = sum(n for _, n, _ in folds)
        mods = [(p[0], p[1] + n - 1) for p, n, _ in folds] + list(g["rewrites"])
        if folds and saved > guards:
            k1, k2 = g["start"][0], max(mods)[0]
            if not any(LOCAL.search(x) for k in {k1, k2} for x in outs[k]):
                edits.append((g["start"], ds, folds, g["rewrites"], max(mods)))
        g = None

    i, seen = 0, -1
    while i < len(flat):
        k, j = flat[i]
        out = outs[k]
        x = out[j]
        if any(r in resets for r in range(seen + 1, k + 1)):
            close(False)
        seen = k
        f = formation(out, j) if x.startswith("\t") else None
        if f:
            n, base, regs, const = f
            if g and not g["frozen"] and base == g["base"]:
                d = signed16(const - g["const"])
                g["folds"].append(((k, j), n, d))
                g["d"] = d
            else:
                close(True)
                g = {"start": (k, j + n), "base": base, "regs": regs, "const": const,
                     "folds": [], "rewrites": {}, "d": 0, "frozen": False}
            i += n
            continue
        if g is None:
            i += 1
            continue
        if not x.startswith("\t"):
            if x.strip():
                close(False)
            i += 1
            continue
        w = written(x)
        op = x.split()[0].split(".")[0]
        if w is None or BRANCH_CC.match(op) or op.startswith("db") or LOCAL.search(x):
            close(False)
            i += 1
            continue
        rest = INDEX.sub("", x)
        if D7.search(rest):
            pw = PURE_WRITE.match(rest)
            if pw and not D7.search(pw.group(1)):
                if INDEX.search(x):
                    if not rewrite(g, (k, j), x):
                        close(False)
                        i += 1
                        continue
                close(True)
            else:
                close(False)
            i += 1
            continue
        if INDEX.search(x) and not rewrite(g, (k, j), x):
            close(False)
        elif base_written(w, g["regs"]):
            g["frozen"] = True
        i += 1
    close(False)

    dropped = 0
    for n, (start, ds, folds, rewrites, last) in reversed(list(enumerate(edits))):
        k1, k2 = start[0], last[0]
        slow, join = f"{labels[k1]}_f{n}s", f"{labels[k1]}_f{n}j"
        drop = {(p[0], p[1] + m) for p, c, _ in folds for m in range(c)}
        guards = guard_lines(ds, slow)
        copy = [outs[k][j] for k, j in flat if start <= (k, j) <= last]
        for k in range(k2, k1 - 1, -1):
            out = outs[k]
            res = []
            for j, x in enumerate(out):
                if (k, j) == start and guards:
                    res += guards
                if (k, j) not in drop:
                    res.append(rewrites.get((k, j), x))
                if (k, j) == last and guards:
                    res.append(f"{join}:")
            if start == (k, len(out)) and guards:
                res += guards
            out[:] = res
        if guards:
            colds[k1] += slow_path(slow, join, copy)
        dropped += len(folds)
    return dropped


def base_written(w: set, regs: set) -> bool:
    """A line writing `w` changes a held formation's registers (or d7)."""
    return bool(w & (regs | {"d7"}))


def guard_lines(ds: list[int], slow: str) -> list[str]:
    """d7 + d stays in -8000h..7FFFh for every folded difference d, else `slow`."""
    out = []
    if max(ds) > 0:
        out += [f"\tcmp.w #{0x7FFF - max(ds)},d7", f"\tbgt {slow}"]
    if min(ds) < 0:
        out += [f"\tcmp.w #{-0x8000 - min(ds)},d7", f"\tblt {slow}"]
    return out


def slow_path(slow: str, join: str, lines: list[str]) -> list[str]:
    """The group's lines as lowered, out of line, back to `join`."""
    return [f"{slow}:"] + lines + [f"\tbra {join}"]


def rewrite(g: dict, pos: tuple, x: str) -> bool:
    """Record x with every d7 index displaced by the held difference; False when
    one leaves the 8-bit range."""
    d = g["d"]
    if not d:
        return True
    ok = True

    def disp(m):
        nonlocal ok
        v = int(m.group(1)) + d
        ok &= -128 <= v <= 127
        return f"{v}({m.group(2)},d7.w)"

    y = INDEX.sub(disp, x)
    if ok:
        g["rewrites"][pos] = y
    return ok
