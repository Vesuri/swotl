"""Live DOSBox-X find-first/next timestamps over synthetic host files.

No game files or saved references are changed. The tiny COM program asks DOS
for each DTA and writes its bytes; expected dates never enter the program.
"""
import datetime
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def program():
    code, labels, fixups = bytearray(), {}, []

    def emit(hexbytes):
        code.extend(bytes.fromhex(hexbytes))

    def addr(op, name):
        emit(op)
        fixups.append((len(code), name, False))
        emit('00 00')

    def branch(op, name):
        emit(op)
        fixups.append((len(code), name, True))
        emit('00 00')

    # Create the output first; its name cannot match the input wildcard.
    addr('ba', 'output')
    emit('31 c9 b8 00 3c cd 21')
    branch('0f 82', 'fail')
    emit('89 c3 ba 00 04 b4 1a cd 21')  # BX handle, DTA DS:0400
    addr('ba', 'pattern')
    emit('b9 20 00 b4 4e cd 21')
    branch('0f 82', 'fail')
    labels['row'] = len(code)
    emit('ba 00 04 b9 2b 00 b4 40 cd 21')
    branch('0f 82', 'fail')
    emit('83 f8 2b')
    branch('0f 85', 'fail')
    emit('b4 4f cd 21')
    branch('0f 83', 'row')
    emit('83 f8 12')
    branch('0f 85', 'fail')
    addr('ba', 'done')
    emit('b9 04 00 b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21')
    labels['fail'] = len(code)
    emit('b8 01 4c cd 21')
    for name, data in [('output', b'RESULT.BIN\0'), ('pattern', b'S*.DAT\0'), ('done', b'DONE')]:
        labels[name] = len(code)
        code.extend(data)
    for at, name, relative in fixups:
        value = labels[name] - at - 2 if relative else labels[name] + 0x100
        struct.pack_into('<H', code, at, value & 65535)
    assert len(code) + 0x100 < 0x400
    return bytes(code)


def capture():
    dates = [(1978, 1, 1, 0, 0, 0), (1979, 12, 31, 23, 59, 59),
             (1980, 1, 1, 0, 0, 0), (1991, 7, 1, 12, 34, 57),
             (2000, 2, 29, 23, 59, 58), (2000, 3, 1, 0, 0, 1),
             (2026, 10, 14, 1, 23, 45), (2100, 2, 28, 23, 59, 59),
             (2100, 3, 1, 0, 0, 0), (2107, 12, 31, 23, 59, 59)]
    with tempfile.TemporaryDirectory(prefix='swotl-file-date-') as tmp:
        root = Path(tmp)
        cases = {}
        for k, fields in enumerate(dates):
            name = f'S{k:02}.DAT'
            stamp = time.mktime((*fields, 0, 0, -1))
            p = root / name
            p.write_bytes(bytes([k]) * (k + 1))
            os.utime(p, (stamp, stamp))
            # Verify the host filesystem preserved the requested local calendar.
            assert tuple(time.localtime(p.stat().st_mtime)[:6]) == fields
            day = (datetime.date(*fields[:3]) - datetime.date(1978, 1, 1)).days
            cases[name] = (day, fields[3] * 60 + fields[4], fields[5] * 50, k + 1)
        (root / 'STAMP.COM').write_bytes(program())
        conf = root / 'oracle.conf'
        conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmemsize=4\n'
                        '[cpu]\ncore=normal\ncputype=386\ncycles=fixed 12000\n'
                        '[mixer]\nnosound=true\n[log]\nlogfile=dosbox.log\n')
        env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        with (root / 'console.log').open('wb') as log:
            subprocess.run([str(ROOT / 'tools/vendor/dosbox-x/src/dosbox-x'),
                            '-conf', str(conf), '-nogui', '-nomenu', '-silent', '-fastlaunch',
                            '-c', f'mount c {root}', '-c', 'c:', '-c', 'STAMP.COM', '-c', 'exit'],
                           cwd=root, env=env, stdout=log, stderr=log, timeout=45, check=True)
        result = (root / 'RESULT.BIN').read_bytes()
        assert result.endswith(b'DONE') and len(result) == len(cases) * 43 + 4, result
        rows = {}
        for at in range(0, len(result) - 4, 43):
            dta = result[at:at + 43]
            name = dta[30:].split(b'\0')[0].decode()
            assert name in cases and name not in rows, name
            dos_time, dos_date, size = struct.unpack_from('<HHI', dta, 22)
            assert size == cases[name][3]
            rows[name] = (*cases[name][:3], dos_time, dos_date)
        assert rows.keys() == cases.keys()
        return rows


if __name__ == '__main__':
    for name, row in capture().items():
        print(name, row)
