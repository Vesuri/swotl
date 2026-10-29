#!/usr/bin/env python3
"""TFH contract: synthetic resources, expected Paula commands, and FM ownership.
No game bytes: fixtures encode the documented TFH descriptor format.
"""
import ctypes as C
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'


class Voice(C.Structure):
    _fields_ = [('loop', C.POINTER(C.c_int8)), ('bytes', C.c_uint16),
                ('period', C.c_uint16), ('volume', C.c_uint8),
                ('restart', C.c_uint8), ('channel', C.c_int8)]


def resource(sustain=0xffff):
    data = bytearray(4)
    entries = []
    for k in range(13):
        d = bytearray(33)
        struct.pack_into('>I', d, 12, 4 if k in (0, 10) else 0)
        struct.pack_into('>H', d, 18, 800)
        d[22:28] = bytes([255, 64, 64, 255, 64, 32])
        struct.pack_into('>H', d, 28, sustain)
        d[30:33] = bytes([255, 8, 0])
        for rid, payload in [(1001 + k, d), (2001 + k, bytes([k + 1] * 16))]:
            entries.append((rid, len(data)))
            data += struct.pack('>HH', len(payload), 0) + payload
    struct.pack_into('>I', data, 0, len(data))
    data += struct.pack('>IH', 0, len(entries))
    for rid, off in entries:
        data += struct.pack('>HI', rid, off)
    return data


def checks(lib):
    lib.tfh_chip_bytes.argtypes = [C.c_void_p, C.c_uint32]
    lib.tfh_init.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p]
    lib.tfh_field.argtypes = [C.c_void_p] * 4
    lib.fm_init.argtypes = [C.c_void_p, C.c_uint32]
    lib.fm_field.argtypes = [C.c_void_p, C.c_void_p, C.c_uint16, C.c_void_p]
    raw = resource()
    rsc = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
    chip = (C.c_int8 * 212)()
    assert lib.tfh_chip_bytes(rsc, len(raw)) == 212
    for n in (0, 3, 4, len(raw) - 1):
        assert lib.tfh_chip_bytes(rsc, n) == 0
    bad = bytearray(raw)
    bad[:4] = b'\xff' * 4
    assert lib.tfh_chip_bytes(bytes(bad), len(bad)) == 0
    bad = bytearray(raw)
    off = struct.unpack_from('>I', raw)[0]
    bad[off + 8:off + 12] = b'\xff' * 4
    assert lib.tfh_chip_bytes(bytes(bad), len(bad)) == 0
    assert lib.tfh_init(rsc, len(raw), chip) == 0
    opl, starts = (C.c_uint8 * 256)(), (C.c_uint8 * 3)()
    ids = (C.c_uint8 * 3)(255, 255, 255)
    v = (Voice * 4)()
    assert lib.tfh_field(opl, ids, starts, v) == 0
    sounds = [0,10,8,None,None,None,None,3,3,3,3,3,3,4,4,4,4,4,4,None,9,2,None,2,1,2,2,None,11,6,5,5,7,None,12,None,None,7,7]
    volumes = [64,64,64,0,0,0,0,45,16,8,64,46,43,64,30,13,54,27,9,0,64,52,0,64,64,28,18,0,64,64,64,10,64,0,64,0,0,9,24]
    for slot in range(3):
        for effect, sample in enumerate(sounds):
            ids[:] = [255] * 3
            ids[slot] = effect
            starts[slot] = (starts[slot] + 1) & 255
            opl[0xb0 + slot * 3] = 0x20
            mask = lib.tfh_field(opl, ids, starts, v)
            assert mask == (0 if sample is None else 7 << (slot * 3))
            if sample is None:
                continue
            q = v[slot]
            assert q.restart == 1 and q.bytes == 16 and q.volume == volumes[effect]
            assert list(q.loop[:16]) == [sample + 1] * 16
            lib.tfh_field(opl, ids, starts, v)
            assert q.restart == 0 and q.volume == volumes[effect] // 2
            assert q.bytes == (12 if sample in (0, 10) else 4)
            assert list(q.loop[:q.bytes]) == ([sample + 1] * 12 if sample in (0, 10) else [0] * 4)
    # Loop key-off releases to silence; a new start, including counter wrap,
    # starts from the first segment. Reinitialisation must reset counters.
    lib.tfh_init(rsc, len(raw), chip)
    ids[:] = [0, 255, 255]
    starts[:] = [1, 0, 0]
    opl[0xb0] = 0x20
    assert lib.tfh_field(opl, ids, starts, v) == 7 and v[0].restart
    lib.tfh_field(opl, ids, starts, v)
    opl[0xb0] = 0
    for _ in range(12):
        lib.tfh_field(opl, ids, starts, v)
    assert v[0].volume == 0
    for counter in (255, 0):
        starts[0] = counter
        lib.tfh_field(opl, ids, starts, v)
        assert v[0].restart
    # Engine pitch uses slot-zero F-number: 60 mph -> 800, double -> 400.
    for f, want in [(161, 800), (322, 400)]:
        opl[0xa0], opl[0xb0] = f & 255, 0x20 | (3 << 2) | (f >> 8)
        lib.tfh_field(opl, ids, starts, v)
        assert v[0].period == want
    # All 512 masks, including the fourth voice and sticky previous choices.
    pool = (C.c_int8 * 16384)()
    keyon = (C.c_uint8 * 9)(*[1] * 9)
    for ch, mo in enumerate([0,1,2,8,9,10,16,17,18]):
        opl[0xa0 + ch], opl[0xb0 + ch] = 161, 0x2c
        opl[0xc0 + ch] = 0
        for off in (mo, mo + 3):
            opl[0x20 + off] = 0x21
            opl[0x40 + off] = 0
            opl[0x60 + off] = 0xf0
            opl[0x80 + off] = 0x0f
    for mask in range(512):
        lib.fm_init(pool, len(pool))
        lib.fm_field(opl, keyon, 0, v)
        assert all(q.channel >= 0 for q in v)
        lib.fm_field(opl, keyon, mask, v)
        for q in v:
            assert q.channel < 0 or not (mask & (1 << q.channel))
        for k in range(3):
            if mask & (7 << (3*k)) == 7 << (3*k):
                assert v[k].volume == 0
    # A timed sustain (60 fields in the file, at 60 Hz): one second held on
    # PAL (50 fields) and NTSC (60), the key held throughout.
    raw = resource(60)
    rsc = (C.c_uint8 * len(raw)).from_buffer_copy(raw)
    ntsc = C.c_uint8.in_dll(lib, 'fm_ntsc')
    held = []
    for mode in (0, 1):
        ntsc.value = mode
        lib.tfh_init(rsc, len(raw), chip)
        ids[:] = [0, 255, 255]
        starts[:] = [1, 0, 0]
        opl[0xa0], opl[0xb0] = 0, 0x20
        volumes = []
        for _ in range(100):
            lib.tfh_field(opl, ids, starts, v)
            volumes.append(v[0].volume)
        held.append(volumes.count(volumes[2]))
    ntsc.value = 0
    assert held == [51, 61], f'sustain fields PAL/NTSC {held}'
    print('TFH: 117 slot/id mappings, segments/envelopes/restarts/pitch, parser, 512 FM masks, NTSC sustain: ok')


