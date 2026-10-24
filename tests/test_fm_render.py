#!/usr/bin/env python3
"""Exact tonal-loop samples from OPL operator mathematics, plus output bounds.

The reference constructs the OPL ROMs from their closed forms, independently
of the production tables and staging implementation. Nuked whole-sound
level/pitch checks remain mandatory; this checks the loop representation.
"""
import ctypes as C
import math
from pathlib import Path
import random
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'
MULT = (1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 20, 24, 24, 30, 30)
LOG = [round(-math.log2(math.sin((p + .5) * math.pi / 512)) * 256)
       for p in range(256)]
EXP = [round(2 ** ((255 - p) / 256) * 1024) * 2 for p in range(256)]


def sample(wave, phase, attenuation):
    phase &= 1023
    sine = LOG[(phase & 255) ^ (255 if phase & 256 else 0)]
    negative = wave == 0 and bool(phase & 512)
    if wave == 1 and phase & 512 or wave == 3 and phase & 256:
        sine = 4096
    elif wave == 3:
        sine = LOG[phase & 255]
    level = min(sine + attenuation * 8, 8191)
    value = EXP[level & 255] >> (level >> 8)
    return ~value if negative else value


def reference(wc, wm, mc, mm, fb, additive, mq, lg, step=16):
    a, b = MULT[mc] << (wc >= 2), MULT[mm] << (wm >= 2)
    g = a if mq * step >= 384 else math.gcd(a, b)
    size = 1 << lg
    ic, im = (MULT[mc] << 16) // g // size, (MULT[mm] << 16) // g // size
    pc = pm = prev1 = prev2 = 0
    result = []
    settle = 32 if fb else 0
    for i in range(settle + size):
        feedback = (prev1 + prev2) >> (9 - fb) if fb else 0
        mod = sample(wm, (pm >> 6) + feedback, mq * step)
        carrier = sample(wc, (pc >> 6) + (0 if additive else mod), 0)
        if additive:
            carrier = (carrier + mod) >> 1
        pc = (pc + ic) & 0xffffffff
        pm = (pm + im) & 0xffffffff
        prev2, prev1 = prev1, mod
        if i >= settle:
            result.append(((carrier >> 5) + 128) % 256 - 128)
    # Keep the synthesis phase, including both sides of every wrap boundary.
    return result


def checks(source):
    with tempfile.TemporaryDirectory(prefix='fm-render-', dir=ROOT/'tmp') as td:
        p = Path(td)
        (p/'render.c').write_text(source + '''
void check_render(int8_t *dst, uint32_t key, uint16_t bytes) {
    build_wave(); render(dst, key, bytes);
}
int check_operator(unsigned wf, unsigned phase, unsigned attenuation) {
    return op_out((uint8_t)wf, (uint16_t)phase, (uint16_t)attenuation);
}
''')
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall',
                        '-Wextra', '-Werror', '-I'+str(SRC), str(p/'render.c'),
                        '-o', str(p/'render.so')], check=True)
        lib = C.CDLL(str(p/'render.so'))
        lib.check_render.argtypes = [C.c_void_p, C.c_uint32, C.c_uint16]
        lib.check_operator.argtypes = [C.c_uint, C.c_uint, C.c_uint]
        lib.check_operator.restype = C.c_int
        cases = [(wc, wm, 1, 1, fb, add, mq, lg)
                 for wc in range(4) for wm in range(4)
                 for fb, add, mq, lg in ((0, 0, 24, 3), (7, 0, 0, 12),
                                         (5, 1, 23, 8), (1, 1, 127, 4))]
        rng = random.Random(34)
        cases += [(rng.randrange(4), rng.randrange(4), rng.randrange(16),
                   rng.randrange(16), rng.randrange(8), rng.randrange(2),
                   rng.choice((0, 1, 23, 24, 25, 127)), lg)
                  for lg in range(3, 13) for _ in range(16)]
        # Retain all old physical attenuation cases; values >=72 dB produce
        # only signed zero and use the same silent-modulator period.
        cases = [(case, 16) for case in cases]
        cases += [((wc, wm, 1, 3, 5, 0, q, 9), 4)
                  for wc in range(4) for wm in range(4)
                  for q in (1, 2, 3, 31, 63, 95, 96)]
        cases += [((wc, wm, 1, 3, 5, 0, q, 9), 1)
                  for wc in range(4) for wm in range(4)
                  for q in (1, 2, 3, 127, 128, 255, 256, 383, 384)]
        for case, step in cases:
            wc, wm, mc, mm, fb, add, mq, lg = case
            n = 1 << lg
            encoded = min(mq * step, 384)
            key = wc | wm << 2 | mc << 4 | mm << 8 | fb << 12 | add << 15 | encoded << 16 | lg << 25
            memory = (C.c_int8 * (n+32))(*([85]*(n+32)))
            lib.check_render(C.byref(memory, 16), key, n)
            assert list(memory[:16]) == [85]*16 and list(memory[-16:]) == [85]*16, 'output bounds'
            assert list(memory[16:-16]) == reference(*case, step), f'sample mismatch {case}, step {step}'
        for wf in range(4):
            for att in (*range(385), 385, 386, 511, 1023, 65535):
                for phase in (*range(0, 1024, 37), 255, 256, 511, 512, 767, 768, 1023, 65535):
                    assert lib.check_operator(wf, phase, att) == sample(wf, phase, att), (wf, phase, att)
        return len(cases)


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' in sys.argv:
        for name, old, new in (
                ('sample store', '*dst++ = (int8_t)(c >> 5);', '*dst++ = (int8_t)((c >> 5) ^ 1);'),
                ('exponential lookup', 'l = linear_exp[level];', 'l = linear_exp[level] ^ 64;'),
                ('attenuation threshold', '((uint32_t)att << 3)', '(((uint32_t)att + 1) << 3)'),
                ('silent half', '(p & 0x200) ? 0x1000 : c2', '(p & 0x200) ? 0 : c2'),
                ('carrier lookup', 'return carrier_wave[wf][p & 0x3ff];',
                 'return carrier_wave[wf][p & 0x3ff] ^ 64;'),
                ('modulator sign', '^ (uint16_t)((int16_t)w >> 15)', '^ (uint16_t)(w >> 15)'),
                ('modulator level', 'linear_exp + ((uint32_t)matt << 3)', 'linear_exp + ((uint32_t)matt << 2)'),
                ('feedback settle', 'render_run(dst, FB_SETTLE, bytes, wm, lm, cw, ic, im, fb, 0);',
                 'render_run(dst, 0, bytes, wm, lm, cw, ic, im, fb, 0);'),
                ('additive feedback', 'render_run(dst, FB_SETTLE, bytes, wm, lm, cw, ic, im, fb, 1);',
                 'render_run(dst, FB_SETTLE, bytes, wm, lm, cw, ic, im, fb, 0);')):
            assert source.count(old) == 1, f'missing {name} plant'
            try:
                checks(source.replace(old, new))
            except AssertionError as e:
                print(f'caught damaged {name}:', e)
            else:
                raise AssertionError(f'damaged {name} escaped')
    else:
        print('FM exact render:', checks(source), 'cases passed')


if __name__ == '__main__':
    main()
