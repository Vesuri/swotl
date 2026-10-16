"""Directory-search state against live DOSBox, including independent DTAs."""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import tempfile

import test_file_dates as T

# (DTA, operation, pattern): a disk reset must not reset search allocation.
STEPS = [(0x400, 'first', 'A/S*.DAT'), (0x400, 'next', ''),
         (0x400, 'next', ''), (0x400, 'first', 'A/S*.DAT'),
         (0x400, 'first', 'A/S*.DAT'), (0x440, 'first', 'B/T*.DAT'),
         (0x400, 'next', ''), (0x440, 'next', ''),
         (0x400, 'next', ''), (0x440, 'next', ''),
         (0x400, 'reset-first', 'A/S*.DAT'), (0x400, 'next', '')]
STEPS += [(0x400, f'slot-{slot}', '') for slot in (0, 2048, 65535)]


def program():
    code = bytearray()
    def emit(s):
        code.extend(bytes.fromhex(s))
    def imm(op, value):
        emit(op)
        code.extend(struct.pack('<H', value))
    # Zero both DTAs so reserved bytes have the same initial state.
    imm('bf', 0x400)
    imm('b9', 0x80)
    emit('31 c0 f3 aa')
    imm('bf', 0x1000)
    for dta, op, pattern in STEPS:
        imm('ba', dta)
        emit('b4 1a cd 21')
        if op == 'reset-first':
            emit('b4 0d cd 21')
        if op.startswith('slot-'):
            imm('c7 06', dta+13)
            code.extend(struct.pack('<H', int(op[5:])))
        if op.endswith('first'):
            imm('ba', 0x610 if pattern.startswith('A') else 0x620)
            imm('b9', 0x20)
        imm('b8', 0x4e00 if op.endswith('first') else 0x4f00)
        emit('57 cd 21 5f ab 9c 58 ab')
        imm('be', dta)
        imm('b9', 43)
        emit('f3 a4')
    imm('b8', 0x4f44)
    emit('ab')
    imm('b8', 0x454e)
    emit('ab')
    imm('ba', 0x600)
    emit('31 c9 b8 00 3c cd 21 89 c3')
    imm('ba', 0x1000)
    imm('b9', len(STEPS)*47+4)
    emit('b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21')
    assert len(code) < 0x300
    code.extend(bytes(0x500-len(code)))
    code.extend(b'RESULT.BIN\0')
    code.extend(bytes(0x510-len(code)))
    code.extend(b'A\\S*.DAT\0')
    code.extend(bytes(0x520-len(code)))
    code.extend(b'B\\T*.DAT\0')
    return code


