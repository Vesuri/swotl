#!/usr/bin/env python3
"""Summarise a tools/pc_run.py trace directory (validates that outputs parse)."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--ref", type=Path, default=Path(__file__).resolve().parent.parent / "ref")
    args = parser.parse_args()
    t = args.trace
    summary = dict(line.split("=", 1) for line in (t / "summary.txt").read_text().split())
    load_seg = int(summary["load_seg"], 16)
    print(f"load segment {load_seg:04X}, {int(summary['instructions']):,} instructions, "
          f"{int(summary['edges']):,} edges")

    print("\nmodule          loads  executed  file bytes")
    for m in rows(t / "modules.csv"):
        size = (args.ref / m["module"]).stat().st_size if (args.ref / m["module"]).exists() else 0
        print(f"{m['module']:14} {m['loads']:>6} {m['executed_bytes']:>9} {size:>11}")

    print("\ncode loads (module, file pos -> segment relative to load segment)")
    seen = set()
    for e in rows(t / "events.csv"):
        if e["kind"] != "read":
            continue
        name, *fields = e["detail"].split()
        if not name.endswith((".OVL", ".EXE")):
            continue
        kv = dict(f.split("=") for f in fields)
        linear, pos, got = int(kv["linear"], 16), int(kv["pos"], 16), int(kv["got"])
        key = (name, linear, pos, got)
        if got < 1024 or key in seen:
            continue
        seen.add(key)
        rel = linear / 16 - load_seg
        print(f"  {e['icount']:>12} {name:13} pos {pos:05X} len {got:6} -> +{rel:07.1f} by "
              f"{e['module']}+{e['offset']}")

    ints = Counter()
    for r in rows(t / "interrupts.csv"):
        ah = int(r["ax"], 16) >> 8
        key = f"INT {r['vector'][2:]}" + (f" AH={ah:02X}" if r["type"] != "0" and
                                          r["vector"] in ("0x10", "0x21", "0x67", "0x33", "0x16") else "")
        key += "" if r["type"] != "0" else " (hw)"
        ints[key] += int(r["count"])
    print("\ninterrupts")
    for k, n in sorted(ints.items()):
        print(f"  {k:24} {n:>12,}")

    port_count = Counter()
    port_sites = defaultdict(set)
    for r in rows(t / "ports.csv"):
        if r["source_module"] == "-":
            continue  # emulator callbacks (BIOS/DOS stubs), not guest code
        k = f"{r['direction']} {r['port']}"
        port_count[k] += int(r["count"])
        port_sites[k].add((r["source_module"], r["source_offset"]))
    print("\nports (count, sites)")
    for k, n in sorted(port_count.items()):
        print(f"  {k:12} {n:>12,} {len(port_sites[k]):>4}")

    vga = rows(t / "vga.csv")
    sites = {(r["source_module"], r["source_offset"], r["direction"]) for r in vga}
    print(f"\nVGA memory: {sum(int(r['count']) for r in vga):,} accesses from {len(sites)} sites")
    by_module = Counter(m for m, _, _ in sites)
    for m, n in by_module.most_common():
        print(f"  {m:14} {n:>5} sites")

    cw = rows(t / "code-writes.csv")
    writers = Counter((r["writer_module"], r["writer_offset"]) for r in cw)
    print(f"\nwrites into executed paragraphs: {sum(int(r['count']) for r in cw):,} "
          f"from {len(writers)} writer sites")
    for (m, o), n in writers.most_common(10):
        print(f"  {m}+{o} ({n} targets)")


if __name__ == "__main__":
    main()
