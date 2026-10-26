#!/usr/bin/env python3
"""Instruction and short-block differential of the 68020 lowering (gate 4):
original bytes in Unicorn x86-16 vs the generated 68020 code in Unicorn 68020.

Same corpora and states as tests/x86_diff.py (forms, space, boundary, blocks).
Each case is lowered in test mode (every transfer leaves through a stub that
reports CS:IP; flags live at the end of the case), assembled with vasm in
batches and run on the 68020 core over the same guest RAM (reversed below a6
as the register contract maps it, SP/BP mirrored; translator/lower.py; guest
registers enter with upper words 0, FFFFh or random). Compared: registers
(low words), segment registers, CS:IP, defined
flags (undefined ones masked by the IR), FLAGS bits 12-14, every written byte,
the OUT sequence and the raised interrupt/fault. Checked on the 68k side alone:
the poll-point contract of runtime.h (G_IRQ never set without rt_irq_pending;
once IF is set, a pending interrupt re-arms G_IRQ).

Shared by both sides: the case bytes and state; the 68k side never sees the
x86 results or the IR (the IR only supplies the undefined-flag mask).

--record PATH saves each case's x86 side (IR mask or skip, Unicorn result);
--replay PATH reuses it for a case whose state and bytes match, under the
same sources and Unicorn, and runs any other case live (m68k_sabotage sets
REPLAY: the plants reuse make test's boundary run).
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import os
import pickle
import random
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uc as U  # noqa: E402
import x86_diff as X  # noqa: E402
from translator import flags as F, region  # noqa: E402
from translator.decode import DecodeError, decode  # noqa: E402
from translator.interp import State, UndefinedFlag, step  # noqa: E402
from translator.ir import FLAG_BIT, FLAGS, STATUS  # noqa: E402
from translator.lower import Ctx, LowerError, hx  # noqa: E402
from translator.support import HELPERS, equates  # noqa: E402

VASM = Path(os.environ.get("VASM") or Path.home() / ".local/vasmm68k_mot")
GUEST_LO = 0x100000         # lowest host byte of guest RAM
TOP = GUEST_LO + X.RAM + 0x10000 - 1    # a6: guest linear L at TOP - L
STATE = TOP + 1             # state block page
CODE = 0x400000
STUB = 0x300000
STACK = 0x380000
PENDING = STATE + 0x800     # rt_irq_pending
STUBS = ("T_JUMP", "T_CALL", "T_JUMPF", "T_CALLF", "T_INT", "T_FAULT", "T_HALT", "T_END",
         "rt_in8", "rt_in16", "rt_out8", "rt_out16", "T_RET", "T_TRAP")
STUB_AT = {n: STUB + 4 * k for k, n in enumerate(STUBS)}
REGS = ("ax", "bx", "cx", "dx", "sp", "bp", "si", "di")
MIRROR = {"sp": 0x7FFF, "bp": 0x7FFF}   # held as offset ^ 7FFFh
M68 = {"ax": "d0", "cx": "d1", "dx": "d2", "bx": "d3", "sp": "d4", "bp": "d5", "si": "a4",
       "di": "a5"}
BATCH = 1500
REPLAY: Path | None = None   # set by m68k_sabotage


ASM_DEFS = ("-DSWOTL_SYNC=1",)   # the sync build: poll checks host runs deliver at (irq-plan I8)


def assemble(src: str, out: Path) -> bytes:
    s = out.with_suffix(".s")
    s.write_text(src)
    r = subprocess.run([str(VASM), "-quiet", "-m68020", *ASM_DEFS, "-Fbin", "-o", str(out), str(s)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"vasm failed:\n{r.stdout}{r.stderr}"[:4000])
    return out.read_bytes()


def ccr_image(flags: dict) -> int:
    return flags["CF"] | flags["OF"] << 1 | flags["ZF"] << 2 | flags["SF"] << 3


def lower_case(insns, cs: int, tag: str, end_ip: int, **extra) -> tuple[list[str], Counter]:
    """Test-mode 68k text for a straight-line run of decoded instructions
    (`extra`: Ctx fields every instruction gets)."""
    lives = F.seq_lives(insns)
    stats = Counter()

    def ctx_for(k):
        return Ctx(cs=hx(cs), label=f"{tag}_{k}", **extra)

    lines, cold = [f"{tag}:"], []
    for k, lw in enumerate(F.plan(insns, lives, set(), ctx_for)):
        lines.append(f"{tag}_{k}:")
        lines.extend(lw.out)
        cold += lw.cold
        stats.update(lw.stats)
    lines += [f"{tag}_end:", f"\tmove.l #{hx(end_ip)},d7", "\tjmp T_END"]
    return lines + cold, stats


def lower_region_case(insns, cs: int, tag: str, end_ip: int):
    """R6: the run behind a region guard, as a guarded copy (direct [bp+d]) with
    the exact lowering as its fallback; None where no region applies."""
    rng = region.bp_range(insns)
    if rng is None or any(region.writes_bp(i) for i in insns):
        return None
    lives = F.seq_lives(insns)
    stats = Counter()
    lines, cold = [f"{tag}:"] + region.guard(rng, f"{tag}_x"), []
    for k, lw in enumerate(F.plan(insns, lives, set(),
                                  lambda k: Ctx(cs=hx(cs), label=f"{tag}_{k}", bp_direct=True))):
        lines.append(f"{tag}_{k}:")
        lines.extend(lw.out)
        cold += lw.cold
        stats.update(lw.stats)
    lines += [f"{tag}_end:", f"\tmove.l #{hx(end_ip)},d7", "\tjmp T_END"] + cold
    exact, _ = lower_case(insns, cs, f"{tag}_x", end_ip)
    stats["region case"] += 1
    return lines + exact, stats


def loads_segment(i) -> bool:
    """mov/pop to ES, DS or SS, les, lds (lower.putseg)."""
    o = i.operands[0] if i.operands else None
    return i.op in ("les", "lds") or i.op in ("mov", "pop") and getattr(o, "name", None) in \
        ("es", "ds", "ss")


def irq_diffs(f: dict, irq: int, pending: int) -> list[str]:
    """runtime.h: G_IRQ only with rt_irq_pending; with IF set, pending means G_IRQ."""
    if irq and not pending:
        return [f"G_IRQ {irq} without rt_irq_pending"]
    if f["IF"] and pending and not irq:
        return ["IF set, G_IRQ not re-armed"]
    return []


class M68k:
    """Unicorn 68020 with guest RAM, state block, stubs and native stack."""

    def __init__(self, background: bytes, stubs: dict[str, int] | None = None,
                 compute_services=frozenset()):
        assert len(background) == X.RAM
        self.bg = background
        self.stub_at = stubs or STUB_AT
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(STATE, 0x1000)
        e.map(GUEST_LO, TOP + 1 - GUEST_LO)
        self.gwrite(0, background)
        e.map(STUB, 0x1000)
        e.write(STUB, b"\x4a\xfc\x4e\x75" * len(self.stub_at))  # illegal; rts
        e.map(STACK - 0x10000, 0x20000)
        e.map(CODE, 0x800000)
        self.writes: set[int] = set()
        self.outs: list = []
        self.stop: str | None = None
        self.irq_rng = random.Random(1)
        self.upper_rng = random.Random(4)   # guest registers' upper words (speed-plan R4)
        # rt_irq called at a poll point: None stops there (a block exit); a
        # list records (d6, d7) and returns, G_IRQ and rt_irq_pending cleared
        # (an interrupt taken) or, with irq_keep, left set (the bench watch).
        self.irq_calls: list | None = None
        self.irq_keep = False

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            if GUEST_LO <= addr <= TOP:
                self.writes.update(range(TOP - addr - size + 1, TOP - addr + 1))
            return True

        by_addr = {a: n for n, a in self.stub_at.items()}
        self.extra_stops: dict[int, str] = {}
        self.inside: set[int] = set()
        self.entry: int | None = None

        @U.CODE_CB
        def code(h, addr, size, user):
            n = by_addr.get(addr)
            if addr == self.entry:
                self.entry = None  # the case starts here; a later visit is a back edge
                return
            if n is None:
                n = self.extra_stops.get(addr)
                if n is None or addr in self.inside:
                    return
            if n == "rt_irq" and self.irq_calls is not None:
                self.irq_calls.append((self.r("d6"), self.r("d7")))
                if not self.irq_keep:
                    self.e.write(STATE + 8, b"\0")
                    self.e.write(PENDING, b"\0")
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in ("rt_in8", "rt_in16"):
                port = self.r("d7") & 0xFFFF
                w = 8 if n == "rt_in8" else 16
                v = X.port_value(port, w // 8)
                d6 = self.r("d6")
                self.e.reg_write(U.M68K["d6"], d6 & ~(0xFF if w == 8 else 0xFFFF) | v)
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in ("rt_out8", "rt_out16"):
                w = 8 if n == "rt_out8" else 16
                self.outs.append((self.r("d7") & 0xFFFF, w, self.r("d6") & ((1 << w) - 1)))
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in compute_services:  # d7=0: exact fallback, as x86
                self.e.reg_write(U.M68K['d7'], 0)
                self.e.reg_write(U.M68K['pc'], addr + 2)
            elif n.startswith("rt_hle_"):  # EQ: the guest code runs (as x86)
                self.e.reg_write(U.M68K["sr"], self.r("sr") | 4)
                self.e.reg_write(U.M68K["pc"], addr + 2)
            else:
                self.stop = n
                U.uc.uc_emu_stop(h)

        e.hook(U.HOOK_MEM_WRITE, write)
        e.hook(U.HOOK_CODE, code)

    def r(self, name: str) -> int:
        return self.e.reg_read(U.M68K[name])

    def gread(self, a: int, n: int) -> bytes:
        """Guest bytes a..a+n-1 in guest order."""
        return self.e.read(TOP - a - n + 1, n)[::-1]

    def gwrite(self, a: int, data: bytes) -> None:
        self.e.write(TOP - a - len(data) + 1, bytes(data)[::-1])

    def load(self, image: bytes) -> None:
        self.e.write(CODE, image)
        self.e.flush()

    def run(self, entry: int, case, rng, skip_entry: bool = True, init: dict | None = None,
            irq: bool = True, posted: bool = False):
        """irq: rt_irq_pending mostly set, G_IRQ as rt_irq leaves it (IF ? pending : 0);
        otherwise both clear (code with poll points), or with `posted` both set (an
        interrupt posted before a poll point)."""
        regs, flags, flagsx, ip, patches = case
        e = self.e
        for a, data in patches:
            self.gwrite(a, data)
        for r in REGS:   # upper words undefined (R4): 0, FFFFh or random
            hi = (0, 0xFFFF, self.upper_rng.randrange(1, 0xFFFF))[self.upper_rng.randrange(3)]
            e.reg_write(U.M68K[M68[r]], hi << 16 | regs[r] ^ MIRROR.get(r, 0))
        for s, a in (("es", "a1"), ("ss", "a2"), ("ds", "a3")):
            e.reg_write(U.M68K[a], TOP - regs[s] * 16 - 0x7FFF)
        e.reg_write(U.M68K["a6"], TOP)
        for j in ("d6", "d7", "a0"):
            e.reg_write(U.M68K[j], rng.randrange(1 << 32))
        for j, v in (init or {}).items():
            e.reg_write(U.M68K[j], v)
        st = bytearray(16)
        st[16 - 2:16] = bytes([rng.randrange(256) & 0xE0, ccr_image(flags) | rng.randrange(2) << 4])
        st[16 - 3] = 0 if flags["PF"] else 1
        st[16 - 4] = flags["AF"] << 4 | rng.randrange(16) & 0xEF
        st[16 - 5], st[16 - 6], st[16 - 7] = flags["DF"], flags["IF"], flags["TF"]
        st[16 - 10:16 - 8] = flagsx.to_bytes(2, "big")
        for s, at in (("es", 12), ("ss", 14), ("ds", 16)):
            st[16 - at:16 - at + 2] = regs[s].to_bytes(2, "big")
        pending = int(irq and self.irq_rng.randrange(4) != 0)
        st[16 - 8] = pending & flags["IF"]
        if posted:
            pending = st[16 - 8] = 1
        e.write(PENDING, bytes([pending]))
        e.write(STATE, bytes(st))
        sp = STACK - 0x100
        e.write(sp, self.stub_at["T_RET"].to_bytes(4, "big"))
        e.reg_write(U.M68K["sr"], 0)  # user mode first: a7 is then the USP
        e.reg_write(U.M68K["a7"], sp)
        self.writes, self.outs, self.stop = set(), [], None
        self.entry = entry if skip_entry else None
        err = e.start(entry, 0xFFFFFFFF, 4_000_000)
        out = {r: (self.r(M68[r]) ^ MIRROR.get(r, 0)) & 0xFFFF for r in REGS}
        st = e.read(STATE, 16)
        for s, at in (("es", 12), ("ss", 14), ("ds", 16)):
            out[s] = int.from_bytes(st[16 - at:16 - at + 2], "big")
        fl = st[16 - 1]
        f = {"CF": fl & 1, "OF": fl >> 1 & 1, "ZF": fl >> 2 & 1, "SF": fl >> 3 & 1,
             "PF": int(bin(st[16 - 3]).count("1") % 2 == 0), "AF": st[16 - 4] >> 4 & 1,
             "DF": st[16 - 5], "IF": st[16 - 6], "TF": st[16 - 7]}
        fx = int.from_bytes(st[16 - 10:16 - 8], "big")
        d6, d7 = self.r("d6") & 0xFFFF, self.r("d7") & 0xFFFF
        info = {"stop": self.stop, "err": err, "d6": d6, "d7": d7, "d6.l": self.r("d6"),
                "d7.l": self.r("d7"),
                "irq": irq_diffs(f, st[16 - 8], e.read(PENDING, 1)[0]),
                "a7": self.r("a7"), "segbase": {a: self.r(a) for a in ("a1", "a2", "a3")}}
        mem = {a: self.gread(a, 1)[0] for a in sorted(self.writes)}
        return out, f, fx, mem, list(self.outs), set(self.writes), info

    def restore(self, addrs) -> None:
        for a, b in X.spans(addrs):
            self.gwrite(a, self.bg[a:b])


def sources_key() -> str:
    """What a recorded x86 side depends on: the test and translator sources, Unicorn."""
    h = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for f in sorted([*root.glob("tests/*.py"), *root.glob("translator/*.py")]):
        h.update(f.name.encode() + f.read_bytes())
    st = os.stat(U.LIB)
    h.update(f"{U.LIB} {st.st_size} {st.st_mtime_ns}".encode())
    return h.hexdigest()


def runs(mem: dict) -> list:
    """{address: byte} as [(first address, bytes)] (a REP store writes 64 KiB)."""
    out = []
    for a in sorted(mem):
        if out and out[-1][0] + len(out[-1][1]) == a:
            out[-1][1].append(mem[a])
        else:
            out.append((a, bytearray([mem[a]])))
    return [(a, bytes(d)) for a, d in out]


def unruns(rs: list) -> dict:
    return {a + k: v for a, d in rs for k, v in enumerate(d)}


class Harness(X.Harness):
    recording = False   # --record
    keep_failing = True     # keep the source and image of a batch with mismatches
    dirs: list = []         # batch directories made by this process

    def __init__(self, seed: int):
        super().__init__(seed)
        self.m = M68k(self.bg)
        self.pending: list = []
        self.stats = Counter()
        self.lowered = Counter()
        self.tmp = Path(tempfile.mkdtemp(prefix="m68k-diff-"))
        Harness.dirs.append(self.tmp)
        self.nbatch = 0
        self.seed = seed
        self.record: list | None = [] if self.recording else None   # [(case key, x86 side)]
        self.replay: list = []
        self.replayed = self.ncases = 0
        if REPLAY and REPLAY.exists():
            key, rec = pickle.loads(zlib.decompress(REPLAY.read_bytes()))
            if key == sources_key():
                self.replay = rec

    def save(self, path: Path) -> None:
        part = path.with_name(path.name + ".part")
        part.write_bytes(zlib.compress(pickle.dumps((sources_key(), self.record), 5), 1))
        part.replace(path)

    def case(self, code: bytes, label: str, n: int = 1, overrides=None, block=False):
        regs, flags, flagsx, ip = self.state(overrides)
        cs = regs["cs"]
        patches = []
        sp_lin = regs["ss"] * 16 + regs["sp"]
        stack = bytearray(self.rng.randrange(256) for _ in range(8))
        for k in (1, 3, 5, 7):
            stack[k] &= 0xFE
        patches.append((sp_lin, bytes(stack)))
        for a, data in (overrides or {}).get("mem", []):
            patches.append((a(regs) if callable(a) else a, data))
        patches.append((cs * 16 + ip, code))
        case = (regs, flags, flagsx, ip, patches)
        key = hashlib.blake2b(repr((self.seed, n, sorted(regs.items()), sorted(flags.items()),
                                    flagsx, ip, patches)).encode(), digest_size=16).digest()
        k, self.ncases = self.ncases, self.ncases + 1
        if k < len(self.replay) and self.replay[k][0] == key:
            side = self.replay[k][1]
            self.replayed += 1
        else:
            side = self.x86_side(code, n, case)
        if self.record is not None:
            self.record.append((key, side))
        if side[0] == "undefined":
            self.undefined[side[1]] += 1
            return
        if side[0] == "skipped":
            self.skipped[side[1]] += 1
            return
        _, undef, (err, out, fl, mem, ints, outs) = side
        oracle = (err, out, fl, unruns(mem), ints, outs)
        # decode the whole run statically (the 68k side runs what the bytes say)
        insns, k, at = [], 0, ip
        while len(insns) < n:
            i = decode(code, at, k)
            insns.append(i)
            k += i.size
            at = i.next_ip
        tag = f"c{len(self.pending)}"
        try:
            text, st = lower_case(insns, cs, tag, insns[-1].next_ip)
        except LowerError as e:
            self.bad.append(f"{label} {code.hex()}: lowering: {e}")
            return
        self.lowered.update(st)
        self.pending.append((label, code, case, undef, oracle, text, regs, flags, insns[-1].op))
        guarded = lower_region_case(insns, cs, f"c{len(self.pending)}", insns[-1].next_ip)
        if guarded:     # the same case through a region guard (speed-plan R6)
            self.lowered.update(guarded[1])
            self.pending.append((label + " bp-region", code, case, undef, oracle, guarded[0],
                                 regs, flags, insns[-1].op))
        if any(map(loads_segment, insns)):   # segment loads compared first (R30)
            tag = f"c{len(self.pending)}"
            try:
                text, st = lower_case(insns, cs, tag, insns[-1].next_ip, seg_repeat=True)
            except LowerError as e:
                self.bad.append(f"{label} seg-repeat {code.hex()}: lowering: {e}")
                return
            self.lowered.update(st)
            self.pending.append((label + " seg-repeat", code, case, undef, oracle, text,
                                 regs, flags, insns[-1].op))
        if len(self.pending) >= BATCH:
            self.flush()

    def x86_side(self, code: bytes, n: int, case) -> tuple:
        """("undefined", why) | ("skipped", why) | ("ok", undefined flags, Unicorn result)."""
        regs, flags, flagsx, ip, patches = case
        cs = regs["cs"]
        # IR side: only the undefined-flag mask (and decode).
        s = State(dict(regs, flagsx=flagsx), dict(flags), self.mem, ip)
        s.port_in = lambda port, w: X.port_value(port, w // 8)
        for a, data in patches:
            self.mem[a:a + len(data)] = data
        insns = []
        try:
            for _ in range(n):
                ex, insn = step(s)
                insns.append(insn)
                if ex.kind in ("int", "fault", "trap"):
                    break
        except (UndefinedFlag, DecodeError) as e:
            self.reset(patches, s.writes, set())
            return ("undefined", type(e).__name__)
        undef = set(s.undef)
        self.reset(patches, s.writes, set())
        err, out, fl, umem, ints, outs, uwrites = self.oracle.run(case, n)
        code_span = set(range(cs * 16 + ip, cs * 16 + ip + len(code)))
        why = None
        if code_span & uwrites:
            why = "writes its own code"
        elif X.restarted(cs * 16 + ip, len(code), s.writes, ip, out, ints):
            why = "oracle: store into its code's page restarts it"
        elif n == 1 and (dev := X.oracle_deviation(code, regs)):
            why = f"oracle: {dev}"
        if why:
            self.oracle.restore(uwrites | {a for a, d in patches for a in range(a, a + len(d))})
            return ("skipped", why)
        mem = {a: umem.get(a, self.oracle.e.read(a, 1)[0]) for a in set(umem) | uwrites}
        self.oracle.restore(uwrites | set(umem) | {a for a, d in patches
                                                   for a in range(a, a + len(d))})
        return ("ok", undef, (err, out, fl, runs(mem), ints, outs))

    def flush(self) -> None:
        if not self.pending:
            return
        src = [equates()]
        src += [f"{n}\tequ\t${a:x}" for n, a in STUB_AT.items()]
        src.append(f"rt_irq_pending\tequ\t${PENDING:x}")
        src.append(f"\torg\t${CODE:x}")
        src.append("table:")
        src += [f"\tdc.l\tc{k}" for k in range(len(self.pending))]
        for p in self.pending:
            src += p[5]
        src.append(HELPERS)
        self.nbatch += 1
        out = self.tmp / f"batch{self.nbatch}.bin"
        image = assemble("\n".join(src) + "\n", out)
        self.m.load(image)
        bad = len(self.bad)
        for k, (label, code, case, undef, oracle, text, regs, flags, last) in enumerate(self.pending):
            entry = int.from_bytes(image[4 * k:4 * k + 4], "big")
            self.compare(label, code, case, undef, oracle, entry, regs, flags, last)
        self.pending = []
        if len(self.bad) == bad or not self.keep_failing:
            out.unlink()
            out.with_suffix(".s").unlink()

    @staticmethod
    def tidy() -> None:
        """Remove the batch directories that keep no failing batch."""
        for d in Harness.dirs:
            with contextlib.suppress(OSError):
                d.rmdir()
        Harness.dirs.clear()

    def compare(self, label, code, case, undef, oracle, entry, regs, flags, last) -> None:
        err, out, fl, umem, ints, outs = oracle
        mo, mf, mfx, mmem, mouts, mwrites, info = self.m.run(entry, case, self.rng)
        diffs = []
        if err:
            diffs.append(f"unicorn x86 error {err}")
        if info["err"]:
            diffs.append(f"unicorn 68k error {info['err']} stop={info['stop']}")
        diffs += info["irq"]
        stop = info["stop"]
        if "trap" in out or stop == "T_TRAP":
            # TF set by POPF/IRET: a stop at that instruction, nothing else compared
            if stop != "T_TRAP" or info["d7"] != out.get("trap"):
                diffs.append(f"exit {stop} ip={info['d7']:04x} want T_TRAP at {out.get('trap')}")
            self.count[label] += 1
            if diffs:
                self.bad.append(f"{label} {code.hex()}: {'; '.join(diffs)}")
            self.m.restore(set(mwrites) | {a for p, d in case[4] for a in range(p, p + len(d))})
            return
        exc = ints[0] if ints else None
        if exc is not None and exc in X.EXCEPTIONS:
            want = "T_FAULT"
        elif exc is not None:
            want = "T_INT"
        else:
            want = None
        if want and stop != want:
            diffs.append(f"exit {stop} want {want}")
        if want and info["d6"] != exc:
            diffs.append(f"vector 68k={info['d6']} x86={exc}")
        if not want and stop in ("T_INT", "T_FAULT", None):
            diffs.append(f"exit {stop} without x86 interrupt")
        for r in REGS:
            if mo[r] != out[r]:
                diffs.append(f"{r} 68k={mo[r]:04x} x86={out[r]:04x}")
        for sname, a in (("es", "a1"), ("ss", "a2"), ("ds", "a3")):
            if mo[sname] != out[sname]:
                diffs.append(f"{sname} 68k={mo[sname]:04x} x86={out[sname]:04x}")
            if info["segbase"][a] != TOP - out[sname] * 16 - 0x7FFF:
                diffs.append(f"{sname} base {info['segbase'][a]:x}")
        # CS:IP
        far = stop in ("T_JUMPF", "T_CALLF") or stop == "T_RET" and last in ("retf", "iret")
        mcs = info["d6"] if far else regs["cs"]
        if stop == "T_RET" and last in ("retf", "iret"):
            mcs = info["d7.l"] >> 16
        mip = info["d7"]
        if mip != out["ip"]:
            diffs.append(f"ip 68k={mip:04x} x86={out['ip']:04x} ({stop})")
        if mcs != out["cs"]:
            diffs.append(f"cs 68k={mcs:04x} x86={out['cs']:04x}")
        for f in FLAGS:
            if f not in undef and mf[f] != fl >> FLAG_BIT[f] & 1:
                diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
        if (mfx >> 12) & 7 != (fl >> 12) & 7:
            diffs.append(f"flags[14:12] 68k={mfx >> 12 & 7} x86={fl >> 12 & 7}")
        for a in sorted(set(umem) | mwrites):
            x = umem.get(a, self.bg[a] if a not in {p for p, d in case[4] for p in range(p, p + len(d))}
                         else None)
            m = mmem.get(a)
            if m is None:
                m = self.m.gread(a, 1)[0]
            if x is None:
                x = next(d[a - p] for p, d in case[4] if p <= a < p + len(d))
            if m != x:
                diffs.append(f"mem {a:05x} 68k={m:02x} x86={x:02x}")
                break
        if mouts != outs:
            diffs.append(f"out 68k={mouts} x86={outs}")
        if stop in (None,) and not info["err"]:
            diffs.append("no exit (instruction limit)")
        self.count[label] += 1
        if diffs:
            st = " ".join(f"{k}={v:04x}" for k, v in regs.items())
            fs = "".join(f for f in FLAGS if flags[f])
            self.bad.append(f"{label} {code.hex()} ip={case[3]:04x} [{st} {fs}]: "
                            f"{'; '.join(diffs[:6])}")
        touched = set(mwrites) | {a for p, d in case[4] for a in range(p, p + len(d))}
        self.m.restore(touched)


atexit.register(Harness.tidy)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    record = None
    if "--record" in argv:
        k = argv.index("--record")
        record = Path(argv[k + 1])
        del argv[k:k + 2]
    if "--replay" in argv:
        global REPLAY
        k = argv.index("--replay")
        REPLAY = Path(argv[k + 1])
        del argv[k:k + 2]
    Harness.recording = record is not None
    h = X.run(argv, harness=Harness)
    h.flush()
    if record:
        h.save(record)
    total = sum(h.count.values())
    groups = Counter()
    for k, v in h.count.items():
        groups[k.split(":")[0]] += v
    print("cases", total, dict(groups), "batches", h.nbatch)
    if h.skipped:
        print("not compared:", dict(h.skipped))
    if h.undefined:
        print("skipped (IR reads undefined flag / undecodable):", dict(h.undefined))
    print("lowering counters:", dict(h.lowered))
    for b in h.bad[:40]:
        print(b)
    print(f"{len(h.bad)} mismatches")
    return 1 if h.bad or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
