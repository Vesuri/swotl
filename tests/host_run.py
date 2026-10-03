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
  service call that the guest did not write afterwards (DOSBox-X's own code
  and the interrupt frame's FLAGS word leave other values there, open-work 24);
- every machine byte outside COMPARE that generated code read holds the
  reference value.
With --amiga DIR, the same RAM/register checks run on the A1200 model's
capture (amiga/diag_m1.gdb: ram.bin, regs.txt), masked by this host run's
dead-stack set.
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
MILESTONES = {"m1-mode13h": ("RTSVGA.OVL", 0x390D)}
# Compared guest RAM: the DOS arena from the environment MCB to the top of
# conventional memory; below it are IVT/BIOS/DOS internals the runtime models
# only through services, above it video and BIOS ROM.
COMPARE = [(0x07C90, 0xA0000)]
REGS = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
DEAD_STACK = 0x60


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


SABOTAGE = {
    "read": "first byte of each guest file read flipped",
    "ax": "AX of the tenth service result off by one",
    "psp": "one command-tail byte of the PSP changed at the guest entry",
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
                                                "plat_close", "plat_log", "plat_exit")}

        @U.CODE_CB
        def stub(h, addr, size, user):
            n = self.stubs.get(addr)
            if n:
                self.platform(n)

        e.hook_range(U.HOOK_CODE, stub, self.syms["host_stubs"], self.syms["host_stubs_end"])

        self.ret_hooks: list[int] = []

        @U.CODE_CB
        def ret_hit(h, addr, size, user):
            if self.pending and addr == self.pending[-1][0]:
                _, hh = self.pending.pop()
                if self.sabotage == "ax" and len(self.services) == 19:
                    self.e.reg_write(U.M68K["d0"], (self.r("d0") + 1) & 0xFFFF)
                self.services.append(("svc_ret", self.guest_regs(self.pending_vec.pop())))
                self.in_service = bool(self.pending)

        self.ret_cb = ret_hit
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
            ret = struct.unpack(">I", self.e.read(self.r("a7"), 4))[0]
            hh = self.e.hook_range(U.HOOK_CODE, self.ret_cb, ret, ret)
            self.pending.append((ret, hh))
            self.pending_vec.append(d6 & 0xFF)

        a = self.syms["rt_int"]
        e.hook_range(U.HOOK_CODE, int_entry, a, a)

        # memory watch from the guest entry on (rt_start's own writes are not watched)
        self.in_service = False
        self.masked: set[int] = set()
        self.machine_reads: set[int] = set()

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            if not self.in_service and self.masked:
                self.masked.difference_update(range(addr - GUEST, addr - GUEST + size))
            return True

        @U.MEM_CB
        def read(h, kind, addr, size, value, user):
            if not self.in_service:
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
        args = struct.unpack(">III", self.mem(sp + 4, 12))
        res = 0
        if n == "plat_open":
            name = self.cstr(args[0])
            matches = [p for p in self.root.iterdir() if p.name.upper() == name]
            if matches and matches[0].is_file():
                self.files[self.next_file] = matches[0].open("rb")
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
        elif n == "plat_log":
            self.log.append(self.cstr(args[0]))
            print(self.log[-1])
        elif n == "plat_exit":
            self.exit = args[0]
            self.e.stop()
        self.e.reg_write(U.M68K["d0"], res & 0xFFFFFFFF)

    def run(self, stop_label: str | None, limit: int) -> None:
        if stop_label:
            a = self.syms[stop_label]

            @U.CODE_CB
            def hit(h, addr, size, user):
                self.stopped_at = stop_label
                self.e.stop()

            self.e.hook_range(U.HOOK_CODE, hit, a, a)
        self.e.reg_write(U.M68K["sr"], 0x2700)
        self.e.reg_write(U.M68K["a7"], STACK_TOP)
        err = self.e.start(self.entry, 0xFFFFFFFF, limit)
        if err:
            print(f"unicorn error {U.uc.uc_strerror(err).decode()} pc={self.r('pc'):x}")
            self.exit = -1


def machine_ranges() -> list[tuple[int, int]]:
    """Guest memory outside COMPARE."""
    out, at = [], 0
    for lo, hi in COMPARE:
        out.append((at, lo))
        at = hi
    return out + [(at, GUEST_BYTES)]


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


def check_capture(tag, regs, state, ram, ref_regs, ref, snap, h) -> list[str]:
    """Registers (state block: segments) and RAM of one capture vs the snapshot."""
    problems = []
    seg = {"es": state[4:6], "ss": state[2:4], "ds": state[0:2]}  # G_ES -12, G_SS -14, G_DS -16
    regs = dict(regs, **{n: int.from_bytes(v, "big") for n, v in seg.items()})
    for n in REGS + ("es", "ss", "ds"):
        if regs[n] != int(ref_regs[n], 16):
            problems.append(f"{tag}: register {n} {regs[n]:04x} reference {ref_regs[n]}")
    dead = sum(ram[a] != ref[a] for a in h.masked if a < len(ref))
    print(f"{tag}: dead stack {len(h.masked)} bytes masked, {dead} of them differ")
    problems += [f"{tag}: {p}" for p in compare_ram(ram, ref, snap / "residency.csv", h.masked)]
    reads = sorted(a for a in h.machine_reads if a < len(ref) and ram[a] != ref[a])
    print(f"{tag}: machine bytes read by the guest {len(h.machine_reads)}, {len(reads)} differ")
    for a in reads[:20]:
        problems.append(f"{tag}: machine byte {a:05X} read by the guest: ours {ram[a]:02x} "
                        f"reference {ref[a]:02x}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", default="m1-mode13h")
    ap.add_argument("--limit", type=int, default=200_000_000, help="68k instruction limit")
    ap.add_argument("--amiga", type=Path, help="also check this A1200-model capture")
    ap.add_argument("--sabotage", action="store_true",
                    help="each planted runtime fault (SABOTAGE) must fail the check")
    args = ap.parse_args(argv)
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
    mod, off = MILESTONES[args.milestone]
    trace = REPO / f"tmp/pc-runs/ref-{args.milestone}/trace"
    snap = trace / f"snap-{args.milestone}-0"
    h = Host(image.M.REF, sabotage)
    label = emit.label(mod, off)
    h.run(label, args.limit)
    problems = []
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
                                  ref_regs, ref, snap, h)
        if args.amiga:
            regs = dict(kv.split("=") for kv in (args.amiga / "regs.txt").read_text().split())
            ga = {n: int(regs[n], 16) for n in REGS}
            problems += check_capture("amiga", ga, (args.amiga / "state.bin").read_bytes(),
                                      (args.amiga / "ram.bin").read_bytes(), ref_regs, ref,
                                      snap, h)
    return problems


if __name__ == "__main__":
    sys.exit(main())
