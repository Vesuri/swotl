#!/usr/bin/env python3
"""fm_effect_run.s (the prerender's inner loop, docs/sound-plan.md R4) against
the C loop it replaces.

  python3 tests/test_fm_effect_asm.py [--sabotage]

fm_paula.c built for the 68020 with FM_EFFECT_ASM and the assembly, run on the
Unicorn 68020 core; fm_paula.c's C loop built natively. Both render every
captured effect (t-sfx-capture's tmp/sfx-capture.csv) and four synthetic ones,
one per loop variant (feedback on/off x FM/additive, waveforms 0-3): every
output byte, the length and the peak equal. Plants (the assembly):

  mask      the carrier's phase index masked to 9 bits
  feedback  the feedback doubled
  history   the modulator's previous output not kept
"""
import ctypes as C
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import uc as U  # noqa: E402
from host_run import elf_load  # noqa: E402

SRC = ROOT / "src/platform/amiga"
CAPTURE = ROOT / "tmp/sfx-capture.csv"
MAX = 131068                        # tfh_paula.h TFH_EFFECT_BYTES
WRITES = 4096
TOOLS = Path(os.environ.get("AMIGA_TOOLCHAIN") or Path.home() / ".local/opt") / "bin"
PLANTS = {
    "mask": ("\tand.w\t#$3ff,d3\n", "\tand.w\t#$1ff,d3\n"),
    "feedback": ("\tasr.l\td6,d7\n", "\tasr.l\td6,d7\n\tadd.l\td7,d7\n"),
    "history": ("\tmovea.l\td2,a5\n", "\tnop\n"),
}
HARNESS = r'''
#include "fm_paula.h"
static int8_t pool[FM_POOL_BYTES];
uint8_t fx_opl[256];
struct fm_write fx_writes[%d];
int16_t fx_buf[%d];
uint32_t fx_n, fx_len, fx_level;
void fx_init(void) { fm_init(pool, sizeof pool); }
void fx_one(void) { fx_len = fm_effect(fx_opl, fx_writes, fx_n, fx_buf, %d, &fx_level); }
void fx_halt(void) { for (;;) ; }
''' % (WRITES, MAX, MAX)


def effects():
    """(name, start registers, writes) per captured id and synthetic variant."""
    opl0, fx = bytes(256), {}
    for line in CAPTURE.read_text().splitlines():
        if line.startswith("# opl "):
            opl0 = bytes.fromhex(line[6:].strip())
        elif line[:1].isdigit():
            t, i, r, v = line.split(",")
            fx.setdefault(int(i), []).append((int(t), int(r, 16), int(v, 16)))
    out = [(f"id {i}", opl0, w) for i, w in sorted(fx.items())]
    for mode in range(4):           # channel 3: feedback 7 or 0, FM or additive
        regs = bytearray(256)
        regs[1] = 0x20              # waveform select on
        w = [(0, 0xc3, (7 << 1 if mode & 2 else 0) | (mode & 1))]
        for k, (off, mult) in enumerate(((8, 0x2f), (11, 0x21))):
            w += [(0, 0x20 + off, mult), (0, 0x40 + off, 0x04 * k), (0, 0x60 + off, 0xf4),
                  (0, 0x80 + off, 0x35), (0, 0xe0 + off, (mode + k) & 3)]
        w += [(0, 0xa3, 0x89), (0, 0xb3, 0x31), (60, 0x43 + 8, 0x10), (120, 0xb3, 0x11),
              (121, 0xa3, 0x40), (122, 0xb3, 0x2e), (300, 0xb3, 0x0e)]
        out.append((f"variant {mode}", bytes(regs), w))
    return out


