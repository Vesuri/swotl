#!/usr/bin/env python3
"""Render a snapshot's mode 13h framebuffer (vram.bin + dac.bin) as PNG.

Chained mode 13h: DOSBox-X keeps CPU address A0000+a at
vram[((a & ~3) << 2) | (a & 3)] (planes interleaved per byte).
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    rows = b"".join(b"\0" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                     chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path, help="snap-<name> directory")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    planes = (args.snapshot / "vram.bin").read_bytes()
    vram = bytes(planes[((a & ~3) << 2) | (a & 3)] for a in range(64000))
    dac = (args.snapshot / "dac.bin").read_bytes()
    palette = [bytes(min(255, c * 255 // 63) for c in dac[i * 3:i * 3 + 3]) for i in range(256)]
    rgb = b"".join(palette[p] for p in vram)
    write_png(args.output or args.snapshot / "frame.png", 320, 200, rgb)


if __name__ == "__main__":
    main()
