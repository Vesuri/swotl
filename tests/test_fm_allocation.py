#!/usr/bin/env python3
"""Allocation contracts using synthetic sustained OPL notes; no game data."""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile

from test_fm_quality import Voice

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'


def checks(source):
    with tempfile.TemporaryDirectory(prefix='fm-allocation-', dir=ROOT/'tmp') as td:
        p = Path(td)
        (p/'fm.c').write_text(source)
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall',
                        '-Wextra', '-Werror', '-I'+str(SRC), str(p/'fm.c'),
                        '-o', str(p/'fm.so')], check=True)
        lib = C.CDLL(str(p/'fm.so'))
        lib.fm_field.argtypes = [C.c_void_p, C.c_void_p, C.c_uint16, C.c_void_p]
        pool = (C.c_int8 * 65536)()
        opl, keys, voices = (C.c_uint8 * 256)(), (C.c_uint8 * 9)(), (Voice * 4)()
        offsets = [0, 1, 2, 8, 9, 10, 16, 17, 18]
        lib.fm_init(pool, len(pool))
        for ch in (0, 1, 3, 4):
            mo = offsets[ch]
            for off in (mo, mo+3):
                opl[0x20+off] = 0x21
                opl[0x60+off] = 0xf0
                opl[0x80+off] = 0x0f
            opl[0x40+mo] = 63
            opl[0xa0+ch], opl[0xb0+ch] = 161, 0x2c
            keys[ch] = 1
        def frame(mask=0):
            lib.fm_field(opl, keys, mask, voices)
            selected = [v.channel for v in voices if v.channel >= 0]
            assert len(selected) == len(set(selected)), 'duplicate OPL voice'
            assert not any(mask & (1 << c) for c in selected), 'sample-owned OPL channel selected'
            for i in range(3):
                if mask & (7 << (3*i)):
                    assert voices[i].volume == 0, 'sample-owned Paula voice selected'
            return {v.channel: i for i, v in enumerate(voices) if v.channel >= 0}
        initial = frame()
        assert set(initial) == {0, 1, 3, 4}, ('unused music capacity', initial)
        for ch in (0, 3, 1, 4, 0, 3):
            for c in (0, 1, 3, 4):
                opl[0x43+offsets[c]] = 8 if c == ch else 0
            current = frame()
            assert current == initial, ('continuing note moved', initial, current)
            assert not any(v.restart for v in voices), 'continuing note restarted'
        keys[1] += 1
        current = frame()
        assert current == initial
        assert [v.channel for v in voices if v.restart] == [1], 'lost or spurious key-on'
        frame(7)
        frame(7 << 3)
        frame(511)
        assert all(v.volume == 0 for v in voices)
        # A newly audible group must enter even if all four voices were busy.
        frame()
        mo = offsets[6]
        for off in (mo, mo+3):
            opl[0x20+off], opl[0x60+off], opl[0x80+off] = 0x21, 0xf0, 0x0f
        opl[0x40+mo] = 63
        opl[0xa0+6], opl[0xb0+6], keys[6] = 161, 0x2c, 1
        current = frame()
        assert 6 in current and len(current) == 4, 'new audible group ignored'
        assert voices[current[6]].restart, 'newly assigned note did not restart'
        # Five audible notes force selection; changing their ranks must not
        # move the same four winners between physical voices.
        opl[0x43+offsets[3]] = 32
        stable = frame()
        assert set(stable) == {0, 1, 4, 6}
        opl[0x43+offsets[0]] = 8
        assert frame() == stable, 'rank change moved a retained winner'
        assert not any(v.restart for v in voices), 'rank change restarted a retained winner'
        frame(7 << 6)
        print('FM allocation: spare capacity, stable notes, key-ons, sample ownership, silence: ok')


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' not in sys.argv:
        checks(source)
        return
    for name, old, new in (
            ('stale assignment', 'if (available == held)', 'if (((void)available, (void)held, 1))'),
            ('idle capacity', 'if (choice[i] < 0 && !(reserved >> i & 1))',
             'if (i == 3 && choice[i] < 0 && !(reserved >> i & 1))'),
            ('note migration', 'if (voice_ch[i] >= 0 && !(reserved >> i & 1))',
             'if (0 && voice_ch[i] >= 0 && !(reserved >> i & 1))')):
        assert old in source, name
        try:
            checks(source.replace(old, new))
        except AssertionError as e:
            print(f'caught {name}: {e}')
        else:
            raise AssertionError(f'{name} escaped')


if __name__ == '__main__':
    main()
