"""DOS SDA initialization and current DTA against live DOSBox-X."""
import argparse
from pathlib import Path
import struct
import tempfile

import test_file_dates as T
from test_dos_search import capture as run_original

# None segment means the original program's PSP; other segments test both words.
STEPS = [None, (None, 0x600), (0x2345, 0xfffe), (0x3456, 0x1234), (None, 0x80)]


def capture():
    code = bytearray.fromhex('bf 00 10')
    def emit(s):
        code.extend(bytes.fromhex(s))
    for step in STEPS:
        if step is not None:
            seg, off = step
            emit('1e')
            if seg is not None:
                emit('b8'); code.extend(struct.pack('<H', seg)); emit('8e d8')
            emit('ba'); code.extend(struct.pack('<H', off))
            emit('b4 1a 57 cd 21 5f 1f')
        # Query InDOS address, save segment/offset, then copy the entire SDA.
        emit('b4 34 57 cd 21 5f 8c c2 89 d0 1e 07 ab 89 d8 ab '
             '1e 8e da 89 de 4e b9 1c 00 f3 a4 1f')
    emit('ba 00 06 31 c9 b8 00 3c cd 21 89 c3 ba 00 10 b9')
    code.extend(struct.pack('<H', len(STEPS)*32))
    emit('b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21')
    code.extend(bytes(0x500-len(code))); code.extend(b'RESULT.BIN\0')
    with tempfile.TemporaryDirectory(prefix='swotl-sda-') as temp:
        data = run_original(Path(temp), code)
    assert len(data) == len(STEPS)*32
    rows = []
    for k in range(len(STEPS)):
        seg, indos = struct.unpack_from('<HH', data, k*32)
        assert indos == 1, (seg, indos)
        rows.append((seg*16+indos-1, data[k*32+4:(k+1)*32]))
    return rows


def compare(h, row):
    address, expected = row
    actual = h.gmem(address, len(expected))
    assert actual == expected, (hex(address), actual.hex(), expected.hex())


def check(sabotage=False):
    rows = capture()
    assert rows == capture(), 'DOS SDA oracle did not repeat'
    psp = int.from_bytes(rows[0][1][16:18], 'little')
    h = T.machine.machine()
    for step, row in zip(STEPS, rows):
        if step is not None:
            seg, off = step
            h.e.write(T.H.TOP+1, struct.pack('>H', psp if seg is None else seg))
            T.service(h, 0x1a00, off)
            assert not h.halted, h.log
        compare(h, row)
        if sabotage:
            for offset in (12, 14):
                old = h.gmem(row[0]+offset, 1)
                T.machine.write_guest(h, row[0]+offset, bytes([old[0]^1]))
                try:
                    compare(h, row)
                except AssertionError:
                    pass
                else:
                    raise AssertionError(('SDA corruption escaped', step, offset))
                T.machine.write_guest(h, row[0]+offset, old)
    # Reinitialization must restore the default DTA, including its offset.
    h.e.write(T.H.TOP+1, struct.pack('>H', 0x3456))
    T.service(h, 0x1a00, 0x1234)
    T.machine.call(h, 'rt_dos_init')
    compare(h, rows[0])
    print('DOS SDA: five complete original states, both DTA words and reinitialization pass')
    if sabotage:
        print('DOS SDA: ten planted DTA byte corruptions caught')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    check(parser.parse_args().sabotage)
