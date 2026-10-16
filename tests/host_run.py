#!/usr/bin/env python3
"""Run the generated program with the runtime on Unicorn 68020 (phase 5.1):
build/host/swotl.elf from the SWOTL.EXE entry to a reference milestone, data
files read from ref/ (read-only).

Checked against the DOSBox-X reference run of that milestone
(tmp/pc-runs/ref-<milestone>, `make reference`):
- service log: every software INT the guest raises, in order, with the
  registers at entry and at return (the tracer's svc/svc_ret events);
- at the milestone label: guest registers and guest RAM (COMPARE ranges);
  dead stack is masked: bytes in the DEAD_STACK window below SS:SP at a
  service call or hardware interrupt that the guest did not write afterwards (DOSBox-X's own code
  and the interrupt frame's FLAGS word leave other values there, open-work 24),
  and the FLAGS images of annotations/flags.csv PUSHFs until rewritten;
- every machine byte outside COMPARE that generated code read holds the
  reference value.
With --amiga DIR, the same checks run on the A1200 model's capture
(amiga/milestone.gdb.in: regs.txt, state.bin, ram.bin, dac.bin), masked by
this host run's dead-stack set, and the shown frame (plane0-7.bin, bytes per
row in regs.txt, colours.bin = LoadRGB32 table) decodes to the reference
framebuffer and DAC. --label prints a milestone's label for the fixture.
Exit 1 on any difference, a runtime stop or the time limit.
"""

from __future__ import annotations

import json
import argparse
import csv
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uc as U  # noqa: E402
from translator import emit, image  # noqa: E402

REPO = image.REPO
ELF = REPO / "build/host/swotl.elf"
MEM = 0x01000000          # flat map: code, data, stack, guest RAM
STACK_TOP = 0x00FF0000
BLOCK = 0x00400000        # src/platform/host/host.c HOST_BLOCK
GUEST_BYTES = 0x110000
SFX_SLOT_IDS = 0x1DE   # SPAZ DS: per OPL channel the effect id·4 (stored at hle.csv sfx_start)
TOP = BLOCK + GUEST_BYTES - 1   # rt_guest: guest linear L at TOP - L (reversed)
STATE = TOP + 1           # state block (translator/lower.py STATE_EQU)
G_IRQ = TOP + 9
# Key names of the reference key script (tracer KeyByName): scan << 8 | ASCII
# as the BIOS INT 09h handler stores them.
KEYS = {"enter": 0x1C0D, "esc": 0x011B, "space": 0x3920, "tab": 0x0F09, "backspace": 0x0E08,
        "up": 0x4800, "down": 0x5000, "left": 0x4B00, "right": 0x4D00,
        **{f"f{k}": (0x3A + k) << 8 for k in range(1, 11)},
        **{c: s << 8 | ord(c) for c, s in zip("qwertyuiopasdfghjklzxcvbnm",
                                             list(range(0x10, 0x1A)) + list(range(0x1E, 0x27))
                                             + list(range(0x2C, 0x33)))},
        **{str(k): (k + 1) << 8 | ord(str(k)) for k in range(1, 10)}, "0": 0x0B30}
GREY = {KEYS[k] for k in ("up", "down", "left", "right")}  # E0-prefixed (DOSBox KBD_up..)
# Modifier bits belong to scripted input, above the base BIOS key word.
KEY_MODIFIERS = {"shift": 1 << 16, "ctrl": 1 << 17, "alt": 1 << 18}


def key_code(name: str) -> int:
    parts = name.split("+")
    modifiers = 0
    for part in parts[:-1]:
        bit = KEY_MODIFIERS.get(part, 0)
        if not bit or modifiers & bit:
            raise ValueError(f"invalid key chord: {name}")
        modifiers |= bit
    if parts[-1] not in KEYS:
        raise ValueError(f"unknown key: {name}")
    return modifiers | KEYS[parts[-1]]


def key_events(key: int) -> tuple[int, ...]:
    if key & ~0x7ffff:
        raise ValueError(f"invalid scripted key: {key:x}")
    base = key & 0xffff
    scan = base >> 8
    modifiers = tuple(scan for bit, scan in ((1 << 16, 0x2a),
                      (1 << 17, 0x1d), (1 << 18, 0x38)) if key & bit)
    body = (0xe0, scan, 0xe0, scan | 0x80) if base in GREY else (scan, scan | 0x80)
    return modifiers + body + tuple(scan | 0x80 for scan in reversed(modifiers))


KEY_HOLD = 600_000  # tracer: x86 instructions from key down to key up
# Compared guest RAM: the DOS arena from the environment MCB to the top of
# conventional memory; below it are IVT/BIOS/DOS internals the runtime models
# only through services, above it video and BIOS ROM.
COMPARE = [(0x07C90, 0xA0000)]
# Chained mode 13h: guest A0000h+a is DOSBox-X vram[((a & ~3) << 2) | (a & 3)]
# (tools/snap_png.py); the whole 64 KiB window is compared with the DAC.
FRAME = (0xA0000, 0xB0000)
REGS = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
DEAD_STACK = 0x60
TABLE = REPO / "reference/milestones.csv"  # --table: another table in that format
POLLS = REPO / "build/gen/poll-points.csv"
# SPAZ's data segment (DS 188Ah, `mov dx` at SPAZ+3DF; CS 1770h is SPAZ+240h):
# from this module offset to the end of SPAZ's block. With --music-skip it holds
# the song and effect state the skip changes, so it is not compared.
SPAZ_DATA = 0x13E0
# Also SPAZ's state in the game's data: per-effect counts at DS:6564+id (inc
# on start SPAZ+64E, dec on end +65E; id 35 the music slot), and the dead stack
# below SS:SP at the label: the effects the reference ignored during the music
# now play and run deeper calls.
SPAZ_COUNTS = (0x6564, 40)
SKIP_DEAD_STACK = 0x800


