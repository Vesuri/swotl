#!/usr/bin/env python3
"""Prepare the local TFH research image and check the documented format evidence.

Inspection only: no output is used by the translator or shipped with the port.
See docs/tfh-cross-reference.md for the Ghidra invocation and evidence limits.
"""
import argparse
import hashlib
from pathlib import Path
import struct

import swotl_model as M


def relocate(data):
    pos = 0

    def word():
        nonlocal pos
        value, = struct.unpack_from('>I', data, pos)
        pos += 4
        return value

    assert word() == 1011 and word() == 0, 'expected unnamed HUNK_HEADER'
    count, first, last = word(), word(), word()
    assert (count, first, last) == (3, 0, 2)
    sizes = [(word() & 0x3fffffff) * 4 for _ in range(count)]
    assert sizes == [204352, 64020, 4], sizes
    bases = [0x10000, 0x41e40, 0x51854]
    image = bytearray(sum(sizes))
    hunk, relocations = 0, []
    while pos < len(data):
        kind = word() & 0x3fffffff
        if kind in (1001, 1002):
            size = word() * 4
            assert size <= sizes[hunk] and pos + size <= len(data)
            start = bases[hunk] - bases[0]
            image[start:start + size] = data[pos:pos + size]
            pos += size
        elif kind == 1003:
            assert word() * 4 == sizes[hunk]
        elif kind == 1004:
            while (n := word()):
                target = word()
                assert target < count
                for _ in range(n):
                    offset = word()
                    assert offset + 4 <= sizes[hunk]
                    relocations.append((hunk, offset, target))
        elif kind == 1010:
            hunk += 1
        else:
            raise ValueError(f'unsupported hunk {kind:x} at {pos - 4:x}')
    assert pos == len(data) and hunk == count and len(relocations) == 1511
    for hunk, offset, target in relocations:
        at = bases[hunk] - bases[0] + offset
        value, = struct.unpack_from('>I', image, at)
        struct.pack_into('>I', image, at, value + bases[target])
    return image


def sprite_count(data):
    """Check record boundaries, not rendering or guest semantics."""
    pos, count = 0, 0
    while pos < len(data):
        pos += 5
        while data[pos] != 255:
            pos += data[pos] + 3
        pos += 1
        count += 1
    assert pos == len(data)
    return count


def first_image_rows(data, shift):
    """Measure only the first screen record; PAC files can also contain text."""
    pos, width, rows = 0, 0, []
    while True:
        token = data[pos]
        pos += 1
        if token == 255:
            assert width == 0
            return rows
        if token == 254:
            rows.append(width)
            width = 0
        elif token == 253:
            width += data[pos] + 1
            pos += 2
        elif shift == 2 and token == 252:
            width += data[pos + 1] + 1
            pos += 2
        elif shift == 2 and token == 251:
            pos += 1
        else:
            width += (token & ((1 << shift) - 1)) + 1


def check(data_dir, image):
    for directory, excluded, expected in [
        (data_dir / 'pi', set(), 16),
        (M.REF / 'AC', {'VGA.PAC', 'CAMOFLAG.PAC', 'CAMOEXP.PAC'}, 26),
    ]:
        files = sorted(p for p in directory.iterdir()
                       if p.suffix.lower() == '.pac' and p.name.upper() not in excluded)
        assert len(files) == expected
        assert all(sprite_count(p.read_bytes()) == 51 for p in files)
        print(f'{directory}: {len(files)} aircraft files, 51 sprites each; exact EOF')
    for path, shift in [(data_dir / 'intro.pac', 3),
                        (data_dir / 'screens/menu.pac', 3),
                        (M.REF / 'FE/ABRIEF.PAC', 2),
                        (M.REF / 'FE/GBRIEF.PAC', 2)]:
        assert first_image_rows(path.read_bytes(), shift) == [320] * 200
        print(f'{path}: first screen 320 x 200')
    gob = (data_dir / 'gobs.gob').read_bytes()
    offsets = list(struct.unpack_from('>35H', image, 0x34456)) + [len(gob)]
    assert offsets == sorted(set(offsets)) and offsets[0] == 0
    for start, end in zip(offsets, offsets[1:]):
        header = gob[start:start + 7]
        pos, extra = start + 7, 0
        for _ in range(header[5]):
            extra = max(extra, gob[pos + 2] - 127)
            pos += gob[pos] + 3
        assert ((pos - start + 1) & ~1) == header[6]
        assert header[6] + header[4] * 6 + extra * 12 == end - start
    print('gobs.gob: all 35 indexed records fit faces, alignment, vertices and extra records')
    rings = struct.unpack_from('>11H', image, 0x34998)
    module = M.load_modules()['DATA.OVL']
    assert struct.unpack_from('<11H', module.data, 0x631c) == rings
    gmat = (data_dir / 'gmat.gob').read_bytes()
    gring = (M.REF / 'GRING.GOB').read_bytes()
    assert len(gmat) == 2048 + len(gring) == 2794
    assert all(offset % 2 == 0 and offset < len(gring) for offset in rings)
    print('terrain rings: 11 matching offsets; both payloads 746 bytes; '
          f'{sum(a != b for a, b in zip(gmat[2048:], gring))} differing bytes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path,
                        default=M.REPO / 'tmp/tfh/TheirFinestHour&Missions/data')
    args = parser.parse_args()
    original = (args.data / 'BOB').read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    assert digest == '4b5931c8500e60b5f4cdbfa7f8e37930c731c14443bd1f88757090fb22443877'
    image = relocate(original)
    out = M.REPO / 'tmp/tfh-xref'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'BOB.bin').write_bytes(image)
    print(f'BOB sha256 {digest}; 1511 relocations; code/data/BSS at 10000/41e40/51854')
    check(args.data, image)


if __name__ == '__main__':
    main()
