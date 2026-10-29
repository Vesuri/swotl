#!/usr/bin/env python3
"""Paula quality contracts: low-note rate, loop joins, non-tonal noise, and
the same pitch and envelope speed on NTSC (fm_ntsc) as on PAL.
Synthetic OPL patches only; the existing Nuked comparison remains the oracle
for level and pitch. Sabotages restore each rejected rendering policy.
"""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile

from test_fm_render import reference

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'


class Voice(C.Structure):
    _fields_ = [('loop', C.POINTER(C.c_int8)), ('bytes', C.c_uint16),
                ('period', C.c_uint16), ('volume', C.c_uint8),
                ('restart', C.c_uint8), ('channel', C.c_int8)]


def checks(lib):
    pool = (C.c_int8 * 65536)()
    opl = (C.c_uint8 * 256)()
    keyon = (C.c_uint8 * 9)()
    voices = (Voice * 4)()
    lib.fm_field.argtypes = [C.c_void_p, C.c_void_p, C.c_uint16, C.c_void_p]
    # Sustained half-frequency sine: 3.7 Hz fundamental (low effect sweep).
    opl[0x20] = opl[0x23] = 0x20
    opl[0x40] = 63
    opl[0x60] = opl[0x63] = 0xf0
    opl[0xa0], opl[0xb0] = 312 & 255, 0x21
    keyon[0] = 1
    lib.fm_init(pool, len(pool))
    lib.fm_field(opl, keyon, 0, voices)
    v = voices[0]
    assert v.loop and 3546895 / v.period >= 8363, 'low-note playback below 8363 Hz'
    # A continuing low note jumping to the highest pitch must not overflow
    # the sample-count product before selecting a shorter loop.
    opl[0xa0], opl[0xb0] = 255, 0x3f
    lib.fm_field(opl, keyon, 0, voices)
    assert v.bytes == 8 and v.period == 143, 'high-pitch loop selection overflow'
    # With both multipliers at 8, this continuing-note jump would make
    # x * g << 12 exactly 2**32 without the pre-shift bound.
    opl[0x20] = opl[0x23] = 0x28
    opl[0xa0], opl[0xb0] = 10, 0x20
    lib.fm_field(opl, keyon, 0, voices)
    assert v.bytes == 4096
    opl[0xa0], opl[0xb0] = 0, 0x3e
    lib.fm_field(opl, keyon, 0, voices)
    assert v.bytes == 8 and v.period == 124, 'overflowing pitch jump'
    # Feedback noise must not repeat as a short pitched waveform.
    opl[0x20] = opl[0x23] = 0x21
    opl[0x40] = 0
    opl[0xc0] = 14
    opl[0xa0], opl[0xb0] = 155, 0x30
    lib.fm_init(pool, len(pool))
    lib.fm_field(opl, keyon, 0, voices)
    assert 3546895 / v.period >= 8363, 'jet-range noise rate below 8363 Hz'
    x = list(v.loop[:v.bytes])
    mean = sum(x) / len(x)
    x = [a - mean for a in x]
    for lag in (128, 256, 512):
        a, b = x[:-lag], x[lag:]
        corr = sum(u*w for u,w in zip(a,b)) / (sum(u*u for u in a)*sum(w*w for w in b))**0.5
        assert corr < .3, f'pitched noise: lag {lag}, correlation {corr:.3f}'
    # Retain these timbre cases, checking every sample and wrap endpoint
    # against canonical synthesis phase instead of an arbitrary quiet crossing.
    opl[0xc0] = 10
    opl[0xa0], opl[0xb0] = 512 & 255, 0x32
    lib.fm_init(pool, len(pool))
    for level in (8, 12, 16, 20, 24):
        opl[0x40] = level
        lib.fm_field(opl, keyon, 0, voices)
        x = list(v.loop[:v.bytes])
        key = lib.quality_key()
        expected = reference(key & 3, (key >> 2) & 3, (key >> 4) & 15,
                             (key >> 8) & 15, (key >> 12) & 7,
                             (key >> 15) & 1, (key >> 16) & 511,
                             (key >> 25) & 15, step=1)
        assert x == expected, 'loop phase differs from operator oracle'


