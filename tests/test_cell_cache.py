#!/usr/bin/env python3
"""Cell caches (D3, translator/smc.py): the runtime drops them where its own
stores or segment registers may reach a self-modified region. The cache
walks themselves are checked against x86 by tests/m68k_blocks.py."""
import argparse
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import test_mouse_irq as machine  # noqa: E402

H = machine.H
U = H.U
VALID = 0xFFFF      # `_plant`: valid, no RET planted; 0: dropped


def plants(h):
    return [n for n in h.syms if n.endswith("_walk_plant")]


def state(h):
    return {n: int.from_bytes(h.mem(h.syms[n], 2), "big") for n in plants(h)}


def valid(h):
    for n in plants(h):
        h.e.write(h.syms[n], struct.pack(">H", VALID))


def runtime_store(sabotage):
    """INT 21h AH=25h stores a vector (wr16) inside smc_lo..smc_hi: dropped;
    outside: kept. The bounds are moved over the vector table for the test."""
    out = []
    for vector, inside in ((0x60, True), (0x61, False)):
        h = machine.machine()
        assert plants(h) and set(state(h).values()) == {0}, "rt_start must leave the caches dropped"
        lo = 0x60 * 4 if not sabotage else 0x10000
        h.e.write(h.syms["smc_lo"], struct.pack(">II", lo, 0x60 * 4 + 3))
        valid(h)
        for r, v in (("ax", 0x2500 | vector), ("dx", 0x1234)):
            h.e.write(h.syms["rt_r"] + 2 * H.REGS.index(r), struct.pack(">H", v))
        machine.call(h, "rt_int21", 0, 0)
        assert not h.halted, h.log
        assert h.gmem(vector * 4, 2) == b"\x34\x12"
        out.append(set(state(h).values()) == ({0} if inside else {VALID}))
    return all(out)


def segment_reload(sabotage):
    """rt_int returning with ES from INT 21h AH=35h: a segment whose window
    reaches a region drops the caches (load_regs); another keeps them."""
    out = []
    for seg in (0x0CBD, 0x2000):
        h = machine.machine()
        limit = int.from_bytes(h.mem(h.syms["smc_seg_limit"], 2), "big")
        if sabotage:
            h.e.write(h.syms["smc_seg_limit"], b"\0\0")
        machine.write_guest(h, 0x62 * 4, struct.pack("<HH", 0x100, seg))
        for slot in (1, 3):     # DS and SS reach no region
            h.e.write(H.TOP + slot, struct.pack(">H", 0x3000))
        valid(h)
        h.e.reg_write(U.M68K["a6"], H.TOP)
        h.e.reg_write(U.M68K["d0"], 0x3562)
        h.e.reg_write(U.M68K["d6"], (0x822 << 16) | 0x21)
        h.e.reg_write(U.M68K["d7"], 0x100)
        machine.call(h, "rt_int")
        assert not h.halted, h.log
        assert h.state(5, 2) == seg
        out.append(set(state(h).values()) == ({0} if seg < limit else {VALID}))
    return all(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sabotage", action="store_true")
    a = ap.parse_args()
    for name, check in (("runtime store into a region", runtime_store),
                        ("segment reaching a region at a runtime return", segment_reload)):
        assert check(False), f"{name}: the caches were not dropped (or dropped outside)"
        if a.sabotage:
            assert not check(True), f"{name}: planted missing notification escaped detection"
            print(f"{name}: planted missing notification caught")
        print(f"{name}: caches dropped inside, kept outside")


if __name__ == "__main__":
    main()
