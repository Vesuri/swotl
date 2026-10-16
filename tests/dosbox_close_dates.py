"""Live original DOS file-close timestamps with independent DOS/host clocks."""
from pathlib import Path
import json
import os
import struct
import tempfile
import time
from unittest.mock import patch


CASES = ['open', 'create', 'write', 'read-after-write', 'seek-after-write',
         'truncate', 'read-write-again']


def program(initial_date=(1991, 1, 1), midnight=0):
    cases = CASES
    code = bytearray()

    def emit(s):
        code.extend(bytes.fromhex(s))

    def imm(op, v):
        emit(op)
        code.extend(struct.pack('<H', v))

    def clock(t):
        emit('31 c0 8e c0')
        imm('26 c7 06', 1132)
        code.extend(struct.pack('<H', t))
        emit('26 c7 06 6e 04 00 00')
        emit('1e 07')

    def svc(ax):
        imm('b8', ax)
        emit('57 cd 21 5f')
    imm('b9', initial_date[0])
    imm('ba', initial_date[1] << 8 | initial_date[2])
    svc(11008)
    imm('ba', 1536)
    svc(6656)
    imm('bf', 4096)
    for k, case in enumerate(cases):
        clock(256)
        imm('ba', 2048 + k * 16)
        imm('b9', 0)
        svc(15360 if case == 'create' else 15618)
        emit('89 c3')
        if case not in ('open', 'create'):
            clock(512)
            imm('ba', 1792)
            imm('b9', 0 if case == 'truncate' else 1)
            svc(16384)
        if case in ('read-after-write', 'read-write-again'):
            clock(768)
            imm('ba', 1792)
            imm('b9', 1)
            svc(16128)
        if case == 'seek-after-write':
            clock(768)
            imm('ba', 0)
            imm('b9', 0)
            svc(16896)
        if case == 'read-write-again':
            clock(848)
            imm('ba', 1792)
            imm('b9', 1)
            svc(16384)
        clock(1024)
        emit('31 c0 8e c0 26 c6 06 70 04')
        code.append(midnight)
        emit('1e 07')
        svc(15872)
        imm('ba', 2048 + k * 16)
        imm('b9', 32)
        svc(19968)
        emit('ab 9c 58 ab')
        imm('be', 1536)
        imm('b9', 43)
        emit('f3 a4')
    imm('b8', 20292)
    emit('ab')
    imm('b8', 17742)
    emit('ab')
    imm('ba', 1920)
    imm('b9', 0)
    svc(15360)
    emit('89 c3')
    imm('ba', 4096)
    imm('b9', len(cases) * 47 + 4)
    svc(16384)
    svc(15872)
    svc(19456)
    assert len(code) < 1280, len(code)
    code.extend(bytes(1664 - len(code)))
    code.extend(b'RESULT.BIN\x00')
    code.extend(bytes(1792 - len(code)))
    for k in range(len(cases)):
        code.extend(f'S{k}.DAT'.encode() + bytes(16 - len(f'S{k}.DAT')))
    return code


def capture(fixed=True, initial_date=(1991, 1, 1), midnight=0):
    from test_dos_search import capture as run_original
    with tempfile.TemporaryDirectory(prefix='swotl-close-clock-') as tmp:
        root = Path(tmp)
        for k in range(len(CASES)):
            p = root/f'S{k}.DAT'
            p.write_bytes(b'abc')
            stamp = time.mktime((2021, 1, 1, 1, 0, 0, 0, 0, -1))
            os.utime(p, (stamp, stamp))
        with patch.dict(os.environ, {'SWOTL_FIXED_FILE_CLOCK': '1' if fixed else '0'}):
            data = run_original(root, program(initial_date, midnight))
        assert data[-4:] == b'DONE' and len(data) == len(CASES)*47+4
        rows = {}
        for k, case in enumerate(CASES):
            row = data[k*47:(k+1)*47]
            ax, flags = struct.unpack_from('<HH', row)
            assert ax == 0 and not flags&1, (case, ax, flags)
            dos_time, date, size = struct.unpack_from('<HHI', row, 26)
            rows[case] = {'time': dos_time, 'date': date, 'size': size, 'dta': row[4:].hex()}
        return rows


TIME_CASES = [(0, 0), (0x400, 1), (0x1800af, 2), (0x10000, 255)]


def capture_time():
    from test_dos_search import capture as run_original
    code = bytearray.fromhex('bf 00 10')
    for ticks, midnight in TIME_CASES:
        code.extend(bytes.fromhex('31 c0 8e c0 26 c7 06 6c 04'))
        code.extend(struct.pack('<H', ticks & 65535))
        code.extend(bytes.fromhex('26 c7 06 6e 04'))
        code.extend(struct.pack('<H', ticks >> 16))
        code.extend(bytes.fromhex('26 c6 06 70 04') + bytes([midnight]))
        code.extend(bytes.fromhex('b8 00 2c 57 cd 21 5f 1e 07 ab 89 c8 ab 89 d0 ab '
                                  '31 c0 8e c0 26 a0 70 04 1e 07 ab'))
    code.extend(bytes.fromhex('ba 00 06 31 c9 b8 00 3c cd 21 89 c3 ba 00 10 b9'))
    code.extend(struct.pack('<H', len(TIME_CASES)*8))
    code.extend(bytes.fromhex('b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21'))
    code.extend(bytes(0x500-len(code)))
    code.extend(b'RESULT.BIN\0')
    with tempfile.TemporaryDirectory(prefix='swotl-dos-time-') as tmp:
        data = run_original(Path(tmp), code)
    assert len(data) == len(TIME_CASES)*8
    return list(struct.iter_unpack('<HHHH', data))


def check_clocks():
    # Source-of-truth DOS paths were measured before instrumenting host time.
    # The two host-clock paths have a distinct noon input, not DOS close time.
    first, second = capture(), capture()
    assert first == second, (first, second)
    for name, row in first.items():
        if name == 'open':
            assert (row['time'], row['date'], row['size']) == (2048, 21025, 3)
        else:
            time = 24576 if name in ('create', 'seek-after-write') else \
                21 if name in ('read-after-write', 'read-write-again') else 28
            assert (row['time'], row['date']) == (time, 5665), (name, row)
            assert row['size'] == (0 if name in ('create', 'truncate') else 3)
    # Turning the host pin off must leave the measured DOS-clock paths alone.
    natural = capture(False)
    for name in ('open', 'write', 'read-after-write', 'truncate', 'read-write-again'):
        assert natural[name] == first[name], (name, natural[name], first[name])
    print('DOS close oracle: repeatability and all seven clock transitions pass')
    return first


if __name__ == '__main__':
    print(json.dumps(check_clocks(), indent=2))
