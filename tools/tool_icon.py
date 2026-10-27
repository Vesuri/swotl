#!/usr/bin/env python3
"""Write a Workbench tool icon (.info) with tool types.

    python3 tools/tool_icon.py OUT.info [--stack BYTES] [TOOLTYPE ...]

A plain DiskObject (WB_DISKMAGIC E310h, version 1, WBTOOL): one 16x8 2-plane
image, no default tool, no drawer data, unplaced, the given stack and tool
types. Layout: NDK workbench/workbench.h (struct DiskObject, 78 bytes with its
embedded struct Gadget), intuition/intuition.h (struct Image); the image data
follows the Image, the tool types follow as a longword count ((n + 1) * 4) and
length-prefixed NUL-terminated strings. Used by amiga/workbench_check.sh.
"""
import argparse
import struct
from pathlib import Path

WB_DISKMAGIC, WB_DISKVERSION, WB_DISKREVISION = 0xE310, 1, 1
WBTOOL = 3
NO_ICON_POSITION = 0x80000000
GFLG_GADGIMAGE, GACT_RELVERIFY_IMMEDIATE, GTYP_BOOLGADGET = 0x0004, 0x0003, 0x0001
WIDTH, HEIGHT, DEPTH = 16, 8, 2


def icon(tooltypes, stack):
    # struct Gadget: next, left, top, width, height, flags, activation, type,
    # render (non-zero: an Image follows), select render, text, mutual
    # exclude, special info, id, user data (the revision).
    gadget = struct.pack('>IhhHHHHHIIIIIHI', 0, 0, 0, WIDTH, HEIGHT, GFLG_GADGIMAGE,
                         GACT_RELVERIFY_IMMEDIATE, GTYP_BOOLGADGET, 1, 0, 0, 0, 0, 0,
                         WB_DISKREVISION)
    assert len(gadget) == 44
    # do_Type, pad, default tool, tool types (non-zero: they follow),
    # current x, y, drawer data, tool window, stack size.
    disk = struct.pack('>HH', WB_DISKMAGIC, WB_DISKVERSION) + gadget + struct.pack(
        '>BBIIIIIII', WBTOOL, 0, 0, 1 if tooltypes else 0, NO_ICON_POSITION,
        NO_ICON_POSITION, 0, 0, stack)
    assert len(disk) == 78
    # struct Image: left, top, width, height, depth, data, plane pick, on/off, next.
    image = struct.pack('>hhHHHIBBI', 0, 0, WIDTH, HEIGHT, DEPTH, 1, 3, 0, 0)
    rows = bytes([0xFF, 0xFF] + [0x80, 0x01] * (HEIGHT - 2) + [0xFF, 0xFF])
    out = disk + image + rows + bytes(len(rows))
    if tooltypes:
        out += struct.pack('>I', (len(tooltypes) + 1) * 4)
        for t in tooltypes:
            s = t.encode('latin1') + b'\0'
            out += struct.pack('>I', len(s)) + s
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('out', type=Path)
    p.add_argument('--stack', type=int, default=4096)
    p.add_argument('tooltypes', nargs='*')
    args = p.parse_args()
    args.out.write_bytes(icon(args.tooltypes, args.stack))


if __name__ == '__main__':
    main()