def main():
    plants = {'mask': ('fm_paula.c', 'taken = mute_mask;', 'taken = 0; (void)mute_mask;'),
              'routing': ('tfh_paula.c', 'mask | 7u <<', 'mask | 3u <<'),
              'restart': ('tfh_paula.c', 'p->segment == 0;', 'p->segment == 9;'),
              'volume': ('tfh_paula.c', ' / VOLUME_FULL);', ' / (VOLUME_FULL * 2));'),
              'ntsc': ('tfh_paula.c', '|| fm_ntsc ?', '|| 0 ?')}
    cases = plants.items() if '--sabotage' in sys.argv else [('normal', None)]
    for name, plant in cases:
        with tempfile.TemporaryDirectory(prefix='swotl-tfh-') as tmp:
            paths = []
            for filename in ('fm_paula.c', 'tfh_paula.c'):
                text = (SRC / filename).read_text()
                if plant and filename == plant[0]:
                    assert plant[1] in text
                    text = text.replace(plant[1], plant[2])
                path = Path(tmp) / filename
                path.write_text(text)
                paths.append(str(path))
            dll = Path(tmp) / 'tfh.dylib'
            subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(SRC), *paths, '-o', str(dll)], check=True)
            try:
                checks(C.CDLL(str(dll)))
            except AssertionError:
                if not plant:
                    raise
                print(f'TFH sabotage {name}: caught')
            else:
                assert not plant, f'missed {name}'


if __name__ == '__main__':
    main()
