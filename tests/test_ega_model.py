"""The two EGA models agree (docs/ecs-plan.md E6): src/runtime/ega.c, built for the
host with a stand-in runtime (guest RAM, rt_stop, D9 marks), against
tools/ega_model.py, the device-row oracle's model.

Random sequences from the mode set (rt_ega_mode / Ega()): port writes to the
sequencer and graphics controller (index and data, 8 and 16 bit; values inside
and, rarely, outside the surface: both must stop), reads (read modes 0 and 1,
every read map, colour compare and don't care as the mode set leaves them) and
writes (write modes 0-2, map and bit masks), at offsets across page 0's end.
After every step: the value read, every register and latch, the stop; after
every sequence: the four planes and the D9 marks. Read mode 1 is outside the
surface (graphics 5 above 02h stops); both models implement it, unexercised. Sabotage: ega.c plants (as
tests/host_run.py's) and Python model plants must be caught."""
from pathlib import Path
import argparse
import ctypes as C
import os
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import ega_model as E

RAM = 0x110000
STUB = r'''
#include <setjmp.h>
#include <stdlib.h>
#include "runtime.h"
static uint8_t memory[%d + 64];
uint8_t *rt_guest = memory + %d - 1;
struct rt_regs rt_r;
struct vram_row rt_vram_rows[200];
uint16_t rt_vram_top = 200, rt_vram_bottom = 0;
uint16_t rt_vdrv_depth = 1;
const uint32_t smc_lo = 0x200000, smc_hi = 0x200000;
static jmp_buf stop;
void smc_expose(void) {}
void rt_vram_stray(void) { longjmp(stop, 2); }
void rt_stop(const char *what, uint32_t a, uint32_t b) { (void)what, (void)a, (void)b; longjmp(stop, 1); }
void *plat_alloc(uint32_t bytes) { return calloc(1, bytes); }
void put(uint32_t a, uint8_t v) { rt_guest[-(int32_t)a] = v; }
uint8_t get(uint32_t a) { return rt_guest[-(int32_t)a]; }
int mode(void) { if (setjmp(stop)) return -1; rt_ega_mode(); return 0; }
int out(uint32_t port, uint32_t value, uint32_t width) {
    int r = setjmp(stop); if (r) return -r; return rt_ega_out(port, value, width);
}
int rd(uint32_t a) { int r = setjmp(stop); if (r) return -r; rt_ega_read_c(a, 1); return get(a); }
int wr(uint32_t a, uint8_t v) { int r = setjmp(stop); if (r) return -r; put(a, v); rt_ega_write_c(a, 1); return 0; }
'''
# ega.c plants: (old, new); tests/host_run.py SABOTAGE's three and two more
C_PLANTS = {
    'bit-mask': ('    case 0: return (uint8_t)((d & mask) | (latch & ~mask));', '    case 0: return d;'),
    'latch': ('        g->latch[p] = rt_ega_planes[(uint32_t)p << 16 | off];', '        (void)p, (void)off;'),
    'write-mode-1': ('        case 1:\n            d = latch;\n            break;\n', ''),
    'write-mode-2': ('            d = alu(v >> p & 1 ? 0xff : 0, latch, function, g->bit_mask);',
                     '            d = alu(v, latch, function, g->bit_mask);'),
    'mark-row': ('    uint16_t y = (uint16_t)(off / 80), x = (uint16_t)(off % 80);',
                 '    uint16_t y = (uint16_t)(off / 160), x = (uint16_t)(off % 80);'),
}
PY_PLANTS = {
    'py-mode-2-bit-mask': ('write', lambda real: lambda self, off, v: (
        lambda mask: (self.r.__setitem__('bit_mask', 0xFF if self.r['mode'] & 3 == 2 else mask),
                      real(self, off, v), self.r.__setitem__('bit_mask', mask)))(self.r['bit_mask'])),
    'py-map-mask': ('data', lambda real: lambda self, port, v: real(self, port, v & 0x07 if port == 0x3C5 else v)),
}


class ModelMismatch(AssertionError):
    pass


def library(plant=None):
    work = ROOT / f'tmp/ega-model-{os.getpid()}'
    work.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'src/runtime/ega.c').read_text()
    if plant:
        old, new = C_PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    (work / 'ega.c').write_text(source)
    (work / 'stub.c').write_text(STUB % (RAM, RAM))
    lib = work / f'ega-{plant}.so'
    subprocess.run(['cc', '-std=gnu11', '-O1', '-shared', '-fPIC', '-I', str(ROOT / 'src/runtime'),
                    '-D__asm__(...)=', '-o', str(lib), str(work / 'ega.c'), str(work / 'stub.c')], check=True)
    return C.CDLL(str(lib))


