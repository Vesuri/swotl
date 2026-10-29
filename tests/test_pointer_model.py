#!/usr/bin/env python3
"""Pointer mask and visibility (docs/pointer-plan.md P3), src/runtime/pointer.c in
the host image: rt_pointer_mask on guest pointer states built in DGROUP and VGA
memory as the guest's show leaves them, each against the expected result, and
rt_pointer_visible on field sequences. The reference fixtures never show the
crosshair (FRONTEND+06E31 unexecuted); the fixtures' presents are checked by
tests/host_run.py.

  python3 tests/test_pointer_model.py [--sabotage]

Lead: the position at the tracker's exit advanced by the guest's rule (clamp
+-BFh/+-7Fh, halve toward zero unless 0, hold in [min, end)) by an unapplied
read, then by the motion not read yet (runtime and platform counts, vertical
counts doubled as DOSBox-X or 1:1); two reads
before an exit discard the lead; the prediction at an exit; a write open at
the blank keeps the last result; a pointer shown away from the last exit
(set directly) is the lead's new start, its pending read dropped; a move
presented before the tracker's exit is predicted there. Cases: arrow at rest; crosshair (hotspot -3, -3); crosshair clipped at the top
left; one opaque pixel overwritten; a second colour besides FEh; drawn wholly
off screen; no DGROUP yet; no sprite platform. Visibility: a state applies once
it holds at two blanks in a row. Plants (pointer.c rebuilt):

  hotspot     the hotspot subtracted
  equality    a pixel that differs from the shape still counts
  visibility  a state applies at its first blank
  clamp       x motion clamped to +-C0h
  trunc       halved by an arithmetic shift (floor)
  bound       x held below x_end instead of x_end - 1
  discard     a second read keeps the lead
  serial      the lead computed while a write is open
  ratio       the platform's vertical counts doubled whatever rt_mickeys_y
  adopt       a shown pointer away from the last exit not adopted
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
    # lead plants (also tests/host_run.py sabotage pointer-*)
    "clamp": ("#define POINTER_X_LIMIT 0xbf", "#define POINTER_X_LIMIT 0xc0"),
    "trunc": ("        m = (int16_t)(m / 2);", "        m = (int16_t)(m >> 1);"),
    "bound": ("v >= hi ? (int16_t)(hi - 1)", "v >= hi ? hi"),
    "discard": ("        if (reads < 2) {", "        if (reads < 3) {"),
    "serial": ("if (!(serial & 1) && lead.tracked)", "if (lead.tracked)"),
    "ratio": ("rt_mickey_y + rt_mickeys_y * dy", "rt_mickey_y + 2 * dy"),
    "adopt": ("    if (lead.x != x || lead.y != y) {\n        consume", "    if (0 && (lead.x != x || lead.y != y)) {\n        consume"),
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
    fields = struct.unpack(">hh", got[4:8]) + (got[1], got[2], got[3]) + struct.unpack("bb", got[274:276])
    if fields != (x + hx, y + hy, w, hh, other, hx, hy):
        problems.append(f"x, y, w, h, other, hotspot {fields}")
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


def rule(p, m, limit, lo, end):
    m = -limit if m <= -limit - 1 else limit if m >= limit + 1 else m
    h = int(m / 2)
    m = h if h else m
    v = p + m
    return end - 1 if v >= end else lo if v < lo else v


def lead_cases(m):
    """(name, reads, runtime mickeys, platform counts, start, bounds) against rule()."""
    out = {}
    h = m.h
    m.setup(ARROW, 100, 50)
    bounds = (8, 312, 4, 196)
    cases = [("rest", [], (0, 0), (0, 0), (100, 50)),
             ("read", [(8, 4)], (0, 0), (0, 0), (100, 50)),
             ("pending", [], (6, 2), (3, 5), (100, 50)),
             ("read and pending", [(-8, 6)], (6, -2), (1, 1), (100, 50)),
             ("clamp", [(-400, 300)], (0, 0), (0, 0), (160, 100)),
             ("trunc", [(-9, -7)], (1, -1), (0, 0), (100, 50)),
             ("bound high", [(40, 30)], (0, 0), (0, 0), (300, 190)),
             ("bound low", [(-40, -30)], (0, 0), (0, 0), (12, 6)),
             ("discard", [(8, 4), (6, 2)], (5, 5), (2, 2), (100, 50))]
    for ratio, name, reads, mickeys, counts, start in [(r, *c) for r in (2, 1) for c in cases]:
        h.e.write(h.syms["rt_mickeys_y"], bytes([ratio]))
        for n, v in zip(("x_min", "x_end", "y_min", "y_end"), bounds):
            m.gw(DS * 16 + H.POINTER[n], struct.pack("<H", v))
        m.gw(DS * 16 + H.POINTER["x"], struct.pack("<H", start[0]))
        m.gw(DS * 16 + H.POINTER["y"], struct.pack("<H", start[1]))
        m.call("rt_pointer_tracked")
        for mx, my in reads:
            m.call("rt_pointer_read", mx & 0xFFFFFFFF, my & 0xFFFFFFFF)
        h.e.write(h.syms["rt_mickey_x"], struct.pack(">h", mickeys[0]))
        h.e.write(h.syms["rt_mickey_y"], struct.pack(">h", mickeys[1]))
        m.call("rt_pointer_lead", counts[0] & 0xFFFFFFFF, counts[1] & 0xFFFFFFFF, FRAME, FRAME + 2)
        got = struct.unpack(">hh", h.mem(FRAME, 4))
        x, y = start
        if len(reads) < 2:
            if reads:
                x = rule(x, reads[0][0], 0xBF, bounds[0], bounds[1])
                y = rule(y, reads[0][1], 0x7F, bounds[2], bounds[3])
            x = rule(x, mickeys[0] + counts[0], 0xBF, bounds[0], bounds[1])
            y = rule(y, mickeys[1] + ratio * counts[1], 0x7F, bounds[2], bounds[3])
        problems = [] if got == (x, y) else [f"lead {got}, expected {(x, y)}"]
        if len(reads) == 1:     # the exit after the read: the prediction
            px = rule(start[0], reads[0][0], 0xBF, bounds[0], bounds[1])
            py = rule(start[1], reads[0][1], 0x7F, bounds[2], bounds[3])
            m.call("rt_pointer_tracked")
            pred = struct.unpack(">3h", h.mem(h.syms["rt_pointer_predicted"], 6))
            if pred != (1, px, py):
                problems.append(f"prediction {pred}, expected {(1, px, py)}")
        h.e.write(h.syms["rt_mickey_x"], b"\0\0")
        h.e.write(h.syms["rt_mickey_y"], b"\0\0")
        out[f"lead {name}" + ("" if ratio == 2 else " 1:1")] = problems
    h.e.write(h.syms["rt_mickeys_y"], b"\2")
    # A write open at the blank (INT 33h between rt_pointer_open and close): the
    # last result, not the half-written state.
    m.call("rt_pointer_tracked")
    m.call("rt_pointer_lead", 0, 0, FRAME, FRAME + 2)
    before = struct.unpack(">hh", h.mem(FRAME, 4))
    m.call("rt_pointer_open")
    h.e.write(h.syms["rt_mickey_x"], struct.pack(">h", 20))
    m.call("rt_pointer_lead", 0, 0, FRAME, FRAME + 2)
    got = struct.unpack(">hh", h.mem(FRAME, 4))
    m.call("rt_pointer_close")
    h.e.write(h.syms["rt_mickey_x"], b"\0\0")
    out["lead open write"] = [] if got == before else [f"lead {got} during a write, expected {before}"]
    # Set directly (0C64) after an exit and a read: shown there, the lead starts there.
    def bounded(x, y):
        m.setup(ARROW, x, y)
        for n, v in zip(("x_min", "x_end", "y_min", "y_end"), bounds):
            m.gw(DS * 16 + H.POINTER[n], struct.pack("<H", v))
    bounded(100, 50)
    m.call("rt_pointer_tracked")
    m.call("rt_pointer_read", 8, 4)
    bounded(120, 60)
    m.mask()
    m.call("rt_pointer_lead", 0, 0, FRAME, FRAME + 2)
    got = struct.unpack(">hh", h.mem(FRAME, 4))
    out["lead adopt"] = [] if got == (120, 60) else [f"lead {got} after a direct set, expected (120, 60)"]
    # The tracker's move presented before its exit: predicted at the present,
    # kept at the exit.
    bounded(100, 50)
    m.call("rt_pointer_tracked")
    m.call("rt_pointer_read", 8, 4)
    want = (1, rule(100, 8, 0xBF, bounds[0], bounds[1]), rule(50, 4, 0x7F, bounds[2], bounds[3]))
    bounded(want[1], want[2])
    m.mask()
    m.call("rt_pointer_tracked")
    pred = struct.unpack(">3h", h.mem(h.syms["rt_pointer_predicted"], 6))
    out["lead adopt predicted"] = [] if pred == want else [f"prediction {pred}, expected {want}"]
    return out


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
    out.update(lead_cases(m))
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
