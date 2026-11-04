#!/usr/bin/env python3
"""Render a snapshot's framebuffer (vram.bin + dac.bin, mode 0Eh also ega.txt) as PNG.

Chained mode 13h: DOSBox-X keeps CPU address A0000+a at
vram[((a & ~3) << 2) | (a & 3)] (planes interleaved per byte).
Mode 0Eh (640x200, 16 colours): plane p of byte a is vram[a * 4 + p]; bit 7 is
the leftmost pixel; the shown page starts at the CRTC start address. The 4-bit
pixel goes through the attribute palette (ega.txt) to the DAC.
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
    dac = (args.snapshot / "dac.bin").read_bytes()
    palette = [bytes(min(255, c * 255 // 63) for c in dac[i * 3:i * 3 + 3]) for i in range(256)]
    regs = (args.snapshot / "regs.txt").read_text()
    out = args.output or args.snapshot / "frame.png"
    if "vga_mode=0e" in regs:
        ega = dict(kv.split("=") for kv in (args.snapshot / "ega.txt").read_text().split())
        attr = bytes.fromhex(ega["attr_palette"])
        start = int(ega["crtc_start"], 16)
        rgb = bytearray()
        for a in range(start, start + 16000):
            p = planes[a * 4:a * 4 + 4]
            for bit in range(7, -1, -1):
                index = sum(((p[k] >> bit) & 1) << k for k in range(4))
                rgb += palette[attr[index] & 0x3F]
        write_png(out, 640, 200, bytes(rgb))
        return
    vram = bytes(planes[((a & ~3) << 2) | (a & 3)] for a in range(64000))
    rgb = b"".join(palette[p] for p in vram)
    write_png(out, 320, 200, rgb)


if __name__ == "__main__":
    main()
