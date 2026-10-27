"""Pointer static facts (docs/pointer-plan.md P2): tools/pointer_static.py on the
original modules, the decoded instructions and the reference snapshots, then
each check against a planted fault, which it must report:

  width     shape 1 widened to 17 pixels
  colour    an FFh pixel in the crosshair (a second colour besides FEh)
  overlap   the crosshair's image moved onto the arrow's
  writer    a store to the image word outside 0C76
  buffer    a fourth instruction naming A42Ah
  argument  a shape select whose argument is a register
  driver    the save loop's store changed
  rows      row 100 of the row table moved by a pixel
  segment   the draw segment B800h
  census    an F9h pixel on a pointer screen
  partial   the same, with one pointer pixel overwritten: no pointer screen, no report
"""
import dataclasses
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pointer_static as P  # noqa: E402
import swotl_model as M  # noqa: E402


def setup():
    mods = M.load_modules()
    insns = list(P.instructions(ROOT / "build/gen"))
    snap = next(p for p in sorted((ROOT / "tmp/pc-runs").glob("ref-c9-mouse-menu/trace/snap-*")))
    return mods, P.dgroup(mods), insns, P.snapshot(snap)


def shape_plant(dg, n, edit):
    b = bytearray(dg)
    edit(b, n)
    return bytes(b)


def main():
    mods, dg, insns, (sdg, screen) = setup()
    ids, problems = P.shape_ids(insns)
    assert ids == {0, 1}, ids
    assert not problems, problems
    assert not P.check_shapes(dg, ids), P.check_shapes(dg, ids)
    assert not P.check_writers(insns), P.check_writers(insns)
    assert not P.check_driver(mods, dg), P.check_driver(mods, dg)
    complete, shown = P.census(sdg, screen)
    assert complete and not any(shown.values()), (complete, shown)
    print("clean: shapes {0, 1}, writers, driver, c9 census")

    def width(b, n):
        struct.pack_into("<h", b, P.SHAPE_TABLE + 8 * 1, 17)

    def colour(b, n):
        b[P.word(dg, P.IMAGE_TABLE + 2) + 2] = 0xFF

    def overlap(b, n):
        struct.pack_into("<H", b, P.IMAGE_TABLE + 2, P.word(dg, P.IMAGE_TABLE) + 4)

    def segment(b, n):
        struct.pack_into("<H", b, P.SCREEN_SEGMENT, 0xB800)

    caught = {}
    for name, edit, check in (("width", width, "shapes"), ("colour", colour, "shapes"),
                              ("overlap", overlap, "shapes"), ("segment", segment, "driver")):
        planted = shape_plant(dg, 1, edit)
        found = P.check_shapes(planted, ids) if check == "shapes" else P.check_driver(mods, planted)
        caught[name] = found

    store = ("NOTCAMP.OVL", 0x1000, 0x3156, 0x0800, "mov", "word ds:[0x9dc8], ax")
    caught["writer"] = P.check_writers(insns + [store])
    caught["buffer"] = P.check_writers(insns + [("FRONTEND.OVL", 0x2000, 0x1F40, 0x0100, "mov", "ax, 0xa42a")])
    call = [("FRONTEND.OVL", 0x2000, 0x1F40, 0x0100, "push", "bx"),
            ("FRONTEND.OVL", 0x2001, 0x1F40, 0x0101, "push", "bx"),
            ("FRONTEND.OVL", 0x2002, 0x1F40, 0x0102, "callf", "0x320:0xc76")]
    caught["argument"] = P.shape_ids(insns + call)[1]

    def module_plant(off, value):
        rts = bytearray(mods["RTSVGA.OVL"].data)
        rts[off:off + len(value)] = value
        planted = dict(mods)
        planted["RTSVGA.OVL"] = dataclasses.replace(mods["RTSVGA.OVL"], data=bytes(rts))
        return P.check_driver(planted, dg)

    caught["driver"] = module_plant(0x4125, b"\x88\x05")
    caught["rows"] = module_plant(mods["RTSVGA.OVL"].code_start + P.ROW_TABLE + 200, struct.pack("<H", 32001))

    pixels = P.pointer_pixels(sdg)
    outside = next(o for o in range(64000) if o not in pixels and screen[o] != 0xF9)
    planted = bytearray(screen)
    planted[outside] = 0xF9
    caught["census"] = P.check_census([("plant", (sdg, bytes(planted)))])[0]
    first = min(pixels)
    planted[first] = pixels[first] ^ 1
    partial = P.check_census([("plant", (sdg, bytes(planted)))])
    assert partial == ([], 0), partial

    expect = {"width": "does not fit", "colour": "one besides FEh", "overlap": "overlaps",
              "segment": "draw segment", "writer": "writes the pointer image",
              "buffer": "names the save buffer", "argument": "not a constant",
              "driver": "RTSVGA+4122", "rows": "row table", "census": "F9h on 1 pixels"}
    missed = []
    for name, found in caught.items():
        hit = [f for f in found if expect[name] in f]
        print(f"{name}: {hit[0] if hit else 'MISSED'}")
        missed += [] if hit else [name]
    print("partial: not a pointer screen, nothing reported")
    if missed:
        raise SystemExit(f"FAIL: plants missed: {', '.join(missed)}")
    print(f"PASS: {len(caught) + 1} plants")


if __name__ == "__main__":
    main()
