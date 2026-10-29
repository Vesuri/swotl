#!/usr/bin/env python3
"""Flight mouse scaling (src/runtime/input.c, rt_mouse_scale) in the host image:
INT 33h AX=0Bh motion against the game clock (IRQ0 deliveries) at 236.7 Hz.

  python3 tests/test_mouse_scale.py [--sabotage]

Checks: off (the reference) the motion is returned as counted; on, a steady
mouse speed gives the same deflection at 5, 24 and 70 ticks per frame (the
68060's 50 fps, about the reference frame, the 68020's): the motion over
MOUSE_FRAME_MS, its rounding carried so long runs sum exactly; signs, the
vertical counter (twice the counts), a frame with no tick, a reset; no scaling
while the last present showed the guest's pointer or one within
MOUSE_POINTER_FIELDS did. Plants
(input.c or pointer.c rebuilt):

  rest     remainders dropped
  ticks    the frame time not measured since the last AX=0Bh
  guard    scaled while a pointer was just shown
  shown    scaled while the last present showed the pointer
  stamp    the present with the pointer shown not recorded
  flag     scaled with rt_mouse_scale clear
"""
import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import host_run as H  # noqa: E402

DIVISOR = 5041                       # SPAZ's 236.7 Hz
FRAME = 100 * (1193182 * 256 // 1000) // DIVISOR / 256   # MOUSE_FRAME_MS in ticks
PLANTS = {
    "rest": ("input.c", "    *rest = n - q * elapsed;", "    *rest = 0;"),
    "ticks": ("input.c", "    mouse_ticks = now;\n", ""),
    "guard": ("input.c", "rt_fields - rt_pointer_field <= MOUSE_POINTER_FIELDS", "0"),
    "shown": ("input.c", "rt_pointer.shown || ", ""),
    "stamp": ("pointer.c", "    rt_pointer_field = rt_fields;\n", ""),
    "flag": ("input.c", "if (!rt_mouse_scale ||", "if ("),
}


def planted_elf(name):
    """The host image with one runtime file planted (tmp/mouse-scale-plant/NAME)."""
    file, old, new = PLANTS[name]
    source = (ROOT / "src/runtime" / file).read_text()
    assert source.count(old) == 1, name
    out = ROOT / "tmp/mouse-scale-plant" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / file).write_text(source.replace(old, new))
    stem = Path(file).stem
    tools = Path(os.environ.get("AMIGA_TOOLCHAIN") or Path.home() / ".local/opt") / "bin"
    subprocess.run([str(tools / "m68k-amiga-elf-gcc"), "-m68020", "-O2", "-ffreestanding", "-nostdlib",
                    "-fomit-frame-pointer", "-fno-tree-loop-distribute-patterns", "-Wall", "-Wextra",
                    "-Werror", "-I" + str(ROOT / "src/runtime"), "-DSWOTL_SYNC", "-c",
                    "-o", str(out / (stem + ".o")), str(out / file)], check=True)
    host = ROOT / "build/host"
    objects = [host / n for n in ("host_s.o", "host.o", "rt_entry.o")]
    objects += [out / (stem + ".o") if p.stem == stem else host / (p.stem + ".o")
                for p in sorted((ROOT / "src/runtime").glob("*.c"))]
    objects += [host / n for n in ("program.o", "compute_projection.o", "compute_normalise.o",
                                   "compute_scenery.o", "compute_native.o")]
    subprocess.run([str(tools / "m68k-amiga-elf-ld"), "-Ttext=0x10000", "-e", "_start",
                    "-o", str(out / "swotl.elf"), *map(str, objects)], check=True)
    return out / "swotl.elf"


