#!/usr/bin/env python3
"""Write or check release/originals.sha256: SHA-256 of every original input.

    python3 tools/originals.py [--check]

Rows: the 542 SWOTL files of the original DOS Air Combat Classics install
(ACC_REFERENCE, default tmp/accx/dosrun/c/CLASSICS/SWOTL), the ref/ v2.2
repack, the three ACC volumes CLASSICS.001-003 and the local disk images
(ACC_IMAGES, default tmp/acc), and TFH sfx.rsc (TFH_RSC). Hashes only, no
bytes; the packager and checker refuse any member matching one.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'release/originals.sha256'
sys.path.insert(0, str(ROOT / 'tools/install-data'))
from test_install import IMAGES, REFERENCE, TFH_RSC, fat12_file  # noqa: E402


def rows():
    out = {}
    def add(name, data):
        out.setdefault(hashlib.sha256(data).hexdigest(), name)
    for base, label in ((REFERENCE, 'acc'), (ROOT / 'ref', 'ref')):
        for p in sorted(base.rglob('*')):
            if p.is_file() and p.suffix.lower() != '.pdf':
                add(f'{label}/{p.relative_to(base).as_posix()}', p.read_bytes())
    for n in (1, 2, 3):
        image = IMAGES / f'disk{n}.img'
        add(f'CLASSICS.00{n}', fat12_file(image, f'CLASSICS00{n}'))
        add(f'disk{n}.img', image.read_bytes())
    add('tfh/sfx.rsc', TFH_RSC.read_bytes())
    return ''.join(f'{h}  {name}\n' for h, name in sorted(out.items(), key=lambda kv: kv[1]))


def load():
    return {line.split()[0] for line in TABLE.read_text().splitlines() if line.strip()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--check', action='store_true')
    text = rows()
    if p.parse_args().check:
        if TABLE.read_text() != text:
            raise SystemExit('FAIL: release/originals.sha256 differs from the local originals')
        print(f'PASS: {len(text.splitlines())} original hashes')
        return
    TABLE.write_text(text)
    print(f'{TABLE}: {len(text.splitlines())} hashes')


if __name__ == '__main__':
    main()