def ntsc_checks(lib):
    """Pitch in Hz from each clock's periods, envelope steps per second from
    each field rate: PAL and NTSC agree within their rounding."""
    pool = (C.c_int8 * 65536)()
    opl = (C.c_uint8 * 256)()
    keyon = (C.c_uint8 * 9)()
    voices = (Voice * 4)()
    lib.fm_field.argtypes = [C.c_void_p, C.c_void_p, C.c_uint16, C.c_void_p]
    ntsc = C.c_uint8.in_dll(lib, 'fm_ntsc')
    clock, field_hz = (3546895, 3579545), (3546895 / (227 * 313), 3579545 / (227.5 * 263))
    for fb, fnum, block in ((0, 312, 0), (0, 580, 4), (0, 1000, 7), (7, 155, 4)):
        opl[0x20] = opl[0x23] = 0x21
        opl[0x40] = 0 if fb else 63
        opl[0x60] = opl[0x63] = 0xf0
        opl[0xc0] = fb << 1
        opl[0xa0], opl[0xb0] = fnum & 255, 0x20 | block << 2 | fnum >> 8
        keyon[0] += 1
        hz, steps = [], []
        for mode in (0, 1):
            ntsc.value = mode
            lib.fm_init(pool, len(pool))
            lib.fm_field(opl, keyon, 0, voices)
            v = voices[0]
            hz.append(clock[mode] / v.period * 2 / v.bytes if v.loop else 0)
            steps.append([lib.quality_steps(r) * field_hz[mode] for r in range(64)])
        assert hz[0] and abs(hz[1] / hz[0] - 1) < 1.5 / voices[0].period, \
            f'NTSC pitch {hz[1]:.2f} Hz, PAL {hz[0]:.2f} Hz'
    ntsc.value = 0
    for r in range(16, 64):
        assert abs(steps[1][r] / steps[0][r] - 1) < 2e-3, f'NTSC envelope rate {r}'


def run(source):
    with tempfile.TemporaryDirectory(prefix='swotl-fm-quality-') as tmp:
        p = Path(tmp)
        (p/'fm.c').write_text(source + '\nuint32_t quality_key(void) { return memo[0].key; }\n'
                                '\nuint32_t quality_steps(unsigned r) { return steps[r]; }\n')
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall', '-Wextra',
                        '-Werror', '-I'+str(SRC), str(p/'fm.c'), '-o', str(p/'fm.so')], check=True)
        lib = C.CDLL(str(p/'fm.so'))
        lib.quality_key.restype = C.c_uint32
        lib.quality_steps.restype = C.c_uint32
        checks(lib)
        ntsc_checks(lib)


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' not in sys.argv:
        run(source)
        print('FM quality: rate, noise, loop joins and NTSC ok')
        return
    plants = {
        'rate': ('#define LOOP_LOG 12', '#define LOOP_LOG 6'),
        'noise': ('(0x1fbu << 4)', '(0x200u << 4)'),
        'noise-rate': ('#define NOISE_PERIOD_PAL 18264u', '#define NOISE_PERIOD_PAL 36528u'),
        'ntsc-pitch': ('#define PERIOD_NUM_NTSC 150994649u', '#define PERIOD_NUM_NTSC 149617386u'),
        'ntsc-noise': ('#define NOISE_PERIOD_NTSC 18432u', '#define NOISE_PERIOD_NTSC 18264u'),
        'ntsc-envelope': ('#define RATE_FIELD_NTSC 26592u', '#define RATE_FIELD_NTSC 31869u'),
        'phase': ('uint32_t pc = 0, pm = 0;', 'uint32_t pc = 64, pm = 64;'),
    }
    for name, (old, new) in plants.items():
        assert old in source, f'missing plant {name}'
        try:
            run(source.replace(old,new))
        except AssertionError as e:
            print(f'caught {name}: {e}')
        else:
            raise AssertionError(f'uncaught {name}')


if __name__ == '__main__':
    main()
