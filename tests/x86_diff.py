#!/usr/bin/env python3
"""x86 semantics differential: IR interpreted on the host vs Unicorn x86-16 (gate 3).

Corpora (deterministic seeds):
  forms     every instruction form the translator decodes in the game
            (op, width, operand kinds, addressing, prefixes), up to 4
            samples each, random states
  space     random encodings of every supported opcode byte
  boundary  explicit edge cases random state misses (shift/rotate counts,
            divide faults and overflow, REP with CX 0/1 and DF=1, SI/DI and
            SP wrap, word at offset FFFFh, BCD over all AL, flags words, STI/CLI,
            REP fast path guard and stop edges, overlapping MOVS)
  blocks    straight-line runs of 2..8 game instructions ending at the first
            transfer, random states
Each case runs the same bytes from the same state (registers, flags, 1 MiB+
random RAM) on both sides and compares registers, CS:IP, defined flags
(undefined ones masked per instruction), FLAGS bits 12-14, every byte
either side wrote, OUT sequence and the raised interrupt/fault. A case
whose IR reads an undefined flag is counted separately and fails the run
unless it is a block case (game code reading flags left undefined).

Shared by both sides: the case bytes and state, and the code hook's notion
of an instruction boundary (REP iterations stay one instruction); the
decoder is cross-checked by tests/test_decode.py.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uc as U  # noqa: E402
from translator import cfg, image  # noqa: E402
from translator.decode import DecodeError, Imm, Mem, Reg, decode  # noqa: E402
from translator.interp import State, UndefinedFlag, execute, step  # noqa: E402
from translator.ir import FLAG_BIT, FLAGS  # noqa: E402
from translator.sem import lift  # noqa: E402

RAM = 0x120000
REGS = ("ax", "bx", "cx", "dx", "sp", "bp", "si", "di")
SEGS = ("es", "cs", "ss", "ds")
UNSUPPORTED = {0x0F, *range(0x60, 0x70), 0x9B, 0xC0, 0xC1, 0xC8, 0xC9, 0xD6, *range(0xD8, 0xE0),
               0xF0, 0xF1, 0xF4}  # + HLT: Unicorn stops on it


EXCEPTIONS = {0, 1, 5, 6, 8, 13}


def oracle_deviation(code: bytes, regs: dict) -> str | None:
    """Known Unicorn deviations from Intel/DOSBox, counted instead of compared."""
    k = 0
    while code[k] in (0x26, 0x2E, 0x36, 0x3E):
        k += 1
    if code[k] in (0xCA, 0xCB) and regs["sp"] >= 0xFFFD:
        return "retf CS read at SS:SP+2 without 16-bit SP wrap"
    if code[k] == 0xCD and k + 1 < len(code) and code[k + 1] in EXCEPTIONS:
        return "int n on an exception vector (QEMU's exception path)"
    return None


def restarted(code_lo: int, size: int, writes: set, ip: int, out: dict, ints: list) -> bool:
    """QEMU restarts an instruction that stores into the page of its own code
    (self-modifying-code check); stopped after one instruction, the oracle
    then has not executed it: IP unchanged, no store, no interrupt."""
    pages = {a >> 12 for a in range(code_lo, code_lo + size)}
    return out["ip"] == ip and not ints and any(a >> 12 in pages for a in writes)


def port_value(port: int, size: int) -> int:
    return ((port * 0x9E37 + size * 0x55) ^ 0xA5C3) & (0xFF if size == 1 else 0xFFFF)


def is_rep_string(code: bytes) -> bool:
    k, rep = 0, False
    while k < len(code) and code[k] in (0x26, 0x2E, 0x36, 0x3E, 0xF2, 0xF3):
        rep |= code[k] in (0xF2, 0xF3)
        k += 1
    return rep and k < len(code) and code[k] in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD,
                                                0xAE, 0xAF)


class Oracle:
    """Unicorn x86-16. Its interrupt hook skips QEMU's exception delivery, so
    `old_exception` stays set and the next exception becomes #DF (8), then a
    silent triple fault: the engine is reopened after every exception."""

    def __init__(self, background: bytes):
        self.bg = background
        self.ints: list[int] = []
        self.outs: list[tuple[int, int, int]] = []
        self.writes: set[int] = set()
        self.limit = 1
        self.done = 0
        self.prev = None

        @U.CODE_CB
        def code(h, addr, size, user):
            if self.prev is not None and (addr != self.prev or not is_rep_string(
                    self.e.read(addr, 8))):
                self.done += 1
                if self.done >= self.limit:
                    U.uc.uc_emu_stop(h)
            self.prev = addr

        @U.INTR_CB
        def intr(h, no, user):
            self.ints.append(no)
            U.uc.uc_emu_stop(h)

        @U.OUT_CB
        def out(h, port, size, value, user):
            self.outs.append((port, size * 8, value))

        @U.IN_CB
        def inp(h, port, size, user):
            return port_value(port, size)

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            self.writes.update(range(addr, addr + size))
            return True

        self.callbacks = ((U.HOOK_CODE, code), (U.HOOK_INTR, intr),
                          (U.HOOK_INSN, out, U.X86_INS_OUT), (U.HOOK_INSN, inp, U.X86_INS_IN),
                          (U.HOOK_MEM_WRITE, write))
        self.open()

    def open(self) -> None:
        if getattr(self, "e", None):
            U.uc.uc_close(self.e.h)
        self.e = U.Engine(U.ARCH_X86, U.MODE_16)
        self.e.map(0, RAM)
        self.e.write(0, self.bg)
        for kind, cb, *extra in self.callbacks:
            self.e.hook(kind, cb, *extra)

    def run(self, case, n: int):
        regs, flags, flagsx, ip, patches = case
        for a, data in patches:
            self.e.write(a, data)
        self.e.flush()
        for r in REGS + SEGS:
            self.e.reg_write(U.X86[r], regs[r])
        self.e.reg_write(U.X86["ip"], ip)
        word = 2 | flagsx | sum(flags[f] << FLAG_BIT[f] for f in FLAGS)
        self.e.reg_write(U.X86["flags"], word)
        self.ints, self.outs, self.writes = [], [], set()
        # One instruction per emu_start: QEMU mis-computes OF/AF when a REP string
        # op follows a flag setter inside one translation block.
        err = 0
        for _ in range(n):
            self.limit, self.done, self.prev = 1, 0, None
            begin = self.e.reg_read(U.X86["cs"]) * 16 + self.e.reg_read(U.X86["ip"])
            err = self.e.start(begin, 0xFFFFFFFFFFFF)
            if err or self.ints:
                break
        out = {r: self.e.reg_read(U.X86[r]) & 0xFFFF for r in REGS + SEGS}
        out["ip"] = self.e.reg_read(U.X86["ip"]) & 0xFFFF
        fl = self.e.reg_read(U.X86["flags"])
        mem = {a: self.e.read(a, 1)[0] for a in self.writes}
        if self.ints and self.ints[0] in EXCEPTIONS:
            self.open()
            self.writes = set()  # fresh engine holds the background
        return err, out, fl, mem, list(self.ints), list(self.outs), set(self.writes)

    def restore(self, addrs):
        for a in sorted(addrs):
            self.e.write(a, self.bg[a:a + 1])
        self.e.flush()


class Harness:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        bg = bytes(random.Random(seed ^ 0x5EED).randrange(256) for _ in range(RAM))
        self.bg = bg
        self.mem = bytearray(bg)
        self.oracle = Oracle(bg)
        self.count = Counter()
        self.undefined = Counter()
        self.skipped = Counter()
        self.bad: list[str] = []

    def state(self, overrides=None):
        r = self.rng
        regs = {x: r.randrange(0x10000) for x in REGS}
        regs.update({s: r.randrange(0x10000) for s in SEGS})
        regs["cs"] = r.randrange(0x0100, 0xF000)
        flags = {f: r.randrange(2) for f in FLAGS}
        flags["TF"] = 0
        flagsx = 0
        ip = r.randrange(0, 0xFF00)
        if overrides:
            regs.update(overrides.get("regs", {}))
            flags.update(overrides.get("flags", {}))
            flagsx = overrides.get("flagsx", 0)
            ip = overrides.get("ip", ip)
        return regs, flags, flagsx, ip

    def case(self, code: bytes, label: str, n: int = 1, overrides=None, block=False):
        regs, flags, flagsx, ip = self.state(overrides)
        cs = regs["cs"]
        patches = []
        # Stack words popped by POPF/IRET/RET get TF clear (a set TF would single-step Unicorn).
        sp_lin = regs["ss"] * 16 + regs["sp"]
        stack = bytearray(self.rng.randrange(256) for _ in range(8))
        for k in (1, 3, 5, 7):
            stack[k] &= 0xFE
        patches.append((sp_lin, bytes(stack)))
        for a, data in (overrides or {}).get("mem", []):
            patches.append((a(regs) if callable(a) else a, data))
        patches.append((cs * 16 + ip, code))
        case = (regs, flags, flagsx, ip, patches)
        # Interpreter side.
        s = State(dict(regs, flagsx=flagsx), dict(flags), self.mem, ip)
        s.port_in = lambda port, w: port_value(port, w // 8)
        for a, data in patches:
            self.mem[a:a + len(data)] = data
        exit_vec = None
        try:
            for _ in range(n):
                ex, insn = step(s)
                if ex.kind in ("int", "fault"):
                    exit_vec = ex.vector
                    break
        except UndefinedFlag as e:
            self.undefined[label if not block else "block"] += 1
            if not block:
                self.bad.append(f"{label} {code.hex()}: IR reads undefined {e}")
            self.reset(patches, s.writes, set())
            return
        except DecodeError:
            self.reset(patches, s.writes, set())
            return
        err, out, fl, umem, ints, outs, uwrites = self.oracle.run(case, n)
        code_span = set(range(cs * 16 + ip, cs * 16 + ip + len(code)))
        if code_span & (s.writes | uwrites):
            self.skipped["writes its own code"] += 1  # QEMU refetches; the CPU would not
            self.reset(patches, s.writes, uwrites)
            return
        if restarted(cs * 16 + ip, len(code), s.writes, ip, out, ints):
            self.skipped["oracle: store into its code's page restarts it"] += 1
            self.reset(patches, s.writes, uwrites)
            return
        why = oracle_deviation(code, regs) if n == 1 else None
        if why:
            self.skipped[f"oracle: {why}"] += 1
            self.reset(patches, s.writes, uwrites)
            return
        diffs = []
        if err:
            diffs.append(f"unicorn error {err}")
        for r in REGS + SEGS:
            if s.regs[r] != out[r]:
                diffs.append(f"{r} ir={s.regs[r]:04x} uc={out[r]:04x}")
        if s.ip != out["ip"]:
            diffs.append(f"ip ir={s.ip:04x} uc={out['ip']:04x}")
        for f in FLAGS:
            if f not in s.undef and s.flags[f] != fl >> FLAG_BIT[f] & 1:
                diffs.append(f"{f} ir={s.flags[f]} uc={fl >> FLAG_BIT[f] & 1}")
        if (s.regs["flagsx"] >> 12) & 7 != (fl >> 12) & 7:
            diffs.append(f"flags[14:12] ir={s.regs['flagsx'] >> 12 & 7} uc={fl >> 12 & 7}")
        for a in sorted(s.writes | uwrites):
            if self.mem[a] != umem.get(a, self.oracle.e.read(a, 1)[0]):
                diffs.append(f"mem {a:05x} ir={self.mem[a]:02x} uc={umem.get(a, -1):02x}")
                break
        if [exit_vec] != (ints[:1] or [None]):
            diffs.append(f"interrupt ir={exit_vec} uc={ints}")
        if s.outs != outs:
            diffs.append(f"out ir={s.outs} uc={outs}")
        self.count[label] += 1
        if diffs:
            st = " ".join(f"{k}={v:04x}" for k, v in regs.items())
            fs = "".join(f for f in FLAGS if flags[f])
            self.bad.append(f"{label} {code.hex()} ip={ip:04x} [{st} {fs}]: {'; '.join(diffs[:6])}")
        self.reset(patches, s.writes, uwrites)

    def reset(self, patches, ir_writes, uc_writes):
        addrs = set(ir_writes) | set(uc_writes)
        for a, data in patches:
            addrs.update(range(a, a + len(data)))
        for a in addrs:
            self.mem[a] = self.bg[a]
        self.oracle.restore(addrs)


def form_key(n) -> tuple:
    def kind(o):
        if isinstance(o, Reg):
            return ("r", o.width, o.name if o.name in ("cl", "dx", "al", "ax") else "")
        if isinstance(o, Mem):
            return ("m", o.width, o.base, o.index, bool(o.disp), o.override)
        if isinstance(o, Imm):
            return ("i", o.width)
        return (type(o).__name__,)
    return (n.op, n.width, n.cc, n.rep, n.seg is not None, tuple(kind(o) for o in n.operands))


def boundary(h: Harness) -> None:
    rng = h.rng
    # Shifts and rotates by CL: every op, both widths, counts around the widths.
    for w, opc in ((8, 0xD2), (16, 0xD3)):
        for reg in range(8):
            if reg == 6:
                continue
            for cl in (0, 1, 2, 7, 8, 9, 15, 16, 17, 18, 31, 32, 33, 255):
                for _ in range(3):
                    h.case(bytes([opc, 0xC0 | reg << 3 | 3]), f"b:shift{w}/{reg}",
                           overrides={"regs": {"cx": rng.randrange(256) << 8 | cl}})
            for _ in range(8):  # by 1
                h.case(bytes([opc - 2, 0xC0 | reg << 3 | 3]), f"b:shift1_{w}/{reg}")
    # MUL/IMUL/DIV/IDIV with edge operands (BL / BX).
    edges8, edges16 = (0, 1, 0x7F, 0x80, 0xFF), (0, 1, 0x7FFF, 0x8000, 0xFFFF)
    for reg in (4, 5, 6, 7):
        for e8 in edges8:
            for ax in (0, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0xFF80, 0xFFFF, 0x0100, 0x7F00):
                h.case(bytes([0xF6, 0xC0 | reg << 3 | 3]), f"b:muldiv8/{reg}",
                       overrides={"regs": {"ax": ax, "bx": e8}})
        for e16 in edges16:
            for dx, ax in ((0, 0), (0, 0xFFFF), (0x7FFF, 0xFFFF), (0x8000, 0), (0xFFFF, 0xFFFF),
                           (0xFFFF, 0x8000), (0, 0x8000), (0x0001, 0)):
                h.case(bytes([0xF7, 0xC0 | reg << 3 | 3]), f"b:muldiv16/{reg}",
                       overrides={"regs": {"ax": ax, "dx": dx, "bx": e16}})
    # String instructions: REP with CX 0/1/n, DF both ways, SI/DI wrapping at 64 KiB.
    for b in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF):
        for pre in (b"", b"\xf3", b"\xf2", b"\x26\xf3", b"\xf3\x2e"):
            for cx in (0, 1, 2, 7):
                for si, di in ((0, 0), (0xFFFF, 0xFFFF), (0xFFFE, 1), (1, 0xFFFE)):
                    for df in (0, 1):
                        h.case(pre + bytes([b]), f"b:string{b:02x}",
                               overrides={"regs": {"cx": cx, "si": si, "di": di},
                                          "flags": {"DF": df}})
    # REPE/REPNE CMPSB/SCASB over equal and unequal runs.
    for b in (0xA6, 0xAE):
        for pre in (b"\xf3", b"\xf2"):
            for fill in (0x00, 0x41):
                h.case(pre + bytes([b]), f"b:repcmp{b:02x}",
                       overrides={"regs": {"cx": 6, "ax": 0x41, "si": 0x100, "di": 0x200,
                                           "ds": 0x5000, "es": 0x5000},
                                  "flags": {"DF": 0},
                                  "mem": [(0x50100, bytes([0x41, 0x41, fill, 0x41, 0x41, 0x41])),
                                          (0x50200, bytes([0x41, 0x41, 0x41, 0x41, fill, 0x41]))]})
    # Stack wrap: push/pop/call/ret at SP 0, 1, FFFE, FFFF.
    for code in (b"\x50", b"\x58", b"\x54", b"\x5c", b"\x9c", b"\x9d", b"\xe8\x10\x00", b"\xc3",
                 b"\xc2\x04\x00", b"\xcb", b"\xca\x02\x00", b"\xcf", b"\x9a\x34\x12\x78\x56",
                 b"\xff\x1f", b"\x0e", b"\x1f"):
        for sp in (0, 1, 2, 0xFFFE, 0xFFFF):
            for _ in range(4):
                h.case(code, f"b:stack{code.hex()}", overrides={"regs": {"sp": sp}})
    # Word and far-pointer accesses at offsets FFFEh/FFFFh, segment FFFFh above 1 MiB.
    for code in (b"\xa1\xff\xff", b"\xa3\xff\xff", b"\x8b\x07", b"\x89\x07", b"\xc4\x07", b"\xc5\x07",
                 b"\xff\x2f", b"\x87\x07", b"\xd1\x27", b"\xf7\x17", b"\xff\x07"):
        for bx in (0xFFFF, 0xFFFE, 0xFFFD):
            for ds in (0xFFFF, 0xF000, 0x1234):
                h.case(code, f"b:wrap{code.hex()}", overrides={"regs": {"bx": bx, "ds": ds}})
    # Effective address wrap: [bx+si+disp] beyond FFFFh.
    for _ in range(64):
        h.case(b"\x8b\x80\xff\x7f", "b:eawrap", overrides={"regs": {"bx": 0xFFF0, "si": 0x9000}})
    # BCD over every AL with each AF/CF combination.
    for code in (b"\x27", b"\x2f", b"\x37", b"\x3f", b"\xd4\x0a", b"\xd5\x0a", b"\xd4\x07", b"\xd5\x10",
                 b"\xd4\x00"):
        for al in range(256):
            for af in (0, 1):
                for cf in (0, 1):
                    h.case(code, f"b:bcd{code.hex()}",
                           overrides={"regs": {"ax": rng.randrange(256) << 8 | al},
                                      "flags": {"AF": af, "CF": cf}})
    # Flags words: LAHF/SAHF/PUSHF/POPF/IRET with every low pattern and bits 12-15.
    for _ in range(256):
        h.case(b"\x9e", "b:sahf")
        h.case(b"\x9f", "b:lahf")
        h.case(b"\x9c", "b:pushf", overrides={"flagsx": rng.choice((0, 0x1000, 0x3000, 0x7000))})
        word = rng.randrange(0x10000) & ~0x0100
        h.case(b"\x9d", "b:popf", overrides={"mem": [(lambda r: r["ss"] * 16 + r["sp"],
                                                       word.to_bytes(2, "little"))]})
    # INC/DEC/NEG/ADC/SBB at the sign and carry edges.
    for code in (b"\x40", b"\x48", b"\xf7\xd8", b"\x13\xc3", b"\x1b\xc3", b"\x03\xc3", b"\x2b\xc3",
                 b"\x3b\xc3", b"\xfe\xc0", b"\xfe\xc8", b"\xf6\xd8", b"\x12\xc3", b"\x1a\xc3"):
        for ax in (0, 1, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0xFFFF):
            for bx in (0, 1, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0xFFFF):
                for cf in (0, 1):
                    h.case(code, f"b:arith{code.hex()}",
                           overrides={"regs": {"ax": ax, "bx": bx}, "flags": {"CF": cf}})
    # LOOP/JCXZ with CX 0/1 and LOOPE/LOOPNE on ZF; INTO on OF.
    for code in (b"\xe2\x10", b"\xe1\x10", b"\xe0\x10", b"\xe3\x10", b"\xe2\xfe", b"\xce"):
        for cx in (0, 1, 2):
            for zf in (0, 1):
                for of in (0, 1):
                    h.case(code, f"b:loop{code.hex()}",
                           overrides={"regs": {"cx": cx}, "flags": {"ZF": zf, "OF": of}})
    # STI, CLI from either IF (the 68k side's G_IRQ re-arm, runtime.h).
    for code in (b"\xfb", b"\xfa"):
        for _ in range(32):
            h.case(code, f"b:if{code.hex()}")
    # REP fast path guard (D11): SI/DI ranges ending at FFFFh (fast) or
    # 10000h (element body: SI/DI wrap), only SI or only DI at the edge, CX
    # up to FFFFh, either DF.
    for b in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAE, 0xAF):
        n = 1 + (b & 1)
        for pre in (b"\xf3", b"\xf2"):
            for cx in (1, 3, 0x7FFF, 0x8000, 0xFFFF):
                if cx > 3 and pre != b"\xf3":
                    continue
                for slack in (-1, 0):
                    off = max(0, 0x10000 - n * cx) + slack & 0xFFFF
                    pairs = ((off, off), (0, off), (off, 0)) if cx <= 3 else ((off, off),)
                    for si, di in pairs:
                        for df in ((0, 1) if cx <= 3 else (0,)):
                            h.case(pre + bytes([b]), f"b:repguard{b:02x}",
                                   overrides={"regs": {"cx": cx, "si": si, "di": di},
                                              "flags": {"DF": df}})
    # REPE/REPNE CMPS/SCAS stopping at the first, a middle, the last or no
    # element; words differ in both bytes (flags from the little-endian pair).
    for b in (0xA6, 0xA7, 0xAE, 0xAF):
        n = 1 + (b & 1)
        for pre in (b"\xf3", b"\xf2"):
            for at in (0, 4, 8, None):
                same, other = b"\x41" * n, b"\x40\x42"[:n] if n == 2 else b"\x40"
                fill, stop = (same, other) if pre == b"\xf3" else (other, same)
                dst = [fill] * 9
                if at is not None:
                    dst[at] = stop
                h.case(pre + bytes([b]), f"b:repstop{b:02x}",
                       overrides={"regs": {"cx": 9, "ax": 0x4141, "si": 0x100, "di": 0x200,
                                           "ds": 0x5000, "es": 0x5000},
                                  "flags": {"DF": 0},
                                  "mem": [(0x50100, same * 9), (0x50200, b"".join(dst))]})
    # Overlapping REP MOVS (the copy propagates as on the x86).
    for b in (0xA4, 0xA5):
        for d in (-1, 1, 2, 3):
            h.case(b"\xf3" + bytes([b]), f"b:repoverlap{b:02x}",
                   overrides={"regs": {"cx": 8, "si": 0x100, "di": 0x100 + d,
                                       "ds": 0x5000, "es": 0x5000}, "flags": {"DF": 0}})

    address_guard_cases(h)
    carry_reuse_cases(h)
    byteorder_cases(h)
    crossflag_cases(h)
    compact_mask_cases(h)
    dead_dx_cases(h)
    dead_dx_memory_cases(h)
    dead_dx_flag_cases(h)
    high_byte_write_cases(h)
    high_byte_write_cases(h, bytes.fromhex("83d500"))
    byte_copy_cases(h)


def address_guard_cases(h):
    """T2: single/base+index EAs, both guard edges and 16-bit wrapping."""
    eas = (("bx", "si"), ("bx", "di"), ("bp", "si"), ("bp", "di"),
           ("si",), ("di",), ("bp",), ("bx",))
    for rm, names in enumerate(eas):
        for disp in (-0x8000, -0x7f, -1, 0, 1, 0x7f, 0x7fff):
            for width in (1, 2):
                lo = max(0, -disp)
                hi = min(0xffff * len(names), 0x10000 - width - disp)
                values = {0, 1, 0x7fff, 0x8000, 0xfffe, 0xffff}
                values.update(x + delta for x in (lo, hi) for delta in (-1, 0, 1))
                if len(names) == 2:
                    values.update((0x10000, 0x10001, 0x1fffe))
                for value in sorted(v for v in values if 0 <= v <= 0xffff * len(names)):
                    regs = dict(cs=0x2000, ds=0x5000, ss=0x6000)
                    regs[names[0]] = min(value, 0xffff)
                    if len(names) == 2:
                        regs[names[1]] = value - regs[names[0]]
                    for store in (False, True):
                        op = (0x88 if store else 0x8a) + (width == 2)
                        code = bytes((op, 0x80 | rm)) + (disp & 0xffff).to_bytes(2, "little")
                        h.case(code * 4, f"b:ea:{rm}:{disp}:{width}:{value}:{store}",
                               n=4, block=True, overrides={"regs": regs, "ip": 0x100})
    # A full or partial write ends the corresponding entry-value proof.
    for change in (b"\x43", b"\xb3\xff", b"\xb7\xff", b"\x46", b"\x47"):
        load = b"\x8b\x80\xff\xff"  # AX <- [BX+SI-1]
        h.case(load * 4 + change + load * 4, "b:ea:base-write", n=9, block=True,
               overrides={"regs": {"bx": 1, "si": 0, "cs": 0x2000,
                                    "ds": 0x5000}, "ip": 0x100})



def carry_reuse_cases(h):
    """T4: carry reuse, X-clobbering operand setup and live non-carry flags."""
    producers = ("01d8", "29d8", "f7d8", "d1e0", "d1e8", "d1f8",
                 "10d8", "18d8", "d1d0", "d1d8")
    consumers = ("11ca", "19ca", "10ec", "18ec", "1317", "1b17",
                 "1300", "134001", "1380ff7f", "1108", "114801",
                 "d1d2", "d1da", "d15001", "d158ff")
    for producer in producers:
        for consumer in consumers:
            for ax, bx, dx in ((0, 0, 0), (0xffff, 1, 0), (0, 1, 0xffff),
                               (0x7fff, 1, 0x7fff), (0x8000, 0xffff, 0x8000),
                               (0xff, 1, 0xff)):
                for cf in (0, 1):
                    h.case(bytes.fromhex(producer + consumer), "b:carry-pair",
                           n=2, block=True, overrides={"regs": {
                               "ax": ax, "bx": bx, "dx": dx, "cx": 0,
                               "si": 0xffff, "ds": 0x5000, "ss": 0x6000,
                               "cs": 0x2000}, "ip": 0x100, "flags": {"CF": cf}})
    for count in (0, 1, 8, 16, 17, 31, 32, 255):
        for consumer in ("d3d2", "d3da", "d35001", "d358ff"):
            for ax in (0, 0x8000, 0xffff):
                h.case(bytes.fromhex("d1e0" + consumer + "11d8"),
                       "b:carry-variable", n=3, block=True, overrides={"regs": {
                           "ax": ax, "bx": 0xffff, "dx": 0x8000, "cx": count,
                           "si": 1, "cs": 0x2000, "ds": 0x5000}, "ip": 0x100})
    # A live carry consumer's result feeds another one, then PUSHF observes flags.
    for ax in (0, 1, 0x7fff, 0x8000, 0xffff):
        h.case(bytes.fromhex("01d8 11ca 11de 9c"), "b:carry-chain", n=4,
               block=True, overrides={"regs": {"ax": ax, "bx": 1, "dx": 0xffff,
                   "cx": 0, "si": 0xffff, "sp": 0xfffe, "cs": 0x2000}, "ip": 0x100})



def byteorder_cases(h):
    """T3: raw word chains, partial reads, EA uses, aliases and stack wrap."""
    chains = (
        ("8b07", "894502", "894504"),       # load/store/store, native exit
        ("8b07", "89c2", "8915", "b80000", "ba0000"),
        ("58", "50", "50", "b80000"),     # pop and repeated push
        ("8905", "b80000"),                 # dead store source
        ("50", "b80000"),                   # dead push source
        ("8b07", "8905", "b001"),          # AL write must restore AH
        ("8b07", "8905", "b401"),          # AH write must restore AL
        ("8b07", "8905", "01d0", "9c"),  # arithmetic flags from native AX
        ("8b1d", "891d", "8b07"),          # raw BX then address use
        ("8b6d00", "896d02", "8b4600"),    # raw BP then SS address use
        ("8b07", "89c2", "8915", "01d0"),
        ("8b07", "894502", "8b07", "894504", "b80000"),
        ("8b07", "8905", "9c"),            # flags remain unchanged
        ("8b07", "8905", "8bd0", "8915"),
        ("8b07", "50", "5a", "8915"),
    )
    for words in chains:
        for edge in (0, 1, 0x7fff, 0x8000, 0xfffe, 0xffff):
            for value in (0x0001, 0x0100, 0x80ff, 0xff80):
                for cf in (0, 1):
                    regs = dict(cs=0x2000, ds=0x5000, ss=0x7000, es=0x9000,
                                bx=edge, si=edge, di=edge, bp=edge, sp=edge,
                                ax=value, dx=value ^ 0xffff)
                    h.case(bytes.fromhex("".join(words)), "b:byteorder-chain",
                           n=len(words), block=True, overrides={"regs": regs,
                           "ip": 0x100, "flags": {"CF": cf}, "mem": [
                               (0x50000 + edge, value.to_bytes(2, "little"))]})
    # Both one- and two-register EAs with displacement wrap; source equals base.
    for rm in range(8):
        for disp in (-0x8000, -1, 0, 1, 0x7fff):
            for base in (0, 1, 0xfffe, 0xffff):
                load = bytes((0x8b, 0x80 | rm)) + (disp & 0xffff).to_bytes(2, "little")
                store = bytes((0x89, 0x80 | rm)) + (disp & 0xffff).to_bytes(2, "little")
                h.case(load + store + store + b"\xb8\x00\x00", "b:byteorder-ea",
                       n=4, block=True, overrides={"regs": dict(cs=0x2000,
                       ds=0x5000, ss=0x7000, bx=base, bp=base, si=1, di=1), "ip": 0x100})


def crossflag_cases(h):
    """T4: every branch condition, flag combination and displacement edge."""
    for cc in range(16):
        for bits in range(32):
            flags = dict(zip(("CF", "ZF", "SF", "OF", "PF"),
                             ((bits >> k) & 1 for k in range(5))))
            for disp in (-128, 0, 127):
                h.case(bytes((0x70 + cc, disp & 0xff)), "b:cross-flag-reader",
                       overrides={"regs": {"cs": 0x2000}, "ip": 0x100, "flags": flags})


def compact_mask_cases(h):
    """T6: zero-extended sources, dirty scratch/results, and preserved flags."""
    for value in (0, 1, 0x7fff, 0x8000, 0xfffe, 0xffff):
        regs = dict(cs=0x2000, ds=0x5000, ss=0x7000, es=0x9000,
                    ax=value, cx=value, dx=value, bx=value, bp=value,
                    si=value, di=value, sp=0xfffe)
        # Every data/address register as a segment source and a move source.
        for src in range(8):
            for op in (bytes((0x8e, 0xd8 | src)), bytes((0x8e, 0xc0 | src)),
                       bytes((0x89, 0xc0 | src << 3)), bytes((0x87, 0xc0 | src << 3))):
                h.case(op + b"\x9c", "b:compact-source", n=2, block=True,
                       overrides={"regs": regs, "ip": 0x100})
        # Multiplication and signed extension must not inherit a stale zero proof.
        for op in ("f7e3", "f7eb", "69c3ffff", "69c30080", "98", "99",
                   "c1e010", "c1e810", "c1f810", "c1c008", "c1c808"):
            h.case(bytes.fromhex(op), "b:compact-dirty", overrides={"regs": regs, "ip": 0x100})
        for op in ("8cc6", "8cd7", "5e", "5f", "d1e0", "d1e8", "d1f8", "d1c0", "d1c8"):
            h.case(bytes.fromhex(op), "b:compact-ccr", overrides={"regs": regs, "ip": 0x100})
        for count in (0, 1, 16, 31):
            h.case(bytes.fromhex("d3e0 8ed8 9c"), "b:compact-shift-segment", n=3,
                   block=True, overrides={"regs": {**regs, "cx": count}, "ip": 0x100})


def dead_dx_cases(h):
    """T7: normal/fault results, live flags, aliases, partial and full writes."""
    tails = (("ba3412 050100", 2), ("ba3412 9c", 2),
             ("89d1 ba3412 050100", 3), ("b234 b656 050100", 3),
             ("f7e3 ba3412 050100", 3), ("f7e2 ba3412 050100", 3),
             ("99 050100", 2))
    for op in ("f7e3", "f7eb", "f7f3", "f7fb"):
        for ax in (0, 1, 0x7fff, 0x8000, 0xffff):
            for dx in (0, 1, 0x7fff, 0xffff):
                for bx in (0, 1, 2, 0xffff):
                    for tail, n in tails:
                        h.case(bytes.fromhex(op + tail), "b:dead-dx", n=n+1,
                               block=True, overrides={"regs": dict(cs=0x2000,
                               ss=0x7000, sp=0xfffe, ax=ax, dx=dx, bx=bx), "ip": 0x100})
    # A byte multiply preserves DX, but DL/DH sources still consume it.
    for byte_mul in ("f6e3", "f6e2", "f6e6"):
        for value in (0, 1, 0x8000, 0xffff):
            h.case(bytes.fromhex("f7e3"+byte_mul+"ba3412 050100"),
                   "b:dead-dx-byte", n=4, block=True, overrides={"regs":
                   dict(cs=0x2000, ax=value, dx=value, bx=0xffff), "ip": 0x100})


def dead_dx_memory_cases(h):
    """T7: every word memory form, two-register sums and FFFFh accesses."""
    eas = (("bx", "si"), ("bx", "di"), ("bp", "si"), ("bp", "di"),
           ("si",), ("di",), ("bp",), ("bx",))
    for operation in (4, 5, 6, 7):
        for rm, names in enumerate(eas):
            for edge in (0, 0xffff):
                for disp in (-1, 1):
                    regs = dict(cs=0x2000, ds=0x5000, ss=0x7000, ax=0x8000,
                                dx=0 if edge else 1, cx=0, sp=0xfffe)
                    regs.update({name: edge for name in names})
                    offset = (sum(regs[name] for name in names) + disp) & 0xffff
                    segment = regs["ss" if "bp" in names else "ds"]
                    code = bytes((0xf7, 0x80 | operation << 3 | rm)) + (disp & 0xffff).to_bytes(2, "little")
                    for tail, count in (("ba3412 050100", 3), ("89d1 ba3412 050100", 4)):
                        h.case(code + bytes.fromhex(tail), "b:dead-dx-memory", n=count,
                               block=True, overrides={"regs": regs, "ip": 0x100,
                               "mem": [(segment * 16 + offset, edge.to_bytes(2, "little"))]})


def dead_dx_flag_cases(h):
    """T7: consume only defined MUL flags while DX is overwritten first."""
    for op in ("f7e3", "f7eb"):
        for ax in (0, 1, 0x7fff, 0x8000, 0xffff):
            for bx in (0, 1, 0x8000, 0xffff):
                for dx in (0, 0xffff):
                    # ADC reads CF; CLC kills CF before JO reads only OF.
                    for tail, n in (("ba3412 83d100", 3), ("ba3412 f8 7002", 4)):
                        h.case(bytes.fromhex(op+tail), "b:dead-dx-live-flags", n=n,
                               block=True, overrides={"regs": dict(cs=0x2000,
                               ax=ax, bx=bx, dx=dx, cx=1), "ip": 0x100})


def high_byte_write_cases(h, tail=bytes.fromhex("9c")):
    """T8: all high-byte destinations, source aliases, flags and memory EAs."""
    def case(code, regs, memory=()):
        h.case(code + tail, "b:high-byte-write", n=2,
               block=True, overrides={"regs": dict(cs=0x2000, ds=0x5000,
               ss=0x7000, sp=0xfffe, **regs), "ip": 0x100, "mem": list(memory)})
    for dest in range(4, 8):
        for value in (0, 1, 0x7f, 0x80, 0xff):
            regs = dict(ax=0xa55a, cx=0x5aa5, dx=0xff00, bx=0x00ff,
                        bp=0xffff, si=1, di=0)
            case(bytes((0xb0 + dest, value)), regs)
            for src in range(8):
                for op in (0x88, 0x86, 0x00, 0x10, 0x18, 0x28, 0x20, 0x08, 0x30):
                    changed = dict(regs)
                    name = ("ax", "cx", "dx", "bx")[src % 4]
                    shift = 8 if src >= 4 else 0
                    changed[name] = (changed[name] & ~(255 << shift)) | value << shift
                    case(bytes((op, 0xc0 | src << 3 | dest)), changed)
            for op, ext in ((0xfe, 0), (0xfe, 1), (0xf6, 2), (0xf6, 3)):
                case(bytes((op, 0xc0 | ext << 3 | dest)), regs)
            for ext in range(8):
                if ext != 6:
                    case(bytes((0xd0, 0xc0 | ext << 3 | dest)), regs)
        for rm, names in enumerate((("bx", "si"), ("bx", "di"), ("bp", "si"),
                                   ("bp", "di"), ("si",), ("di",), ("bp",), ("bx",))):
            for edge in (0, 0x7fff, 0xffff):
                regs = dict(ax=0xa55a, cx=0x5aa5, dx=0xff00, bx=1,
                            bp=1, si=1, di=1)
                regs[names[0]] = (edge - sum(regs[n] for n in names[1:])) & 0xffff
                for override in (b"", b"\x2e"):
                    segment = 0x2000 if override else 0x7000 if "bp" in names else 0x5000
                    for op in (0x8a, 0x86, 0x02, 0x12, 0x1a, 0x2a, 0x22, 0x0a, 0x32):
                        case(override + bytes((op, 0x80 | dest << 3 | rm, 0, 0)),
                             regs, ((segment * 16 + edge, b"\x80"),))
    for flags in (0x202, 0x203, 0x2d7, 0xad7):
        h.case(bytes.fromhex("9f 9c"), "b:high-byte-lahf", n=2, block=True,
               overrides={"regs": dict(cs=0x2000, ss=0x7000, sp=0xfffe,
               ax=0xa55a), "flags": {f: flags >> FLAG_BIT[f] & 1 for f in FLAGS}, "ip": 0x100})
    # A high-byte destination must keep X available for a following CF reader.
    for dest in range(4, 8):
        for value in (0, 0x7f, 0x80, 0xff):
            h.case(bytes((0x80, 0xc0 | dest, value, 0x83, 0xd1, 0)),
                   "b:high-byte-carry", n=2, block=True, overrides={"regs":
                   dict(cs=0x2000, ax=0xffff, cx=0xffff, dx=0xffff, bx=0xffff), "ip": 0x100})


def byte_copy_cases(h):
    """T10: every byte-register pair, aliases, preserved neighbors and flags."""
    names = ("ax", "cx", "dx", "bx")
    for dest in range(8):
        for src in range(8):
            for value in (0, 1, 0x7f, 0x80, 0xff):
                for word in (0x202, 0x203, 0x2d7, 0xad7):
                    regs = dict(cs=0x2000, ss=0x7000, sp=0xfffe, ax=0xa55a,
                                cx=0x5aa5, dx=0xff00, bx=0x00ff, bp=0x1234)
                    shift = 8 if src >= 4 else 0
                    name = names[src % 4]
                    regs[name] = (regs[name] & ~(255 << shift)) | value << shift
                    code = bytes((0x88, 0xc0 | src << 3 | dest))
                    flags = {f: word >> FLAG_BIT[f] & 1 for f in FLAGS}
                    h.case(code + b"\x9c", "b:byte-copy", n=2, block=True,
                           overrides={"regs": regs, "flags": flags, "ip": 0x100})
            for cf in (0, 1):
                code = bytes((0xf9 if cf else 0xf8, 0x88, 0xc0 | src << 3 | dest, 0x83, 0xd5, 0))
                h.case(code, "b:byte-copy-carry", n=3, block=True, overrides={
                       "regs": dict(cs=0x2000, ax=0xa55a, cx=0x5aa5,
                       dx=0xff00, bx=0x00ff, bp=0xffff), "ip": 0x100})
    # The byte-register optimization must not consume memory or word forms.
    for reg in range(8):
        for rm, bases in enumerate((("bx", "si"), ("bx", "di"), ("bp", "si"),
                                   ("bp", "di"), ("si",), ("di",), ("bp",), ("bx",))):
            regs = dict(cs=0x2000, ds=0x5000, ss=0x7000, sp=0xfffe,
                        ax=0xa55a, cx=0x5aa5, dx=0xff00, bx=0xffff,
                        bp=0xffff, si=1, di=1)
            offset = (sum(regs[n] for n in bases) + 1) & 0xffff
            segment = regs["ss" if "bp" in bases else "ds"]
            for op in (0x88, 0x8a):
                h.case(bytes((op, 0x80 | reg << 3 | rm, 1, 0, 0x9c)),
                       "b:byte-copy-memory-guard", n=2, block=True, overrides={
                       "regs": regs, "ip": 0x100,
                       "mem": [(segment * 16 + offset, b"\x80")]})
        h.case(bytes((0x89, 0xc0 | reg << 3 | reg, 0x9c)), "b:byte-copy-word-guard",
               n=2, block=True, overrides={"regs": dict(cs=0x2000, ss=0x7000, sp=0xfffe), "ip": 0x100})


def run(argv: list[str] | None = None, quiet: bool = False, harness=None) -> Harness:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--states", type=int, default=24, help="random states per form sample")
    ap.add_argument("--space", type=int, default=48, help="random encodings per opcode byte")
    ap.add_argument("--blocks", type=int, default=4000)
    ap.add_argument("--only", default="", help="comma list of corpora: forms,space,boundary,blocks")
    ap.add_argument("--shard", default="0/1", help="K/N: only the forms, opcode bytes and blocks "
                    "whose index is K mod N (make test runs shards in parallel)")
    args = ap.parse_args(argv)
    shard, shards = map(int, args.shard.split("/"))

    def mine(index: int) -> bool:
        return index % shards == shard

    only = set(args.only.split(",")) if args.only else {"forms", "space", "boundary", "blocks"}
    h = (harness or Harness)(args.seed)
    mods = image.load()
    units = cfg.build(mods)
    if "forms" in only:
        forms = defaultdict(list)
        for name, u in units.items():
            for off, n in sorted(u.insns.items()):
                if n.op != "hlt":
                    forms[form_key(n)].append(n.raw)
        for index, key in enumerate(sorted(forms, key=str)):
            if not mine(index):
                continue
            samples = forms[key]
            picks = h.rng.sample(samples, min(4, len(samples)))
            for raw in picks:
                for _ in range(args.states):
                    h.case(raw, f"f:{key[0]}{key[1] or ''}")
        if not quiet:
            print(f"forms {len(forms)}")
    if "space" in only:
        for first in range(256):
            if first in UNSUPPORTED or not mine(first):
                continue
            for _ in range(args.space):
                raw = bytes([first]) + bytes(h.rng.randrange(256) for _ in range(7))
                try:
                    n = decode(raw, 0)
                except DecodeError:
                    continue
                if n.op == "hlt":
                    continue
                h.case(raw[:n.size], f"s:{n.op}{n.width or ''}")
    if "boundary" in only and shard == 0:
        boundary(h)
    if "blocks" in only:
        starts = [(name, off) for name, u in units.items() for off in u.insns]
        for index in range(args.blocks):
            if not mine(index):
                continue
            name, off = h.rng.choice(starts)
            u, data = units[name], mods[name].data
            want = h.rng.randrange(2, 9)
            run, k = [], off
            while len(run) < want and k in u.insns and u.cs.get(k) == u.cs[off]:
                n = u.insns[k]
                run.append(n)
                if n.op in ("jmp", "jmpf", "jcc", "call", "callf", "ret", "retf", "iret", "int",
                            "loop", "loope", "loopne", "jcxz", "hlt", "into", "int3") \
                        or k in u.manager_calls:
                    break
                k += n.size
            if len(run) < 2 or any(n.op == "hlt" for n in run):
                continue
            code = bytes(data[off:off + sum(n.size for n in run)])
            h.case(code, "blocks", n=len(run), overrides={"ip": run[0].ip}, block=True)
    return h


def main() -> int:
    h = run()
    total = sum(h.count.values())
    groups = Counter()
    for k, v in h.count.items():
        groups[k.split(":")[0]] += v
    print("cases", total, dict(groups))
    if h.skipped:
        print("not compared:", dict(h.skipped))
    if h.undefined:
        print("undefined-flag reads:", dict(h.undefined))
    for b in h.bad[:40]:
        print(b)
    print(f"{len(h.bad)} mismatches")
    return 1 if h.bad or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