class Native:
    def __init__(self, lib):
        self.lib = lib
        for f in ('out', 'rd', 'wr', 'mode'):
            getattr(lib, f).restype = C.c_int

    def regs(self):
        return C.string_at(C.addressof(C.c_uint8.in_dll(self.lib, 'rt_ega_regs')), E.REGS_BYTES)

    def planes(self):
        p = C.c_void_p.in_dll(self.lib, 'rt_ega_planes').value
        return C.string_at(p, 4 * E.WINDOW)

    def marks(self):
        rows = (C.c_uint16 * 400).in_dll(self.lib, 'rt_vram_rows')
        return (tuple((rows[2 * y], rows[2 * y + 1]) for y in range(200)),
                C.c_uint16.in_dll(self.lib, 'rt_vram_top').value, C.c_uint16.in_dll(self.lib, 'rt_vram_bottom').value)

    def reset_marks(self):
        (C.c_uint16 * 400).in_dll(self.lib, 'rt_vram_rows')[:] = [0] * 400
        C.c_uint16.in_dll(self.lib, 'rt_vram_top').value = 200
        C.c_uint16.in_dll(self.lib, 'rt_vram_bottom').value = 0


def step(rng):
    """One operation: ('out', port, value, width) | ('read', off) | ('write', off, v)."""
    k = rng.random()
    if k < 0.35:
        roll = rng.random()
        if roll < 0.3:      # sequencer map mask
            port, idx, v = 0x3C4, 2, rng.randrange(16)
        elif roll < 0.5:
            port, idx, v = 0x3CE, 8, rng.randrange(256)     # bit mask
        elif roll < 0.72:
            port, idx, v = 0x3CE, 5, rng.choice((0, 1, 2))   # write modes (read mode 1 is outside the surface)
        elif roll < 0.995:
            port, idx, v = 0x3CE, 4, rng.randrange(4)      # read map
        else:               # outside the surface
            port, idx, v = rng.choice(((0x3C4, 0, 1), (0x3C4, 2, 0x10), (0x3CE, 3, 0x08), (0x3CE, 5, 3),
                                       (0x3CE, 4, 4), (0x3CE, 0, 1), (0x3D4, 0, 0)))
        if rng.random() < 0.6 or port == 0x3D4:
            return [('out', port, idx | v << 8, 16)]
        return [('out', port, idx, 8), ('out', port + 1, v, 8)]
    off = rng.choice((rng.randrange(E.WINDOW), rng.randrange(15900, 16100), rng.randrange(0, 160)))
    if k < 0.65:
        return [('read', off)]
    return [('read', off), ('write', off, rng.randrange(256))] if rng.random() < 0.5 else [('write', off, rng.randrange(256))]


def run_sequence(native, seed, length):
    rng = random.Random(seed)
    if native.lib.mode() != 0:
        raise ModelMismatch((seed, 'mode set stopped'))
    native.reset_marks()
    py = E.Ega()     # the mode set leaves the index registers and latches as they were
    before = native.regs()
    py.r['seq_index'], py.r['gc_index'], py.latch = before[0], before[2], list(before[12:16])
    if native.regs() != py.regs_image():
        raise ModelMismatch((seed, 'mode set registers', native.regs().hex(), py.regs_image().hex()))
    for n in range(length):
        for op in step(rng):
            try:
                if op[0] == 'out':
                    py.out(op[1], op[2], op[3])
                    want = 1
                elif op[0] == 'read':
                    want = py.read(op[1])
                else:
                    py.write(op[1], op[2])
                    want = 0
            except E.OutsideSurface:
                want = 'stop'
            if op[0] == 'out':
                got = native.lib.out(op[1], op[2], op[3])
                got = 'stop' if got == -1 else 1 if got == 1 else got
                if op[1] == 0x3D4 and want == 'stop':
                    got = 'stop' if got == 0 else got   # not an EGA port: ports.c stops
            elif op[0] == 'read':
                got = native.lib.rd(E.BASE + op[1])
            else:
                got = native.lib.wr(E.BASE + op[1], op[2])
            if got != want:
                raise ModelMismatch((seed, n, op, 'result', got, want))
            if want == 'stop':
                return n
            if native.regs() != py.regs_image():
                raise ModelMismatch((seed, n, op, 'registers', native.regs().hex(), py.regs_image().hex()))
    if native.planes() != py.planes_image():
        raise ModelMismatch((seed, 'planes'))
    if native.marks() != (tuple(tuple(r) for r in py.rows), py.top, py.bottom):
        raise ModelMismatch((seed, 'marks'))
    return length


def run_all(plant=None, sequences=300, length=400):
    native = Native(library(plant if plant in C_PLANTS else None))
    real = {}
    if plant in PY_PLANTS:
        name, make = PY_PLANTS[plant]
        real[name] = getattr(E.Ega, name)
        setattr(E.Ega, name, make(real[name]))
    try:
        steps = stops = 0
        for seed in range(sequences):
            n = run_sequence(native, seed, length)
            steps += n
            stops += n < length
        return steps, stops
    finally:
        for name, f in real.items():
            setattr(E.Ega, name, f)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    steps, stops = run_all()
    print(f'ega model: ega.c and tools/ega_model.py agree over {steps} steps, {stops} sequences end in a stop',
          flush=True)
    if args.sabotage:
        for plant in [*C_PLANTS, *PY_PLANTS]:
            try:
                run_all(plant)
            except ModelMismatch as error:
                print('caught', plant, str(error)[:120], flush=True)
            else:
                raise AssertionError(plant + ' escaped')
