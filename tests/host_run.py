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
Exit 1 on any difference, a runtime stop or an instruction limit.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uc as U  # noqa: E402
from translator import emit, image  # noqa: E402

REPO = image.REPO
ELF = REPO / "build/host/swotl.elf"
MEM = 0x01000000          # flat map: code, data, stack, guest RAM
STACK_TOP = 0x00FF0000
GUEST = 0x00400010        # src/platform/host/host.c HOST_GUEST
GUEST_BYTES = 0x110000
# Key names of the reference key script (tracer KeyByName): scan << 8 | ASCII
# as the BIOS INT 09h handler stores them.
KEYS = {"enter": 0x1C0D, "esc": 0x011B, "space": 0x3920, "tab": 0x0F09, "backspace": 0x0E08,
        "up": 0x4800, "down": 0x5000, "left": 0x4B00, "right": 0x4D00,
        **{f"f{k}": (0x3A + k) << 8 for k in range(1, 11)},
        **{c: s << 8 | ord(c) for c, s in zip("qwertyuiopasdfghjklzxcvbnm",
                                             list(range(0x10, 0x1A)) + list(range(0x1E, 0x27))
                                             + list(range(0x2C, 0x33)))},
        **{str(k): (k + 1) << 8 | ord(str(k)) for k in range(1, 10)}, "0": 0x0B30}
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


def elf_load(path: Path):
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
            name, value, _, info, _, shndx = struct.unpack_from(">IIIBBH", d, s[4] + k * 16)
            if name and shndx:
                a = strtab[4] + name
                syms[d[a:d.index(b"\0", a)].decode()] = value
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


def reference_inputs(trace: Path) -> tuple[list, list[int]]:
    """The reference's hardware interrupts as (service events so far, poll
    point label, its executions since the last service event, vector), and
    the service-event count at each key release."""
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
                releases.append(n)
    return irqs, releases


