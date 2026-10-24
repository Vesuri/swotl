#!/usr/bin/env python3
"""SwotlInstallData on the host: exact files, sources, refusals, cleanup, cancel.

    python3 tools/install-data/test_install.py build/install-data/SwotlInstallData

Inputs are local, never shipped: the three ACC floppy images (ACC_IMAGES,
default tmp/acc/disk1-3.img) and TFH sfx.rsc (TFH_RSC). Oracle: the SWOTL
drawer made by the original DOS ACC INSTALL.EXE in DOSBox (ACC_REFERENCE,
default tmp/accx/dosrun/c/CLASSICS/SWOTL) minus its DOS installer files; it
also must hold the original SWOTL.EXE (ref/).
"""
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGES = Path(os.environ.get('ACC_IMAGES', ROOT / 'tmp/acc'))
REFERENCE = Path(os.environ.get('ACC_REFERENCE', ROOT / 'tmp/accx/dosrun/c/CLASSICS/SWOTL'))
TFH_RSC = Path(os.environ.get('TFH_RSC', ROOT / 'tmp/tfh/TheirFinestHour&Missions/data/sfx.rsc'))
SKIPPED = {'INSTALL.EXE', 'INSTALL2.BAT', 'READ.ME'}
FILES = 539


def tree(base):
    return {p.relative_to(base).as_posix().upper(): p for p in base.rglob('*') if p.is_file()}


def fat12_file(image, name):
    """CLASSICS.00n from a FAT12 image, read independently of the helper."""
    b = image.read_bytes()
    le = lambda o, n=2: int.from_bytes(b[o:o + n], 'little')
    bps, spc, reserved, fats, roots, spf = le(11), b[13], le(14), b[16], le(17), le(22)
    fat, root = reserved * bps, (reserved + fats * spf) * bps
    data = root + roots * 32
    for e in range(root, root + roots * 32, 32):
        if b[e:e + 11] == name.ljust(11).encode():
            size, c, out = le(e + 28, 4), le(e + 26), bytearray()
            while 2 <= c < 0xff8:
                out += b[data + (c - 2) * spc * bps:data + (c - 1) * spc * bps]
                v = le(fat + c + c // 2)
                c = v >> 4 if c & 1 else v & 0xfff
            return bytes(out[:size])
    raise SystemExit(f'{name} not in {image}')


def main():
    binary = Path(sys.argv[1]).resolve()
    images = [IMAGES / f'disk{n}.img' for n in (1, 2, 3)]
    expected = {k: p for k, p in tree(REFERENCE).items() if k not in SKIPPED}
    assert len(expected) == FILES, len(expected)
    assert expected['SWOTL.EXE'].read_bytes() == (ROOT / 'ref/SWOTL.EXE').read_bytes()
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='swotl-install-', dir=ROOT / 'tmp') as td:
        base = Path(td)

        def run(source, dest, good):
            r = subprocess.run([binary, source, dest], capture_output=True, text=True)
            assert (r.returncode == 0) == good, f'{source} -> {dest}\n{r.stdout}{r.stderr}'
            if not good:
                assert 'existing installations were not changed' in r.stdout or 'Destination exists' in r.stdout, r.stdout
            return r.stdout

        def drawer(name, files):
            d = base / name
            d.mkdir()
            for target, data in files.items():
                (d / target).write_bytes(data)
            return d

        def verify(dest):
            got = tree(dest)
            assert got.keys() == expected.keys(), sorted(got.keys() ^ expected.keys())[:10]
            for k, p in expected.items():
                assert got[k].read_bytes() == p.read_bytes(), k

        disks = [i.read_bytes() for i in images]
        source = drawer('images', {f'Disk{n}.img': d for n, d in enumerate(disks, 1)})
        assert 'Installed 539' in run(source, base / 'a', True)
        verify(base / 'a')
        volumes = [fat12_file(i, f'CLASSICS00{n}') for n, i in enumerate(images, 1)]
        files = drawer('files', {f'CLASSICS.00{n}': v for n, v in enumerate(volumes, 1)})
        run(files, base / 'b', True)
        verify(base / 'b')
        # An existing destination is refused and left as it was.
        keep = base / 'a/SWOTL.EXE'
        stamp = keep.stat().st_mtime_ns
        assert 'Destination exists' in run(source, base / 'a', False)
        assert keep.stat().st_mtime_ns == stamp
        # Missing, truncated or damaged volumes create nothing.
        flipped = bytearray(volumes[1])
        flipped[700000] ^= 1
        for index, bad in enumerate((
                {'CLASSICS.001': volumes[0], 'CLASSICS.002': volumes[1]},
                {'CLASSICS.001': volumes[0], 'CLASSICS.002': volumes[1][:-1], 'CLASSICS.003': volumes[2]},
                {'CLASSICS.001': volumes[0], 'CLASSICS.002': bytes(flipped), 'CLASSICS.003': volumes[2]},
                {'Disk1.img': disks[0], 'Disk2.img': disks[2], 'Disk3.img': disks[1]},
                {'Disk1.img': disks[0][:4096], 'Disk2.img': disks[1], 'Disk3.img': disks[2]})):
            dest = base / f'bad-{index}'
            run(drawer(f'badsrc-{index}', bad), dest, False)
            assert not dest.exists(), dest
        # Cancel (Ctrl-C on the Amiga) removes what the run created.
        dest = base / 'cancelled'
        proc = subprocess.Popen([binary, source, dest], stdout=subprocess.PIPE, text=True)
        while 'Extracting' not in proc.stdout.readline():
            pass
        proc.send_signal(signal.SIGTERM)
        out = proc.communicate(timeout=60)[0]
        assert proc.returncode == 20 and 'cancelled' in out, out
        assert not dest.exists()
        # TFH sfx.rsc: copied exactly; a wrong or truncated file is refused.
        rsc = TFH_RSC.read_bytes()
        run(TFH_RSC, base / 'sfx', True)
        assert (base / 'sfx/sfx.rsc').read_bytes() == rsc and len(tree(base / 'sfx')) == 1
        for index, bad in enumerate((rsc[:-1], rsc[:5000] + bytes([rsc[5000] ^ 1]) + rsc[5001:])):
            src = drawer(f'sfxsrc-{index}', {'sfx.rsc': bad})
            run(src / 'sfx.rsc', base / f'sfx-bad-{index}', False)
            assert not (base / f'sfx-bad-{index}').exists()
    print(f'PASS: {FILES} files equal the DOS ACC install from images and CLASSICS files; '
          'refusal, damaged/missing disks, cancel cleanup, sfx.rsc copy and refusal')


if __name__ == '__main__':
    main()
