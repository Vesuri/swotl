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
import test_mouse_irq as machine

H = machine.H


def service(h, ax, dx=0, cx=0, bx=0):
    for r, value in [('ax', ax), ('dx', dx), ('cx', cx), ('bx', bx)]:
        h.e.write(h.syms['rt_r'] + 2 * H.REGS.index(r), struct.pack('>H', value))
    machine.call(h, 'rt_int21', 0, 0)
    return bool(machine.call(h, 'rt_flags_word') & 1)


def check_runtime(rows):
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
        # A writable open alone preserves the old stamp; a write and close
        # updates the in-memory platform file, just as a native file does.
        days, minutes, ticks, want_time, want_date = rows['S06.DAT']
        now = datetime.datetime(1978, 1, 1) + datetime.timedelta(
            days=days, minutes=minutes, seconds=ticks // 50)
        with patch.object(H.time, 'time', return_value=time.mktime(now.timetuple())):
            for writing, want in [(False, rows['S00.DAT'][3:]), (True, (want_time, want_date))]:
                machine.write_guest(h, 0x40100, b'S00.DAT\0')
                assert not service(h, 0x3d02, 0x100)
                handle = int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big')
                if writing:
                    machine.write_guest(h, 0x40280, b'X')
                    assert not service(h, 0x4000, 0x280, 1, handle)
                assert not service(h, 0x3e00, bx=handle)
                assert not service(h, 0x4e00, 0x100, 0x20)
                assert struct.unpack_from('<HH', h.gmem(0x40200, 43), 22) == want
    print(f'find-first/next: {len(found)} DOSBox timestamps; end-of-search and write-close metadata checked')


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
    check_runtime(rows)
    if args.sabotage:
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
