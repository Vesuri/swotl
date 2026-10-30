"""INT 67h EMS mapping (src/runtime/ems.c) against a live DOSBox-X oracle.

One operation list drives both: a generated .COM program on DOSBox-X
(memsize=4, the reference machine) and the host runtime. Results: every
call's AX (and BX/DX where the function returns them) and the whole 64 KB
page frame at each dump. Covers allocation, filling every logical page
through a frame page, write-back on remap, the game's sliding four-page
window (SWOTL+04918) with writes between maps, an identical remap after a
write, unmapping (FFFFh), error codes, a page mapped at two frame pages
without writes through either (ems.c keeps such aliases as separate copies,
DOSBox does not), a final read-back of every page, and release: frame pages
left mapped, freed pages reused (split across free runs, stale bytes kept),
the free count and longest run apart, error codes. Release of the OS handle
0 stops (its pages are outside the store).
  test_ems.py [--sabotage]
"""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import tempfile

import test_file_dates as T

H = T.H
FRAME = 0xE0000
PAGE = 0x4000
RESULTS = 0x2000


def ops():
    o = [('status',), ('frame',), ('pages',), ('alloc', 0, 12), ('alloc', 1, 5), ('pages',)]
    for p in range(12):
        o += [('map', 0, p, 0), ('fill', 0, (13 * p + 1) & 255, 2 * p + 1)]
    for p in range(5):
        o += [('map', 1, p, 1), ('fill', 1, (29 * p + 7) & 255, 2 * p + 3)]
    for n, base in enumerate((0, 1, 1, 2, 8, 1)):
        o += [('map', k, base + k, 0) for k in range(4)]
        o += [('poke', k, (0x1234 * (k + 1) + n) & 0x3FFF, 0xA0 + n) for k in range(4)]
        o += [('dump',)]
    o += [('map', 2, 0xFFFF, 0), ('map', 2, 3, 1), ('poke', 2, 0, 0x55), ('dump',)]
    o += [('map', 4, 0, 0), ('maph', 0, 0, 0x7F), ('map', 0, 12, 0), ('map', 0, 5, 1)]
    o += [('map', 0, 4, 0), ('map', 1, 4, 0), ('dump',), ('map', 1, 5, 0), ('dump',)]
    for base in (0, 4, 8):
        o += [('map', k, base + k, 0) for k in range(4)] + [('dump',)]
    o += [('map', k, k, 1) for k in range(4)] + [('dump',)]
    # release (the game's exit): mappings outlive the handle, freed pages are
    # reused page by page, smallest free run first (DOSBox-X MEM_AllocatePages)
    o += [('poke', 0, 5, 0x11), ('release', 1), ('pages',), ('release', 1), ('releaseh', 0x7F),
          ('alloc', 3, 0), ('poke', 1, 7, 0x22), ('alloc', 2, 3), ('pages',), ('map', 3, 0, 2),
          ('dump',), ('release', 0), ('pages',), ('alloc', 4, 20), ('pages',)]
    for base in (0, 12):            # before filling: the pages' previous owners' bytes
        o += [('map', k, base + k, 4) for k in range(4)] + [('dump',)]
    o += [('map', k, 0xFFFF, 4) for k in range(1, 4)]  # no aliases of the pages filled next
    for p in range(20):
        o += [('map', 0, p, 4), ('fill', 0, (37 * p + 5) & 255, 2 * p + 7)]
    for base in (0, 4, 8, 12, 16):
        o += [('map', k, base + k, 4) for k in range(4)] + [('dump',)]
    o += [('map', k, k, 2) for k in range(3)] + [('dump',)]
    o += [('release', 4), ('release', 2), ('pages',), ('alloc', 5, 164), ('pages',),
          ('release', 5), ('alloc', 6, 2), ('map', 0, 1, 6), ('dump',)]
    return o


def pattern(seed, step):
    out, al, ah = bytearray(), seed, step
    for _ in range(64):
        for _ in range(256):
            out.append(al)
            al = (al + ah) & 255
        ah = (ah + 2) & 255
    return bytes(out)