def capture(root, code):
    (root/'SEARCH.COM').write_bytes(code)
    conf = root/'oracle.conf'
    conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmemsize=4\n'
                    '[cpu]\ncore=normal\ncputype=386\ncycles=fixed 12000\n'
                    '[mixer]\nnosound=true\n[log]\nlogfile=dosbox.log\n')
    with (root/'console.log').open('wb') as log:
        subprocess.run([str(T.H.REPO/'tools/vendor/dosbox-x/src/dosbox-x'),
                        '-conf', str(conf), '-nogui', '-nomenu', '-silent', '-fastlaunch',
                        '-c', f'mount c "{root}"', '-c', 'c:', '-c', 'SEARCH.COM', '-c', 'exit'],
                       cwd=root, env=dict(os.environ, SDL_VIDEODRIVER='dummy',
                                          SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=log, timeout=45, check=True)
    return (root/'RESULT.BIN').read_bytes()


def check():
    with tempfile.TemporaryDirectory(prefix='swotl-search-') as tmp:
        root = Path(tmp)
        for directory, prefix in [('A', 'S'), ('B', 'T')]:
            (root/directory).mkdir()
            for k in (1, 2):
                p = root/directory/f'{prefix}{k}.DAT'
                p.write_bytes(bytes([k])*k)
                os.utime(p, (1609459200, 1609459200))
        data = capture(root, program())
        assert len(data) == len(STEPS)*47+4 and data[-4:] == b'DONE'
        h = T.machine.machine()
        h.root = root
        h.e.write(T.H.TOP+1, struct.pack('>H', 0x4000))
        T.machine.write_guest(h, 0x40400, bytes(0x80))
        errors = []
        for k, (dta, op, pattern) in enumerate(STEPS):
            T.service(h, 0x1a00, dta)  # set-DTA preserves flags, including prior exhaustion
            if op == 'reset-first':
                T.service(h, 0x0d00)
                if h.halted:
                    errors.append((k, op, 'runtime stopped', h.log))
                    break
            if op.startswith('slot-'):
                T.machine.write_guest(h, 0x40000+dta+13, struct.pack('<H', int(op[5:])))
            T.machine.write_guest(h, 0x40600, pattern.encode()+b'\0')
            carry = T.service(h, 0x4e00 if op.endswith('first') else 0x4f00, 0x600, 0x20)
            row = data[k*47:(k+1)*47]
            expected = (int.from_bytes(row[:2], 'little'), row[2]&1, row[4:])
            actual = (int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big'), int(carry),
                      h.gmem(0x40000+dta, 43))
            if actual != expected:
                errors.append((k, op, actual[:2], expected[:2], actual[2].hex(), expected[2].hex()))
        assert not errors, errors
    print(f'DOS search: {len(STEPS)} complete DTA/status comparisons, reset, interleaved directories and invalid slots pass')


def boundary_program(exhaust, count):
    code = bytearray.fromhex('ba 00 04 b4 1a cd 21 bf 00 10')
    code.extend(b'\xbd'+struct.pack('<H', count))  # BP loop counter
    start = len(code)
    code.extend(bytes.fromhex('ba 10 06 b9 20 00 b8 00 4e 57 55 cd 21 5d 5f '
                              'ab 9c 58 ab a1 0d 04 ab'))
    if exhaust:
        code.extend(bytes.fromhex('b8 00 4f 57 55 cd 21 5d 5f'))
    code.extend(bytes.fromhex('4d 75'))
    displacement = start-len(code)-1
    assert -128 <= displacement < 128
    code.append(displacement & 255)
    code.extend(bytes.fromhex('b8 44 4f ab b8 4e 45 ab ba 00 06 31 c9 '
                              'b8 00 3c cd 21 89 c3 ba 00 10 b9'))
    code.extend(struct.pack('<H', count*6+4))
    code.extend(bytes.fromhex('b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21'))
    code.extend(bytes(0x500-len(code)))
    code.extend(b'RESULT.BIN\0')
    code.extend(bytes(0x510-len(code)))
    code.extend(b'S*.DAT\0')
    return code


def check_boundaries():
    count = 2050  # Cross DOSBox's 2048-slot boundary with live and freed slots.
    for exhaust in (False, True):
        with tempfile.TemporaryDirectory(prefix='swotl-search-wrap-') as tmp:
            root = Path(tmp)
            (root/'S1.DAT').write_bytes(b'x')
            data = capture(root, boundary_program(exhaust, count))
            assert len(data) == count*6+4 and data[-4:] == b'DONE'
            h = T.machine.machine()
            h.root = root
            h.e.write(T.H.TOP+1, struct.pack('>H', 0x4000))
            T.service(h, 0x1a00, 0x400)
            T.machine.write_guest(h, 0x40610, b'S*.DAT\0')
            for k in range(count):
                carry = T.service(h, 0x4e00, 0x610, 0x20)
                expected = struct.unpack_from('<HHH', data, k*6)
                actual = (int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big'), int(carry),
                          int.from_bytes(h.gmem(0x4040d, 2), 'little'))
                assert actual == (expected[0], expected[1]&1, expected[2]), (exhaust, k, actual, expected)
                if exhaust:
                    assert T.service(h, 0x4f00)
                    assert int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big') == 0x12
            T.machine.call(h, 'rt_dos_close')
            assert not h.allocations, 'search allocation pool leaked'
        print(f'DOS search: {count} allocations with exhausted={exhaust} match live slot/status results')


def sabotage():
    original = T.service
    for plant in ('slot-zero', 'counter-reset'):
        def service(h, ax, dx=0, cx=0, bx=0):
            result = original(h, ax, dx, cx, bx)
            if ax == 0x4e00:
                if plant == 'counter-reset':
                    h.e.write(h.syms['next_search'], bytes(2))
                else:
                    seg = int.from_bytes(h.mem(h.syms['dta_seg'], 2), 'big')
                    off = int.from_bytes(h.mem(h.syms['dta_off'], 2), 'big')
                    T.machine.write_guest(h, seg*16+off+13, bytes(2))
            return result
        T.service = service
        try:
            try:
                check()
            except AssertionError:
                print(f'DOS search: {plant} fault caught')
            else:
                raise AssertionError(f'{plant} escaped detection')
        finally:
            T.service = original



# Successful DOS create empties the directory cache: allocation restarts at
# zero, but live FindFirst snapshots survive (DOS_Drive_Cache::Clear).
CREATE_STEPS = [(0x400, 'first'), (0x440, 'first'), (0x480, 'create-first'),
                (0x400, 'next'), (0x440, 'next'), (0x400, 'next'),
                (0x440, 'next'), (0x480, 'create-first'), (0x480, 'delete-next')]


def check_create_search():
    code = bytearray.fromhex('bf 00 04 b9 00 01 31 c0 f3 aa bf 00 10')
    for dta, op in CREATE_STEPS:
        code.extend(b'\xba' + struct.pack('<H', dta) + bytes.fromhex('b4 1a cd 21'))
        if op == 'create-first':
            code.extend(bytes.fromhex('ba 20 06 31 c9 b8 00 3c 57 cd 21 5f '
                                      '89 c3 b4 3e 57 cd 21 5f'))
        if op == 'delete-next':
            code.extend(bytes.fromhex('ba 30 06 b8 00 41 57 cd 21 5f'))
        code.extend(bytes.fromhex('ba 10 06 b9 20 00 b8'))
        code.extend(struct.pack('<H', 0x4e00 if op.endswith('first') else 0x4f00))
        code.extend(bytes.fromhex('57 cd 21 5f ab 9c 58 ab be') + struct.pack('<H', dta))
        code.extend(bytes.fromhex('b9 2b 00 f3 a4'))
    code.extend(bytes.fromhex('ba 00 06 31 c9 b8 00 3c cd 21 89 c3 ba 00 10 b9'))
    code.extend(struct.pack('<H', len(CREATE_STEPS)*47))
    code.extend(bytes.fromhex('b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21'))
    assert len(code) < 0x300
    code.extend(bytes(0x500-len(code)))
    code.extend(b'RESULT.BIN\0' + bytes(5) + b'S*.DAT\0' + bytes(9) + b'NEW.DAT\0' + bytes(8) + b'S2.DAT\0')
    with tempfile.TemporaryDirectory(prefix='swotl-search-create-') as tmp:
        root = Path(tmp)
        for k in (1, 2):
            p = root / f'S{k}.DAT'
            p.write_bytes(bytes([k])*k)
            os.utime(p, (1609459200, 1609459200))
        data = capture(root, code)
        p = root/'S2.DAT'
        p.write_bytes(bytes([2])*2)
        os.utime(p, (1609459200,1609459200))
        assert len(data) == len(CREATE_STEPS)*47
        h = T.machine.machine()
        h.root = root
        h.e.write(T.H.TOP+1, struct.pack('>H', 0x4000))
        T.machine.write_guest(h, 0x40400, bytes(0x100))
        T.machine.write_guest(h, 0x40610, b'S*.DAT\0')
        T.machine.write_guest(h, 0x40620, b'NEW.DAT\0')
        T.machine.write_guest(h, 0x40630, b'S2.DAT\0')
        # The first create must start with a missing file on both arms.
        (root/'NEW.DAT').unlink()
        for k, (dta, op) in enumerate(CREATE_STEPS):
            T.service(h, 0x1a00, dta)
            if op == 'create-first':
                assert not T.service(h, 0x3c00, 0x620)
                handle = int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big')
                assert not T.service(h, 0x3e00, bx=handle)
            if op == 'delete-next':
                assert not T.service(h, 0x4100, 0x630)
            carry = T.service(h, 0x4e00 if op.endswith('first') else 0x4f00, 0x610, 0x20)
            row = data[k*47:(k+1)*47]
            actual = (int.from_bytes(h.mem(h.syms['rt_r'], 2), 'big'), int(carry),
                      h.gmem(0x40000+dta, 43))
            expected = (int.from_bytes(row[:2], 'little'), row[2]&1, row[4:])
            assert actual == expected, (k, op, actual, expected)
        T.machine.call(h, 'rt_dos_close')
        assert not h.allocations, 'search snapshots leaked'
    print('DOS search: create/truncate preserve snapshots; deleted entries skipped; allocations freed')


def sabotage_create_search():
    original = T.service
    for plant in ('create-counter-kept', 'snapshot-name-corrupt'):
        def planted(h, ax, dx=0, cx=0, bx=0):
            previous = h.mem(h.syms['next_search'], 2)
            result = original(h, ax, dx, cx, bx)
            if ax == 0x3c00:
                if plant == 'create-counter-kept':
                    h.e.write(h.syms['next_search'], previous)
                else:
                    for address in h.allocations:
                        if h.mem(address+4, 7) == b'S2.DAT\0':
                            h.e.write(address+4, b'S1.DAT\0')
            return result
        T.service = planted
        try:
            try:
                check_create_search()
            except AssertionError:
                print(f'DOS search: {plant} fault caught')
            else:
                raise AssertionError(f'{plant} escaped detection')
        finally:
            T.service = original

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    check()
    check_boundaries()
    check_create_search()
    if args.sabotage:
        sabotage()
        sabotage_create_search()
