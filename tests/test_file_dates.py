"""DOS find-first/next DTA dates against a live DOSBox-X file oracle."""
import argparse
import subprocess
import datetime
import os
from pathlib import Path
import struct
import tempfile
import time
from unittest.mock import patch

import dosbox_file_dates as oracle
import dosbox_close_dates as close_oracle
import test_mouse_irq as machine

H = machine.H


def service(h, ax, dx=0, cx=0, bx=0):
    for r, value in [('ax', ax), ('dx', dx), ('cx', cx), ('bx', bx)]:
        h.e.write(h.syms['rt_r'] + 2 * H.REGS.index(r), struct.pack('>H', value))
    machine.call(h, 'rt_int21', 0, 0)
    return bool(machine.call(h, 'rt_flags_word') & 1)


def check_runtime(rows, close_rows=None):
    close_rows = close_oracle.capture() if close_rows is None else close_rows
    fixed_host = time.mktime((1991, 1, 1, 12, 0, 0, 0, 0, -1))
    with patch.object(H.time, 'time', return_value=fixed_host):
        h = machine.machine()
    with tempfile.TemporaryDirectory(prefix='swotl-dta-date-') as tmp:
        h.root = Path(tmp)
        for k, (name, (days, minutes, ticks, _time, _date)) in enumerate(rows.items()):
            dt = datetime.datetime(1978, 1, 1) + datetime.timedelta(days=days, minutes=minutes,
                                                                  seconds=ticks // 50)
            stamp = time.mktime(dt.timetuple())
            p = h.root / name
            p.write_bytes(bytes([k]) * (k + 1))
            os.utime(p, (stamp, stamp))
        h.e.write(H.TOP + 1, struct.pack('>H', 0x4000))  # G_DS
        assert not service(h, 0x1a00, 0x200)
        machine.write_guest(h, 0x40100, b'S*.DAT\0')
        failed = service(h, 0x4e00, 0x100, 0x20)
        found = {}
        while not failed:
            dta = h.gmem(0x40200, 43)
            name = dta[30:].split(b'\0')[0].decode()
            assert name in rows and name not in found, name
            actual = struct.unpack_from('<HH', dta, 22)
            expected = rows[name][3:]
            assert actual == expected, (name, 'DOS time/date', actual, expected)
            found[name] = actual
            failed = service(h, 0x4f00)
        assert found.keys() == rows.keys(), (found.keys(), rows.keys())
        assert int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big') == 0x12
        # Existing-file dates stay checked above. The live close oracle, not
        # mocked host wall time, supplies the write-close expectation.
        written = close_rows['write']
        with patch.object(H.time, 'time', return_value=fixed_host):
            for writing, want in [(False, rows['S00.DAT'][3:]),
                                  (True, (written['time'], written['date']))]:
                machine.write_guest(h, 0x40100, b'S00.DAT\0')
                assert not service(h, 0x3d02, 0x100)
                handle = int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big')
                if writing:
                    machine.write_guest(h, 0x40280, b'X')
                    assert not service(h, 0x4000, 0x280, 1, handle)
                machine.write_guest(h, 0x46c, struct.pack('<I', 0x400))
                assert not service(h, 0x3e00, bx=handle)
                assert not service(h, 0x4e00, 0x100, 0x20)
                assert struct.unpack_from('<HH', h.gmem(0x40200, 43), 22) == want
    print(f'find-first/next: {len(found)} DOSBox timestamps; end-of-search and write-close metadata checked')


def check_close_runtime(rows, initial_date=(1991, 1, 1), midnight=0):
    """Replay all seven original operations with independent DOS/host clocks."""
    fixed_host = time.mktime((*initial_date, 12, 0, 0, 0, 0, -1))
    with tempfile.TemporaryDirectory(prefix='swotl-close-runtime-') as tmp, \
            patch.object(H.time, 'time', return_value=fixed_host):
        h = machine.machine()
        h.root = Path(tmp)
        fixed_host = time.mktime((1991, 1, 1, 12, 0, 0, 0, 0, -1))
        H.time.time.return_value = fixed_host
        h.e.write(H.TOP + 1, struct.pack('>H', 0x4000))
        service(h, 0x1a00, 0x600)
        errors = []
        for k, case in enumerate(close_oracle.CASES):
            path = h.root / f'S{k}.DAT'
            path.write_bytes(b'abc')
            stamp = time.mktime((2021, 1, 1, 1, 0, 0, 0, 0, -1))
            os.utime(path, (stamp, stamp))
            machine.write_guest(h, 0x40800, path.name.encode() + b'\0')
            machine.write_guest(h, 0x40700, b'X')
            def clock(ticks):
                machine.write_guest(h, 0x46c, struct.pack('<I', ticks))
            clock(0x100)
            assert not service(h, 0x3c00 if case == 'create' else 0x3d02, 0x800)
            handle = int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big')
            if case not in ('open', 'create'):
                clock(0x200)
                assert not service(h, 0x4000, 0x700, 0 if case == 'truncate' else 1, handle)
            if case in ('read-after-write', 'read-write-again'):
                clock(0x300)
                assert not service(h, 0x3f00, 0x700, 1, handle)
            if case == 'seek-after-write':
                clock(0x300)
                assert not service(h, 0x4200, bx=handle)
            if case == 'read-write-again':
                clock(0x350)
                assert not service(h, 0x4000, 0x700, 1, handle)
            clock(0x400)
            machine.write_guest(h, 0x470, bytes([midnight]))
            assert not service(h, 0x3e00, bx=handle)
            assert not service(h, 0x4e00, 0x800, 0x20)
            actual = struct.unpack_from('<HHI', h.gmem(0x40600, 43), 22)
            expected = tuple(rows[case][key] for key in ('time', 'date', 'size'))
            if actual != expected:
                errors.append((case, actual, expected))
        assert not errors, errors
    print(f'DOS close: seven transitions match, date={initial_date}, midnight={midnight}')


def check_time():
    rows = close_oracle.capture_time()
    h = machine.machine()
    for (ticks, midnight), expected in zip(close_oracle.TIME_CASES, rows):
        machine.write_guest(h, 0x46c, struct.pack('<I', ticks))
        machine.write_guest(h, 0x470, bytes([midnight]))
        service(h, 0x2c00)
        ax, cx, dx = struct.unpack('>HHH', h.mem(h.syms['rt_r'], 6))
        actual = (ax, cx, dx, h.gmem(0x470, 1)[0])
        assert actual == expected, (ticks, midnight, actual, expected)
    print('DOS time: four live AX/CX/DX and midnight-consumption cases match')


def sabotage_close(rows):
    original = service
    for plant in ('read-stamp-lost', 'seek-keeps-write', 'stamp-dropped'):
        def planted(h, ax, dx=0, cx=0, bx=0):
            result = original(h, ax, dx, cx, bx)
            if (plant == 'read-stamp-lost' and ax == 0x3f00) or \
                    (plant == 'seek-keeps-write' and ax == 0x4200):
                psp = machine.call(h, 'rt_psp')
                sft = h.gmem(psp * 16 + 0x18 + bx, 1)[0]
                if plant == 'read-stamp-lost':
                    h.e.write(h.syms['file_stamped'] + sft, b'\0')
                else:
                    h.e.write(h.syms['file_action'] + sft, b'\2')
            return result
        global_service = globals()
        global_service['service'] = planted
        platform = H.Host.platform
        def drop(h, name):
            if name == 'plat_file_stamp' and plant == 'stamp-dropped':
                return
            return platform(h, name)
        H.Host.platform = drop
        try:
            try:
                check_close_runtime(rows)
            except AssertionError:
                print(f'DOS close: {plant} fault caught')
            else:
                raise AssertionError(f'{plant} escaped detection')
        finally:
            global_service['service'] = original
            H.Host.platform = platform


def check_conversion(rows, header, good=True):
    with tempfile.TemporaryDirectory(prefix='swotl-date-conversion-') as tmp:
        p = Path(tmp)
        (p / 'FileDate.h').write_text(header)
        cases = ',\n'.join('{' + ','.join(map(str, row)) + '}' for row in rows.values())
        source = '\n'.join([
            '#include "FileDate.h"',
            'static const int32_t rows[][5] = {' + cases + '};',
            'int main(void) {',
            'for (unsigned i=0; i<sizeof(rows)/sizeof(rows[0]); ++i) {',
            'uint16_t t,d; amiga_file_date(rows[i][0],rows[i][1],rows[i][2],&t,&d);',
            'if (t != rows[i][3] || d != rows[i][4]) return 1;',
            'if (rows[i][0] >= 730) {',
            'int32_t days, minutes, ticks;',
            'amiga_date_stamp(t,d,&days,&minutes,&ticks);',
            'if (days != rows[i][0] || minutes != rows[i][1] ||',
            'ticks != rows[i][2] / 100 * 100) return 2;',
            '}',
            '} return 0; }'])
        (p / 'test.c').write_text(source)
        subprocess.run(['cc', '-std=c99', '-Wall', '-Werror', '-O2',
                        str(p / 'test.c'), '-o', str(p / 'test')], check=True)
        result = subprocess.run([str(p / 'test')])
        assert (result.returncode == 0) == good, result.returncode
    print('Amiga DateStamp: DOSBox cases match' if good else 'Amiga DateStamp: planted fault caught')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    rows = oracle.capture()
    header = (H.REPO / 'src/platform/amiga/FileDate.h').read_text()
    check_conversion(rows, header)
    check_time()
    close_rows = close_oracle.check_clocks()
    check_close_runtime(close_rows)
    for date in [(1992, 2, 28), (2000, 2, 28), (2100, 2, 28)]:
        check_close_runtime(close_oracle.capture(initial_date=date, midnight=2), date, 2)
    check_runtime(rows, close_rows)
    if args.sabotage:
        sabotage_close(close_rows)
        for old, new in [('ticks / 100', 'ticks / 50'),
                         ('year % 100 != 0', 'year % 100 == 0'),
                         ('days + 1', 'days')]:
            assert old in header
            check_conversion(rows, header.replace(old, new), False)
        original = H.dos_file_stamp
        try:
            H.dos_file_stamp = lambda stamp: (0, 0)
            try:
                check_runtime(rows)
            except AssertionError:
                print('DTA timestamp loss: planted fault caught')
            else:
                raise AssertionError('DTA timestamp loss was not caught')
        finally:
            H.dos_file_stamp = original

        write = H.MemFile.write
        def stale_write(file, data):
            result = write(file, data)
            file.modified = False
            return result
        try:
            H.MemFile.write = stale_write
            try:
                check_runtime(rows)
            except AssertionError:
                print('stale write-close timestamp: planted fault caught')
            else:
                raise AssertionError('stale write-close timestamp was not caught')
        finally:
            H.MemFile.write = write
