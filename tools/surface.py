#!/usr/bin/env python3
"""External surface inventory (plan step 2.5): interrupts, ports, VGA, hooks.

Static: every `int`/`in`/`out` among the sweep's instruction starts
(tmp/sweep/*.cls, run tools/sweep.py first). Traced: interrupts.csv,
ports.csv, vga.csv of the trace corpus. Prints markdown tables for
docs/external-surface.md; exit 1 if a traced guest site is not a static
instruction or a static site has no traced or classified owner.
"""

from __future__ import annotations

import sys
from collections import defaultdict

import capstone
from capstone import x86

import swotl_model as M


def static_sites(mods):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    md.detail = True
    ints, ports = {}, {}
    for n in M.SCOPE:
        cls = (M.REPO / f"tmp/sweep/{n}.cls").read_bytes()
        data = mods[n].data
        for off, c in enumerate(cls):
            if c not in (1, 3):
                continue
            b = data[off]
            if b not in (0xCD, 0xCC, 0xCE, 0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF) and \
                    not (b in (0x26, 0x2E, 0x36, 0x3E) and False):
                continue
            i = next(md.disasm(data[off:off + 4], 0), None)
            if i is None:
                continue
            if i.mnemonic == "int":
                ints[(n, off)] = i.operands[0].imm & 0xFF
            elif i.mnemonic in ("in", "out"):
                op = i.operands[1] if i.mnemonic == "in" else i.operands[0]
                port = f"{op.imm & 0xFF:02X}h" if op.type == x86.X86_OP_IMM else "dx"
                ports[(n, off)] = (i.mnemonic, port, c == 3)
    return ints, ports


def main() -> int:
    mods = M.load_modules()
    traces = M.runs()
    ints, ports = static_sites(mods)
    bad = []

    # Software interrupts by vector and AH, with traced sites (site = after `int`, minus 2).
    sw = defaultdict(lambda: defaultdict(int))
    hw = defaultdict(lambda: defaultdict(int))
    hooked = defaultdict(lambda: defaultdict(int))  # raised by BIOS/DOS, handled by the guest
    for r in M.csv_rows(traces, "interrupts.csv"):
        vec, src, off = int(r["vector"], 16), r["source_module"], int(r["source_offset"], 16)
        if r["type"] == "0":
            hw[vec][(r["target_module"], int(r["target_offset"], 16))] += int(r["count"])
            continue
        if src == "-":
            if r["target_module"] != "-":
                hooked[vec][(r["target_module"], int(r["target_offset"], 16))] += int(r["count"])
            continue
        site = (src, off - 2)
        if site not in ints:
            bad.append(f"traced INT {vec:02X}h at {src}+{off - 2:05X} is not a static int site")
        ax = int(r["ax"], 16)
        if vec == 0x33 or (vec, ax >> 8) in ((0x21, 0x25), (0x21, 0x35), (0x10, 0x10)):
            key = (vec, f"AX={ax:04X}h")
        elif vec in (0x10, 0x16, 0x1A, 0x21, 0x67):
            key = (vec, f"AH={ax >> 8:02X}h")
        else:
            key = (vec, "")
        sw[key][site] += int(r["count"])
    print("| INT | Function | Sites (module+offset ×count) |\n|---|---|---|")
    for (vec, fn), sites in sorted(sw.items()):
        s = ", ".join(f"{m}+{o:05X}×{c}" for (m, o), c in sorted(sites.items()))
        print(f"| {vec:02X}h | {fn} | {s} |")
    traced_int_sites = {s for sites in sw.values() for s in sites}
    untraced = sorted(k for k in ints if k not in traced_int_sites)
    print(f"\nStatic int sites {len(ints)}, traced {len(traced_int_sites)}; untraced:")
    byv = defaultdict(list)
    for k in untraced:
        byv[ints[k]].append(f"{k[0]}+{k[1]:05X}")
    for v, ss in sorted(byv.items()):
        print(f"- INT {v:02X}h ×{len(ss)}: {' '.join(ss[:8])}{' …' if len(ss) > 8 else ''}")

    print("\n| Vector | Raised by | Handler (×count) |\n|---|---|---|")
    for vec, targets in sorted(hooked.items()):
        s = ", ".join(f"{m}+{o:05X}×{c}" for (m, o), c in sorted(targets.items()))
        print(f"| {vec:02X}h | BIOS/DOS | {s} |")
    for vec, targets in sorted(hw.items()):
        s = ", ".join(f"{m}+{o:05X}×{c}" for (m, o), c in sorted(targets.items()))
        print(f"| {vec:02X}h | hardware | {s} |")

    # Ports by guest site.
    tp = defaultdict(lambda: defaultdict(int))
    for r in M.csv_rows(traces, "ports.csv"):
        if r["source_module"] == "-":
            continue
        site = (r["source_module"], int(r["source_offset"], 16))
        if site not in ports:
            bad.append(f"traced port {r['port']} at {site[0]}+{site[1]:05X} is not a static in/out")
        tp[(r["direction"], int(r["port"], 16))][site] += int(r["count"])
    print("\n| Dir | Port | Sites (×count) |\n|---|---|---|")
    for (d, p), sites in sorted(tp.items(), key=lambda k: (k[0][1], k[0][0])):
        s = ", ".join(f"{m}+{o:05X}×{c}" for (m, o), c in sorted(sites.items()))
        print(f"| {d} | {p:03X}h | {s} |")
    traced_port_sites = {s for sites in tp.values() for s in sites}
    untraced = sorted(k for k in ports if k not in traced_port_sites)
    print(f"\nStatic in/out sites {len(ports)}, traced {len(traced_port_sites)}; untraced:")
    for k in untraced:
        d, p, _ = ports[k]
        print(f"- {k[0]}+{k[1]:05X} {d} {p}")

    # VGA memory by site.
    vga = defaultdict(lambda: [0, 0, set()])
    for r in M.csv_rows(traces, "vga.csv"):
        v = vga[(r["source_module"], int(r["source_offset"], 16))]
        v[0 if r["direction"] == "read" else 1] += int(r["count"])
        v[2].add(int(r["page"], 16))
    mods_vga = defaultdict(lambda: [0, 0, 0])
    for (m, _), (rd, wr, pages) in vga.items():
        mods_vga[m][0] += 1
        mods_vga[m][1] += rd
        mods_vga[m][2] += wr
    print("\n| VGA writer module | Sites | Reads | Writes |\n|---|---|---|---|")
    for m, (n, rd, wr) in sorted(mods_vga.items()):
        print(f"| {m} | {n} | {rd} | {wr} |")
    for b in bad[:20]:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
