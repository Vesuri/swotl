#!/usr/bin/env python3
"""The game's own gameport code against the runtime's port 201h model.

Runs the original root routines on Unicorn (x86 semantics) with port 201h
answered by src/runtime/ports.c built natively (stand-in headers): the probe (+042B0), the
three calibration steps (+04333 centre, +04352 upper left, +04389 lower right)
and the read (+043BC: X, Y in -127..127, buttons). Code and data segment come
from a reference RAM snapshot (load segment 0822, DS = 0822 + 3BAB), so this
needs `make reference` (tmp/pc-runs) and Unicorn (tests/uc.py).

Checks: without rt_joystick no stick is found (the reference); with it, stick A
is found at the platform's axis counts (16 + pot, 16..271), calibrated reads
give 0 at the centre and the ends (115) at the calibration corners, move with the
axes, and report both buttons. --sabotage proves the checks catch axis, latch
and button faults.
"""
import argparse
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import uc as U  # noqa: E402

SNAP = ROOT / 'tmp/pc-runs/ref-m1-mode13h/trace/snap-m1-mode13h-0/ram.bin'
LOAD = 0x0822
DS = LOAD + 0x3bab
RET = 0x9000            # far return segment; the run stops at its offset 0
STACK = 0x8000
FULL = 127 - 12        # the read's dead zone (+04451) takes 12 off the magnitude
# Stand-ins for the 68k runtime headers: only what ports.c uses.
HEADERS = {
    'runtime.h': '''#pragma once
#include <stdint.h>
extern uint8_t rt_bench, rt_joystick;
extern volatile uint16_t rt_joystick_axis[2];
extern volatile uint8_t rt_joystick_buttons;
void rt_bench_watch(void);
void rt_stop(const char *, uint32_t, uint32_t) __attribute__((noreturn));
''',
    'platform.h': 'void plat_timer_rate(uint32_t);\n',
}
STUBS = r'''
#include <stdlib.h>
#include <stdio.h>
#include "runtime.h"
uint8_t rt_bench;
void rt_bench_watch(void) {}
void plat_timer_rate(uint32_t d) { (void)d; }
void rt_stop(const char *what, uint32_t a, uint32_t b) { fprintf(stderr, "%s %x %x\n", what, a, b); abort(); }
'''


def build(source: str, d: Path) -> C.CDLL:
    for path, text in HEADERS.items():
        (d / path).write_text(text)
    (d / 'ports.c').write_text(source)
    (d / 'stubs.c').write_text(STUBS)
    lib = d / 'ports.dylib'
    subprocess.run(['cc', '-shared', '-O1', str(d / 'ports.c'), str(d / 'stubs.c'), '-o', str(lib)], check=True)
    return C.CDLL(str(lib))


class Game:
    def __init__(self, lib: C.CDLL):
        self.lib = lib
        lib.rt_port_in.restype = C.c_uint32
        lib.rt_port_in.argtypes = [C.c_uint32, C.c_uint32]
        lib.rt_port_out.argtypes = [C.c_uint32, C.c_uint32, C.c_uint32]
        self.joystick = C.c_uint8.in_dll(lib, 'rt_joystick')
        self.axis = (C.c_uint16 * 2).in_dll(lib, 'rt_joystick_axis')
        self.buttons = C.c_uint8.in_dll(lib, 'rt_joystick_buttons')
        self.e = U.Engine(U.ARCH_X86, U.MODE_16)
        self.e.map(0, 0x100000)
        self.e.write(0, SNAP.read_bytes())
        self.reads = 0

        @U.IN_CB
        def port_in(_uc, port, size, _user):
            assert port == 0x201 and size == 1, (port, size)
            self.reads += 1
            return lib.rt_port_in(port, 8)

        @U.OUT_CB
        def port_out(_uc, port, size, value, _user):
            assert port == 0x201 and size == 1, (port, size)
            lib.rt_port_out(port, value, 8)
        self.e.hook(U.HOOK_INSN, port_out, U.X86_INS_OUT)
        self.e.hook(U.HOOK_INSN, port_in, U.X86_INS_IN)

    def word(self, off: int) -> int:
        return int.from_bytes(self.e.read(DS * 16 + off, 2), 'little', signed=True)

    def call(self, ip: int, *args: int) -> int:
        """Far call root +ip with C arguments; returns AX."""
        sp = 0x1000
        frame = [0, RET, *args]
        for k, v in enumerate(frame):
            self.e.write(STACK * 16 + sp + 2 * k, (v & 0xffff).to_bytes(2, 'little'))
        for r, v in (('cs', LOAD), ('ds', DS), ('es', DS), ('ss', STACK), ('sp', sp), ('ip', ip)):
            self.e.reg_write(U.X86[r], v)
        err = self.e.start(LOAD * 16 + ip, RET * 16, timeout_us=60_000_000)
        assert not err, U.uc.uc_strerror(err).decode()
        assert self.e.reg_read(U.X86['cs']) == RET
        return self.e.reg_read(U.X86['ax']) & 0xffff

    def stick(self, x: int, y: int, buttons: int = 0) -> None:
        self.axis[0], self.axis[1], self.buttons.value = x, y, buttons

    def read(self) -> tuple:
        out = 0x0fe0                      # two words in the data segment's spare top
        buttons = self.call(0x43bc, out, out + 2, 0)
        return self.word(out), self.word(out + 2), buttons


