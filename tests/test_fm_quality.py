#!/usr/bin/env python3
"""Paula quality contracts: low-note rate, loop joins and non-tonal noise.
Synthetic OPL patches only; the existing Nuked comparison remains the oracle
for level and pitch. Sabotages restore each rejected rendering policy.
"""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile

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
    # Tonal feedback loops should join near zero even as timbre changes.
    opl[0xc0] = 10
    opl[0xa0], opl[0xb0] = 512 & 255, 0x32
    lib.fm_init(pool, len(pool))
    for level in (8, 12, 16, 20, 24):
        opl[0x40] = level
        lib.fm_field(opl, keyon, 0, voices)
        x = list(v.loop[:v.bytes])
        best = min(abs(x[i])+abs(x[i-1]) for i in range(len(x)))
        assert abs(x[0])+abs(x[-1]) == best, 'loop join misses quietest boundary'


def run(source):
    with tempfile.TemporaryDirectory(prefix='swotl-fm-quality-') as tmp:
        p = Path(tmp)
        (p/'fm.c').write_text(source)
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall', '-Wextra',
                        '-Werror', '-I'+str(SRC), str(p/'fm.c'), '-o', str(p/'fm.so')], check=True)
        checks(C.CDLL(str(p/'fm.so')))


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' not in sys.argv:
        run(source)
        print('FM quality: rate, noise and loop joins ok')
        return
    plants = {
        'rate': ('#define LOOP_LOG 12', '#define LOOP_LOG 6'),
        'noise': ('(0x1fbu << 4)', '(0x200u << 4)'),
        'noise-rate': ('#define NOISE_PERIOD 18264u', '#define NOISE_PERIOD 36528u'),
        'join': ('uint16_t lo = j == 1 ? best : 0;', 'uint16_t lo = bytes; (void)best;'),
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
