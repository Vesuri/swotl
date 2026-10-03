#!/usr/bin/env python3
"""Rebuild root and overlay images from ref/ and compare with a snapshot.

Loader model (gate 1; layout in docs/plink.md, code in swotl_model.py):
- Root: MZ load image at the load segment, each relocation word += load seg.
- Overlays: code (after the fixup list) at load seg + link seg; each fixup
  word += load seg.

Every snapshot residency row is compared with the rebuilt bytes (raw file
bytes before an overlay's code). A differing byte must have a CPU writer
since its load (snapshot `writes.csv`) or be the byte the last traced DOS
read put there (events.csv: buffers that cover paragraphs partly); written
bytes are split into executed instruction bytes (trace bitmap + Capstone
length: self-modifying code, listed by writer) and data. Exit 1 if any byte
differs without a writer.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import Counter
from pathlib import Path

import capstone

import swotl_model as M


def build(ref: Path, load: int) -> dict[str, tuple[int, bytearray, int]]:
    """Module -> (linear base, image, file offset of image byte 0)."""
    out = {}
    for name, m in M.load_modules(ref).items():
        code = bytearray(m.data[m.code_start:])
        if name != M.ROOT and len(code) != m.paras * 16:
            raise SystemExit(f"{name}: code {len(code)} B, table says {m.paras * 16}")
        for fx in m.fixups:
            a = fx - m.code_start
            struct.pack_into("<H", code, a, (struct.unpack_from("<H", code, a)[0] + load) & 0xFFFF)
        out[name] = ((load + m.link_seg) * 16, code, m.code_start)
    return out


def dos_reads(events: Path, until: int, ref: Path) -> dict[int, int]:
    """Linear address -> byte from the last traced DOS read before `until`."""
    files = {p.name.upper(): p for p in ref.rglob("*") if p.is_file()}
    run_root = events.parent.parent / "root"  # files the game wrote (e.g. RP2.TMP film)
    if run_root.exists():
        for p in run_root.rglob("*"):
            if p.is_file():
                files.setdefault(p.name.upper(), p)
    cache, out = {}, {}
    for line in events.open():
        f = line.rstrip("\n").split(",", 4)
        if len(f) < 5 or f[1] != "read" or int(f[0]) > until:
            continue
        name, *kv = f[4].split()
        kv = dict(x.split("=") for x in kv)
        if name not in cache:
            cache[name] = files[name].read_bytes()
        lin, pos, got = int(kv["linear"], 16), int(kv["pos"], 16), int(kv["got"])
        for k in range(got):
            out[lin + k] = cache[name][pos + k]
    return out


def code_bytes(module_image: bytes, base_off: int, bitmap: bytes) -> set[int]:
    """File offsets covered by executed instructions (lengths from Capstone)."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    cover = set()
    for off, hit in enumerate(bitmap):
        if not hit:
            continue
        i = off - base_off
        if not 0 <= i < len(module_image):
            continue
        insn = next(md.disasm(bytes(module_image[i:i + 16]), 0), None)
        cover.update(range(off, off + (insn.size if insn else 1)))
    return cover


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", type=Path, help="tmp/pc-runs/<run>/trace/snap-<name>")
    ap.add_argument("--ref", type=Path, default=M.REF)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    snap, trace = args.snapshot, args.snapshot.parent
    regs = dict(kv.split("=") for kv in (snap / "regs.txt").read_text().split())
    load = int(regs["load_seg"], 16)
    ram = (snap / "ram.bin").read_bytes()
    images = build(args.ref, load)
    raw = {m: (args.ref / m).read_bytes() for m in images}
    read = dos_reads(trace / "events.csv", int(regs["icount"]), args.ref)
    writer = {}
    for r in csv.DictReader((snap / "writes.csv").open()):
        w = f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}"
        for a in range(int(r["first_linear"], 16), int(r["last_linear"], 16) + 1):
            writer[a] = w
    cover = {}
    smc = Counter()
    failed = False
    print(f"load segment {load:04X}")
    print(f"{'module':12} {'linear':>13} {'bytes':>7} {'same':>7} {'code-wr':>7} "
          f"{'data-wr':>7} {'unexpl':>6}")
    for r in csv.DictReader((snap / "residency.csv").open()):
        mod = r["module"]
        if mod not in images:
            continue
        lo, hi = int(r["first_para"], 16) * 16, (int(r["last_para"], 16) + 1) * 16
        base, img, file0 = images[mod]
        moff = int(r["module_offset"], 16)
        if mod not in cover:
            bm = trace / f"executed-{mod}.bin"
            cover[mod] = code_bytes(img, file0, bm.read_bytes() if bm.exists() else b"")
        same = code_wr = data_wr = 0
        bad = []
        for k in range(hi - lo):
            foff = moff + k
            i = foff - file0
            expect = img[i] if 0 <= i < len(img) else raw[mod][foff]
            if expect == ram[lo + k]:
                same += 1
            elif lo + k not in writer:
                if read.get(lo + k) == ram[lo + k]:
                    data_wr += 1
                else:
                    bad.append(foff)
            elif foff in cover[mod]:
                code_wr += 1
                smc[(mod, writer[lo + k])] += 1
            else:
                data_wr += 1
        failed |= bool(bad)
        print(f"{mod:12} {lo:06X}-{hi:06X} {hi - lo:7} {same:7} {code_wr:7} {data_wr:7} {len(bad):6}")
        if args.verbose and bad:
            print("  unexplained at", " ".join(f"{o:05X}" for o in bad[:32]))
    for (mod, w), n in sorted(smc.items()):
        print(f"self-modified {mod} executed bytes: {n:5} by {w}")
    print("gate: FAIL" if failed else "gate: every byte matches the file + loader model or has a CPU writer")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