class Mouse:
    def __init__(self, elf=None):
        self.h = H.Host(H.image.M.REF, elf=elf)
        self.h.e.write(self.h.syms["rt_guest"], H.TOP.to_bytes(4, "big"))
        self.ticks = 0
        self.put("rt_pit_divisor", DIVISOR, 4)
        self.put("rt_fields", 1000, 4)
        self.put("rt_pointer_field", 0, 4)
        self.put("rt_mouse_scale", 1, 1)

    def put(self, name, value, size):
        self.h.e.write(self.h.syms[name], value.to_bytes(size, "big"))

    def call(self, name, *args):
        h, ret = self.h, self.h.syms["plat_exit"]
        stack = struct.pack(">I", ret) + b"".join(struct.pack(">I", a) for a in args)
        h.e.write(H.STACK_TOP - len(stack), stack)
        h.e.reg_write(H.U.M68K["sr"], 0x2700)
        h.e.reg_write(H.U.M68K["a7"], H.STACK_TOP - len(stack))
        h.e.start(h.syms[name], ret, timeout_us=2_000_000)
        assert h.r("pc") == ret, name

    def int33(self, ax, dx=0, dy=0, ticks=0):
        """Advance the game clock, count the motion, call INT 33h; CX, DX."""
        self.ticks += ticks
        self.put("rt_irq0_runs", self.ticks, 4)
        self.h.mouse_dx, self.h.mouse_dy = dx, dy
        self.put("rt_r", ax, 2)
        self.call("rt_int33")
        cx, dxr = struct.unpack(">hh", self.h.e.read(self.h.syms["rt_r"] + 2, 4))
        return cx, dxr

    def frames(self, n, dx, dy, ticks):
        sx = sy = 0
        for _ in range(n):
            x, y = self.int33(0xB, dx, dy, ticks)
            sx += x
            sy += y
        return sx, sy


def cases(m):
    out = []

    def want(name, got, expected):
        if got != expected:
            out.append(f"{name}: {got}, expected {expected}")

    m.int33(0xB, ticks=1)                                  # start the clock
    # A steady speed of 1 count per tick, 840 ticks per run, at three frame rates.
    for ticks in (5, 24, 70):
        n = 840 // ticks
        got = m.frames(n, ticks, -ticks, ticks)
        per = (round(got[0] / n), round(got[1] / n))
        want(f"{ticks} ticks per frame", per, (round(FRAME), round(-2 * FRAME)))
        exact = n * FRAME
        if abs(got[0] - exact) > 1 or abs(got[1] + 2 * exact) > 1:
            out.append(f"{ticks} ticks per frame: sums {got}, expected {exact:.1f}, {-2 * exact:.1f}")
    # Slow motion is carried, not lost: one count every 70-tick frame.
    got = m.frames(60, 1, 0, 70)[0]
    if abs(got - 60 * FRAME / 70) > 1:
        out.append(f"slow motion: {got}, expected {60 * FRAME / 70:.1f}")
    # A reset drops the remainders; a frame with no tick counts as one.
    m.int33(0x0)
    want("no tick", m.int33(0xB, 2, 0, 0)[0], int(2 * FRAME))
    # The pointer shown within 25 fields: motion as counted.
    m.put("rt_pointer_field", 990, 4)
    want("pointer shown", m.int33(0xB, 7, 3, 70), (7, 6))
    # The present that shows a pointer stamps rt_pointer_field.
    m.put("rt_pointer_field", 0, 4)
    m.put("rt_fields", 2000, 4)
    want("pointer stamp", stamped(m), 2000)
    # Still shown at the last present, however long ago (a still menu presents nothing).
    m.put("rt_fields", 9000, 4)
    want("pointer still shown", m.int33(0xB, 7, 3, 5), (7, 6))
    m.h.e.write(m.h.syms["rt_pointer"], b"\0")
    if m.int33(0xB, 7, 3, 5) == (7, 6):
        out.append("pointer gone: not scaled")
    # Off: the reference's motion.
    m.put("rt_pointer_field", 0, 4)
    m.put("rt_mouse_scale", 0, 1)
    want("off", m.int33(0xB, 7, -3, 70), (7, -6))
    return out


def stamped(m):
    """rt_pointer_field after a present with the arrow shown (pointer model's setup)."""
    import test_pointer_model as P
    model = P.Model.__new__(P.Model)
    model.h = m.h
    model.dg = H.image.M.load_modules()["DATA.OVL"]
    model.setup(P.ARROW, 100, 80)
    model.call("rt_pointer_mask", P.FRAME)
    return int.from_bytes(m.h.e.read(m.h.syms["rt_pointer_field"], 4), "big")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sabotage", action="store_true")
    args = ap.parse_args()
    problems = cases(Mouse())
    print("mouse scale:", "ok" if not problems else "; ".join(problems))
    if problems:
        return 1
    if args.sabotage:
        missed = []
        for name in PLANTS:
            planted = cases(Mouse(planted_elf(name)))
            print(f"plant {name}: {planted[0] if planted else 'MISSED'}")
            missed += [] if planted else [name]
        if missed:
            print("FAIL: plants missed:", ", ".join(missed))
            return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
