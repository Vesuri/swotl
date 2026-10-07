#!/usr/bin/env python3
"""Account for every byte in an elf2hunk executable, without modifying it."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import struct


def inspect(data):
    pos = 0
    sizes = Counter()
    symbols = 0

    def skip(n):
        nonlocal pos
        if n < 0 or pos + n > len(data):
            raise ValueError(f"truncated hunk at byte {pos}")
        pos += n

    def word():
        nonlocal pos
        skip(4)
        return struct.unpack_from(">I", data, pos - 4)[0]

    if word() != 0x3f3:
        raise ValueError("not an Amiga HUNK_HEADER executable")
    while (n := word()):
        skip(n * 4)
    table, first, last = word(), word(), word()
    if last < first or last >= table:
        raise ValueError("invalid hunk table")
    alloc = [word() for _ in range(last - first + 1)]
    if any(n >> 30 == 3 for n in alloc):
        raise ValueError("extended allocation attributes are unsupported")
    sizes["headers"] = pos
    loadable = hashlib.sha256(data[:pos])
    ended = 0
    while pos < len(data):
        start = pos
        kind = word() & 0x3fffffff
        if kind in (0x3e9, 0x3ea, 0x3f1):
            n = word() * 4
            skip(n)
            key = {0x3e9: "code", 0x3ea: "data", 0x3f1: "debug"}[kind]
            if key == "debug":
                sizes[key] += pos - start
            else:
                sizes[key] += n
                sizes["headers"] += 8
        elif kind == 0x3eb:
            word()  # BSS consumes memory, but has no payload in the file.
            sizes["headers"] += pos - start
        elif kind == 0x3ec:
            while (n := word()):
                word()
                skip(n * 4)
            sizes["relocations"] += pos - start
        elif kind == 0x3f0:
            while (n := word()):
                skip(n * 4)
                word()
                symbols += 1
            sizes["symbols"] += pos - start
        elif kind == 0x3f2:
            ended += 1
            sizes["headers"] += 4
        else:
            raise ValueError(f"unsupported hunk type {kind:#x} at byte {start}")
        if kind not in (0x3f0, 0x3f1):
            loadable.update(data[start:pos])
    if ended != len(alloc):
        raise ValueError(f"expected {len(alloc)} hunk ends, found {ended}")
    assert sum(sizes.values()) == len(data)
    return dict(file_bytes=len(data), sections=dict(sizes), symbol_count=symbols,
                loadable_sha256=loadable.hexdigest(),
                allocated_hunk_bytes=sum((n & 0x3fffffff) * 4 for n in alloc))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    reports = {str(p): inspect(p.read_bytes()) for p in args.files}
    if args.json:
        print(json.dumps(reports, indent=2))
        return
    for path, report in reports.items():
        print(f"{path}: {report['file_bytes']:,} bytes")
        for kind, size in sorted(report["sections"].items(), key=lambda x: -x[1]):
            print(f"  {kind:12} {size:>12,}  {100 * size / report['file_bytes']:6.2f}%")
        print(f"  symbols: {report['symbol_count']:,}; allocated hunk payload: "
              f"{report['allocated_hunk_bytes']:,} bytes (excludes loader overhead)")


if __name__ == "__main__":
    main()