def build_68k(out, asm_source):
    (out / "fx_test.c").write_text(HARNESS)
    (out / "fm_effect_run.s").write_text(asm_source)
    subprocess.run(["vasmm68k_mot", "-m68020", "-Felf", "-quiet", "-x", "-no-opt", "-nowarn=62",
                    "-o", str(out / "fm_effect_run.o"), str(out / "fm_effect_run.s")], check=True)
    subprocess.run([str(TOOLS / "m68k-amiga-elf-gcc"), "-m68020", "-msoft-float", "-O2", "-ffreestanding",
                    "-nostdlib", "-fomit-frame-pointer", "-fno-tree-loop-distribute-patterns", "-Wall",
                    "-Wextra", "-Werror", "-DFM_EFFECT_ASM", "-I" + str(SRC),
                    str(SRC / "fm_paula.c"), str(out / "fx_test.c"), str(out / "fm_effect_run.o"),
                    "-Wl,-Ttext=0x10000", "-Wl,-e,fx_init", "-o", str(out / "fx.elf")], check=True)
    return out / "fx.elf"


class M68k:
    STACK = 0xF00000

    def __init__(self, elf):
        _, segs, self.syms = elf_load(elf)
        self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        self.e.map(0, 0x1000000)
        for vaddr, data, memsz in segs:
            self.e.write(vaddr, data + bytes(memsz - len(data)))
        self.call("fx_init")

    def call(self, name):
        halt = self.syms["fx_halt"]
        self.e.reg_write(U.M68K["a7"], self.STACK - 4)
        self.e.write(self.STACK - 4, struct.pack(">I", halt))
        U.check(self.e.start(self.syms[name], halt), name)

    def render(self, opl, writes):
        assert len(writes) <= WRITES
        self.e.write(self.syms["fx_opl"], opl)
        self.e.write(self.syms["fx_writes"], b"".join(struct.pack(">HBB", *w) for w in writes))
        self.e.write(self.syms["fx_n"], struct.pack(">I", len(writes)))
        self.call("fx_one")
        n, level = (struct.unpack(">I", self.e.read(self.syms[s], 4))[0] for s in ("fx_len", "fx_level"))
        return self.e.read(self.syms["fx_buf"], n), level


class Native:
    def __init__(self, out):
        lib = out / "fx_native.dylib"
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-I", str(SRC), str(SRC / "fm_paula.c"), "-o", str(lib)], check=True)
        self.lib = C.CDLL(str(lib))
        self.pool = (C.c_int8 * 65536)()
        self.lib.fm_init(self.pool, len(self.pool))
        self.buf = (C.c_int16 * MAX)()

    def render(self, opl, writes):
        w = (C.c_uint8 * (4 * len(writes)))(*b"".join(struct.pack("=HBB", *x) for x in writes))
        level = C.c_uint32()
        self.lib.fm_effect.restype = C.c_uint32
        n = self.lib.fm_effect((C.c_uint8 * 256)(*opl), w, C.c_uint32(len(writes)), self.buf,
                               C.c_uint32(MAX), C.byref(level))
        return bytes(C.string_at(self.buf, n)), level.value


def cases(asm_source):
    with tempfile.TemporaryDirectory(prefix="swotl-fx-asm-") as tmp:
        out = Path(tmp)
        m68k, native = M68k(build_68k(out, asm_source)), Native(out)
        total = 0
        for name, opl, writes in effects():
            got, want = m68k.render(opl, writes), native.render(opl, writes)
            if got != want:
                k = next((k for k, (a, b) in enumerate(zip(got[0], want[0])) if a != b), None)
                return [f"{name}: {len(got[0])} samples peak {got[1]}, C {len(want[0])} peak {want[1]}, "
                        f"first difference at {k}"]
            total += len(got[0])
        print(f"fm_effect_run.s: {len(effects())} effects, {total} samples equal the C loop")
        return []


def main():
    source = (SRC / "fm_effect_run.s").read_text()
    problems = cases(source)
    print("effect loop:", "ok" if not problems else problems[0])
    if problems:
        return 1
    if "--sabotage" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            assert old in source, name
            planted = cases(source.replace(old, new))
            print(f"plant {name}: {planted[0] if planted else 'MISSED'}")
            missed += [] if planted else [name]
        if missed:
            print("FAIL: plants missed:", ", ".join(missed))
            return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