def check(source: str) -> None:
    with tempfile.TemporaryDirectory(prefix='gameport-', dir=ROOT / 'tmp') as name:
        g = Game(build(source, Path(name)))
        # The reference: no stick; both sticks' axes run the loop out.
        g.joystick.value = 0
        assert g.call(0x42b0) == 0
        # Stick A at the centre of the platform's range (pot 110 of 0..255).
        g.joystick.value = 1
        lo, mid, hi = 16, 16 + 110, 16 + 230
        g.stick(mid, mid + 20)
        g.reads = 0
        assert g.call(0x42b0) == 1
        assert abs(g.word(0x7c8) - mid) <= 1 and abs(g.word(0x7ca) - mid - 20) <= 1, (g.word(0x7c8), g.word(0x7ca))
        assert g.word(0x7da) == 1          # stick B absent, so the game selects stick A
        select = 0                         # [A518] with one stick
        # The calibration screen's three steps.
        g.call(0x4333, select)
        g.stick(lo, lo)
        g.call(0x4352, select)
        g.stick(hi, hi)
        g.call(0x4389, select)
        g.stick(mid, mid + 20)
        assert g.read() == (0, 0, 0)
        g.stick(lo, lo)
        assert g.read() == (-FULL, -FULL, 0), g.read()
        g.stick(hi, hi)
        assert g.read() == (FULL, FULL, 0), g.read()
        # Monotonic across X, dead zone at the centre, Y independent.
        last = -128
        for x in range(lo, hi + 1, 5):
            g.stick(x, mid + 20)
            vx, vy, _ = g.read()
            assert vx >= last and vy == 0, (x, vx, last, vy)
            last = vx
        g.stick(mid + 3, mid + 20 - 3)
        assert g.read() == (0, 0, 0)
        g.stick(mid + 40, mid - 20)
        vx, vy, _ = g.read()
        assert 20 < vx < FULL and -FULL < vy < -20, (vx, vy)
        for b in (1, 2, 3):
            g.stick(mid, mid + 20, b)
            assert g.read() == (0, 0, b), (b, g.read())
        # A read costs about its longest axis in port reads.
        g.stick(hi, hi)
        g.reads = 0
        g.read()
        assert hi <= g.reads <= hi + 8, g.reads
        print(f'gameport: probe, calibration and reads through the game code: ok ({g.reads} port reads at full deflection)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    source = (ROOT / 'src/runtime/ports.c').read_text()
    check(source)
    if args.sabotage:
        for old, new in [('(joystick_reads <= joystick_latch[0]) |\n', '(joystick_reads <= joystick_latch[1]) |\n'),
                         ('(joystick_reads <= joystick_latch[1]) << 1', '(joystick_reads < joystick_latch[1]) << 3'),
                         ('(~rt_joystick_buttons & 3) << 4', '(~rt_joystick_buttons & 3) << 6'),
                         ('            joystick_reads = 0;\n', ''),
                         ('rt_joystick ? joystick_in() : 0xff', '0xff')]:
            assert source.count(old) == 1, old
            try:
                check(source.replace(old, new))
            except (AssertionError, U.UcError):
                print('gameport: planted fault caught')
            else:
                raise SystemExit(f'planted fault not caught: {old!r}')
