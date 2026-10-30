#!/usr/bin/env python3
"""Prerendered effect playback (docs/sound-plan.md R3): tfh_paula.c's effect
routing with synthetic samples, no game bytes.

  python3 tests/test_sfx_play.py [--sabotage]

The wanted set: without TFH the 27 played non-engine ids (host_run.py
SFX_PRERENDERED, the capture's), with TFH only those TFH has no sample for.
Per slot and id: the slot's three OPL channels muted, its voice restarted on
the sample's first chunk at the effect period and volume, the next chunk (or
silence) latched a field after the latched one starts, volume 0 once the last
has played; a new start restarts. A sample over one Paula loop splits into
equal chunks. TFH's own samples keep their ids. PAL and NTSC periods and
field lengths. Volume from fm_effect's peak.
"""
import ctypes as C
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import host_run as H  # noqa: E402
import test_tfh as T  # noqa: E402

SRC = ROOT / 'src/platform/amiga'
PLAYED = sorted(H.SFX_PRERENDERED)  # the host capture's set: the same ids
TFH_FM = [19]                       # played ids TFH has no sample for
PERIOD = {0: 214, 1: 216}           # FM_EFFECT_RATE on PAL, NTSC
FIELD = {0: 71051 / 214, 1: 119665 / 2 / 216}   # samples a field
LOOP = 65534


def run_effect(lib, slot, bytes_, ids, starts, opl, v, mode):
    """Starts the registered effect on `slot` and steps fields until silent:
    (fields, the voice per field)."""
    starts[slot] = (starts[slot] + 1) & 255
    out = []
    for _ in range(int(bytes_ / FIELD[mode]) + 8):
        mask = lib.tfh_field(opl, ids, starts, v)
        q = v[slot]
        out.append((mask, q.restart, C.addressof(q.loop.contents) if q.loop else 0, q.bytes,
                    q.period, q.volume))
        if q.volume == 0:
            break
    return out


