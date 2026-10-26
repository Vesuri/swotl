#!/usr/bin/env python3
"""Exercise production Input.cpp through its ciaa.resource calls and MMIO registers.

The fake registers model hardware values, not Input::key/moveMouse calls. Both
builds: sync (SWOTL_SYNC) posts IRQ1 per event, production none (irq-plan I8).
The keyboard is read at the vertical blank from ciaa.resource's SP flag with
the SP interrupt disabled (docs/irq-plan.md I7). This is handler coverage, not
emulator interrupt-routing or physical input validation. --sabotage proves the
assertions catch decode, wrap, flag and mask faults.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {
    'Util.h': '#include <stdint.h>\n',
    'proto/exec.h': '''#pragma once
#include <stdint.h>
struct Library {};
struct Node { int ln_Type, ln_Pri; char *ln_Name; };
struct Interrupt { Node is_Node; void *is_Data; void (*is_Code)(); };
#define NT_INTERRUPT 2
using CONST_STRPTR = const char *;
void Disable(); void Enable();
Library *OpenResource(CONST_STRPTR);
''',
    'proto/cia.h': '''#include <proto/exec.h>
short AbleICR(Library *, long);
short SetICR(Library *, long);
''',
    'exec/interrupts.h': '#include <proto/exec.h>\n',
    'hardware/cia.h': '#define CIACRAF_SPMODE 0x40\n',
    'resources/cia.h': '#define CIAANAME "ciaa.resource"\n#define CIAICRF_SP 0x08\n'
                       '#define CIAICRF_SETCLR 0x80\n',
    'runtime.h': '''#pragma once
#include <stdint.h>
#define RT_KEY_E0 0x100
#define RT_KEY_RING 16
#define RT_IRQ_RING 32
extern uint16_t rt_key_ring[RT_KEY_RING];
extern uint8_t rt_irq_ring[RT_IRQ_RING];
extern unsigned rt_key_tail, rt_irq_tail, raises;
#define RT_RAISE_IRQ() (++raises)
''',
    'platform.h': '',
    'AmigaHardware.h': '''#pragma once
#include <stdint.h>
extern volatile uint8_t sdr, cra, pra;
extern volatile uint16_t joy, pot, potgo;
#define ciaasdrPointer (&sdr)
#define ciaacraPointer (&cra)
#define joy0datPointer (&joy)
#define potinpPointer (&pot)
#define potgoPointer (&potgo)
class AmigaHardware {
public:
    static bool isLeftMouseButtonPressed() { return !(pra & 64); }
    static bool isRightMouseButtonPressed() { return !(pot & 1024); }
};
''',
}
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <proto/cia.h>
#include "Input.h"
#include "AmigaHardware.h"
extern "C" {
#include "runtime.h"
uint32_t plat_mouse(int32_t *, int32_t *);
uint16_t rt_key_ring[RT_KEY_RING];
uint8_t rt_irq_ring[RT_IRQ_RING];
unsigned rt_key_tail, rt_irq_tail, raises;
}
volatile uint8_t sdr, cra, pra = 255;
volatile uint16_t joy, pot = 65535, potgo = 65535;
static Library resource;
static unsigned enabled = 0x0c, icr = 0x08;   // keyboard.device's SP on, a stale byte
static int depth;
void Disable() { ++depth; }
void Enable() { assert(depth > 0); --depth; }
Library *OpenResource(CONST_STRPTR) { return &resource; }
short AbleICR(Library *r, long mask) {
    assert(r == &resource);
    unsigned old = enabled;
    enabled = mask & 0x80 ? enabled | (mask & 0x1f) : enabled & ~mask;
    return old;
}
short SetICR(Library *r, long mask) {
    assert(r == &resource && !(mask & 0x80));
    unsigned old = icr;
    icr &= ~mask;
    return old;
}
static void edge(unsigned wire, unsigned scan, unsigned irq) {
    unsigned k = rt_key_tail, i = rt_irq_tail;
    sdr = wire;
    cra = 0x81;
    Input::verticalBlank();        // no byte flagged: none read
    assert(rt_key_tail == k && cra == 0x81);
    icr |= 0x08;
    Input::verticalBlank();
    assert(cra == 0x81 && depth == 0 && !(icr & 0x08));
    assert(rt_key_tail == k + 1);
    assert(rt_key_ring[k % RT_KEY_RING] == scan);
#ifdef SWOTL_SYNC                  // sync builds post IRQ1; production none (irq-plan I8)
    assert(rt_irq_tail == i + 1 && rt_irq_ring[i % RT_IRQ_RING] == irq);
#else
    assert(rt_irq_tail == i);
    (void)irq;
#endif
}
static void mouse(unsigned counters, unsigned buttons, int dx, int dy) {
    joy = counters;
    pra = buttons & 1 ? 0xbf : 0xff;
    pot = 0xffff ^ ((buttons & 2 ? 1u : 0u) << 10)
                 ^ ((buttons & 4 ? 1u : 0u) << 8);
    Input::verticalBlank();
    int32_t x, y;
    assert(plat_mouse(&x, &y) == buttons);
    assert(x == dx && y == dy && depth == 0);
    assert(plat_mouse(&x, &y) == buttons && x == 0 && y == 0);
}
int main() {
    joy = 0xfafa;
    assert(Input::begin());
    assert(enabled == 0x04 && icr == 0 && potgo == 0);
    // Amiga serial wire bytes: inverted rotate-left raw code, including up.
    // Return (44/C4), left arrow (4F/CF), shift (60/E0).
    edge(0x77, 0x1c, 9); edge(0x76, 0x9c, 0x89);
    edge(0x61, 0x14b, 9); edge(0x60, 0x1cb, 0x89);
    edge(0x3f, 0x2a, 9); edge(0x3e, 0xaa, 0x89);
    // Both wrap directions, then every combination of three hardware buttons.
    mouse(0x0302, 0, 8, 9);
    mouse(0xfcfe, 1, -4, -7);
    for (unsigned b = 0; b < 8; ++b) mouse(0xfcfe, b, 0, 0);
    // Pending motion accumulates until the guest consumes it.
    joy = 0xfdff; Input::verticalBlank();
    joy = 0x0002; Input::verticalBlank();
    int32_t x, y;
    assert(plat_mouse(&x, &y) == 7 && x == 4 && y == 4);
    icr = 0x08;
    Input::end();
    assert(enabled == 0x0c && icr == 0 && depth == 0);
    puts("Amiga input register paths: ok");
}
'''


def run(source: str, expected_ok: bool, sync: bool) -> None:
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='input-registers-', dir=ROOT / 'tmp') as name:
        d = Path(name)
        for path, text in HEADERS.items():
            p = d / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (d / 'Input.cpp').write_text(source)
        (d / 'probe.cpp').write_text(HARNESS)
        subprocess.run(['c++', '-std=c++17', '-O2', *(['-DSWOTL_SYNC'] if sync else []), '-I', str(d), '-I',
                        str(ROOT / 'src/platform/amiga'), str(d / 'Input.cpp'),
                        str(d / 'probe.cpp'), '-o', str(d / 'probe')], check=True)
        result = subprocess.run([str(d / 'probe')], capture_output=True, text=True)
        assert (result.returncode == 0) == expected_ok, result.stdout + result.stderr
        build = 'sync' if sync else 'production'
        print(f"{build}: {result.stdout.strip()}" if expected_ok else f'{build}: planted input fault caught')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    source = (ROOT / 'src/platform/amiga/Input.cpp').read_text()
    for sync in (True, False):
        run(source, True, sync)
    if args.sabotage:
        # production posts a keyboard interrupt / the sync build posts none
        posting = '#ifdef SWOTL_SYNC\n    rt_irq_ring'
        assert source.count(posting) == 1
        run(source.replace(posting, '#if 1\n    rt_irq_ring'), False, False)
        run(source.replace(posting, '#if 0\n    rt_irq_ring'), False, True)
        for old, new in [('(code >> 1) | (code << 7)', '(code << 1) | (code >> 7)'),
                         ('(int8_t)(x - mouseCounterX)', '(int16_t)(x - mouseCounterX)'),
                         ('isRightMouseButtonPressed() ? 2 : 0', 'isRightMouseButtonPressed() ? 4 : 0'),
                         ('    SetICR(ciaaBase, CIAICRF_SP);\n    uint8_t code', '    uint8_t code'),
                         ('    AbleICR(ciaaBase, CIAICRF_SP);\n', ''),
                         ('!(SetICR(ciaaBase, 0) & CIAICRF_SP)', 'false'),
                         ('    SetICR(ciaaBase, CIAICRF_SP);\n    return true;', '    return true;'),
                         ('AbleICR(ciaaBase, CIAICRF_SETCLR | CIAICRF_SP);', '(void)spEnabled;')]:
            assert source.count(old) == 1
            for sync in (True, False):
                run(source.replace(old, new), False, sync)
