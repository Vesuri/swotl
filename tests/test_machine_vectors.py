"""Initial machine vectors read by pilot creation, against live DOSBox."""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import tempfile

import test_file_dates as T


def capture():
    # DOS get-vector, then save ES:BX. No expected vector enters the COM.
    code = bytearray.fromhex('bf 00 04')
    for vector in (0, 0x32):
        code.extend(bytes([0xb8, vector, 0x35, 0xcd, 0x21, 0x89, 0x1d,
                           0x8c, 0x45, 0x02, 0x83, 0xc7, 0x04]))
    code.extend(bytes.fromhex('ba 00 05 31 c9 b8 00 3c cd 21 89 c3 '
                              'ba 00 04 b9 08 00 b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21'))
    code.extend(bytes(0x400-len(code)))
    code.extend(b'VECTORS.BIN\0')
    with tempfile.TemporaryDirectory(prefix='swotl-vectors-') as tmp:
        root = Path(tmp)
        (root/'VECTOR.COM').write_bytes(code)
        conf = root/'oracle.conf'
        conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmemsize=4\n'
                        '[cpu]\ncore=normal\ncputype=386\ncycles=fixed 12000\n'
                        '[mixer]\nnosound=true\n[log]\nlogfile=dosbox.log\n')
        with (root/'console.log').open('wb') as log:
            subprocess.run([str(T.H.REPO/'tools/vendor/dosbox-x/src/dosbox-x'),
                            '-conf', str(conf), '-nogui', '-nomenu', '-silent', '-fastlaunch',
                            '-c', f'mount c "{root}"', '-c', 'c:', '-c', 'VECTOR.COM', '-c', 'exit'],
                           cwd=root, env=dict(os.environ, SDL_VIDEODRIVER='dummy',
                                              SDL_AUDIODRIVER='dummy'),
                           stdout=log, stderr=log, timeout=45, check=True)
        data = (root/'VECTORS.BIN').read_bytes()
        assert len(data) == 8
        return dict(zip((0, 0x32), (data[:4], data[4:])))


def compare(h, expected):
    for vector, value in expected.items():
        assert h.gmem(vector*4, 4) == value, (vector, h.gmem(vector*4, 4).hex(), value.hex())
        T.service(h, 0x3500+vector)
        bx = int.from_bytes(h.mem(h.syms['rt_r']+6, 2), 'big')
        es = h.state(5, 2)
        assert struct.pack('<HH', bx, es) == value


def check(sabotage=False):
    expected = capture()
    h = T.machine.machine()
    compare(h, expected)
    if sabotage:
        T.machine.write_guest(h, 0x32*4, bytes(4))
        try:
            compare(h, expected)
        except AssertionError:
            print('missing initial vector: planted fault caught')
        else:
            raise AssertionError('missing vector escaped detection')
    # Initial vector data must not silently implement this software interrupt.
    h = T.machine.machine()
    T.machine.call(h, 'rt_int_c', 0x08220032, 0x100)
    assert h.halted and any('unsupported interrupt' in line for line in h.log), h.log
    print('initial vectors: complete IVT values and DOS queries match; unsupported interrupt still stops')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    check(parser.parse_args().sabotage)
