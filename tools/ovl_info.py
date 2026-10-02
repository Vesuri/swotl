#!/usr/bin/env python3
"""Summarise PLINK .OVL files: size and leading far-pointer table segments."""

from __future__ import annotations

import argparse
import struct
from collections import Counter
from pathlib import Path


def leading_table(data: bytes) -> tuple[int, Counter[int]]:
    """Far pointers from offset 0 until a zero segment; may overrun into code."""
    count, segments = 0, Counter()
    while count * 4 + 4 <= len(data):
        _, segment = struct.unpack_from("<HH", data, count * 4)
        if segment == 0:
            break
        segments[segment] += 1
        count += 1
    return count, segments


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("overlays", type=Path, nargs="+")
    args = parser.parse_args()
    print(f"{'file':14} {'bytes':>7} {'paras':>6}  first-seg  entries  top segments")
    for path in args.overlays:
        data = path.read_bytes()
        count, segments = leading_table(data)
        first = struct.unpack_from("<H", data, 2)[0]
        top = " ".join(f"{s:04X}x{n}" for s, n in segments.most_common(4))
        print(f"{path.name:14} {len(data):7} {(len(data) + 15) // 16:6}  "
              f"{first:04X}       {count:7}  {top}")


if __name__ == "__main__":
    main()
