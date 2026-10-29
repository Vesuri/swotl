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
extern uint8_t rt_joystick;
extern volatile uint16_t rt_joystick_axis[2];
extern volatile uint8_t rt_joystick_buttons;
''',
    'platform.h': '',
    'AmigaHardware.h': '''#pragma once
#include <stdint.h>
extern volatile uint8_t sdr, cra, pra;
extern volatile uint16_t joy, joy1, pot, pot1, potgo;
#define ciaasdrPointer (&sdr)
#define ciaacraPointer (&cra)
#define ciaapraPointer (&pra)
#define joy0datPointer (&joy)
#define joy1datPointer (&joy1)
#define pot1datPointer (&pot1)
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
#include <vector>
#include <proto/cia.h>
#include "Input.h"
#include "AmigaHardware.h"
extern "C" {
#include "runtime.h"
uint32_t plat_mouse(int32_t *, int32_t *);
uint16_t rt_key_ring[RT_KEY_RING];
uint8_t rt_irq_ring[RT_IRQ_RING];
unsigned rt_key_tail, rt_irq_tail, raises;
uint8_t amiga_ntsc;
uint8_t rt_joystick;
volatile uint16_t rt_joystick_axis[2];
volatile uint8_t rt_joystick_buttons;
}
volatile uint8_t sdr, cra, pra = 255;
volatile uint16_t joy, joy1, pot = 65535, pot1, potgo = 65535;
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
// A held key's repeats over 1.5 s of fields, PAL (50 Hz) or NTSC (60 Hz):
// the first after the same time (within a field), the same count.
static void repeat(uint8_t ntsc) {
    amiga_ntsc = ntsc;
    unsigned hz = ntsc ? 60 : 50, first = 0, n = 0;
    edge(0x77, 0x1c, 9);
    unsigned k = rt_key_tail;
    for (unsigned f = 1; f <= hz * 3 / 2; ++f) {
        Input::verticalBlank();
        if (rt_key_tail != k) {
            assert(rt_key_tail == k + 1 && rt_key_ring[k % RT_KEY_RING] == 0x1c);
            if (!first) first = f;
            ++n;
            k = rt_key_tail;
        }
    }
    edge(0x76, 0x9c, 0x89);
    printf("repeat %u Hz: first %u fields, %u\n", hz, first, n);
    assert(first == (ntsc ? 35u : 29u) && n == 11);   // 580 and 583 ms
    amiga_ntsc = 0;
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
// Port 2 at a vertical blank: JOY1DAT, then the PC codes posted.
static void stick(unsigned value, std::vector<unsigned> scans) {
    unsigned k = rt_key_tail;
    joy1 = value;
    Input::verticalBlank();
    assert(rt_key_tail == k + scans.size() && depth == 0);
    for (size_t n = 0; n < scans.size(); ++n) {
        assert(rt_key_ring[(k + n) % RT_KEY_RING] == scans[n]);
    }
}
static unsigned buttons() {
    int32_t x, y;
    return plat_mouse(&x, &y);
}
// Digital joystick: JOY1DAT (L78: up b8^b9, left b9, down b0^b1, right b1)
// presses the cursor keys; fire (PRA bit 7) and pin 9 (POTINP bit 14) are
// mouse buttons 1 and 2.
static void digital() {
    pra = 0xff; pot = 0xffff;      // mouse buttons released
    stick(0x0100, {0x148}); stick(0, {0x1c8});
    stick(0x0001, {0x150}); stick(0, {0x1d0});
    stick(0x0300, {0x14b}); stick(0, {0x1cb});
    stick(0x0003, {0x14d}); stick(0, {0x1cd});
    stick(0x0200, {0x148, 0x14b}); stick(0x0002, {0x1c8, 0x150, 0x1cb, 0x14d});
    stick(0x0002, {}); stick(0, {0x1d0, 0x1cd});
    // A held direction repeats as its key does.
    stick(0x0100, {0x148});
    unsigned k = rt_key_tail;
    for (unsigned f = 0; f < 29; ++f) Input::verticalBlank();
    assert(rt_key_tail == k + 1 && rt_key_ring[k % RT_KEY_RING] == 0x148);
    stick(0, {0x1c8});
    pra = 0x7f; assert(buttons() == 1 && rt_joystick_buttons == 1);
    pra = 0x3f; assert(buttons() == 1);
    pra = 0xff; pot = 0xffff ^ 1 << 14; assert(buttons() == 2 && rt_joystick_buttons == 2);
    pot = 0xffff ^ 1 << 14 ^ 1 << 10; assert(buttons() == 2);
    pot = 0xffff; assert(buttons() == 0 && rt_joystick_buttons == 0);
}
// Proportional joystick: POTGO START at each vertical blank, POT1DAT read at
// the next, four fields averaged, plus 16; buttons on pins 3 and 4 (JOY1DAT
// bits 9 and 1); directions post nothing; POTINP's buttons as read before
// the START.
static void analog() {
    rt_joystick = 1;
    potgo = 0;
    pot1 = 0x6040;
    stick(0, {});
    assert(potgo == 1 && rt_joystick_axis[0] == 0 && rt_joystick_axis[1] == 0);
    potgo = 0;
    stick(0, {});
    assert(potgo == 1 && rt_joystick_axis[0] == 16 + 0x40 && rt_joystick_axis[1] == 16 + 0x60);
    pot1 = 0x7050;
    stick(0, {});
    assert(rt_joystick_axis[0] == 16 + 68 && rt_joystick_axis[1] == 16 + 100);
    for (unsigned f = 0; f < 3; ++f) stick(0, {});
    assert(rt_joystick_axis[0] == 16 + 0x50 && rt_joystick_axis[1] == 16 + 0x70);
    stick(0x0100, {}); stick(0x0003, {}); stick(0, {});
    joy1 = 0x0200; assert(buttons() == 1 && rt_joystick_buttons == 1);
    joy1 = 0x0002; assert(buttons() == 2 && rt_joystick_buttons == 2);
    joy1 = 0x0202; assert(buttons() == 3 && rt_joystick_buttons == 3);
    joy1 = 0x0101; assert(buttons() == 0 && rt_joystick_buttons == 0);
    pra = 0x7f; pot = 0xffff ^ 1 << 14; assert(buttons() == 0);
    pra = 0xff;
    pot = 0xffff ^ 1 << 10;        // the START's discharge: not a right button
    assert(buttons() == 0);
    Input::verticalBlank();
    assert(buttons() == 2);
    pot = 0xffff;
    Input::verticalBlank();
    assert(buttons() == 0);
    rt_joystick = 0;
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
    repeat(0); repeat(1);
    // Both wrap directions, then every combination of three hardware buttons.
    mouse(0x0302, 0, 8, 9);
    mouse(0xfcfe, 1, -4, -7);
    for (unsigned b = 0; b < 8; ++b) mouse(0xfcfe, b, 0, 0);
    // Pending motion accumulates until the guest consumes it.
    joy = 0xfdff; Input::verticalBlank();
    joy = 0x0002; Input::verticalBlank();
    int32_t x, y;
    assert(plat_mouse(&x, &y) == 7 && x == 4 && y == 4);
    // A request takes the counters at once: motion since the last field and
    // a button change reach the guest without a vertical blank, both wraps.
    joy = 0x0405; pra = 0xff;
    assert(plat_mouse(&x, &y) == 6 && x == 3 && y == 4 && depth == 0);
    joy = 0xfefc; Input::verticalBlank();
    joy = 0x0101;
    assert(plat_mouse(&x, &y) == 6 && x == -4 && y == -3);
    assert(plat_mouse(&x, &y) == 6 && x == 0 && y == 0);
    digital();
    analog();
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
                         ('#endif\n    Input::sample();\n', '#endif\n'),
                         ('(int8_t)(x - mouseCounterX)', '(int16_t)(x - mouseCounterX)'),
                         ('(pins & (1 << 10) ? 0 : 2)', '(pins & (1 << 10) ? 0 : 4)'),
                         ('{0x4c, 0x4d, 0x4f, 0x4e}', '{0x4c, 0x4d, 0x4e, 0x4f}'),
                         ('(joy >> 8 ^ left) & 1', '(joy >> 8) & 1'),
                         ('(joy ^ right) & 1) << 1', '(joy & 1)) << 1'),
                         ('pins & (1 << 14) ? 0 : 2', 'pins & (1 << 12) ? 0 : 2'),
                         ('*ciaapraPointer & 0x80 ? 0 : 1', '*ciaapraPointer & 0x40 ? 0 : 1'),
                         ('(joy >> 9 & 1) | (joy & 2)', '(joy >> 9 & 1) | (joy << 1 & 2)'),
                         ('rt_joystick ? potButtons : *potinpPointer', '*potinpPointer'),
                         ('16 + ((x + 2) >> 2)', '((x + 2) >> 2)'),
                         ('potHistory[potIndex] = raw;', '(void)raw;'),
                         ('    *potgoPointer = 1;\n', ''),
                         ('        digitalJoystick();\n', ''),
                         ('    SetICR(ciaaBase, CIAICRF_SP);\n    uint8_t code', '    uint8_t code'),
                         ('    AbleICR(ciaaBase, CIAICRF_SP);\n', ''),
                         ('!(SetICR(ciaaBase, 0) & CIAICRF_SP)', 'false'),
                         ('    SetICR(ciaaBase, CIAICRF_SP);\n    return true;', '    return true;'),
                         ('AbleICR(ciaaBase, CIAICRF_SETCLR | CIAICRF_SP);', '(void)spEnabled;')]:
            assert source.count(old) == 1
            for sync in (True, False):
                run(source.replace(old, new), False, sync)
