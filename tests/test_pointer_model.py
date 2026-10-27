#!/usr/bin/env python3
"""Pointer mask and visibility (docs/pointer-plan.md P3), src/runtime/pointer.c in
the host image: rt_pointer_mask on guest pointer states built in DGROUP and VGA
memory as the guest's show leaves them, each against the expected result, and
rt_pointer_visible on field sequences. The reference fixtures never show the
crosshair (FRONTEND+06E31 unexecuted); the fixtures' presents are checked by
tests/host_run.py.

  python3 tests/test_pointer_model.py [--sabotage]

Cases: arrow at rest; crosshair (hotspot -3, -3); crosshair clipped at the top
left; one opaque pixel overwritten; a second colour besides FEh; drawn wholly
off screen; no DGROUP yet; no sprite platform. Visibility: a state applies once
it holds at two blanks in a row. Plants (pointer.c rebuilt):

  hotspot     the hotspot subtracted
  equality    a pixel that differs from the shape still counts
  visibility  a state applies at its first blank
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

DS = 0x43CD
ARROW = (6, 7, 0, 0, 0x0600)
CROSS = (7, 7, -3, -3, 0x062A)
FRAME = 0x900000
PLANTS = {
    "hotspot": ("word(POINTER_X) + word(POINTER_HOT_X)", "word(POINTER_X) - word(POINTER_HOT_X)"),
    "equality": ("!= p) {\n                return;", "!= p && 0) {\n                return;"),
    "visibility": ("        held = 0;\n", "        held = 1;\n"),
}


def planted_elf(name):
    """The host image with pointer.c planted (tmp/pointer-plant/NAME)."""
    old, new = PLANTS[name]
    source = (ROOT / "src/runtime/pointer.c").read_text()
    assert source.count(old) == 1, name
    out = ROOT / "tmp/pointer-plant" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "pointer.c").write_text(source.replace(old, new))
    tools = Path(os.environ.get("AMIGA_TOOLCHAIN") or Path.home() / ".local/opt") / "bin"
    subprocess.run([str(tools / "m68k-amiga-elf-gcc"), "-m68020", "-O2", "-ffreestanding", "-nostdlib",
                    "-fomit-frame-pointer", "-fno-tree-loop-distribute-patterns", "-Wall", "-Wextra",
                    "-Werror", "-I" + str(ROOT / "src/runtime"), "-DSWOTL_SYNC", "-c",
                    "-o", str(out / "pointer.o"), str(out / "pointer.c")], check=True)
    host = ROOT / "build/host"
    objects = [host / n for n in ("host_s.o", "host.o", "rt_entry.o")]
    objects += [out / "pointer.o" if p.stem == "pointer" else host / (p.stem + ".o")
                for p in sorted((ROOT / "src/runtime").glob("*.c"))]
    objects += [host / n for n in ("program.o", "compute_projection.o", "compute_normalise.o",
                                   "compute_scenery.o", "compute_native.o")]
    subprocess.run([str(tools / "m68k-amiga-elf-ld"), "-Ttext=0x10000", "-e", "_start",
                    "-o", str(out / "swotl.elf"), *map(str, objects)], check=True)
    return out / "swotl.elf"


class Model:
    def __init__(self, elf=None):
        self.h = H.Host(H.image.M.REF, elf=elf)
        self.h.e.write(self.h.syms["rt_guest"], H.TOP.to_bytes(4, "big"))
        self.dg = H.image.M.load_modules()["DATA.OVL"]

    def gw(self, a, data):
        self.h.e.write(H.TOP - a - len(data) + 1, bytes(data)[::-1])

    def call(self, name, *args):
        h, ret = self.h, self.h.syms["plat_exit"]
        stack = struct.pack(">I", ret) + b"".join(struct.pack(">I", a) for a in args)
        h.e.write(H.STACK_TOP - len(stack), stack)
        h.e.reg_write(H.U.M68K["sr"], 0x2700)
        h.e.reg_write(H.U.M68K["a7"], H.STACK_TOP - len(stack))
        h.e.start(h.syms[name], ret, timeout_us=2_000_000)
        assert h.r("pc") == ret, name
        return h.r("d0")

    def setup(self, shape, x, y, *, ds=DS, sprite=1, image=None, edit=None):
        """DGROUP from DATA.OVL, the shape selected, the screen a gradient, the
        guest's show at (x, y): the screen under the shape saved, then drawn."""
        h = self.h
        data = self.dg.data[self.dg.code_start + 0x580:]
        w, hh, hx, hy, img = shape
        self.gw(DS * 16, data)
        pixels = bytearray(image if image is not None else data[img:img + w * hh])
        self.gw(DS * 16 + 0xF000, pixels)
        words = {"x": x, "y": y, "width": w, "height": hh, "hot_x": hx, "hot_y": hy, "image": 0xF000}
        for name, v in words.items():
            self.gw(DS * 16 + H.POINTER[name], struct.pack("<H", v & 0xFFFF))
        screen = bytearray((k * 7 + k // 320) % 200 for k in range(64000))
        x0, y0 = x + hx, y + hy
        saved = bytearray(w * hh)
        for r in range(hh):
            for c in range(w):
                o = (y0 + r) * 320 + x0 + c
                saved[r * w + c] = screen[o] if 0 <= o < 64000 else 0x55
        for r in range(hh):
            for c in range(w):
                p = pixels[r * w + c]
                if p != 0xFD and 0 <= x0 + c < 320 and 0 <= y0 + r < 200:
                    screen[(y0 + r) * 320 + x0 + c] = p
        if edit:
            edit(screen)
        self.gw(DS * 16 + H.POINTER["buffer"], saved)
        self.gw(0xA0000, screen)
        h.e.write(FRAME, bytes(screen))
        h.e.write(h.syms["rt_pointer_ds"], struct.pack(">H", ds))
        h.e.write(h.syms["rt_pointer_sprite"], bytes([sprite]))
        h.e.write(h.syms["rt_pointer"], b"\0" * H.POINTER_BYTES)
        return screen, saved

    def mask(self):
        self.call("rt_pointer_mask", FRAME)
        got = self.h.mem(self.h.syms["rt_pointer"], H.POINTER_BYTES)
        return got, self.h.mem(FRAME, 64000)


def expect_shown(m, shape, x, y, other, box):
    screen, saved = m.setup(shape, x, y)
    got, frame = m.mask()
    w, hh, hx, hy, _ = shape
    problems = []
    if got[0] != 1:
        return ["not shown"]
    fields = struct.unpack(">hh", got[4:8]) + (got[1], got[2], got[3])
    if fields != (x + hx, y + hy, w, hh, other):
        problems.append(f"x, y, w, h, other {fields}")
    if struct.unpack(">4H", got[10:18]) != box:
        problems.append(f"masked box {struct.unpack('>4H', got[10:18])}, expected {box}")
    want = bytearray(screen)
    pixels = got[H.POINTER_PIXELS:]
    composite = bytearray(frame)
    for r in range(hh):
        for c in range(w):
            sx, sy = x + hx + c, y + hy + r
            p = pixels[r * H.POINTER_SIZE + c]
            if p != 0xFD and 0 <= sx < 320 and 0 <= sy < 200:
                want[sy * 320 + sx] = saved[r * w + c]
                composite[sy * 320 + sx] = p
    if frame != bytes(want):
        problems.append("frame is not VGA memory with the save buffer under the pointer")
    if bytes(composite) != bytes(screen):
        problems.append("frame + sprite is not VGA memory")
    return problems


def expect_hidden(m, shape, x, y, **kw):
    screen, _ = m.setup(shape, x, y, **kw)
    got, frame = m.mask()
    problems = [] if got[0] == 0 else ["shown"]
    return problems + ([] if frame == bytes(screen) else ["frame changed"])


def cases(m):
    out = {}
    out["arrow"] = expect_shown(m, ARROW, 100, 50, 0x00, (100, 50, 106, 57))
    out["crosshair"] = expect_shown(m, CROSS, 100, 50, 0xF0, (97, 47, 104, 54))
    out["clipped"] = expect_shown(m, CROSS, 1, 1, 0xF0, (0, 0, 5, 5))

    def overwrite(screen):
        screen[50 * 320 + 100] ^= 1
    out["overwritten"] = expect_hidden(m, ARROW, 100, 50, edit=overwrite)
    data = m.dg.data[m.dg.code_start + 0x580:]
    second = bytearray(data[0x600:0x600 + 42])
    second[0] = 0xFF
    out["two colours"] = expect_hidden(m, ARROW, 100, 50, image=second)
    out["off screen"] = expect_hidden(m, ARROW, 330, 50)
    out["no DGROUP"] = expect_hidden(m, ARROW, 100, 50, ds=0)
    out["no sprites"] = expect_hidden(m, ARROW, 100, 50, sprite=0)
    seq, want = [1, 1, 0, 1, 1, 0, 0, 0, 1, 0, 1, 1], [0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1]
    got = [m.call("rt_pointer_visible", s) & 0xFF for s in seq]
    out["visibility"] = [] if got == want else [f"visible {got}, expected {want}"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sabotage", action="store_true")
    args = ap.parse_args()
    results = cases(Model())
    for name, problems in results.items():
        print(f"{name}: {'ok' if not problems else '; '.join(problems)}")
    if any(results.values()):
        return 1
    if args.sabotage:
        missed = []
        for name in PLANTS:
            planted = cases(Model(planted_elf(name)))
            failed = [k for k, v in planted.items() if v]
            print(f"plant {name}: {', '.join(failed) if failed else 'MISSED'}")
            missed += [] if failed else [name]
        if missed:
            print("FAIL: plants missed:", ", ".join(missed))
            return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
