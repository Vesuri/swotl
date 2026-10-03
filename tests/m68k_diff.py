#!/usr/bin/env python3
"""Instruction and short-block differential of the 68020 lowering (gate 4):
original bytes in Unicorn x86-16 vs the generated 68020 code in Unicorn 68020.

Same corpora and states as tests/x86_diff.py (forms, space, boundary, blocks).
Each case is lowered in test mode (every transfer leaves through a stub that
reports CS:IP; flags live at the end of the case), assembled with vasm in
batches and run on the 68020 core over the same guest RAM (byte-exact,
little-endian, at a6). Compared: registers, segment registers, CS:IP, defined
flags (undefined ones masked by the IR), FLAGS bits 12-14, every written byte,
the OUT sequence and the raised interrupt/fault.

Shared by both sides: the case bytes and state; the 68k side never sees the
x86 results or the IR (the IR only supplies the undefined-flag mask).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uc as U  # noqa: E402
import x86_diff as X  # noqa: E402
from translator import flags as F  # noqa: E402
from translator.decode import DecodeError, decode  # noqa: E402
from translator.interp import State, UndefinedFlag, step  # noqa: E402
from translator.ir import FLAG_BIT, FLAGS, STATUS  # noqa: E402
from translator.lower import Ctx, LowerError, hx  # noqa: E402
from translator.support import HELPERS, equates  # noqa: E402

VASM = Path.home() / ".local/vasmm68k_mot"
GUEST = 0x100000            # a6: guest linear 0
STATE = GUEST - 0x1000      # state block page
CODE = 0x400000
STUB = 0x300000
STACK = 0x380000
STUBS = ("T_JUMP", "T_CALL", "T_JUMPF", "T_CALLF", "T_INT", "T_FAULT", "T_HALT", "T_END",
         "rt_in8", "rt_in16", "rt_out8", "rt_out16", "T_RET")
STUB_AT = {n: STUB + 4 * k for k, n in enumerate(STUBS)}
REGS = ("ax", "bx", "cx", "dx", "sp", "bp", "si", "di")
M68 = {"ax": "d0", "cx": "d1", "dx": "d2", "bx": "d3", "sp": "d4", "bp": "d5", "si": "a4",
       "di": "a5"}
BATCH = 1500


def assemble(src: str, out: Path) -> bytes:
    s = out.with_suffix(".s")
    s.write_text(src)
    r = subprocess.run([str(VASM), "-quiet", "-m68020", "-Fbin", "-o", str(out), str(s)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"vasm failed:\n{r.stdout}{r.stderr}"[:4000])
    return out.read_bytes()


def ccr_image(flags: dict) -> int:
    return flags["CF"] | flags["OF"] << 1 | flags["ZF"] << 2 | flags["SF"] << 3


def lower_case(insns, cs: int, tag: str, end_ip: int) -> tuple[list[str], Counter]:
    """Test-mode 68k text for a straight-line run of decoded instructions."""
    lives = F.seq_lives(insns)
    stats = Counter()

    def ctx_for(k):
        return Ctx(cs=hx(cs), label=f"{tag}_{k}")

    lines = [f"{tag}:"]
    for k, lw in enumerate(F.plan(insns, lives, set(), ctx_for)):
        lines.append(f"{tag}_{k}:")
        lines.extend(lw.out)
        stats.update(lw.stats)
    lines += [f"{tag}_end:", f"\tmove.l #{hx(end_ip)},d7", "\tjmp T_END"]
    return lines, stats


class M68k:
    """Unicorn 68020 with guest RAM, state block, stubs and native stack."""

    def __init__(self, background: bytes, stubs: dict[str, int] | None = None):
        self.bg = background
        self.stub_at = stubs or STUB_AT
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(STATE, 0x1000)
        e.map(GUEST, len(background) + 0x10000)
        e.write(GUEST, background)
        e.map(STUB, 0x1000)
        e.write(STUB, b"\x4a\xfc\x4e\x75" * len(self.stub_at))  # illegal; rts
        e.map(STACK - 0x10000, 0x20000)
        e.map(CODE, 0x800000)
        self.writes: set[int] = set()
        self.outs: list = []
        self.stop: str | None = None

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            if GUEST <= addr < GUEST + len(background) + 0x10000:
                self.writes.update(range(addr - GUEST, addr - GUEST + size))
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
            if n in ("rt_in8", "rt_in16"):
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
            else:
                self.stop = n
                U.uc.uc_emu_stop(h)

        e.hook(U.HOOK_MEM_WRITE, write)
        e.hook(U.HOOK_CODE, code)

    def r(self, name: str) -> int:
        return self.e.reg_read(U.M68K[name])

    def load(self, image: bytes) -> None:
        self.e.write(CODE, image)
        self.e.flush()

    def run(self, entry: int, case, rng, skip_entry: bool = True):
        regs, flags, flagsx, ip, patches = case
        e = self.e
        for a, data in patches:
            e.write(GUEST + a, data)
        for r in REGS:
            e.reg_write(U.M68K[M68[r]], regs[r])
        for s, a in (("es", "a1"), ("ss", "a2"), ("ds", "a3")):
            e.reg_write(U.M68K[a], GUEST + regs[s] * 16)
        e.reg_write(U.M68K["a6"], GUEST)
        for j in ("d6", "d7", "a0"):
            e.reg_write(U.M68K[j], rng.randrange(1 << 32))
        st = bytearray(16)
        st[16 - 2:16] = bytes([rng.randrange(256) & 0xE0, ccr_image(flags) | rng.randrange(2) << 4])
        st[16 - 3] = 0 if flags["PF"] else 1
        st[16 - 4] = flags["AF"] << 4 | rng.randrange(16) & 0xEF
        st[16 - 5], st[16 - 6], st[16 - 7] = flags["DF"], flags["IF"], flags["TF"]
        st[16 - 10:16 - 8] = flagsx.to_bytes(2, "big")
        for s, at in (("es", 12), ("ss", 14), ("ds", 16)):
            st[16 - at:16 - at + 2] = regs[s].to_bytes(2, "big")
        e.write(GUEST - 16, bytes(st))
        sp = STACK - 0x100
        e.write(sp, self.stub_at["T_RET"].to_bytes(4, "big"))
        e.reg_write(U.M68K["sr"], 0)  # user mode first: a7 is then the USP
        e.reg_write(U.M68K["a7"], sp)
        self.writes, self.outs, self.stop = set(), [], None
        self.entry = entry if skip_entry else None
        err = e.start(entry, 0xFFFFFFFF, 4_000_000)
        out = {r: self.r(M68[r]) for r in REGS}
        st = e.read(GUEST - 16, 16)
        for s, at in (("es", 12), ("ss", 14), ("ds", 16)):
            out[s] = int.from_bytes(st[16 - at:16 - at + 2], "big")
        fl = st[16 - 1]
        f = {"CF": fl & 1, "OF": fl >> 1 & 1, "ZF": fl >> 2 & 1, "SF": fl >> 3 & 1,
             "PF": int(bin(st[16 - 3]).count("1") % 2 == 0), "AF": st[16 - 4] >> 4 & 1,
             "DF": st[16 - 5], "IF": st[16 - 6], "TF": st[16 - 7]}
        fx = int.from_bytes(st[16 - 10:16 - 8], "big")
        d6, d7 = self.r("d6") & 0xFFFF, self.r("d7") & 0xFFFF
        info = {"stop": self.stop, "err": err, "d6": d6, "d7": d7, "d6.l": self.r("d6"),
                "upper": {r: out[r] >> 16 for r in REGS},
                "a7": self.r("a7"), "segbase": {a: self.r(a) for a in ("a1", "a2", "a3")}}
        mem = {a: b for a, b in zip(sorted(self.writes), (e.read(GUEST + a, 1)[0]
                                                          for a in sorted(self.writes)))}
        return out, f, fx, mem, list(self.outs), set(self.writes), info

    def restore(self, addrs) -> None:
        for a in addrs:
            self.e.write(GUEST + a, self.bg[a:a + 1])


class Harness(X.Harness):
    def __init__(self, seed: int):
        super().__init__(seed)
        self.m = M68k(self.bg)
        self.pending: list = []
        self.stats = Counter()
        self.lowered = Counter()
        self.tmp = Path(tempfile.mkdtemp(prefix="m68k-diff-"))
        self.nbatch = 0

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
                if ex.kind in ("int", "fault"):
                    break
        except (UndefinedFlag, DecodeError) as e:
            self.undefined[type(e).__name__] += 1
            self.reset(patches, s.writes, set())
            return
        undef = set(s.undef)
        # decode the whole run statically (the 68k side runs what the bytes say)
        insns, k, at = [], 0, ip
        while len(insns) < n:
            i = decode(code, at, k)
            insns.append(i)
            k += i.size
            at = i.next_ip
        self.reset(patches, s.writes, set())
        err, out, fl, umem, ints, outs, uwrites = self.oracle.run(case, n)
        code_span = set(range(cs * 16 + ip, cs * 16 + ip + len(code)))
        if code_span & uwrites:
            self.skipped["writes its own code"] += 1
            self.oracle.restore(uwrites | {a for a, d in patches for a in range(a, a + len(d))})
            return
        why = X.oracle_deviation(code, regs) if n == 1 else None
        if why:
            self.skipped[f"oracle: {why}"] += 1
            self.oracle.restore(uwrites | {a for a, d in patches for a in range(a, a + len(d))})
            return
        oracle = (err, out, fl, {a: umem.get(a, self.oracle.e.read(a, 1)[0])
                                 for a in set(umem) | uwrites}, ints, outs)
        self.oracle.restore(uwrites | set(umem) | {a for a, d in patches
                                                   for a in range(a, a + len(d))})
        tag = f"c{len(self.pending)}"
        try:
            text, st = lower_case(insns, cs, tag, insns[-1].next_ip)
        except LowerError as e:
            self.bad.append(f"{label} {code.hex()}: lowering: {e}")
            return
        self.lowered.update(st)
        self.pending.append((label, code, case, undef, oracle, text, regs, flags, insns[-1].op))
        if len(self.pending) >= BATCH:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        src = [equates()]
        src += [f"{n}\tequ\t${a:x}" for n, a in STUB_AT.items()]
        src.append(f"\torg\t${CODE:x}")
        src.append("table:")
        src += [f"\tdc.l\tc{k}" for k in range(len(self.pending))]
        for p in self.pending:
            src += p[5]
        src.append(HELPERS)
        self.nbatch += 1
        image = assemble("\n".join(src) + "\n", self.tmp / f"batch{self.nbatch}.bin")
        self.m.load(image)
        for k, (label, code, case, undef, oracle, text, regs, flags, last) in enumerate(self.pending):
            entry = int.from_bytes(image[4 * k:4 * k + 4], "big")
            self.compare(label, code, case, undef, oracle, entry, regs, flags, last)
        self.pending = []

    def compare(self, label, code, case, undef, oracle, entry, regs, flags, last) -> None:
        err, out, fl, umem, ints, outs = oracle
        mo, mf, mfx, mmem, mouts, mwrites, info = self.m.run(entry, case, self.rng)
        diffs = []
        if err:
            diffs.append(f"unicorn x86 error {err}")
        if info["err"]:
            diffs.append(f"unicorn 68k error {info['err']} stop={info['stop']}")
        stop = info["stop"]
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
            if mo[r] & 0xFFFF != out[r]:
                diffs.append(f"{r} 68k={mo[r] & 0xFFFF:04x} x86={out[r]:04x}")
            if mo[r] >> 16:
                diffs.append(f"{r} upper word {mo[r] >> 16:04x}")
        for sname, a in (("es", "a1"), ("ss", "a2"), ("ds", "a3")):
            if mo[sname] != out[sname]:
                diffs.append(f"{sname} 68k={mo[sname]:04x} x86={out[sname]:04x}")
            if info["segbase"][a] != GUEST + out[sname] * 16:
                diffs.append(f"{sname} base {info['segbase'][a]:x}")
        # CS:IP
        far = stop in ("T_JUMPF", "T_CALLF") or stop == "T_RET" and last in ("retf", "iret")
        mcs = info["d6"] if far else regs["cs"]
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
                m = self.m.e.read(GUEST + a, 1)[0]
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


def main(argv=None) -> int:
    h = X.run(argv, harness=Harness)
    h.flush()
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
