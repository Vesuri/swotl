#!/usr/bin/env python3
"""Tonal loops retain the OPL synthesis phase as attenuation changes.

An independent operator-math oracle checks every sample, including the
wrap endpoints. Rotating each loop to a different zero crossing fails.
"""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile

from test_fm_render import MULT, sample

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'


def expected(wave, feedback, attenuation, size):
    # Equal unit multipliers: one common period, starting at phase zero.
    increment = (MULT[1] << 16) // (MULT[1] << (wave >= 2)) // size
    phase = previous = older = 0
    result = []
    settle = 32 if feedback else 0
    for i in range(settle + size):
        offset = (previous + older) >> (9-feedback) if feedback else 0
        modulator = sample(wave, (phase >> 6) + offset, attenuation)
        carrier = sample(wave, (phase >> 6) + modulator, 0)
        older, previous = previous, modulator
        phase = (phase + increment) & 0xffffffff
        if i >= settle:
            result.append(((carrier >> 5) + 128) % 256 - 128)
    return result


def checks(source):
    with tempfile.TemporaryDirectory(prefix='fm-phase-', dir=ROOT/'tmp') as td:
        p = Path(td)
        (p/'phase.c').write_text(source + '''
void phase_render(int8_t *out, uint32_t key, uint16_t size) {
    build_wave(); render(out, key, size);
}
''')
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall',
                        '-Wextra', '-Werror', '-I'+str(SRC), str(p/'phase.c'),
                        '-o', str(p/'phase.so')], check=True)
        lib = C.CDLL(str(p/'phase.so'))
        lib.phase_render.argtypes = [C.c_void_p, C.c_uint32, C.c_uint16]
        count = 0
        for wave in range(4):
            for feedback in (0, 3, 5, 7):
                for attenuation in (80, 81, 82, 83, 126, 127, 128, 129):
                    for lg in (6, 8):
                        size = 1 << lg
                        out = (C.c_int8 * size)()
                        key = wave | wave << 2 | 1 << 4 | 1 << 8 | feedback << 12 | attenuation << 16 | lg << 25
                        lib.phase_render(out, key, size)
                        assert list(out) == expected(wave, feedback, attenuation, size), (
                            'synthesis phase changed', wave, feedback, attenuation, size)
                        count += 1
        print(f'FM phase: {count} loops, all samples and wrap endpoints match the operator oracle')


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' not in sys.argv:
        checks(source)
        return
    old = 'uint32_t pc = 0, pm = 0;'
    assert old in source
    try:
        checks(source.replace(old, 'uint32_t pc = 64, pm = 64;'))
    except AssertionError as e:
        print('caught loop phase shift:', e)
    else:
        raise AssertionError('loop phase shift escaped')


if __name__ == '__main__':
    main()
