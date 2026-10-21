#!/usr/bin/env python3
"""Timbre envelope resolution under four simultaneously changing voices.

Inject operator attenuation at the voice boundary to isolate quantization
and cache scheduling from the independently checked OPL envelope rate law.
Inspect the attenuation actually encoded in each commanded loop, not just
the requested memo value (a budget-deferred loop may differ).
"""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT/'src/platform/amiga'
WRAPPER = r'''
static int8_t test_pool[65536];
static uint8_t test_opl[256];
void envelope_init(void) {
    fm_init(test_pool, sizeof test_pool);
    for (unsigned c = 0; c < 9; ++c) {
        test_opl[0x20 + op_off[c]] = 1;
        test_opl[0x23 + op_off[c]] = (uint8_t)(c + 1);
        test_opl[0xa0 + c] = 0;
        test_opl[0xb0 + c] = 0x32;
    }
}
void envelope_frame(unsigned raw, unsigned restart, unsigned *effective) {
    static const unsigned channels[4] = {0, 3, 6, 1};
    ++stamp;
    budget = RENDER_BUDGET;
    for (unsigned i = 0; i < 4; ++i) {
        unsigned c = channels[i];
        struct fm_voice v = {0};
        v.restart = restart;
        ops[2*c].rout = raw << 8;
        voice_cmd(&v, i, test_opl, c, 0);
        effective[i] = v.loop ? ((memo[i].key >> 16) & 511) : 0xffff;
    }
}
'''


def checks(source):
    with tempfile.TemporaryDirectory(prefix='fm-envelope-', dir=ROOT/'tmp') as td:
        p = Path(td)
        (p/'envelope.c').write_text(source+WRAPPER)
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall',
                        '-Wextra', '-Werror', '-I'+str(SRC), str(p/'envelope.c'),
                        '-o', str(p/'envelope.so')], check=True)
        lib = C.CDLL(str(p/'envelope.so'))
        effective = (C.c_uint * 4)()
        lib.envelope_init()
        values = list(range(385)) + list(range(383, -1, -1)) + [0, 383, 0, 192, 1, 384]
        largest = 0
        for field, raw in enumerate(values):
            lib.envelope_frame(raw, field == 0 or field % 33 == 0, effective)
            for voice, actual in enumerate(effective):
                error = abs(actual - raw)
                largest = max(largest, error)
                assert error <= 2, (field, voice, raw, actual, 'commanded timbre exceeds 0.375 dB rounding error')
        print(f'FM envelope: {len(values)} fields, four voices, max error {largest * .1875} dB')


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' not in sys.argv:
        checks(source)
        return
    for name, old, new in (
            ('hysteresis', '#define MOD_HOLD 0', '#define MOD_HOLD 12'),
            ('deferred voice', '#define RENDER_BUDGET FM_VOICES', '#define RENDER_BUDGET 1')):
        assert old in source, f'missing plant {name}'
        try:
            checks(source.replace(old, new))
        except AssertionError as e:
            print(f'caught {name}: {e}')
        else:
            raise AssertionError(f'{name} escaped')


if __name__ == '__main__':
    main()