def program(operations):
    code = bytearray()
    emit = lambda s: code.extend(bytes.fromhex(s))
    word = lambda v: code.extend(struct.pack('<H', v))

    def record(regs):
        emit('8b 3e 00 1f')                         # mov di,[1F00]
        for r in regs:
            emit({'ax': '89 05', 'bx': '89 1d', 'dx': '89 15'}[r] + ' 47 47')
        emit('89 3e 00 1f')                         # mov [1F00],di

    emit('fc c7 06 00 1f'); word(RESULTS)           # cld; results pointer
    emit('ba'); word(0x1e80); emit('31 c9 b4 3c cd 21 a3 02 1f')  # create RESULT.BIN
    for op in operations:
        kind = op[0]
        if kind in ('status', 'frame', 'pages'):
            emit({'status': 'b8 00 40', 'frame': 'b8 00 41', 'pages': 'b8 00 42'}[kind] + ' cd 67')
            record({'status': ['ax'], 'frame': ['ax', 'bx'], 'pages': ['ax', 'bx', 'dx']}[kind])
        elif kind == 'alloc':
            emit('ba ee ee bb'); word(op[2]); emit('b8 00 43 cd 67')  # DX kept on errors
            record(['ax', 'dx'])
            emit('89 16'); word(0x1e00 + 2 * op[1])  # mov [handle slot],dx
        elif kind in ('release', 'releaseh'):
            if kind == 'release':
                emit('8b 16'); word(0x1e00 + 2 * op[1])
            else:
                emit('ba'); word(op[1])
            emit('b4 45 cd 67')
            record(['ax'])
        elif kind in ('map', 'maph'):
            emit('bb'); word(op[2])
            if kind == 'map':
                emit('8b 16'); word(0x1e00 + 2 * op[3])
            else:
                emit('ba'); word(op[3])
            emit('b0'); code.append(op[1]); emit('b4 44 cd 67')
            record(['ax'])
        elif kind == 'fill':
            emit('b8 00 e0 8e c0 bf'); word(op[1] * PAGE)
            emit('b0'); code.append(op[2]); emit('b4'); code.append(op[3])
            emit('ba 40 00 b9 00 01 aa 00 e0 e2 fb fe c4 fe c4 4a 75 f1')
        elif kind == 'poke':
            emit('b8 00 e0 8e c0 26 c6 06'); word(op[1] * PAGE + op[2]); code.append(op[3])
        elif kind == 'dump':
            emit('8b 1e 02 1f 1e b8 00 e0 8e d8 31 d2 b9 00 80 b4 40 cd 21 '
                 'ba 00 80 b9 00 80 b4 40 cd 21 1f')
    emit('8b 1e 02 1f ba'); word(RESULTS)
    emit('8b 0e 00 1f 81 e9'); word(RESULTS)
    emit('b4 40 cd 21 b4 3e cd 21 b8 00 4c cd 21')
    assert len(code) < 0x1d00, len(code)
    code.extend(bytes(0x1d80 - len(code)))
    code.extend(b'RESULT.BIN\0')
    return code


def oracle(operations):
    with tempfile.TemporaryDirectory(prefix='swotl-ems-') as tmp:
        root = Path(tmp)
        (root / 'EMS.COM').write_bytes(program(operations))
        conf = root / 'oracle.conf'
        conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmemsize=4\n'
                        '[cpu]\ncore=normal\ncputype=386\ncycles=max\n'
                        '[mixer]\nnosound=true\n[log]\nlogfile=dosbox.log\n')
        with (root / 'console.log').open('wb') as log:
            subprocess.run([str(H.REPO / 'tools/vendor/dosbox-x/src/dosbox-x'),
                            '-conf', str(conf), '-nogui', '-nomenu', '-silent', '-fastlaunch',
                            '-c', f'mount c "{root}"', '-c', 'c:', '-c', 'EMS.COM', '-c', 'exit'],
                           cwd=root, env=dict(os.environ, SDL_VIDEODRIVER='dummy',
                                              SDL_AUDIODRIVER='dummy'),
                           stdout=log, stderr=log, timeout=120, check=True)
        data = (root / 'RESULT.BIN').read_bytes()
    dumps = sum(op[0] == 'dump' for op in operations)
    frames = [data[k * 0x10000:(k + 1) * 0x10000] for k in range(dumps)]
    words = data[dumps * 0x10000:]
    return list(struct.unpack(f'<{len(words) // 2}H', words)), frames


def reg(h, name):
    return int.from_bytes(h.mem(h.syms['rt_r'] + 2 * H.REGS.index(name), 2), 'big')


