#!/usr/bin/env python3
"""EGA model for the device-row oracle (docs/ecs-plan.md E6, docs/native-compute.md
"Device rows"): mode 0Eh memory and the registers the EGA driver uses, written
from the IBM EGA technical reference and DOSBox-X's src/hardware/vga_memory.cpp
(the reference), independently of src/runtime/ega.c; tests/test_ega_model.py
runs both on the same operations.

Four 64 KiB planes behind A0000h-AFFFFh, the sequencer's map mask, the graphics
controller's set/reset, enable set/reset, colour compare, data rotate and
function, read map, mode (write modes 0-2, read modes 0-1), colour don't care
and bit mask, four latches loaded by every read. Registers or values outside
the surface (sequencer 2, graphics 4, 5 = 00h-02h, 8) raise OutsideSurface.
`marks` is the D9 bookkeeping as ega.c keeps it: per row of page 0 (80 bytes,
16,000 bytes) the changed byte columns [lo, hi), and the rows [top, bottom).
"""
from __future__ import annotations

BASE, WINDOW, PAGE = 0xA0000, 0x10000, 16000
# struct rt_ega_regs (src/runtime/runtime.h), in order
REGS = ("seq_index", "map_mask", "gc_index", "set_reset", "enable_set_reset", "color_compare",
        "data_rotate", "read_map", "mode", "misc", "color_dont_care", "bit_mask")
REGS_BYTES = len(REGS) + 4 + 16 + 1


class OutsideSurface(ValueError):
    pass


class Ega:
    def __init__(self, planes: bytes | None = None, **regs):
        self.planes = [bytearray(WINDOW) for _ in range(4)] if planes is None else \
            [bytearray(planes[p * WINDOW:(p + 1) * WINDOW]) for p in range(4)]
        self.r = dict.fromkeys(REGS, 0)
        self.r.update(map_mask=0x0F, misc=0x05, color_dont_care=0x0F, bit_mask=0xFF)
        self.latch = [0, 0, 0, 0]
        self.attr = bytes(k if k < 8 else k + 8 for k in range(16))
        self.overscan = 0
        for k, v in regs.items():
            if k == "latch":
                self.latch = list(v)
            else:
                assert k in self.r, k
                self.r[k] = v
        self.rows = [[0, 0] for _ in range(200)]
        self.top, self.bottom = 200, 0

    @classmethod
    def from_snapshot(cls, snap) -> "Ega":
        """A DOSBox-X snapshot (vram.bin: byte a, plane p at a * 4 + p; ega.txt).
The index registers are not recorded: 0 (every converter access writes its index)."""
        vram = (snap / "vram.bin").read_bytes()
        planes = b"".join(vram[p::4][:WINDOW] for p in range(4))
        t = dict(kv.split("=") for kv in (snap / "ega.txt").read_text().split())
        h = lambda k: int(t[k], 16)  # noqa: E731
        e = cls(planes, map_mask=h("seq_map_mask"), set_reset=h("gc_set_reset"),
                enable_set_reset=h("gc_enable_set_reset"), color_compare=h("gc_color_compare"),
                data_rotate=h("gc_data_rotate"), read_map=h("gc_read_map"), mode=h("gc_mode"),
                misc=h("gc_misc"), color_dont_care=h("gc_color_dont_care"), bit_mask=h("gc_bit_mask"),
                latch=bytes.fromhex(t["latch"]))
        e.attr = bytes.fromhex(t["attr_palette"])
        e.overscan = h("attr_overscan")
        return e

    def regs_image(self) -> bytes:
        """struct rt_ega_regs as bytes."""
        return bytes(self.r[k] for k in REGS) + bytes(self.latch) + self.attr + bytes([self.overscan])

    def planes_image(self) -> bytes:
        return b"".join(bytes(p) for p in self.planes)

    # memory
    def read(self, off: int) -> int:
        self.latch = [self.planes[p][off] for p in range(4)]
        if not self.r["mode"] & 8:
            return self.latch[self.r["read_map"] & 3]
        result = 0xFF   # read mode 1: bits where every cared plane matches colour compare
        for p in range(4):
            if self.r["color_dont_care"] >> p & 1:
                want = 0xFF if self.r["color_compare"] >> p & 1 else 0
                result &= ~(self.latch[p] ^ want) & 0xFF
        return result

    def write(self, off: int, value: int) -> None:
        r = self.r
        function, count = r["data_rotate"] >> 3 & 3, r["data_rotate"] & 7
        rotated = (value >> count | value << (8 - count)) & 0xFF
        mask = r["bit_mask"]
        for p in range(4):
            if not r["map_mask"] >> p & 1:
                continue
            latch = self.latch[p]
            mode = r["mode"] & 3
            if mode == 1:
                self.planes[p][off] = latch
                continue
            if mode == 0:
                d = (0xFF if r["set_reset"] >> p & 1 else 0) if r["enable_set_reset"] >> p & 1 else rotated
            else:
                d = 0xFF if value >> p & 1 else 0
            if function == 0:
                v = (d & mask) | (latch & ~mask)
            elif function == 1:
                v = (d | ~mask) & latch
            elif function == 2:
                v = (d & mask) | latch
            else:
                v = (d & mask) ^ latch
            self.planes[p][off] = v & 0xFF
        self.mark(off)

    def mark(self, off: int) -> None:
        if off >= PAGE:
            return
        y, x = divmod(off, 80)
        row = self.rows[y]
        if not row[1]:
            row[:] = [x, x + 1]
        else:
            row[0], row[1] = min(row[0], x), max(row[1], x + 1)
        self.top, self.bottom = min(self.top, y), max(self.bottom, y + 1)

    # ports
    def out(self, port: int, value: int, width: int) -> None:
        lo, hi = value & 0xFF, value >> 8 & 0xFF
        if port in (0x3C4, 0x3CE) and width in (8, 16):
            self.r["seq_index" if port == 0x3C4 else "gc_index"] = lo
            if width == 16:
                self.data(port + 1, hi)
        elif port in (0x3C5, 0x3CF) and width == 8:
            self.data(port, lo)
        else:
            raise OutsideSurface(f"port {port:x}/{width}")

    def data(self, port: int, v: int) -> None:
        r = self.r
        if port == 0x3C5:
            if r["seq_index"] != 2 or v & 0xF0:
                raise OutsideSurface(f"sequencer {r['seq_index']}={v:x}")
            r["map_mask"] = v
        elif r["gc_index"] == 4 and v <= 3:
            r["read_map"] = v
        elif r["gc_index"] == 5 and v <= 2:
            r["mode"] = v
        elif r["gc_index"] == 8:
            r["bit_mask"] = v
        else:
            raise OutsideSurface(f"graphics {r['gc_index']}={v:x}")
