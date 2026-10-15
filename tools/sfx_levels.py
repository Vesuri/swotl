#!/usr/bin/env python3
"""FM levels of SPAZ's effects (docs/sound-plan.md, TFH mode volumes).

The original SPAZ code runs under Unicorn x86 from a reference snapshot in
flight (SPAZ resident and initialised): stop all, play(id), then its timer
handler at 236.7 Hz; the AdLib writes are rendered by build/tools/opl_render
(Nuked OPL). Per id: the peak 20 ms RMS level in dB and the length above
-40 dB of it. Output: tmp/sound/sfx-levels.csv, tmp/sound/sfx/ID.{csv,wav}.

    tools/sfx_levels.py [--seconds S] [ID ...]
"""

from __future__ import annotations

import argparse
import csv
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import uc as U  # noqa: E402

SNAP = REPO / "tmp/pc-runs/ref-c6-flight-keys/trace/snap-c6-flight-keys-0"
RENDER = REPO / "build/tools/opl_render"
OUT = REPO / "tmp/sound"
# SPAZ.OVL file offsets (docs/sound-plan.md) and its header
PLAY, STOP_ALL, TIMER, HEADER = 0x3D5, 0x666, 0x7CC, 0x240
TICK_HZ = 1193182 / 5041            # SPAZ's timer (236.7 Hz)
DELAY = 0xCFA8                      # game DS: the gun delay byte play reads
EFFECTS = 39
RET_SEG = 0x0050                    # a free BIOS-data paragraph: the far return
BIOS = 0xF0000                      # chained BIOS handlers: taken as IRET
DB_FLOOR = -40.0


def snapshot() -> tuple[bytes, dict, int]:
    regs = {}
    for line in (SNAP / "regs.txt").read_text().split("\n")[1:]:
        for kv in line.split():
            k, _, v = kv.partition("=")
            regs[k] = int(v, 16)
    for r in csv.reader((SNAP / "residency.csv").open()):
        if r[2] == "SPAZ.OVL":
            seg = int(r[0], 16) - (int(r[3], 16) - HEADER) // 16
            return (SNAP / "ram.bin").read_bytes(), regs, seg
    raise SystemExit(f"{SNAP}: SPAZ.OVL not resident")


class Spaz:
    def __init__(self, ram: bytes, regs: dict, seg: int):
        self.e = U.Engine(U.ARCH_X86, U.MODE_16)
        self.e.map(0, 0x110000)
        self.e.write(0, ram)
        self.seg, self.regs = seg, regs
        self.ret = RET_SEG * 16
        self.e.write(self.ret, b"\xf4")            # hlt: the far return lands here
        self.ms, self.writes, self.index = 0.0, [], 0

        @U.OUT_CB
        def out(h, port, size, value, user):
            if port == 0x388:
                self.index = value & 0xFF
            elif port == 0x389:
                self.writes.append((self.ms, self.index, value & 0xFF))

        @U.IN_CB
        def inp(h, port, size, user):
            return 0

        self.e.hook(U.HOOK_INSN, out, U.X86_INS_OUT)
        self.e.hook(U.HOOK_INSN, inp, U.X86_INS_IN)

        @U.CODE_CB
        def bios(h, addr, size, user):   # a chained BIOS handler: IRET
            sp = self.e.reg_read(U.X86["sp"])
            ss = self.e.reg_read(U.X86["ss"])
            ip, cs, fl = struct.unpack("<3H", self.e.read(ss * 16 + sp, 6))
            self.e.reg_write(U.X86["sp"], (sp + 6) & 0xFFFF)
            self.e.reg_write(U.X86["cs"], cs)
            self.e.reg_write(U.X86["ip"], ip)
            self.e.reg_write(U.X86["flags"], fl)

        self.e.hook_range(U.HOOK_CODE, bios, BIOS, 0x10FFFF)

    def push(self, *words: int) -> None:
        sp = self.e.reg_read(U.X86["sp"])
        for w in words:
            sp = (sp - 2) & 0xFFFF
            self.e.write(self.regs["ss"] * 16 + sp, struct.pack("<H", w & 0xFFFF))
        self.e.reg_write(U.X86["sp"], sp)

    def run(self, off: int, *frame: int) -> None:
        for r in ("ss", "ds", "es"):
            self.e.reg_write(U.X86[r], self.regs[r])
        self.e.reg_write(U.X86["sp"], self.regs["sp"] - 0x400)
        self.push(*frame)
        ip = off - HEADER
        self.e.reg_write(U.X86["cs"], self.seg)
        self.e.reg_write(U.X86["ip"], ip)
        err = self.e.start(self.seg * 16 + ip, self.ret)
        pc = self.e.reg_read(U.X86["cs"]) * 16 + self.e.reg_read(U.X86["ip"])
        if err or pc not in (self.ret, self.ret + 1):
            raise SystemExit(f"SPAZ+{off:04X}: stopped at {pc:05x} ({U.uc.uc_strerror(err).decode()})")

    def call(self, off: int, *args: int) -> None:     # far C call, args pushed right to left
        self.run(off, *reversed(args), RET_SEG, 0)

    def tick(self) -> None:                           # the interrupt frame: FLAGS, CS, IP
        self.run(TIMER, 0x0202, RET_SEG, 0)


def level(path: Path) -> tuple[float, float]:
    with wave.open(str(path)) as w:
        rate, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        data = struct.unpack(f"<{n * ch}h", w.readframes(n))
    win = rate // 50
    rms = []
    for k in range(0, n - win + 1, win):
        seg = data[k * ch:(k + win) * ch:ch]
        rms.append(math.sqrt(sum(x * x for x in seg) / win) or 1e-9)
    peak = max(rms)
    db = 20 * math.log10(peak / 32768)
    loud = sum(1 for r in rms if 20 * math.log10(r / peak) > DB_FLOOR)
    return db, loud / 50


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*", type=int)
    ap.add_argument("--seconds", type=float, default=4.0)
    args = ap.parse_args()
    if not RENDER.exists():
        print(f"missing {RENDER}: make {RENDER.relative_to(REPO)}")
        return 1
    ram, regs, seg = snapshot()
    (OUT / "sfx").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in args.ids or range(EFFECTS):
        s = Spaz(ram, regs, seg)
        s.e.write(regs["ds"] * 16 + DELAY, b"\0\0")
        s.call(STOP_ALL)
        s.writes.clear()
        s.call(PLAY, 4 * i)
        for t in range(int(args.seconds * TICK_HZ)):
            s.ms = 1000 * (t + 1) / TICK_HZ
            s.tick()
        csv_path, wav = OUT / f"sfx/{i}.csv", OUT / f"sfx/{i}.wav"
        with csv_path.open("w") as f:
            f.write("ms,reg,value\n0.0,0x01,0x20\n")
            f.writelines(f"{ms:.6f},0x{r:02x},0x{v:02x}\n" for ms, r, v in s.writes)
        subprocess.run([str(RENDER), str(csv_path), str(wav)], capture_output=True, check=True)
        db, secs = level(wav) if s.writes else (float("-inf"), 0.0)
        rows.append((i, len(s.writes), f"{db:.1f}", f"{secs:.2f}"))
        print(f"{i:2} writes {len(s.writes):5}  peak {db:6.1f} dB  {secs:4.2f} s", flush=True)
    with (OUT / "sfx-levels.csv").open("w") as f:
        f.write("id,writes,peak_db,seconds\n")
        f.writelines(",".join(map(str, r)) + "\n" for r in rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
