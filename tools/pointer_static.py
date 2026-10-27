#!/usr/bin/env python3
"""Static facts behind the hardware-sprite pointer (docs/pointer-plan.md P2).

    python3 tools/pointer_static.py [--runs GLOB]

From the original modules (ref/), the decoded instructions (build/gen/*.ir,
`make gen`) and the reference snapshots (tmp/pc-runs/ref-*/trace/snap-*):

- shapes: every shape the guest selects (the constants its callers push to
  SWOTL.EXE 0320:0C76) is at most 16 pixels wide, its image and table slots lie
  apart inside DGROUP, and its opaque colours are FEh (sprite 6, colour FEh
  exact) and at most one other (sprite 4, colour F9h set to it); FDh is
  transparent;
- writers: only 0C76 stores the shape words, only 0C64 and the tracker store the
  position, and only hide/show (0CAC/0CD2) name the save buffer A42Ah;
- driver: the VGA entries (index 8) of the driver tables are RTSVGA's save,
  restore and draw; save and restore copy w bytes per row at row(y) + x with
  the row table at cs:35FC equal to 320 y, so buffer byte r w + c is the
  screen byte 320 (y0 + r) + x0 + c of every pixel the draw writes (rows 0-199,
  columns 0-319); the draw's segment (ds:284C) is A000h;
- census: in each snapshot whose pointer is complete in VGA memory, no pixel
  outside the pointer is F9h (the entry sprite 4's colour takes).

Exit 1 with the problems listed; each check is also a function for
tests/test_pointer_static.py.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import swotl_model as M  # noqa: E402

DGROUP_OFFSET = 0x580             # DGROUP = DATA.OVL image + 580h
DGROUP_PARAS = DGROUP_OFFSET // 16
SHAPE_TABLE, IMAGE_TABLE = 0x05F0, 0x065C   # 8 B (w, h, hx, hy), 2 B image offset
SHAPE_WORDS = {0x9D62: "width", 0x9D86: "height", 0x9D3A: "hotspot x",
               0x9D4C: "hotspot y", 0x9DC8: "image"}
POSITION_WORDS = {0x9C1A: "x", 0x9CBA: "y"}
BUFFER = 0xA42A
SCREEN_SEGMENT = 0x284C
EXACT = 0xFE                      # sprite 6 colour 2 (BPLCON4 ESPRM Fh): entry FEh as it is
TRANSPARENT = 0xFD
STOLEN = (0xF9,)                  # sprite 4 colour 1: set to the shape's other colour
SPRITE_WIDTH = 16
DRIVER_TABLES = {"save": 0x06C0, "restore": 0x06CC, "draw": 0x06D8}
VGA_INDEX = 8
DRIVER = {"save": 0x40E6, "restore": 0x4138, "draw": 0x4184}   # RTSVGA module offsets
ROW_TABLE = 0x35FC                # RTSVGA cs offset (module offset - 20h)
# The routines' inner loops (module offset: bytes), x86 as decoded in the IR.
SIGNATURES = {
    0x4122: bytes.fromhex("268a05" "8804" "47" "46" "e2f7"),   # save: es:[di] -> [si], w per row
    0x4175: bytes.fromhex("f3a4"),                             # restore: rep movsb [si] -> es:[di]
    0x41cf: bytes.fromhex("8a04" "3cfd" "7403" "268805"),      # draw: FDh skipped
}
SHAPE_SELECT = ("SWOTL.EXE", 0x0C76)
WRITERS = {
    "shape": {("SWOTL.EXE", o) for o in (0x3E85, 0x3E8C, 0x3E93, 0x3E9A, 0x3EA6)},
    "position": {("SWOTL.EXE", o) for o in (0x3E6A, 0x3E70, 0x4204, 0x420A)},
    "buffer": {("SWOTL.EXE", o) for o in (0x3EC4, 0x3EEA)},
}
LINE = re.compile(r"^(\S+)\+([0-9A-F]+) ([0-9A-F]{4}):([0-9A-F]{4}) [0-9a-f]+\s+(\S+)\s*(.*)$")


def dgroup(mods) -> bytes:
    data = mods["DATA.OVL"]
    return data.data[data.code_start + DGROUP_OFFSET:]


def word(b: bytes, off: int, signed=False) -> int:
    return struct.unpack_from("<h" if signed else "<H", b, off)[0]


def instructions(gen: Path):
    """(module, module offset, cs, ip, mnemonic, operands) per decoded instruction."""
    for path in sorted(gen.glob("*.ir")):
        for line in path.read_text().splitlines():
            m = LINE.match(line)
            if m:
                yield m[1], int(m[2], 16), int(m[3], 16), int(m[4], 16), m[5], m[6]


def shape_ids(insns) -> tuple[set[int], list[str]]:
    """The constants pushed to 0C76 (sub ax, ax or mov ax, N; push ax; call)."""
    ids, problems, last = set(), [], []
    for mod, off, cs, ip, op, args in insns:
        far = op == "callf" and args == f"0x{0x320:x}:0x{SHAPE_SELECT[1]:x}"
        near = mod == SHAPE_SELECT[0] and cs == 0x320 and op == "call" and args == f"0x{SHAPE_SELECT[1]:x}"
        if far or near:
            if len(last) == 2 and last[1][4:] == ("push", "ax") and last[0][4:] == ("sub", "ax, ax"):
                ids.add(0)
            elif len(last) == 2 and last[1][4:] == ("push", "ax") and last[0][4] == "mov" \
                    and last[0][5].startswith("ax, 0x"):
                ids.add(int(last[0][5][4:], 16))
            else:
                problems.append(f"shape select at {mod}+{off:05X}: argument not a constant")
        last = (last + [(mod, off, cs, ip, op, args)])[-2:]
    return ids, problems


def shapes(dg: bytes, ids) -> dict[int, tuple]:
    out = {}
    for n in sorted(ids):
        w, h, hx, hy = struct.unpack_from("<4h", dg, SHAPE_TABLE + 8 * n)
        image = word(dg, IMAGE_TABLE + 2 * n)
        out[n] = (w, h, hx, hy, image, dg[image:image + max(w, 0) * max(h, 0)])
    return out


def check_shapes(dg: bytes, ids) -> list[str]:
    problems = []
    if not ids:
        return ["no shape selected"]
    spans = [(SHAPE_TABLE, SHAPE_TABLE + 8 * (max(ids) + 1), "shape table"),
             (IMAGE_TABLE, IMAGE_TABLE + 2 * (max(ids) + 1), "image table")]
    for n, (w, h, hx, hy, image, pixels) in shapes(dg, ids).items():
        if not 0 < w <= SPRITE_WIDTH or h <= 0:
            problems.append(f"shape {n}: {w}x{h} does not fit a {SPRITE_WIDTH}-pixel sprite")
            continue
        spans.append((image, image + w * h, f"shape {n} image"))
        other = sorted({p for p in pixels if p not in (TRANSPARENT, EXACT)})
        if len(other) > 1:
            problems.append(f"shape {n}: colours {', '.join(f'{p:02X}h' for p in other)}: one besides FEh at most")
    spans.sort()
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        if b0 < a1:
            problems.append(f"{an} [{a0:04X}, {a1:04X}) overlaps {bn} [{b0:04X}, {b1:04X})")
    if spans and spans[-1][1] > len(dg):
        problems.append(f"{spans[-1][2]} past DGROUP's initialized bytes")
    return problems


def check_writers(insns) -> list[str]:
    problems = []
    named = {"shape": SHAPE_WORDS, "position": POSITION_WORDS}
    for mod, off, cs, ip, op, args in insns:
        dest = args.split(",")[0]
        for kind, words in named.items():
            for a, what in words.items():
                if f"[0x{a:x}]" in dest and op not in ("cmp", "test", "push") \
                        and (mod, off) not in WRITERS[kind]:
                    problems.append(f"{mod}+{off:05X} {op} {args}: writes the pointer {what}")
        if re.search(rf"\b0x{BUFFER:x}\b", args) and (mod, off) not in WRITERS["buffer"]:
            problems.append(f"{mod}+{off:05X} {op} {args}: names the save buffer")
    return problems


def check_driver(mods, dg: bytes) -> list[str]:
    problems = []
    thunks = {a: (name, off) for a, name, off in M.thunks(mods)}
    for kind, table in DRIVER_TABLES.items():
        off, seg = struct.unpack_from("<HH", dg, table + VGA_INDEX)
        target = thunks.get(seg * 16 + off)
        if target != ("RTSVGA.OVL", DRIVER[kind]):
            problems.append(f"VGA {kind} entry {seg:04X}:{off:04X} is {target}, not RTSVGA+{DRIVER[kind]:04X}")
    rts = mods["RTSVGA.OVL"].data
    for off, sig in SIGNATURES.items():
        if rts[off:off + len(sig)] != sig:
            problems.append(f"RTSVGA+{off:04X}: {rts[off:off + len(sig)].hex()} is not {sig.hex()}")
    rows = struct.unpack_from("<200H", rts, mods["RTSVGA.OVL"].code_start + ROW_TABLE)
    if any(r != 320 * y for y, r in enumerate(rows)):
        problems.append("RTSVGA row table is not 320 y")
    if word(dg, SCREEN_SEGMENT) != 0xA000:
        problems.append(f"draw segment ds:{SCREEN_SEGMENT:04X} is {word(dg, SCREEN_SEGMENT):04X}h, not A000h")
    return problems


def snapshot(path: Path):
    """(DGROUP bytes, chained mode 13h screen bytes) of a reference snapshot;
    None before DATA.OVL is loaded or outside mode 13h."""
    data = [line.split(",") for line in (path / "residency.csv").read_text().splitlines()[1:]]
    para = next((int(first, 16) for first, _, module, _ in data if module == "DATA.OVL"), None)
    if para is None or "vga_mode=13" not in (path / "regs.txt").read_text():
        return None
    ram = (path / "ram.bin").read_bytes()
    planes = (path / "vram.bin").read_bytes()
    screen = bytes(planes[((a & ~3) << 2) | (a & 3)] for a in range(64000))
    base = (para + DGROUP_PARAS) * 16
    return ram[base:base + 0x10000], screen


def pointer_pixels(dg: bytes):
    """{screen offset: colour} of the opaque pixels the draw writes."""
    x, y = word(dg, 0x9C1A, True), word(dg, 0x9CBA, True)
    w, h = word(dg, 0x9D62, True), word(dg, 0x9D86, True)
    hx, hy = word(dg, 0x9D3A, True), word(dg, 0x9D4C, True)
    image = word(dg, 0x9DC8)
    if not (0 < w <= 64 and 0 < h <= 64):
        return {}
    out = {}
    for r in range(h):
        for c in range(w):
            p, sx, sy = dg[image + r * w + c], x + hx + c, y + hy + r
            if p != TRANSPARENT and 0 <= sx < 320 and 0 <= sy < 200:
                out[sy * 320 + sx] = p
    return out


def census(dg: bytes, screen: bytes) -> tuple[bool, dict[int, int]]:
    """(pointer complete, {stolen colour: pixels outside the pointer})."""
    pixels = pointer_pixels(dg)
    complete = bool(pixels) and all(screen[o] == p for o, p in pixels.items())
    shown = {c: 0 for c in STOLEN}
    for o, p in enumerate(screen):
        if p in shown and o not in pixels:
            shown[p] += 1
    return complete, shown


def check_census(snaps) -> tuple[list[str], int]:
    problems, screens = [], 0
    for name, snap in snaps:
        if snap is None:
            continue
        dg, screen = snap
        complete, shown = census(dg, screen)
        if complete:
            screens += 1
            for c, n in shown.items():
                if n:
                    problems.append(f"{name}: colour {c:02X}h on {n} pixels of a pointer screen")
    return problems, screens


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default="ref-*", help="tmp/pc-runs glob of the census")
    ap.add_argument("--gen", type=Path, default=REPO / "build/gen")
    args = ap.parse_args()
    mods = M.load_modules()
    dg = dgroup(mods)
    insns = list(instructions(args.gen))
    ids, problems = shape_ids(insns)
    problems += check_shapes(dg, ids) + check_writers(insns) + check_driver(mods, dg)
    for n, (w, h, hx, hy, image, _) in shapes(dg, ids).items():
        print(f"shape {n}: {w}x{h} hotspot ({hx}, {hy}) image ds:{image:04X}")
    paths = sorted(p for run in sorted((REPO / "tmp/pc-runs").glob(args.runs))
                   for p in (run / "trace").glob("snap-*"))
    found, screens = check_census((p.name, snapshot(p)) for p in paths)
    problems += found
    print(f"census: {len(paths)} snapshots, {screens} with the pointer complete")
    for p in problems:
        print("FAIL:", p)
    if not paths:
        print("FAIL: no reference snapshots")
        return 1
    print("PASS" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