def runtime(operations, plant=None):
    h = T.machine.machine()
    words, frames, handles = [], [], {}

    def ems(ax, bx=0, dx=0):
        for r, v in (('ax', ax), ('bx', bx), ('dx', dx)):
            h.e.write(h.syms['rt_r'] + 2 * H.REGS.index(r), struct.pack('>H', v))
        T.machine.call(h, 'rt_int67')
        assert not h.halted, h.log

    last, loaded = {}, {}   # per frame page: mapped page, its bytes right after mapping
    for op in operations:
        kind = op[0]
        if kind in ('status', 'frame', 'pages'):
            ems({'status': 0x4000, 'frame': 0x4100, 'pages': 0x4200}[kind])
            words += [reg(h, r) for r in {'status': ['ax'], 'frame': ['ax', 'bx'],
                                          'pages': ['ax', 'bx', 'dx']}[kind]]
            if plant == 'constant-total' and kind == 'pages':
                words[-1] = 0xA4    # total pages ignore allocations
            if plant == 'free-run' and kind == 'pages':
                words[-1] = words[-2]   # the longest free run taken as the free count
        elif kind == 'alloc':
            ems(0x4300, op[2], 0xEEEE)
            words += [reg(h, 'ax'), reg(h, 'dx')]
            handles[op[1]] = reg(h, 'dx')
        elif kind in ('release', 'releaseh'):
            ems(0x4500, 0, handles[op[1]] if kind == 'release' else op[1])
            words.append(reg(h, 'ax'))
            if plant == 'release-unmaps' and reg(h, 'ax') == 0:
                for phys in range(4):   # frame pages written back and unmapped
                    ems(0x4400 | phys, 0xFFFF)
                    last.pop(phys, None)
                    loaded.pop(phys, None)
        elif kind in ('map', 'maph'):
            phys, frame = op[1], FRAME + op[1] * PAGE
            same = last.get(phys) == op[2]
            # lost-writeback: writes through the frame since its last map never
            # reach the store; stale-remap: the same on an identical remap
            if phys in loaded and ((plant == 'lost-writeback' and not same) or
                                   (plant == 'stale-remap' and same)):
                T.machine.write_guest(h, frame, loaded[phys])
            ems(0x4400 | phys, op[2], handles[op[3]] if kind == 'map' else op[3])
            words.append(reg(h, 'ax'))
            if phys < 4 and reg(h, 'ax') >> 8 == 0:
                if plant == 'short-tail':
                    T.machine.write_guest(h, frame + PAGE - 3, bytes(3))
                last[phys], loaded[phys] = op[2], h.gmem(frame, PAGE)
        elif kind == 'fill':
            T.machine.write_guest(h, FRAME + op[1] * PAGE, pattern(op[2], op[3]))
        elif kind == 'poke':
            T.machine.write_guest(h, FRAME + op[1] * PAGE + op[2], bytes([op[3]]))
        elif kind == 'dump':
            frames.append(h.gmem(FRAME, 0x10000))
    return words, frames


def compare(expected, actual):
    (ew, ef), (aw, af) = expected, actual
    errors = [f'result words differ: {[(k, hex(e), hex(a)) for k, (e, a) in enumerate(zip(ew, aw)) if e != a][:8]}']\
        if ew != aw else []
    for k, (e, a) in enumerate(zip(ef, af)):
        if e != a:
            first = next(i for i in range(len(e)) if e[i] != a[i])
            errors.append(f'dump {k}: first difference at frame offset {first:#06x}')
    if len(ef) != len(af) or len(ew) != len(aw):
        errors.append('result counts differ')
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    operations = ops()
    expected = oracle(operations)
    if args.sabotage:
        for plant in ('constant-total', 'free-run', 'lost-writeback', 'short-tail', 'stale-remap',
                      'release-unmaps'):
            assert compare(expected, runtime(operations, plant)), plant + ' plant escaped'
            print(f'EMS: {plant} plant caught')
        return
    errors = compare(expected, runtime(operations))
    assert not errors, errors
    h = T.machine.machine()         # the OS handle's pages lie outside the store
    for r, v in (('ax', 0x4500), ('dx', 0)):
        h.e.write(h.syms['rt_r'] + 2 * H.REGS.index(r), struct.pack('>H', v))
    T.machine.call(h, 'rt_int67')
    assert h.halted and any('EMS release of handle 0' in line for line in h.log), h.log
    print(f'EMS: {len(expected[0])} result words and {len(expected[1])} 64 KB frame dumps '
          f'match DOSBox-X over {len(operations)} operations')


if __name__ == '__main__':
    main()