def fnv(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


SABOTAGE = {
    "read": "first byte of each guest file read flipped",
    "ax": "AX of the tenth service result off by one",
    "psp": "one command-tail byte of the PSP changed at the guest entry",
    "dac": "one DAC gun off at each frame present",
}


class Host:
    def __init__(self, ref_root: Path, sabotage: str | None = None):
        self.root = ref_root
        self.sabotage = sabotage
        entry, segs, self.syms = elf_load(ELF)
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(0, MEM)
        for vaddr, data, memsz in segs:
            e.write(vaddr, data + bytes(memsz - len(data)))
        self.entry = entry
        self.files: dict[int, object] = {}
        self.next_file = 1
        self.log: list[str] = []
        self.exit: int | None = None
        self.services: list[tuple[str, dict]] = []
        self.stopped_at: str | None = None
        self.stubs = {self.syms[n]: n for n in ("plat_open", "plat_read", "plat_seek",
                                                "plat_close", "plat_dir_entry", "plat_timer_rate", "plat_present", "plat_log",
                                                "plat_exit")}
        self.presents = 0

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
            span = range(addr - GUEST, addr - GUEST + size)
            if self.dead_flags is not None and self.dead_flags in span:
                self.masked.update(span)
                self.dead_flags = None
            elif not self.in_service and self.masked:
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
            a = self.syms[emit.label(r["module"], int(r["save"], 16))]
            e.hook_range(U.HOOK_CODE, dead_pushf, a, a)

        @U.MEM_CB
        def read(h, kind, addr, size, value, user):
            if not self.in_service and self.code[0] <= self.r("pc") < self.code[1]:
                self.machine_reads.update(range(addr - GUEST, addr - GUEST + size))
            return True

        @U.CODE_CB
        def guest_start(h, addr, size, user):
            if self.watching:
                return
            self.watching = True
            if self.sabotage == "psp":
                a = GUEST + 0x8120 + 0x82
                self.e.write(a, bytes([self.mem(a, 1)[0] ^ 0x20]))
            self.e.hook_range(U.HOOK_MEM_WRITE, write, GUEST, GUEST + GUEST_BYTES - 1)
            for lo, hi in machine_ranges():
                self.e.hook_range(U.HOOK_MEM_READ, read, GUEST + lo, GUEST + hi - 1)

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

    def u32(self, a: int) -> int:
        return struct.unpack(">I", self.mem(a, 4))[0]

    def cstr(self, a: int) -> str:
        b = self.mem(a, 256)
        return b[:b.index(b"\0")].decode("latin-1")

    def state(self, off: int, n: int) -> int:
        return int.from_bytes(self.mem(GUEST + off, n), "big")

    def guest_regs(self, vector: int) -> dict:
        regs = {n: self.r(r) & 0xFFFF for n, r in zip(REGS, ("d0", "d1", "d2", "d3", "d4", "d5",
                                                             "a4", "a5"))}
        regs.update(es=self.state(-12, 2), ss=self.state(-14, 2), ds=self.state(-16, 2))
        ccr = self.state(-1, 1)
        regs["cf"], regs["zf"] = ccr & 1, ccr >> 2 & 1
        regs["df"], regs["if"] = int(self.state(-5, 1) != 0), int(self.state(-6, 1) != 0)
        regs["vector"] = vector
        return regs

    def platform(self, n: str) -> None:
        sp = self.r("a7")
        args = struct.unpack(">IIII", self.mem(sp + 4, 16))
        res = 0
        if n in ("plat_open", "plat_dir_entry"):
            path = self.root
            for part in filter(None, self.cstr(args[0]).split("/")):
                matches = [p for p in path.iterdir() if p.name.upper() == part] if path.is_dir() else []
                path = matches[0] if matches else self.root / "\0"
        if n == "plat_dir_entry":
            entries = sorted(p for p in path.iterdir() if p.is_file() and len(p.name) <= 12) \
                if path.is_dir() else []
            if args[1] < len(entries):
                f = entries[args[1]]
                self.e.write(args[2], f.name.encode() + b"\0")
                self.e.write(args[3], struct.pack(">I", f.stat().st_size))
                res = 1
        elif n == "plat_open":
            if path.is_file():
                self.files[self.next_file] = path.open("rb")
                res, self.next_file = self.next_file, self.next_file + 1
            else:
                res = -1
        elif n == "plat_read":
            f = self.files[args[0]]
            data = f.read(args[2])
            if self.sabotage == "read" and data and self.watching:
                data = bytes([data[0] ^ 0xFF]) + data[1:]
            self.e.write(args[1], data)
            res = len(data)
        elif n == "plat_seek":
            f = self.files[args[0]]
            off = args[1] - (1 << 32) if args[1] & 0x80000000 else args[1]
            res = f.seek(off, args[2])
        elif n == "plat_close":
            self.files.pop(args[0]).close()
        elif n == "plat_present":
            self.presents += 1
            if self.sabotage == "dac":
                self.e.write(args[1] + 300, bytes([self.mem(args[1] + 300, 1)[0] ^ 1]))
        elif n == "plat_log":
            self.log.append(self.cstr(args[0]))
            print(self.log[-1])
        elif n == "plat_exit":
            self.exit = args[0]
            self.halted = True
            self.e.stop()
        self.e.reg_write(U.M68K["d0"], res & 0xFFFFFFFF)

    def post(self, vector: int) -> None:
        tail = self.mem(self.syms["rt_irq_tail"], 1)[0]
        self.e.write(self.syms["rt_irq_ring"] + tail % 32, bytes([vector]))
        self.e.write(self.syms["rt_irq_tail"], bytes([(tail + 1) & 0xFF]))
        self.e.write(GUEST - 8, b"\1")

    def guest_vector(self, vector: int) -> bool:
        """machine.c guest_vector: the IVT entry points into the program's memory."""
        off, seg = struct.unpack("<HH", self.mem(GUEST + vector * 4, 4))
        psp = int.from_bytes(self.mem(self.syms["load_segment"], 4), "big") - 0x10
        top = struct.unpack("<H", self.mem(GUEST + psp * 16 + 2, 2))[0]
        return psp * 16 <= seg * 16 + off < top * 16

    def press(self, key: int) -> None:
        tail = self.mem(self.syms["rt_key_tail"], 1)[0]
        self.e.write(self.syms["rt_key_ring"] + 2 * (tail % 16), struct.pack(">H", key))
        self.e.write(self.syms["rt_key_tail"], bytes([(tail + 1) & 0xFF]))

    def run(self, script: dict | None, limit: int) -> None:
        """Run to the script's last snapshot trigger (None: until a stop).
        Hardware interrupts replay the reference's (script["irqs"]): posted at
        the same visit of the same poll point after the same service event;
        a key's release is at the service event the reference released it."""
        steps = [(t, k) for t, k in script["keys"]] + [(t, None) for t in script["snapshots"]] \
            if script else []
        releases = list(script["releases"]) if script else []
        self.irqs = list(script["irqs"]) if script else []
        self.step, self.hits, self.release = 0, 0, None
        self.irq_i, self.visit_n, self.visits, self.group = 0, None, {}, None
        self.irq_lost: str | None = None
        makes = 0

        @U.CODE_CB
        def hit(h, addr, size, user):
            if self.release is not None and len(self.services) >= self.release:
                self.release = None  # key up: the next trigger counts from here
            if self.step == len(steps) or self.release is not None:
                return
            (lab, _, n), key = steps[self.step]
            if self.syms[lab] != addr:
                return
            self.hits += 1
            if self.hits < n:
                return
            self.step, self.hits = self.step + 1, 0
            if key is not None:
                self.press(key)
                self.release = releases.pop(0)
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
            self.visits[addr] = self.visits.get(addr, 0) + 1
            svc, lab, hits, _ = self.irqs[self.irq_i]
            if n > svc and not self.irq_lost:
                self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                                f"not reached (service events {n})"
            if n != svc or self.syms[lab] != addr or self.visits[addr] != hits + 1:
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
        for a in {self.syms[t[0]] for t, _ in steps}:
            self.e.hook_range(U.HOOK_CODE, hit, a, a)
        for a in {self.syms[lab] for _, lab, _, _ in self.irqs}:
            self.e.hook_range(U.HOOK_CODE, poll, a, a)
        self.e.hook_range(U.HOOK_CODE, back, self.syms["rt_irq_back"], self.syms["rt_irq_back"])
        self.e.reg_write(U.M68K["sr"], 0x2700)
        self.e.reg_write(U.M68K["a7"], STACK_TOP)
        self.halted = False
        err = self.e.start(self.entry, 0xFFFFFFFF, limit)
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
    r = rows[name]
    keys = []
    for k in filter(None, r["keys"].split(";")):
        spec, _, key = k.partition("=")
        keys.append((trigger(spec), KEYS[key]))
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
    seg = {"es": state[4:6], "ss": state[2:4], "ds": state[0:2]}  # G_ES -12, G_SS -14, G_DS -16
    regs = dict(regs, **{n: int.from_bytes(v, "big") for n, v in seg.items()})
    for n in REGS + ("es", "ss", "ds"):
        if regs[n] != int(ref_regs[n], 16):
            problems.append(f"{tag}: register {n} {regs[n]:04x} reference {ref_regs[n]}")
    dead = sum(ram[a] != ref[a] for a in h.masked if a < len(ref))
    print(f"{tag}: dead stack {len(h.masked)} bytes masked, {dead} of them differ")
    problems += [f"{tag}: {p}" for p in compare_ram(ram, ref, snap / "residency.csv", h.masked)]
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
    ap.add_argument("--milestone", default="m1-mode13h")
    ap.add_argument("--limit", type=int, default=2_000_000_000, help="68k instruction limit")
    ap.add_argument("--amiga", type=Path, help="also check this A1200-model capture")
    ap.add_argument("--label", action="store_true", help="print the milestone's label and exit")
    ap.add_argument("--table", type=Path, help="milestone table (default reference/milestones.csv)")
    ap.add_argument("--sabotage", action="store_true",
                    help="each planted runtime fault (SABOTAGE) must fail the check")
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
            problems = check(args.milestone, args.limit, None, name)
            print(f"sabotage {name:5} ({what}): {len(problems)} problems")
            if not problems:
                missed.append(name)
        print("not caught: " + ", ".join(missed) if missed else "all sabotages caught")
        return 1 if missed else 0
    problems = check(args.milestone, args.limit, args.amiga, None)
    for p in problems:
        print(p)
    print(f"host run to {args.milestone}: {'ok' if not problems else 'FAIL'}")
    return 1 if problems else 0


def check(milestone: str, limit: int, amiga: Path | None, sabotage: str | None) -> list[str]:
    class args:  # noqa: N801
        pass
    args.milestone, args.limit, args.amiga = milestone, limit, amiga
    script = milestone_script(args.milestone)
    frame = script["frame"]
    trace = REPO / f"tmp/pc-runs/ref-{args.milestone}/trace"
    snap = trace / f"snap-{args.milestone}-{len(script['snapshots']) - 1}"  # where the run stops
    h = Host(image.M.REF, sabotage)
    label = script["snapshots"][-1][0]
    script["irqs"], script["releases"] = reference_inputs(trace)
    summary = dict(kv.split("=", 1) for kv in (trace / "summary.txt").read_text().split())
    problems = []
    if int(summary.get("polls", "0"), 16) != fnv(POLLS.read_bytes()):
        problems.append("reference recorded with other poll points: rerun make reference")
    h.run(script, args.limit)
    if h.irq_lost:
        problems.append(h.irq_lost)
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
        problems += check_capture("host", g, h.mem(GUEST - 16, 16), h.mem(GUEST, 0x100000),
                                  h.mem(h.syms["rt_dac"], 768) if frame else None,
                                  ref_regs, ref, snap, h)
        if args.amiga:
            regs = dict(kv.split("=") for kv in (args.amiga / "regs.txt").read_text().split())
            ga = {n: int(regs[n], 16) for n in REGS}
            if frame:
                problems += compare_shown(args.amiga, int(regs["bpr"]), snap)
            problems += check_capture("amiga", ga, (args.amiga / "state.bin").read_bytes(),
                                      (args.amiga / "ram.bin").read_bytes(),
                                      (args.amiga / "dac.bin").read_bytes() if frame else None,
                                      ref_regs, ref,
                                      snap, h)
    return problems


if __name__ == "__main__":
    sys.exit(main())