def checks(lib):
    lib.tfh_chip_bytes.argtypes = [C.c_void_p, C.c_uint32]
    lib.tfh_init.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p]
    lib.tfh_field.argtypes = [C.c_void_p] * 4
    lib.tfh_effect_wanted.argtypes = [C.c_uint8]
    lib.tfh_effect.argtypes = [C.c_uint8, C.c_void_p, C.c_uint32, C.c_uint8, C.c_void_p]
    lib.tfh_effect_volume.argtypes = [C.c_uint32]
    lib.tfh_effect_volume.restype = C.c_uint8
    wanted = [i for i in range(39) if lib.tfh_effect_wanted(i)]
    assert wanted == PLAYED, f'wanted without TFH {wanted}'
    for level, vol in [(0, 1), (32, 1), (4095, 64), (2048, 32), (9000, 64), (64, 1), (96, 2)]:
        assert lib.tfh_effect_volume(level) == vol, f'volume of {level}'
    silence = (C.c_int8 * 4)()
    small = (C.c_int8 * 1000)(*[5] * 1000)
    big_bytes = 72184
    big = (C.c_int8 * big_bytes)()
    opl, starts = (C.c_uint8 * 256)(), (C.c_uint8 * 3)()
    ids = (C.c_uint8 * 3)(255, 255, 255)
    v = (T.Voice * 4)()
    ntsc = C.c_uint8.in_dll(lib, 'fm_ntsc')
    # Unregistered: FM keeps every slot.
    ids[1] = 7
    starts[1] = 1
    assert lib.tfh_field(opl, ids, starts, v) == 0
    for i in PLAYED:
        lib.tfh_effect(i, small if i != 20 else big, 1000 if i != 20 else big_bytes, 10 + i, silence)
    base = C.addressof(small)
    for mode in (0, 1):
        ntsc.value = mode
        for slot in (1, 2):
            for i in PLAYED:
                if i == 20:
                    continue
                ids[:] = [255] * 3
                ids[slot] = i
                f = run_effect(lib, slot, 1000, ids, starts, opl, v, mode)
                assert all(m == 7 << (3 * slot) for m, *_ in f), f'id {i} slot {slot}: mask'
                assert f[0][1:] == (1, base, 1000, PERIOD[mode], 10 + i), f'id {i}: start {f[0]}'
                assert f[1][1:3] == (0, C.addressof(silence)) and f[1][3] == 4, f'id {i}: latch {f[1]}'
                playing = [x for x in f if x[5]]
                want = 1 + -(-(1000 + FIELD[mode]) // FIELD[mode])
                assert abs(len(playing) - want) <= 1 and f[-1][5] == 0, f'id {i}: {len(playing)} fields'
    # Two chunks: equal halves, the second latched at field 1, silence a
    # field after the second starts, then volume 0.
    ntsc.value = 0
    ids[:] = [255, 20, 255]
    f = run_effect(lib, 1, big_bytes, ids, starts, opl, v, 0)
    half = big_bytes // 2
    b = C.addressof(big)
    assert f[0][1:4] == (1, b, half), f'chunk 0 {f[0]}'
    assert f[1][1:4] == (0, b + half, half), f'chunk 1 {f[1]}'
    k = next(n for n, x in enumerate(f) if x[2] == C.addressof(silence))
    field8 = 256 * 71051 // 214     # tfh_paula.c's 24.8 samples a field
    want = next(n for n in range(1, 1000) if n * field8 >> 8 >= half + (field8 >> 8))
    assert k == want, f'silence latched at field {k}, not {want}'
    assert f[-1][5] == 0 and len(f) - 1 >= big_bytes / FIELD[0], f'ended after {len(f)} fields'
    # A new start mid-effect restarts; the same start number does not.
    starts[1] = (starts[1] + 1) & 255
    for _ in range(3):
        lib.tfh_field(opl, ids, starts, v)
    assert v[1].restart == 0 and v[1].volume == 30
    starts[1] = (starts[1] + 1) & 255
    assert lib.tfh_field(opl, ids, starts, v) and v[1].restart == 1
    assert lib.tfh_field(opl, ids, starts, v) and v[1].restart == 0
    # A sample over two loops is refused (id 19 keeps its own, checked below).
    lib.tfh_effect(19, big, 131070, 64, silence)
    # TFH loaded: its samples keep their ids; the effects play the rest.
    raw = T.resource()
    rsc = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
    chip = (C.c_int8 * 212)()
    assert lib.tfh_init(rsc, len(raw), chip) == 0
    wanted = [i for i in range(39) if lib.tfh_effect_wanted(i)]
    assert wanted == TFH_FM, f'wanted with TFH {wanted}'
    for i in PLAYED:
        ids[:] = [255, i, 255]
        starts[1] = (starts[1] + 1) & 255
        lib.tfh_field(opl, ids, starts, v)
        own = C.addressof(v[1].loop.contents)
        if i in TFH_FM:
            assert own == base and v[1].period == 214, f'id {i}: not the effect'
        else:
            assert C.addressof(chip) <= own < C.addressof(chip) + 212, f'id {i}: not TFH'
    print(f'effect play: wanted sets, {len(PLAYED) - 1} ids x 2 slots x PAL/NTSC, chunks, restart, TFH precedence: ok')


def main():
    plants = {'latch': ('tfh_paula.c', '* e->chunk + (field >> 8)', '* e->chunk'),
              'chunk': ('tfh_paula.c', '(bytes + EFFECT_LOOP_BYTES - 1) / EFFECT_LOOP_BYTES', '1'),
              'volume': ('tfh_paula.c', 'v->volume = e->volume;', 'v->volume = (uint8_t)(e->volume / 2);'),
              'wanted': ('tfh_paula.c', 'id == 33 || ', ''),
              'precedence': ('tfh_paula.c', 'tfh_loaded && sound_of[id[k]] != FM', 'tfh_loaded && sound_of[id[k]] != FM && !effects[id[k]].pcm'),
              'ntsc': ('tfh_paula.c', 'fm_ntsc ? EFFECT_PERIOD_NTSC', '0 ? EFFECT_PERIOD_NTSC')}
    cases = plants.items() if '--sabotage' in sys.argv else [('normal', None)]
    missed = []
    for name, plant in cases:
        with tempfile.TemporaryDirectory(prefix='swotl-sfx-play-') as tmp:
            paths = []
            for filename in ('fm_paula.c', 'tfh_paula.c'):
                text = (SRC / filename).read_text()
                if plant and filename == plant[0]:
                    assert plant[1] in text, name
                    text = text.replace(plant[1], plant[2])
                path = Path(tmp) / filename
                path.write_text(text)
                paths.append(str(path))
            dll = Path(tmp) / 'sfx.dylib'
            subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(SRC),
                            *paths, '-o', str(dll)], check=True)
            try:
                checks(C.CDLL(str(dll)))
            except AssertionError as e:
                if not plant:
                    raise
                print(f'plant {name}: caught ({e})')
            else:
                if plant:
                    print(f'plant {name}: MISSED')
                    missed.append(name)
    if missed:
        print('FAIL: plants missed:', ', '.join(missed))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