def elf_load(path: Path, function_extents: dict | None = None):
    d = path.read_bytes()
    entry, phoff, shoff = struct.unpack_from(">III", d, 0x18)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from(">HHHHH", d, 0x2A)
    segs = []
    for k in range(phnum):
        typ, off, vaddr, _, filesz, memsz = struct.unpack_from(">IIIIII", d, phoff + k * phentsize)
        if typ == 1:
            segs.append((vaddr, d[off:off + filesz], memsz))
    secs = [struct.unpack_from(">IIIIIIIIII", d, shoff + k * shentsize) for k in range(shnum)]
    syms = {}
    for s in secs:
        if s[1] != 2:  # SHT_SYMTAB
            continue
        strtab = secs[s[6]]
        for k in range(s[5] // 16):
            name, value, size, info, _, shndx = struct.unpack_from(">IIIBBH", d, s[4] + k * 16)
            if name and shndx:
                a = strtab[4] + name
                symbol = d[a:d.index(b"\0", a)].decode()
                syms[symbol] = value
                if function_extents is not None and info & 15 == 2 and size:
                    function_extents[symbol] = (value, value + size)
    return entry, segs, syms


def reference_services(trace: Path) -> list[tuple[str, dict]]:
    out = []
    with (trace / "events.csv").open() as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                vec, *kv = r["detail"].split()
                regs = {k: int(v, 16) for k, v in (x.split("=") for x in kv)}
                regs["vector"] = int(vec, 16)
                out.append((r["kind"], regs))
    return out


def reference_inputs(trace: Path, *, exact_releases: bool = False) -> tuple[list, list]:
    """The reference's hardware interrupts as (service events so far, poll
    point label, its executions since the last service event, vector), and
    the service-event count at each key release. Exact releases additionally
    retain recorded ineligible visits to the next trigger in that interval.
    The default preserves the existing diagnostic Amiga replay input format."""
    irqs, releases, n = [], [], 0
    with (trace / "events.csv").open() as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                n += 1
            elif r["kind"] == "irq":
                vec, svc, hits = r["detail"].split()
                assert int(svc[4:]) == n, r
                irqs.append((n, emit.label(r["module"], int(r["offset"], 16)),
                             int(hits[5:]), int(vec, 16)))
            elif r["kind"] == "key_up":
                fields = r["detail"].split()
                release = n
                if exact_releases and len(fields) > 1:
                    if len(fields) != 2 or not fields[1].startswith("skip="):
                        raise ValueError(f"invalid key release: {r}")
                    skipped = int(fields[1][5:])
                    if skipped < 0:
                        raise ValueError(f"negative key release visits: {r}")
                    release = (n, skipped)
                releases.append(release)
    return irqs, releases


class KeyRelease:
    """Count trigger visits while held; IRQ replay remains independent.

    The recorder resets this count on key-down and each service event. For
    a snapshot, the release instruction itself is ineligible; for another
    key it is eligible. The recorded skip count already includes that order.
    Old captures retain their service-only behavior.
    """

    def __init__(self, release):
        self.service, self.skip = (release, None) if isinstance(release, int) else release
        self.interval, self.visits = None, 0

    def ready(self, service: int, target: bool) -> bool:
        if service != self.interval:
            self.interval, self.visits = service, 0
        if target:
            self.visits += 1
        if service != self.service:
            return service > self.service
        return self.skip is None or (target and self.visits > self.skip)


def fnv(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


SABOTAGE = {
    "mouse-motion": "scripted vertical mouse motion lost",
    "mouse-buttons": "scripted middle mouse button lost",
    "read": "first byte of each guest file read flipped",
    "ax": "AX of the tenth service result off by one",
    "psp": "one command-tail byte of the PSP changed at the guest entry",
    "dac": "one DAC gun off at each DAC change",
    "vram": "graphics driver stores to video memory not marked (rt_vram_mark returns at once)",
    "far": "every dispatch row near-only (rt_dispatch_far must stop, R14e)",
    "sp": "rt_irq delivers with the guest SP from before the frame (its SP reload dropped)",
    "keyon": "rt_out8 counts no AdLib key-on edge (its addq dropped)",
    "sfx_start": "rt_hle_sfx_start records no effect id (its move.b dropped)",
}
# Plants a milestone other than --milestone exercises (the guest's first
# hardware interrupt handler runs after m1b-logo).
SABOTAGE_AT = {"sp": "m2-choose-side", "keyon": "m2-choose-side", "sfx_start": "c6-flight-keys",
               "mouse-motion": "c9-mouse-menu",
               "mouse-buttons": "c9-mouse-menu"}


def dos_file_stamp(stamp):
    t = time.localtime(stamp)
    return ((t.tm_hour & 31) << 11 | (t.tm_min & 63) << 5 | (t.tm_sec // 2 & 31),
            ((t.tm_year - 1980) & 127) << 9 | (t.tm_mon & 63) << 5 | (t.tm_mday & 31))


class MemFile:
    """An open file the guest writes: kept in memory, never on disk."""

    def __init__(self, data: bytearray):
        self.data, self.pos = data, 0
        self.modified = False
        self.dos_stamp = None

    def read(self, n: int) -> bytes:
        out = bytes(self.data[self.pos:self.pos + n])
        self.pos += len(out)
        return out

    def write(self, b: bytes) -> int:
        self.modified = True
        if not b:  # DOS write of 0 bytes: truncate here
            del self.data[self.pos:]
            return 0
        if self.pos > len(self.data):
            self.data.extend(bytes(self.pos - len(self.data)))
        self.data[self.pos:self.pos + len(b)] = b
        self.pos += len(b)
        return len(b)

    def seek(self, off: int, whence: int) -> int:
        self.pos = max(0, (0, self.pos, len(self.data))[whence] + off)
        return self.pos

    def close(self) -> None:
        pass


class Host:
    def __init__(self, ref_root: Path, sabotage: str | None = None, music_skip: bool = False):
        self.root = ref_root
        self.file_clock = None
        self.calendar_date = None
        self.sabotage = sabotage
        functions = {}
        entry, segs, self.syms = elf_load(ELF, functions)
        self.frame_writer = functions["push_frame"]
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(0, MEM)
        for vaddr, data, memsz in segs:
            e.write(vaddr, data + bytes(memsz - len(data)))
        self.entry = entry
        self.files: dict[int, object] = {}
        self.allocations = {}
        self.free_spans = [(0x900000, 0x500000)]
        self.next_file = 1
        self.written: dict[str, bytearray] = {}  # files the guest wrote (game path -> bytes)
        self.file_stamps: dict[str, tuple[int, int]] = {}
        self.deleted: set[str] = set()
        self.log: list[str] = []
        self.exit: int | None = None
        self.services: list[tuple[str, dict]] = []
        self.stopped_at: str | None = None
        self.stubs = {self.syms[n]: n for n in ("plat_alloc", "plat_free", "plat_open", "plat_create", "plat_read", "plat_write",
                                                "plat_delete", "plat_seek",
                                                "plat_calendar_date", "plat_file_stamp", "plat_close", "plat_dir_entry", "plat_timer_rate", "plat_mouse", "plat_present", "plat_palette",
                                                "plat_service", "plat_log", "plat_exit")}
        self.mouse_dx = self.mouse_dy = self.mouse_buttons = 0
        self.presents = 0
        # D9 display: every byte the guest stores to the frame is inside the
        # rectangles of the next present (the runtime's marks vs the stores)
        self.vram_written: set[int] = set()
        self.display_miss: str | None = None
        e.write(self.syms["rt_present_due"], b"\1")  # a vertical blank is always due
        # HLE music_skip: off (the guest path, which the references hold) unless
        # --music-skip checks the replacement
        e.write(self.syms["rt_music_skip"], bytes([music_skip]))
        self.sound_log = None
        self.sound_tick = 0
        self.music_skip = music_skip
        self.skips = self.moved = 0
        self.skipped_ran: set[str] = set()
        self.music_masked: set[int] = set()
        if sabotage == "vram":
            e.write(self.syms["rt_vram_mark"], b"\x4e\x75")  # rts
        if sabotage == "sp":    # eori.w #$7fff,d4 after rt_irq_c -> nop; nop
            a = self.syms["rt_irq"]
            code = e.read(a, self.syms["rt_irq_back"] - a)
            k = code.index(bytes.fromhex("0a447fff"))
            e.write(a + k - 6, bytes.fromhex("4e71") * 5)     # move.w rt_r+8,d4 too
        if sabotage == "keyon":  # addq.b #1,(a0,d7.w) -> nop; nop
            a = self.syms["rt_out8"]
            code = e.read(a, 0x60)
            e.write(a + code.index(bytes.fromhex("52307000")), bytes.fromhex("4e714e71"))
        if sabotage == "sfx_start":  # move.b d6,(a0,d7.w) -> nop; nop
            a = self.syms["rt_hle_sfx_start"]
            code = e.read(a, 0x20)
            e.write(a + code.index(bytes.fromhex("11867000")), bytes.fromhex("4e714e71"))
        if sabotage == "far":
            rows = int.from_bytes(e.read(self.syms["dispatch_count"], 4), "big")
            for k in range(rows):
                e.write(self.syms["dispatch_table"] + 12 * k + 6, b"\0\0")

        @U.MEM_CB
        def vram(h, kind, addr, size, value, user):  # the frame exists in mode 13h only
            if self.gmem(0x449, 1)[0] == 0x13:
                off = TOP - addr - size + 1 - 0xA0000
                self.vram_written.update(range(max(off, 0), min(off + size, 64000)))
            return True

        e.hook_range(U.HOOK_MEM_WRITE, vram, TOP - 0xA0000 - 63999, TOP - 0xA0000)

        @U.CODE_CB
        def stub(h, addr, size, user):
            n = self.stubs.get(addr)
            if n:
                self.platform(n)

        e.hook_range(U.HOOK_CODE, stub, self.syms["host_stubs"], self.syms["host_stubs_end"])

        # a service returns when the runtime glue's rts goes back to the
        # address after its jsr rt_int (static hooks: Unicorn retranslates
        # on every hook change)
        @U.CODE_CB
        def ret_hit(h, addr, size, user):
            if self.pending and self.u32(self.r("a7")) == self.pending[-1]:
                self.pending.pop()
                if self.sabotage == "ax" and len(self.services) == 19:
                    self.e.reg_write(U.M68K["d0"], (self.r("d0") + 1) & 0xFFFF)
                self.services.append(("svc_ret", self.guest_regs(self.pending_vec.pop())))
                self.in_service = bool(self.pending)

        for n in ("rt_exit", "rt_exit_guest"):
            e.hook_range(U.HOOK_CODE, ret_hit, self.syms[n], self.syms[n])
        self.pending: list = []
        self.pending_vec: list = []

        @U.CODE_CB
        def int_entry(h, addr, size, user):
            d6 = self.r("d6")
            regs = self.guest_regs(d6 & 0xFF)
            self.services.append(("svc", regs))
            self.in_service = True
            top = regs["ss"] * 16 + regs["sp"]
            self.masked.update(range(top - DEAD_STACK, top))
            self.pending.append(self.u32(self.r("a7")))
            self.pending_vec.append(d6 & 0xFF)

        a = self.syms["rt_int"]
        e.hook_range(U.HOOK_CODE, int_entry, a, a)

        # AdLib writes as the guest makes them (check_opl)
        self.opl: list[tuple[int, int]] = []
        self.opl_ports: list[tuple[int, int]] = []

        @U.CODE_CB
        def out8(h, addr, size, user):
            port, v = self.r("d7") & 0xFFFF, self.r("d6") & 0xFF
            if port in (0x388, 0x389):
                self.opl_ports.append((port, v))
            if port == 0x389:
                reg = self.mem(self.syms["rt_opl_index"], 1)[0]
                self.opl.append((reg, v))
                self.sound_event("o", reg, v)

        a = self.syms["rt_out8"]
        e.hook_range(U.HOOK_CODE, out8, a, a)

        # HLE sfx_start (check_sfx): after the guest's store of DI at the
        # hooked instruction, the runtime's report holds the same slot and id.
        self.sfx_starts = [0, 0, 0]
        self.sfx_bad: list[str] = []

        @U.CODE_CB
        def sfx_stored(h, addr, size, user):
            g = self.guest_regs(0)
            slot, rest = divmod(g["bx"], 6)
            stored = int.from_bytes(self.gmem(g["ds"] * 16 + ((SFX_SLOT_IDS + g["bx"]) & 0xFFFF), 2),
                                    "little")
            if rest or slot > 2 or stored != g["di"]:
                self.sfx_bad.append(f"BX {g['bx']:04x}, DI {g['di']:04x}, stored {stored:04x}")
                return
            self.sound_event("s", slot, g["di"] >> 2)
            self.sfx_starts[slot] = (self.sfx_starts[slot] + 1) & 0xFF
            got = (self.mem(self.syms["rt_sfx_id"], 3)[slot], self.mem(self.syms["rt_sfx_starts"], 3)[slot])
            if got != (g["di"] >> 2, self.sfx_starts[slot]):
                self.sfx_bad.append(f"slot {slot}: id {got[0]} start {got[1]}, guest id "
                                    f"{g['di'] >> 2} start {self.sfx_starts[slot]}")

        for r in image.rows("hle.csv"):
            if r["service"] == "sfx_start":
                prefix = emit.label(r["module"], 0)[:-5]
                last = int(r["last"], 16)
                resume = min(int(n[len(prefix):], 16) for n in self.syms
                             if n.startswith(prefix) and len(n) == len(prefix) + 5
                             and int(n[len(prefix):], 16) > last)
                a = self.syms[emit.label(r["module"], resume)]
                e.hook_range(U.HOOK_CODE, sfx_stored, a, a)

        @U.CODE_CB
        def music_entry(h, addr, size, user):
            self.sound_event("m", 0, 0)

        a = self.syms["rt_hle_music_skip"]
        e.hook_range(U.HOOK_CODE, music_entry, a, a)

        # Hardware interrupts: the reference's BIOS handlers (and the INT frame)
        # use the interrupted stack, ours run in C; the window below SS:SP is dead.
        @U.CODE_CB
        def irq_entry(h, addr, size, user):
            g = self.guest_regs(0)
            top = g["ss"] * 16 + g["sp"]
            self.masked.update(range(top - DEAD_STACK, top))

        for n in ("rt_irq", "rt_bios_int08"):
            e.hook_range(U.HOOK_CODE, irq_entry, self.syms[n], self.syms[n])

        # memory watch from the guest entry on (rt_start's own writes are not watched)
        self.in_service = False
        self.masked: set[int] = set()
        self.machine_reads: set[int] = set()

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            span = range(TOP - addr - size + 1, TOP - addr + 1)
            if self.dead_flags is not None and self.dead_flags in span:
                self.masked.update(span)
                self.dead_flags = None
            elif (not self.in_service and self.masked
                  and not self.masked.isdisjoint(span)
                  and not self.frame_writer[0] <= self.r("pc") < self.frame_writer[1]):
                # The interrupt frame belongs to the runtime. Preserve only
                # the existing dead-stack mask; all other writes still clear it.
                self.masked.difference_update(span)
            return True

        # The FLAGS image of an annotations/flags.csv PUSHF is dead by that
        # annotation; its word below SS:SP is masked until the guest rewrites it.
        @U.CODE_CB
        def dead_pushf(h, addr, size, user):
            g = self.guest_regs(0)
            self.dead_flags = g["ss"] * 16 + ((g["sp"] - 2) & 0xFFFF)

        self.dead_flags = None
        for r in image.rows("flags.csv"):
            lab = emit.label(r["module"], int(r["save"], 16))
            for a in {self.syms[x] for x in (lab, lab + "_bp") if x in self.syms}:  # R6 copy
                e.hook_range(U.HOOK_CODE, dead_pushf, a, a)

        @U.MEM_CB
        def read(h, kind, addr, size, value, user):
            if not self.in_service and self.code[0] <= self.r("pc") < self.code[1]:
                self.machine_reads.update(range(TOP - addr - size + 1, TOP - addr + 1))
            return True

        @U.CODE_CB
        def guest_start(h, addr, size, user):
            if self.watching:
                return
            self.watching = True
            if self.sabotage == "psp":
                a = TOP - (0x8120 + 0x82)
                self.e.write(a, bytes([self.mem(a, 1)[0] ^ 0x20]))
            self.e.hook_range(U.HOOK_MEM_WRITE, write, TOP - GUEST_BYTES + 1, TOP)
            for lo, hi in machine_ranges():
                self.e.hook_range(U.HOOK_MEM_READ, read, TOP - hi + 1, TOP - lo)

        # generated code: from the first guest label to program.s's data after
        # the modules (the runtime's own reads, e.g. the BIOS tick, are not the
        # guest's)
        tags = tuple(t + "_" for t in emit.TAG.values())
        self.code = (min(v for k, v in self.syms.items() if k.startswith(tags)),
                     self.syms["load_segment"])
        self.watching = False
        a = self.syms["rt_run_guest"]
        e.hook_range(U.HOOK_CODE, guest_start, a, a)

    def r(self, name: str) -> int:
        return self.e.reg_read(U.M68K[name])

    def mem(self, a: int, n: int) -> bytes:
        return self.e.read(a, n)

    def gmem(self, a: int, n: int) -> bytes:
        """Guest bytes a..a+n-1 in guest order."""
        return self.e.read(TOP - a - n + 1, n)[::-1]

    def u32(self, a: int) -> int:
        return struct.unpack(">I", self.mem(a, 4))[0]

    def cstr(self, a: int) -> str:
        b = self.mem(a, 256)
        return b[:b.index(b"\0")].decode("latin-1")

    def state(self, off: int, n: int) -> int:
        return int.from_bytes(self.mem(TOP + off, n), "big")

    def guest_regs(self, vector: int) -> dict:
        regs = {n: self.r(r) & 0xFFFF for n, r in zip(REGS, ("d0", "d1", "d2", "d3", "d4", "d5",
                                                             "a4", "a5"))}
        regs["sp"] ^= 0x7FFF    # mirrored (translator/lower.py MIRROR)
        regs["bp"] ^= 0x7FFF
        regs.update(es=self.state(5, 2), ss=self.state(3, 2), ds=self.state(1, 2))
        ccr = self.state(16, 1)
        regs["cf"], regs["zf"] = ccr & 1, ccr >> 2 & 1
        regs["df"], regs["if"] = int(self.state(12, 1) != 0), int(self.state(11, 1) != 0)
        regs["vector"] = vector
        return regs

    def platform(self, n: str) -> None:
        sp = self.r("a7")
        args = struct.unpack(">IIII", self.mem(sp + 4, 16))
        res = 0
        if n in ("plat_open", "plat_dir_entry", "plat_create", "plat_delete"):
            name = self.cstr(args[0])
            path = self.root
            for part in filter(None, name.split("/")):
                matches = [p for p in path.iterdir() if p.name.upper() == part] if path.is_dir() else []
                path = matches[0] if matches else self.root / "\0"
            on_disk = path.is_file() and name not in self.deleted
        if n == "plat_alloc":
            size = (args[0] + 3) & ~3
            for i, (address, length) in enumerate(self.free_spans):
                if length >= size:
                    self.allocations[address] = size
                    self.free_spans[i:i+1] = [(address+size, length-size)] if length > size else []
                    res = address
                    break
        elif n == "plat_free":
            address = args[0]
            size = self.allocations.pop(address)
            spans = sorted(self.free_spans + [(address, size)])
            self.free_spans = []
            for address, length in spans:
                if self.free_spans and sum(self.free_spans[-1]) == address:
                    previous, size = self.free_spans.pop()
                    self.free_spans.append((previous, size+length))
                else:
                    self.free_spans.append((address, length))
        elif n == "plat_dir_entry":
            prefix = name + "/" if name else ""
            disk = {p.name: (p.stat().st_size, *dos_file_stamp(p.stat().st_mtime)) for p in path.iterdir()
                    if p.is_file() and len(p.name) <= 12 and prefix + p.name.upper() not in self.deleted} \
                if path.is_dir() else {}
            disk.update({w[len(prefix):]: (len(d), *self.file_stamps[w]) for w, d in self.written.items()
                         if w.startswith(prefix) and "/" not in w[len(prefix):]})
            entries = sorted(disk.items())
            if args[1] < len(entries):
                self.e.write(args[2], entries[args[1]][0].encode() + b"\0")
                self.e.write(args[3], struct.pack(">IHH", *entries[args[1]][1]))
                res = 1
        elif n == "plat_open":
            if args[1] and on_disk and name not in self.written:
                self.written[name] = bytearray(path.read_bytes())  # a copy: ref/ stays untouched
                self.file_stamps[name] = dos_file_stamp(path.stat().st_mtime)
            f = MemFile(self.written[name]) if name in self.written else \
                path.open("rb") if on_disk else None
            if f:
                self.files[self.next_file] = f
                res, self.next_file = self.next_file, self.next_file + 1
            else:
                res = -1
        elif n == "plat_create":
            self.written[name] = bytearray()
            self.file_stamps[name] = dos_file_stamp(self.file_clock if self.file_clock is not None else time.time())
            self.deleted.discard(name)
            self.files[self.next_file] = MemFile(self.written[name])
            res, self.next_file = self.next_file, self.next_file + 1
        elif n == "plat_delete":
            if name in self.written:
                del self.written[name]
            elif on_disk:
                self.deleted.add(name)
            else:
                res = -1
        elif n == "plat_read":
            f = self.files[args[0]]
            data = f.read(args[2])
            if self.sabotage == "read" and data and self.watching:
                data = bytes([data[0] ^ 0xFF]) + data[1:]
            self.e.write(args[1], data)
            res = len(data)
        elif n == "plat_write":
            f = self.files[args[0]]
            res = f.write(self.mem(args[1], args[2])) if isinstance(f, MemFile) else -1
        elif n == "plat_seek":
            f = self.files[args[0]]
            off = args[1] - (1 << 32) if args[1] & 0x80000000 else args[1]
            res = f.seek(off, args[2])
        elif n == "plat_calendar_date":
            calendar = time.localtime(time.time())
            res = self.calendar_date if self.calendar_date is not None else \
                calendar.tm_year << 16 | calendar.tm_mon << 8 | calendar.tm_mday
        elif n == "plat_file_stamp":
            f = self.files[args[0]]
            if not isinstance(f, MemFile):
                raise AssertionError('explicit timestamp on a read-only platform file')
            f.dos_stamp = (args[1], args[2])
        elif n == "plat_close":
            f = self.files.pop(args[0])
            if isinstance(f, MemFile) and f.modified:
                for name, data in self.written.items():
                    if data is f.data:
                        self.file_stamps[name] = f.dos_stamp or dos_file_stamp(self.file_clock if self.file_clock is not None else time.time())
            f.close()
        elif n == "plat_mouse":
            self.e.write(args[0], struct.pack(">i", self.mouse_dx))
            self.e.write(args[1], struct.pack(">i", 0 if self.sabotage == "mouse-motion" else self.mouse_dy))
            self.mouse_dx = self.mouse_dy = 0
            res = self.mouse_buttons & (3 if self.sabotage == "mouse-buttons" else 7)
        elif n == "plat_present":
            self.presents += 1
            shown = bytearray(64000)
            for k in range(args[2]):
                x0, y0, x1, y1 = struct.unpack(">4H", self.mem(args[1] + 8 * k, 8))
                for y in range(y0, y1):
                    shown[y * 320 + x0:y * 320 + x1] = b"\1" * (x1 - x0)
            miss = sorted(o for o in self.vram_written if not shown[o])
            if miss and not self.display_miss:
                self.display_miss = f"present {self.presents}: {len(miss)} stored pixels outside " \
                    f"its rectangles, first x={miss[0] % 320} y={miss[0] // 320}"
            self.vram_written.clear()
            self.e.write(self.syms["rt_present_due"], b"\1")
        elif n == "plat_palette":
            if self.sabotage == "dac":
                self.e.write(args[0] + 300, bytes([self.mem(args[0] + 300, 1)[0] ^ 1]))
        elif n == "plat_log":
            self.log.append(self.cstr(args[0]))
            print(self.log[-1])
        elif n == "plat_exit":
            self.exit = args[0]
            self.halted = True
            self.e.stop()
        self.e.reg_write(U.M68K["d0"], res & 0xFFFFFFFF)

    def sound_event(self, kind: str, a: int, b: int) -> None:
        if self.sound_log is not None:
            self.sound_log.write(f"{self.sound_tick},{kind},{a},{b}\n")

    def post(self, vector: int) -> None:
        if vector == 8:
            self.sound_tick += 1
        tail = self.mem(self.syms["rt_irq_tail"], 1)[0]
        self.e.write(self.syms["rt_irq_ring"] + tail % 32, bytes([vector]))
        self.e.write(self.syms["rt_irq_tail"], bytes([(tail + 1) & 0xFF]))
        self.e.write(self.syms["rt_irq_pending"], b"\1")  # RT_RAISE_IRQ
        self.e.write(G_IRQ, b"\1")

    def guest_vector(self, vector: int) -> bool:
        """machine.c guest_vector: the IVT entry points into the program's memory."""
        off, seg = struct.unpack("<HH", self.gmem(vector * 4, 4))
        psp = int.from_bytes(self.mem(self.syms["load_segment"], 4), "big") - 0x10
        top = struct.unpack("<H", self.gmem(psp * 16 + 2, 2))[0]
        return psp * 16 <= seg * 16 + off < top * 16

    def press(self, key: int) -> None:
        """The key's make and break scan codes (runtime.h rt_key_ring); the
        runtime's BIOS INT 09h model stores the word at the make interrupt."""
        # DOSBox posts one IRQ per scan byte, including modifiers and E0.
        events = key_events(key)
        for ev in events:
            tail = self.mem(self.syms["rt_key_tail"], 1)[0]
            self.e.write(self.syms["rt_key_ring"] + 2 * (tail % 16), struct.pack(">H", ev))
            self.e.write(self.syms["rt_key_tail"], bytes([(tail + 1) & 0xFF]))

    def run(self, script: dict | None, timeout: int) -> None:
        """Run to the script's last snapshot trigger (None: until a stop).
        Hardware interrupts replay the reference's (script["irqs"]): posted at
        the same visit of the same poll point after the same service event;
        key release eligibility uses recorded trigger visits when available."""
        steps = [(t, k) for t, k in script["keys"]] + [(t, None) for t in script["snapshots"]] \
            if script else []
        releases = list(script["releases"]) if script else []
        self.irqs = list(script["irqs"]) if script else []
        self.step, self.hits, self.release = 0, 0, None
        self.irq_i, self.visit_n, self.visits, self.group = 0, None, {}, None
        self.irq_lost: str | None = None
        makes = 0
        # an instruction's label and its guarded copy's (R6) are one guest instruction
        at = {lab: {self.syms[x] for x in (lab, lab + "_bp") if x in self.syms}
              for lab in {t[0] for t, _ in steps} | {lab for _, lab, _, _ in self.irqs}}
        canon = {a: lab for lab, addrs in at.items() for a in addrs}

        @U.CODE_CB
        def hit(h, addr, size, user):
            if self.step == len(steps):
                return
            (lab, _, n), key = steps[self.step]
            if self.release is not None:
                if not self.release.ready(len(self.services), addr in at[lab]):
                    return
                self.release = None
            if addr not in at[lab]:
                return
            self.hits += 1
            if self.hits < n:
                return
            self.step, self.hits = self.step + 1, 0
            if isinstance(key, str):
                amount = int(key[2:])
                if key[1] == "x":
                    self.mouse_dx += amount
                elif key[1] == "y":
                    self.mouse_dy += amount
                else:
                    self.mouse_buttons = amount
            elif key is not None:
                self.press(key)
                self.release = KeyRelease(releases.pop(0))
            elif self.step == len(steps):
                self.stopped_at = lab
                self.halted = True
                self.e.stop()

        @U.CODE_CB
        def poll(h, addr, size, user):
            try:
                replay(addr)
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        def replay(addr):
            if self.irq_i == len(self.irqs):
                return
            n = len(self.services)
            if n != self.visit_n:  # executions of each poll point since the service event
                self.visit_n, self.visits = n, {}
            here = canon[addr]
            self.visits[here] = self.visits.get(here, 0) + 1
            svc, lab, hits, _ = self.irqs[self.irq_i]
            if n > svc and not self.irq_lost:
                self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                                f"not reached (service events {n})"
            if n != svc or here != lab or self.visits[here] != hits + 1:
                return
            post_group(self.r("a7"))

        def post_group(a7):
            """Post the next interrupt of the reference's (svc, label, hits) group;
            for the BIOS's handlers (instant) the whole group. One the guest
            handles, the reference took the next of its group only after the IRET
            back to the same poll point (rt_irq_back at this stack depth)."""
            nonlocal makes
            key = self.irqs[self.irq_i][:3]
            while self.irq_i < len(self.irqs) and self.irqs[self.irq_i][:3] == key:
                vector = self.irqs[self.irq_i][3]
                guest = self.guest_vector(vector)
                if vector == 9:
                    makes += 1
                    vector = 9 if makes % 2 else 0x89  # make, then the key's break
                self.post(vector)
                self.irq_i += 1
                if guest:
                    self.group = (key, a7 - 12)  # a7 at rt_irq_back: jsr rt_irq, movem d6-d7
                    return
            self.group = None

        @U.CODE_CB
        def back(h, addr, size, user):
            try:
                if self.group and self.irq_i < len(self.irqs) and \
                        self.irqs[self.irq_i][:3] == self.group[0] and \
                        self.r("a7") == self.group[1] and len(self.services) == self.group[0][0]:
                    post_group(self.group[1] + 12)
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        # static hooks (Unicorn retranslates on every hook change)
        for a in {a for t, _ in steps for a in at[t[0]]}:
            self.e.hook_range(U.HOOK_CODE, hit, a, a)
        for a in {a for _, lab, _, _ in self.irqs for a in at[lab]}:
            self.e.hook_range(U.HOOK_CODE, poll, a, a)
        self.e.hook_range(U.HOOK_CODE, back, self.syms["rt_irq_back"], self.syms["rt_irq_back"])
        if self.music_skip:
            # The reference took an interrupt in the song code the skip bypasses
            # (the next one pending, in SPAZ, at this service event): post it
            # at the next poll point instead.
            displaced = False

            @U.CODE_CB
            def skip_hit(h, addr, size, user):
                nonlocal displaced
                self.skips += 1
                nxt = self.irqs[self.irq_i] if self.irq_i < len(self.irqs) else None
                if nxt and nxt[0] == len(self.services) and nxt[1].startswith(emit.TAG["SPAZ.OVL"] + "_"):
                    displaced = True

            @U.CODE_CB
            def late(h, addr, size, user):
                nonlocal displaced
                if displaced:
                    displaced = False
                    self.moved += 1
                    post_group(self.r("a7"))

            @U.CODE_CB
            def skipped(h, addr, size, user):
                self.skipped_ran.add(f"{addr:x}")

            a = self.syms["rt_hle_music_skip"]
            self.e.hook_range(U.HOOK_CODE, skip_hit, a, a)
            for r in csv.DictReader(POLLS.open()):
                for a in {self.syms[x] for lab in [emit.label(r["module"], int(r["offset"], 16))]
                          for x in (lab, lab + "_bp") if x in self.syms}:
                    self.e.hook_range(U.HOOK_CODE, late, a, a)
            for r in image.rows("hle.csv"):
                if r["service"] == "music_skip":
                    for off in range(int(r["first"], 16) + 1, int(r["last"], 16) + 1):
                        lab = emit.label(r["module"], off)
                        if lab in self.syms:
                            a = self.syms[lab]
                            self.e.hook_range(U.HOOK_CODE, skipped, a, a)
        self.e.reg_write(U.M68K["sr"], 0x2700)
        self.e.reg_write(U.M68K["a7"], STACK_TOP)
        self.halted = False
        err = self.e.start(self.entry, 0xFFFFFFFF, timeout_us=timeout * 1_000_000)
        if err:
            print(f"unicorn error {U.uc.uc_strerror(err).decode()} pc={self.r('pc'):x}")
            self.exit = -1
        if self.irq_i < len(self.irqs) and self.irqs[self.irq_i][0] < len(self.services) \
                and not self.irq_lost:
            svc, lab, hits, _ = self.irqs[self.irq_i]
            self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                            f"not reached (service events {len(self.services)})"


def trigger(spec: str) -> tuple[str, int, int]:
    """MODULE+HEX[#N] -> (label, offset, N)."""
    at, _, n = spec.partition("#")
    mod, off = at.split("+")
    return emit.label(mod, int(off, 16)), int(off, 16), int(n or 1)


def milestone_script(name: str) -> dict:
    """reference/milestones.csv row: the run stops at the last snapshot trigger;
    keys are pressed in order, each counted from the previous key's release
    (the tracer's rules); the frame is compared at vga_mode 13."""
    rows = {r["name"]: r for r in csv.DictReader(TABLE.open())}
    if name not in rows:
        rows.update({r["name"]: r for r in csv.DictReader((REPO / "reference/coverage.csv").open())})
    r = rows[name]
    keys = []
    for k in filter(None, r["keys"].split(";")):
        spec, _, key = k.partition("=")
        keys.append((trigger(spec), key if key.startswith(("mx", "my", "mb")) else key_code(key)))
    return {"keys": keys, "snapshots": [trigger(s) for s in r["snapshots"].split()],
            "frame": r["vga_mode"] == "13"}


def machine_ranges() -> list[tuple[int, int]]:
    """Guest memory outside COMPARE."""
    out, at = [], 0
    for lo, hi in sorted(COMPARE + [FRAME]):
        out.append((at, lo))
        at = hi
    return [(lo, hi) for lo, hi in out + [(at, GUEST_BYTES)] if lo < hi]


def compare_services(got, want) -> list[str]:
    """CF/ZF: services read no flags, so the state block may hold dead ones at
    entry; at return they are checked where the reference service changed them
    or where they agreed at entry."""
    bad = []
    keys = REGS + ("es", "ss", "ds", "vector")
    entry: list = []
    for k, ((gk, g), (wk, w)) in enumerate(zip(got, want)):
        diff = [f"{n}={g[n]:04x}/{w[n]:04x}" for n in keys if g[n] != w[n]]
        flags = w["flags"]
        if gk == "svc":
            entry.append((g, w))
        else:
            ge, we = entry.pop() if entry else (g, w)
        for n, bit in (("cf", 0x1), ("zf", 0x40), ("if", 0x200), ("df", 0x400)):
            ref = int(bool(flags & bit))
            if n in ("cf", "zf"):
                if gk == "svc":
                    continue
                if int(bool(we["flags"] & bit)) == ref and ge[n] != ref:
                    continue
            if g[n] != ref:
                diff.append(f"{n}={g[n]}/{ref}")
        if gk != wk or diff:
            bad.append(f"service #{k} {wk} int {w['vector']:02x} ax={w['ax']:04x}: "
                       f"{' '.join(diff) or gk}")
            break
    if not bad and len(got) != len(want):
        bad.append(f"service count {len(got)} vs reference {len(want)}")
    return bad


def compare_ram(ram: bytes, ref: bytes, residency: Path, masked: set[int]) -> list[str]:
    rows = image.M.residency(residency)
    bad, total = [], 0
    for lo, hi in COMPARE:
        k = lo
        while k < hi:
            if ram[k] == ref[k] or k in masked:
                k += 1
                continue
            j = k
            while j < hi and (ram[j] != ref[j] or j + 1 < hi and ram[j + 1] != ref[j + 1]):
                j += 1
            total += j - k
            where = image.M.locate(rows, k)
            owner = f"{where[0]}+{where[1]:05X}" if where else "-"
            if len(bad) < 40:
                bad.append(f"ram {k:05X}..{j:05X} ({owner}): ours {ram[k:min(j, k + 12)].hex()} "
                           f"ref {ref[k:min(j, k + 12)].hex()}")
            k = j
    if total:
        bad.append(f"{total} bytes differ")
    return bad


def compare_frame(ram: bytes, dac: bytes, snap: Path, size: int = FRAME[1] - FRAME[0]) -> list[str]:
    planes = (snap / "vram.bin").read_bytes()
    lo = FRAME[0]
    ref = bytes(planes[((a & ~3) << 2) | (a & 3)] for a in range(size))
    bad = [a for a in range(size) if ram[lo + a] != ref[a]]
    out = [f"frame: {len(bad)} bytes differ, first at A000:{bad[0]:04X} ours "
           f"{ram[lo + bad[0]]:02x} reference {ref[bad[0]]:02x}"] if bad else []
    want = (snap / "dac.bin").read_bytes()
    bad = [k for k in range(256) if dac[k * 3:k * 3 + 3] != want[k * 3:k * 3 + 3]]
    if bad:
        k = bad[0]
        out.append(f"DAC: {len(bad)} entries differ, first {k:02x} ours {dac[k * 3:k * 3 + 3].hex()} "
                   f"reference {want[k * 3:k * 3 + 3].hex()}")
    return out


def compare_shown(capture: Path, bytes_per_row: int, snap: Path) -> list[str]:
    """The Amiga screen: 8 bitplanes, plane k = bit k of the pixel; colours =
    LoadRGB32 (count << 16, first 0), 32-bit guns whose top 6 bits are the DAC."""
    if not bytes_per_row:
        return ["amiga: no screen shown"]
    planes = [(capture / f"plane{k}.bin").read_bytes() for k in range(8)]
    lo, hi = FRAME
    shown = bytearray(320 * 200)
    for y in range(200):
        for xb in range(40):
            bits = [p[y * bytes_per_row + xb] for p in planes]
            for b in range(8):
                shown[y * 320 + xb * 8 + b] = sum(((bits[k] >> (7 - b)) & 1) << k for k in range(8))
    words = struct.unpack(f">{1 + 768 + 1}I", (capture / "colours.bin").read_bytes())
    dac = bytes(w >> 26 for w in words[1:769])
    out = []
    if words[0] != 256 << 16:
        out.append(f"amiga: LoadRGB32 header {words[0]:08x}")
    ram = bytes(lo) + bytes(shown) + bytes(hi - lo - len(shown))
    out += [f"amiga shown: {p}" for p in compare_frame(ram, dac, snap, len(shown))]
    return out


def check_capture(tag, regs, state, ram, dac, ref_regs, ref, snap, h) -> list[str]:
    """Registers (state block: segments), RAM, framebuffer and DAC (dac None:
    not compared) of one capture vs the snapshot."""
    problems = []
    seg = {"es": state[4:6], "ss": state[2:4], "ds": state[0:2]}  # G_ES +5, G_SS +3, G_DS +1
    regs = dict(regs, **{n: int.from_bytes(v, "big") for n, v in seg.items()})
    for n in REGS + ("es", "ss", "ds"):
        if regs[n] != int(ref_regs[n], 16):
            problems.append(f"{tag}: register {n} {regs[n]:04x} reference {ref_regs[n]}")
    dead = sum(ram[a] != ref[a] for a in h.masked if a < len(ref))
    print(f"{tag}: dead stack {len(h.masked)} bytes masked, {dead} of them differ")
    problems += [f"{tag}: {p}" for p in compare_ram(ram, ref, snap / "residency.csv",
                                                     h.masked | h.music_masked)]
    if dac is not None:
        problems += [f"{tag}: {p}" for p in compare_frame(ram, dac, snap)]
    reads = sorted(a for a in h.machine_reads if a < len(ref) and ram[a] != ref[a])
    print(f"{tag}: machine bytes read by the guest {len(h.machine_reads)}, {len(reads)} differ")
    for a in reads[:20]:
        problems.append(f"{tag}: machine byte {a:05X} read by the guest: ours {ram[a]:02x} "
                        f"reference {ref[a]:02x}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sound-log", type=Path)
    ap.add_argument("--milestone", default="m1-mode13h")
    ap.add_argument("--timeout", type=int, default=600, help="seconds of emulation before failing")
    ap.add_argument("--amiga", type=Path, help="also check this A1200-model capture")
    ap.add_argument("--label", action="store_true", help="print the milestone's label and exit")
    ap.add_argument("--table", type=Path, help="milestone table (default reference/milestones.csv)")
    ap.add_argument("--sabotage", action="store_true",
                    help="each planted runtime fault (SABOTAGE) must fail the check")
    ap.add_argument("--music-skip", action="store_true",
                    help="HLE music_skip on: song starts skipped, SPAZ's data not compared")
    args = ap.parse_args(argv)
    if args.table:
        global TABLE
        TABLE = args.table.resolve()
    if args.label:
        print(milestone_script(args.milestone)["snapshots"][-1][0])
        return 0
    if args.sabotage:
        missed = []
        for name, what in SABOTAGE.items():
            problems = check(SABOTAGE_AT.get(name, args.milestone), args.timeout, None, name)
            print(f"sabotage {name:5} ({what}): {len(problems)} problems")
            if not problems:
                missed.append(name)
        print("not caught: " + ", ".join(missed) if missed else "all sabotages caught")
        return 1 if missed else 0
    problems = check(args.milestone, args.timeout, args.amiga, None, args.music_skip, args.sound_log)
    for p in problems:
        print(p)
    print(f"host run to {args.milestone}: {'ok' if not problems else 'FAIL'}")
    return 1 if problems else 0


def rearm_problems() -> list[str]:
    """runtime.h poll-point contract on the C path the replay never reaches (it
    posts only where the reference took the interrupt, so with IF set):
    rt_set_flags_word with IF set re-arms G_IRQ from rt_irq_pending."""
    h, problems = Host(image.M.REF), []
    ret = h.syms["plat_exit"]  # stop address, never executed
    h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
    for flags in (0x0002, 0x0202):
        for pending in (0, 1):
            h.e.write(G_IRQ, b"\0")
            h.e.write(h.syms["rt_irq_pending"], bytes([pending]))
            h.e.write(STACK_TOP - 8, ret.to_bytes(4, "big") + flags.to_bytes(4, "big"))
            h.e.reg_write(U.M68K["sr"], 0x2700)  # first: it selects which a7
            h.e.reg_write(U.M68K["a7"], STACK_TOP - 8)
            h.e.start(h.syms["rt_set_flags_word"], ret, timeout_us=1_000_000)
            got, want = h.mem(G_IRQ, 1)[0], int(bool(flags & 0x200) and pending)
            if h.r("pc") != ret or got != want:
                problems.append(f"rt_set_flags_word({flags:04x}) with rt_irq_pending {pending}: "
                                f"G_IRQ {got}, want {want} (pc={h.r('pc'):x})")
    return problems


def check_opl(h, trace: Path, counts: bool = True) -> list[str]:
    """The host's AdLib writes, per port and value, are the reference's
    (ports.csv of the same run; not with the music skipped, which drops
    SPAZ's song writes); rt_opl and rt_opl_keyon hold the registers and
    key-on edges (B0-B8 bit 5 rising) of the host's write sequence."""
    want: dict[tuple[int, int], int] = {}
    for r in csv.DictReader((trace / "ports.csv").open()):
        if r["direction"] == "out" and r["port"] in ("0x0388", "0x0389"):
            k = (int(r["port"], 16), int(r["value"], 16))
            want[k] = want.get(k, 0) + int(r["count"])
    got: dict[tuple[int, int], int] = {}
    for port, v in h.opl_ports:
        got[(port, v)] = got.get((port, v), 0) + 1
    data = sum(n for (p, _), n in want.items() if p == 0x389)
    print(f"OPL: {len(h.opl)} writes, {data} in the reference")
    if counts and got != want:
        diff = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
        return [f"OPL: {len(diff)} port/value counts differ, first {diff[0][0]:x}={diff[0][1]:02x}: "
                f"{got.get(diff[0], 0)} vs {want.get(diff[0], 0)}"]
    regs, edges = bytearray(256), bytearray(9)
    for reg, v in h.opl:
        if 0xB0 <= reg <= 0xB8 and v & 0x20 and not regs[reg] & 0x20:
            edges[reg - 0xB0] = (edges[reg - 0xB0] + 1) & 0xFF
        regs[reg] = v
    problems = []
    if h.mem(h.syms["rt_opl"], 256) != bytes(regs):
        problems.append("OPL: rt_opl differs from the writes")
    if h.mem(h.syms["rt_opl_keyon"], 9) != bytes(edges):
        problems.append(f"OPL: rt_opl_keyon {list(h.mem(h.syms['rt_opl_keyon'], 9))}, "
                        f"key-on edges {list(edges)}")
    print(f"OPL: key-on edges per channel {list(edges)}")
    return problems


def check_sfx(h) -> list[str]:
    """Each HLE sfx_start report (rt_sfx_id, rt_sfx_starts) equals the slot and
    id SPAZ stored at the hooked instruction."""
    print(f"sfx_start: starts per slot {h.sfx_starts}, ids {list(h.mem(h.syms['rt_sfx_id'], 3))}")
    return [f"sfx_start: {len(h.sfx_bad)} reports differ, first {h.sfx_bad[0]}"] if h.sfx_bad else []


def reference_clocks(trace):
    """Use recorded external inputs; old captures retain their unpinned clocks."""
    with (trace / 'events.csv').open() as f:
        arm = next(csv.DictReader(f))
    assert arm['kind'] == 'arm', arm
    detail = dict(kv.split('=', 1) for kv in arm['detail'].split())
    calendar = None
    if 'dos_date' in detail:
        y, m, d = map(int, detail['dos_date'].split('-'))
        calendar = y << 16 | m << 8 | d
    source = trace.parent / 'clock-inputs.json'
    clock = None
    if source.exists():
        fields = json.loads(source.read_text())
        assert fields['SWOTL_FIXED_FILE_CLOCK'] == '1' and fields['basis'] == 'local calendar'
        clock = time.mktime(time.strptime(fields['host_file_clock'], '%Y-%m-%dT%H:%M:%S'))
    return calendar, clock


def check(milestone: str, timeout: int, amiga: Path | None, sabotage: str | None,
          music_skip: bool = False, sound_log: Path | None = None) -> list[str]:
    class args:  # noqa: N801
        pass
    args.milestone, args.timeout, args.amiga = milestone, timeout, amiga
    script = milestone_script(args.milestone)
    frame = script["frame"]
    trace = REPO / f"tmp/pc-runs/ref-{args.milestone}/trace"
    snap = trace / f"snap-{args.milestone}-{len(script['snapshots']) - 1}"  # where the run stops
    h = Host(image.M.REF, sabotage, music_skip)
    h.calendar_date, h.file_clock = reference_clocks(trace)
    label = script["snapshots"][-1][0]
    script["irqs"], script["releases"] = reference_inputs(trace, exact_releases=True)
    summary = dict(kv.split("=", 1) for kv in (trace / "summary.txt").read_text().split())
    problems = rearm_problems()
    if int(summary.get("polls", "0"), 16) != fnv(POLLS.read_bytes()):
        problems.append("reference recorded with other poll points: rerun make reference")
    if sound_log is None:
        h.run(script, args.timeout)
    else:
        with sound_log.open("w") as log:
            h.sound_log = log
            h.run(script, args.timeout)
        h.sound_log = None
    if h.irq_lost:
        problems.append(h.irq_lost)
    if music_skip:
        print(f"music skip: {h.skips} song starts skipped, {h.moved} interrupts moved to the "
              f"next poll point")
        if not h.skips:
            problems.append("music skip: no song start skipped")
        if h.skipped_ran:
            problems.append(f"music skip: skipped code ran at {sorted(h.skipped_ran)}")
        for lo, hi, mod, off in image.M.residency(snap / "residency.csv"):
            if mod == "SPAZ.OVL":
                h.music_masked |= set(range(max(lo, lo + SPAZ_DATA - off), hi))
    if h.display_miss:
        problems.append(h.display_miss)
    if h.stopped_at == label:
        problems += check_opl(h, trace, not music_skip)
        problems += check_sfx(h)
    marked = bytearray(64000)  # stored since the last present: still marked (rt_vram_rows)
    rows = h.mem(h.syms["rt_vram_rows"], 800)
    for y in range(200):
        lo, hi = struct.unpack_from(">2H", rows, 4 * y)
        marked[y * 320 + lo:y * 320 + hi] = b"\1" * max(0, hi - lo)
    unmarked = sorted(o for o in h.vram_written if not marked[o])
    if unmarked:
        problems.append(f"{len(unmarked)} pixels stored since the last present and not marked, "
                        f"first x={unmarked[0] % 320} y={unmarked[0] // 320}")
    print(f"frame presents: {h.presents}")
    print(f"hardware interrupts: {h.irq_i} replayed, {len(script['irqs'])} in the reference")
    if h.stopped_at != label:
        problems.append(f"milestone label {label} not reached (exit {h.exit}, pc={h.r('pc'):x})")
    want = reference_services(trace)
    if h.stopped_at == label:
        problems += compare_services(h.services, want)
    else:
        problems += compare_services(h.services, want[:len(h.services)])
    print(f"services: {len(h.services)} run, {len(want)} in the reference")
    if h.stopped_at == label:
        ref_regs = dict(kv.split("=") for kv in (snap / "regs.txt").read_text().split())
        ref = (snap / "ram.bin").read_bytes()
        g = h.guest_regs(0)
        if music_skip:
            ds, ss, sp = (int(ref_regs[n], 16) for n in ("ds", "ss", "sp"))
            h.music_masked |= set(range(ds * 16 + SPAZ_COUNTS[0], ds * 16 + sum(SPAZ_COUNTS)))
            h.music_masked |= set(range(ss * 16 + sp - SKIP_DEAD_STACK, ss * 16 + sp))
            print(f"music skip: {len(h.music_masked)} bytes not compared")
        problems += check_capture("host", g, h.mem(STATE, 16), h.gmem(0, 0x100000),
                                  h.mem(h.syms["rt_dac"], 768) if frame else None,
                                  ref_regs, ref, snap, h)
        if args.amiga:
            regs = dict(kv.split("=") for kv in (args.amiga / "regs.txt").read_text().split())
            ga = {n: int(regs[n], 16) for n in REGS}
            if frame:
                problems += compare_shown(args.amiga, int(regs["bpr"]), snap)
            problems += check_capture("amiga", ga, (args.amiga / "state.bin").read_bytes(),
                                      (args.amiga / "ram.bin").read_bytes()[::-1],  # reversed
                                      (args.amiga / "dac.bin").read_bytes() if frame else None,
                                      ref_regs, ref,
                                      snap, h)
    return problems


if __name__ == "__main__":
    sys.exit(main())
