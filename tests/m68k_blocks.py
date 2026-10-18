#!/usr/bin/env python3
"""Block differential of the generated program (gate 4, step 4.2): the module code
as `make gen` emits it (program mode: real labels, fused flags, liveness-elided
stores, return checks, compare chains), run from traced block entries in
Unicorn 68020 against the original bytes in Unicorn x86-16.

Self-modified regions (D16): the cell walk runs from traced entries over the
run-time bytes of every distinct snapshot image of the region, a RET planted
a random number of cells on, against the same bytes in x86-16.

A block runs from an executed leader to its first transfer (or the next
leader). The 68k side stops at the first label outside the block or at a
runtime entry. Compared: registers, segment registers, written bytes, OUT
sequence, interrupt/fault, the successor reached (CS:IP), and the flags live
at that successor (flags.py; undefined ones masked by the IR). Calls also check
the return protocol: resuming at the native return address with the right
guest IP reaches the return site, with a wrong IP or CS rt_ret_mismatch
(upper words of the popped IP and CS undefined).
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m68k_diff as D  # noqa: E402
from m68k_assembly import branch_widths  # noqa: E402
import uc as U  # noqa: E402
import x86_diff as X  # noqa: E402
from translator import emit, image, region, smc  # noqa: E402
from translator import lower as L  # noqa: E402
from translator.decode import DecodeError, Imm, Mem, Reg  # noqa: E402
from translator.interp import State, UndefinedFlag, step  # noqa: E402
from translator.ir import FLAG_BIT, STATUS  # noqa: E402
from translator.lower import CCR_BIT, HALF, LOADSEG  # noqa: E402
from translator.support import HELPERS, equates  # noqa: E402

M = image.M
STUBS = emit.RUNTIME + emit.HLE_SERVICES + ("T_RET",)
STUB_AT = {n: D.STUB + 4 * k for k, n in enumerate(STUBS)}
STUB_AT["rt_irq_pending"] = D.PENDING  # data, clear (no interrupt posted)
TRANSFER = {"jmp", "jmpf", "jcc", "call", "callf", "ret", "retf", "iret", "int", "int3", "into",
            "loop", "loope", "loopne", "jcxz", "hlt"}


def program_image(p: emit.Program, cache: Path) -> tuple[bytes, dict]:
    """Assemble every module into one binary; returns it and label -> address."""
    order, body = [], []
    for mod in p.units:
        if not p.units[mod].insns:
            continue
        lines, _ = p.module_text(mod)
        body += lines
        order += [emit.label(mod, o) for o in sorted(p.units[mod].insns)]
        order += [emit.walk_label(m, lo) for m, lo, _ in sorted(p.smc_forms) if m == mod]
        for _ws, starts, nodes, _rng in p.comps:   # R6 guarded copies and their guards
            if next(iter(nodes))[0] == mod:
                order += [emit.copy_label(*n) for n in sorted(nodes)]
                order += [f"{emit.label(*n)}_bpg" for n in sorted(starts)]
                order += [f"{emit.label(*p.fall[n])}_bpr" for n in sorted(nodes)
                          if p.node_insn(n).op in region.REGUARD and p.fall.get(n) in nodes]
    smc_code, smc_data = p.smc_text()
    order += aux_labels(p)
    src = [equates()] + [f"{n}\tequ\t${a:x}" for n, a in STUB_AT.items()]
    src += [f"\torg\t${D.CODE:x}", "labels:"] + [f"\tdc.l\t{x}" for x in order]
    src += body + [HELPERS] + smc_code + smc_data
    text = branch_widths("\n".join(src) + "\n")
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    out = cache / f"program-{key}.bin"
    image_ = out.read_bytes() if out.exists() else D.assemble(text, out)
    addr = {x: int.from_bytes(image_[4 * k:4 * k + 4], "big") for k, x in enumerate(order)}
    return image_, addr


def aux_labels(p: emit.Program) -> list[str]:
    """Cell cache (D3) labels the tests reach that are no block exits: the
    exact walk, the store hooks, smc_expose and the cache data."""
    _code, data = p.smc_text()
    out = ["smc_expose"] + [x.split(":")[0] for x in data if ":" in x]
    for lab, *_ in p.cells:
        out += [f"{lab}_x", f"{lab}_wb", f"{lab}_ww"]
    return out


SNIP = D.CODE + 0x700000    # single lowered instructions (cache_cases), after the program


def snippets(p: emit.Program, addr: dict, nodes: list, cache: Path) -> tuple[bytes, list[int]]:
    """The program's lowering of each instruction alone (no run context: no
    reused index or base), each ending in rts, assembled at SNIP against the
    program image's cell cache labels; returns the image and the entries."""
    src = [equates()] + [f"{n}\tequ\t${a:x}" for n, a in STUB_AT.items()]
    src += [f"{x}\tequ\t${addr[x]:x}" for x in aux_labels(p)]
    src += [f"\torg\t${SNIP:x}", "snips:"] + [f"\tdc.l\tS{k}" for k in range(len(nodes))]
    cold = []
    for k, (mod, off) in enumerate(nodes):
        lw = L.lower(p.units[mod].insns[off], p.ctx(mod, off, Counter()))
        src += [f"S{k}:"] + lw.out + ["\trts"]
        cold += lw.cold
    text = "\n".join(src + cold) + "\n"
    out = cache / f"snip-{hashlib.sha256(text.encode()).hexdigest()[:16]}.bin"
    image_ = out.read_bytes() if out.exists() else D.assemble(text, out)
    return image_, [int.from_bytes(image_[4 * k:4 * k + 4], "big") for k in range(len(nodes))]


def relocated(m: M.Module) -> bytearray:
    data = bytearray(m.data)
    for f in m.fixups:
        v = int.from_bytes(data[f:f + 2], "little")
        data[f:f + 2] = ((v + LOADSEG) & 0xFFFF).to_bytes(2, "little")
    return data


def blocks(p: emit.Program, executed: dict[str, set[int]]):
    for mod, u in p.units.items():
        for off in sorted(u.insns):
            n = (mod, off)
            if n not in p.leaders or off not in executed.get(mod, ()):
                continue
            run, k = [], off
            while True:
                i = u.insns[k]
                run.append(k)
                if i.op in TRANSFER or k in u.manager_calls:
                    break
                nxt = p.fall.get((mod, k))
                if nxt is None or nxt in p.leaders:
                    break
                k = nxt[1]
            yield mod, run


def copy_blocks(p: emit.Program, nodes: set, executed: dict[str, set[int]]):
    """Blocks of a guarded copy (R6): from its executed leaders, within it."""
    for mod, off in sorted(nodes):
        if (mod, off) not in p.leaders or off not in executed.get(mod, ()):
            continue
        u, run, k = p.units[mod], [], off
        while True:
            run.append(k)
            if u.insns[k].op in TRANSFER or k in u.manager_calls:
                break
            nxt = p.fall.get((mod, k))
            if nxt is None or nxt in p.leaders or nxt not in nodes:
                break
            k = nxt[1]
        yield mod, run


def region_images(p: emit.Program) -> dict[tuple[str, int, int], list[bytes]]:
    """Distinct snapshot bytes of each self-modified region (first .. last + 16)."""
    out: dict[tuple[str, int, int], list[bytes]] = {k: [] for k in p.smc_forms}
    for trace in M.runs():
        for snap in sorted(trace.glob("snap-*")):
            ram = (snap / "ram.bin").read_bytes()
            for mod_, lo, hi in p.smc_forms:
                for a, b, mod, off in M.residency(snap / "residency.csv"):
                    if mod == mod_ and off <= lo and hi + 16 <= off + b - a:
                        data = ram[a + lo - off:a + hi + 16 - off]
                        if data not in out[(mod_, lo, hi)]:
                            out[(mod_, lo, hi)].append(data)
    return out


def cells(data: bytes, start: int, forms: list[str]) -> list[str]:
    """Forms of the cells from `start` up to (not including) the first RET or unknown."""
    out, p = [], start
    parsed = [(f, smc._parse(f)) for f in forms if f != "c3"]
    while p < len(data) - 16:
        for f, (code, fixed) in parsed:
            if all(data[p + k] == code[k] for k in fixed):
                out.append(f)
                p += len(code)
                break
        else:
            return out
    return out


def walks(p: emit.Program, h, m, addr, stop_names, cases: int,
          edges: int = 8, steps: int = 24) -> tuple[int, list[str]]:
    count, bad = 0, []
    cached = {lab for lab, *_ in p.cells}

    def one(mod, u, cs, lo, data, e, code, n, want, what, edge=False, entry="", cold=True,
            force=None, memory=(), self_write=False):
        """Walk from `e` over `code` (the region image, patched): `n` x86
        instructions, then the 68k reaches `want` (T_RET, or rt_stop_unknown
        at the x86's IP). `entry`: the walk's label suffix (`_x` the exact
        walk); `cold`: the cell cache dropped first (the harness wrote the
        bytes), else it holds what the store hooks told it. False when the
        case stores over its own bytes (unless `self_write`; an edge case also
        when the x86 then ran them into an exception)."""
        nonlocal count
        ip = u.ip_of(e)
        regs, flags, flagsx, _ = h.state({"regs": {"cs": cs}, "ip": ip})
        regs.update(force or {})
        ret_ip = h.rng.randrange(0x10000)
        sp_lin = regs["ss"] * 16 + regs["sp"]
        patches = [(sp_lin, ret_ip.to_bytes(2, "little")),
                   (cs * 16 + u.ip_of(lo), bytes(code))] + list(memory)
        case = (regs, flags, flagsx, ip, patches)
        err, out, fl, umem, ints, outs, uwrites = h.oracle.run(case, n)
        patched = {a: d[a - a0] for a0, d in patches for a in range(a0, a0 + len(d))}
        umem = {a: umem.get(a, h.oracle.e.read(a, 1)[0]) for a in set(umem) | uwrites}
        h.oracle.restore(uwrites | set(patched))
        if not self_write and uwrites & set(patched) or edge and (err or ints):
            return False  # stores over the cells or the return word
        wl = emit.walk_label(mod, lo)
        if wl in cached and (cold or min(regs[r] for r in ("ds", "es", "ss")) < p.smc_limit):
            m.e.write(addr[f"{wl}_plant"], b"\0\0")   # as rt_wrote or load_regs would
        m.inside, m.extra_stops = set(), stop_names
        mo, mf, mfx, mmem, mouts, mwrites, info = m.run(
            addr[wl + entry], case, h.rng, init={"d7": ip}, irq=False)
        diffs = []
        if info["err"] or info["stop"] != want:
            diffs.append(f"stop {info['stop']} err {info['err']}")
        diffs += info["irq"]
        if info["d7"] != out["ip"]:
            diffs.append(f"ip 68k={info['d7']:04x} x86={out['ip']:04x}")
        for r in D.REGS:
            if mo[r] != out[r]:
                diffs.append(f"{r} 68k={mo[r]:04x} x86={out[r]:04x}")
        for sname in ("es", "ss", "ds"):
            if mo[sname] != out[sname]:
                diffs.append(f"{sname} 68k={mo[sname]:04x} x86={out[sname]:04x}")
        for f in sorted(STATUS) + ["DF", "IF"]:
            if mf[f] != fl >> FLAG_BIT[f] & 1:
                diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
        for a in sorted(set(umem) | mwrites):
            want_b = umem.get(a, patched.get(a, h.bg[a]))
            got = mmem.get(a, m.gread(a, 1)[0])
            if got != want_b:
                diffs.append(f"mem {a:05x} 68k={got:02x} x86={want_b:02x}")
                break
        count += 1
        if diffs:
            bad.append(f"{mod}+{e:05X} walk{entry} {what}: {'; '.join(diffs[:6])}")
        m.restore(set(mwrites) | set(patched))
        return True

    def both(*a, exact=True, **k):
        """Through the cell cache (dropped first), and the exact walk."""
        r = one(*a, **k)
        if r and exact and emit.walk_label(a[0], a[3]) in cached:
            one(*a, **dict(k, entry="_x"))
        return r

    for (mod, lo, hi), images in region_images(p).items():
        u = p.units[mod]
        cs = (LOADSEG + u.segment(lo)) & 0xFFFF
        entries = sorted(o for o in u.smc_entries if lo <= o <= hi)
        for data in images:
            for c in range(cases):
                e = h.rng.choice(entries)
                chain = cells(data, e - lo, p.smc_forms[(mod, lo, hi)])
                k = h.rng.randrange(len(chain) + 1)
                code = bytearray(data)
                at = e - lo + sum(len(smc._parse(f)[0]) for f in chain[:k])
                code[at] = 0xC3
                n = sum(len(smc.FORMS[f][0]) for f in chain[:k]) + 1
                both(mod, u, cs, lo, data, e, code, n, "T_RET", f"of {k} cells", exact=c % 8 == 0)
    # R7 edges, for `edges` entries per image: mov cells up to the region's
    # last IP and past it, the stop at the bound (the counted run's residue
    # varies with the entry), a RET in the last cell before the bound, and an
    # unknown cell (also one that matches a form's first bytes only) at the
    # first, a middle and the last position
    for (mod, lo, hi), images in region_images(p).items():
        u = p.units[mod]
        cs = (LOADSEG + u.segment(lo)) & 0xFFFF
        forms = p.smc_forms[(mod, lo, hi)]
        mov, _ = smc._parse(smc.MOV)
        for data in images:
            for x, e in enumerate(h.rng.sample(sorted(o for o in u.smc_entries if lo <= o <= hi),
                                               edges)):
                exact = x < edges // 4      # the exact walk too, for a quarter of them
                chain = cells(data, e - lo, forms)
                q, ops = e - lo, []     # the operands of the image's own mov cells
                for f in chain:
                    if f == smc.MOV:
                        ops.append(data[q + 2:q + 4])
                    q += len(smc._parse(f)[0])
                ops = ops or [data[e - lo + 2:e - lo + 4]]
                at = e - lo + sum(len(smc._parse(f)[0]) for f in chain)
                n = sum(len(smc.FORMS[f][0]) for f in chain)
                full, q, nf = bytearray(data), at, n
                while q <= hi - lo + 8:     # two mov cells past the bound too
                    full[q:q + 4] = mov[:2] + h.rng.choice(ops)
                    nf += q <= hi - lo
                    q += 4
                q -= 8
                if nf:
                    both(mod, u, cs, lo, data, e, full, nf, "rt_stop_unknown",
                         f"of {nf} cells to the bound", True, exact=exact)
                if q > at:
                    last = bytearray(full)
                    last[q - 4] = 0xC3
                    both(mod, u, cs, lo, data, e, last, nf, "T_RET",
                         f"of {nf - 1} cells, RET at the bound", True, exact=exact)
                for j in sorted({1, len(chain) // 2, len(chain)} & set(range(1, len(chain) + 1))):
                    bad_cell = bytearray(data)
                    c = e - lo + sum(len(smc._parse(f)[0]) for f in chain[:j])
                    junk = h.rng.choice((b"\x90", b"\x88\x86", b"\x2e\x8b\x1f"))
                    bad_cell[c:c + len(junk)] = junk
                    both(mod, u, cs, lo, data, e, bad_cell,
                         sum(len(smc.FORMS[f][0]) for f in chain[:j]), "rt_stop_unknown",
                         f"of {j} cells, unknown cell {junk.hex()}", True, exact=exact)
    cache_cases(p, h, m, addr, stop_names, one, bad, steps)
    return count, bad


def mov_runs(data: bytes, start: int, chain: list[str]) -> list[tuple[int, int, int]]:
    """(byte offset, operand, cells) of each run of mov cells from `start` whose
    operands are consecutive (one reload or other cell ends a run)."""
    out, q = [], start
    for f in chain:
        if f == smc.MOV:
            w = int.from_bytes(data[q + 2:q + 4], "little")
            if out and out[-1][0] + 4 * out[-1][2] == q and (out[-1][1] + out[-1][2]) & 0xFFFF == w:
                out[-1] = (out[-1][0], out[-1][1], out[-1][2] + 1)
            else:
                out.append((q, w, 1))
        q += len(smc._parse(f)[0])
    return out


def cache_cases(p: emit.Program, h, m, addr, stop_names, one, bad, steps: int) -> None:
    """D3: walks over a warm cell cache that the store hooks keep current, each
    against x86 on the same bytes. Per image, `steps` walks, each between a
    RET plant and its restore made through the region's store hook (`_wb`),
    as the generated CS stores do; some steps first patch a mov operand
    through `_ww`, or rewrite cells unseen after a segment load whose window
    reaches the region (a real generated `mov`/`pop` of ES or DS) or after
    smc_expose. Then, on a cold cache: the RET inside and at the ends of runs
    of destinations; destinations that wrap at 16 bits (first, middle, last
    cell; also the exact walk); a DS reaching the region at the entry and from
    a reload, whose own store plants the RET; entries inside a cached cell."""
    loads = {}      # (op, segment) -> node, source register (None: the stack)
    sites = {}      # kind -> [(node, insn)]: byte/word movs to CS memory a cache may see
    for mod, u in p.units.items():
        for off, i in sorted(u.insns.items()):
            if i.op in ("mov", "pop") and isinstance(i.operands[0], Reg) and \
                    i.operands[0].name in ("es", "ds") and \
                    (i.op == "pop" or isinstance(i.operands[1], Reg) and
                     i.operands[1].name in D.REGS and i.operands[1].name not in ("sp", "bp")):
                loads.setdefault((i.op, i.operands[0].name),
                                 ((mod, off), None if i.op == "pop" else i.operands[1].name))
            if i.op == "mov" and isinstance(i.operands[0], Mem) and i.operands[0].seg == "cs" \
                    and (i.operands[0].base or i.operands[0].index) \
                    and p.ctx(mod, off, Counter()).code_regions:
                a, b = i.operands
                kind = ("word" if a.width == 16 else "plant" if isinstance(b, Imm) and b.value == 0xC3
                        else "imm" if isinstance(b, Imm) else "reg")
                sites.setdefault(kind, []).append(((mod, off), i))
    loads = list(loads.values())
    nodes = [n for n, _ in loads] + [n for v in sites.values() for n, _ in v]
    snip, at = snippets(p, addr, nodes, image.REPO / "tmp/m68k")
    m.e.write(SNIP, snip)
    snip_at = dict(zip(nodes, at))

    def run_aux(where, force, patches, init):
        regs, flags, flagsx, _ = h.state({"regs": {"cs": 0x1000}, "ip": 0})
        regs.update(force)
        m.inside, m.extra_stops = set(), stop_names
        out = m.run(where, (regs, flags, flagsx, 0, patches), h.rng, init=init, irq=False)
        m.restore(out[5] | {a for a0, d in patches for a in range(a0, a0 + len(d))})
        return out[-1]

    def site_store(kind, target, value, code_at, code):
        """One generated CS store (its lowering and hook) of `value` at IP
        `target`; False when no site of the kind stores that value."""
        options = [(n, i) for n, i in sites.get(kind, ())
                   if not isinstance(i.operands[1], Imm) or i.operands[1].value == value]
        if not options:
            return False
        node, i = h.rng.choice(options)
        a, b = i.operands
        force = {}
        regs = [r for r in (a.base, a.index) if r]
        for r in regs[1:]:
            force[r] = h.rng.randrange(0x10000)
        force[regs[0]] = (target - a.disp - sum(force.values())) & 0xFFFF
        if isinstance(b, Reg):
            full, sh = HALF.get(b.name, (b.name, 0))
            if full in force:
                return False
            force[full] = value << sh | h.rng.randrange(0x100) << (8 - sh) if b.width == 8 else value
        info = run_aux(snip_at[node], force, [(code_at, bytes(code))], {})
        if info["err"] or info["stop"] != "T_RET":
            bad.append(f"{emit.label(*node)} store: stop {info['stop']} err {info['err']}")
        return True

    def hook(wl, code_at, code, q, word=False, kind=None, value=None, ip=None):
        """The store at region offset q is in `code`: a generated site's own
        store of the same value (when `kind` names one), else the hook alone."""
        if kind and h.rng.randrange(2) and site_store(kind, ip + q, value, code_at, code):
            return
        info = run_aux(addr[f"{wl}_ww" if word else f"{wl}_wb"], {}, [(code_at, bytes(code))],
                       {"d6": q + word + 1})
        if info["err"] or info["stop"] != "T_RET":
            bad.append(f"{wl} store hook at {q:04x}: stop {info['stop']} err {info['err']}")

    def until_ret(code, start, forms):
        return sum(len(smc.FORMS[f][0]) for f in cells(code, start, forms)) + 1

    for (mod, lo, hi), images in region_images(p).items():
        wl = emit.walk_label(mod, lo)
        if wl not in {lab for lab, *_ in p.cells}:
            continue
        u = p.units[mod]
        cs = (LOADSEG + u.segment(lo)) & 0xFFFF
        code_at = cs * 16 + u.ip_of(lo)
        forms = p.smc_forms[(mod, lo, hi)]
        entries = sorted(o for o in u.smc_entries if lo <= o <= hi)
        for data in images:
            m.e.write(addr[f"{wl}_plant"], b"\0\0")
            cur = bytearray(data)
            for step in range(steps):
                e = h.rng.choice(entries)
                chain = cells(cur, e - lo, forms)
                movs = [q + 4 * j for q, _w, k in mov_runs(cur, e - lo, chain) for j in range(k)]
                kind = h.rng.randrange(6) if movs else 5
                touched = -1        # the last cell changed: the walk's RET lies after it
                if kind == 0:       # an operand patch (a word store through the hook)
                    q = touched = h.rng.choice(movs)
                    w = h.rng.randrange(0x10000)
                    cur[q + 2:q + 4] = w.to_bytes(2, "little")
                    hook(wl, code_at, cur, q + 2, word=True, kind="word", value=w, ip=u.ip_of(lo))
                elif kind in (1, 2):    # cells rewritten unseen after a load or smc_expose
                    if kind == 1:
                        node, src = h.rng.choice(loads)
                        value = h.rng.choice((cs, 0, p.smc_limit - 1))
                        if src:
                            info = run_aux(snip_at[node], {src: value}, [], {})
                        else:
                            info = run_aux(snip_at[node], {"ss": 0x1000, "sp": 0x100},
                                           [(0x10100, value.to_bytes(2, "little"))], {})
                        if info["err"] or info["stop"] != "T_RET":
                            bad.append(f"{emit.label(*node)}: stop {info['stop']} err {info['err']}")
                    else:
                        run_aux(addr["smc_expose"], {}, [], {})
                    for q in h.rng.sample(movs, min(3, len(movs))):
                        cur[q + 2:q + 4] = h.rng.randrange(0x10000).to_bytes(2, "little")
                        touched = max(touched, q)
                # a quarter of the RETs where the cells end (never cached): the walk
                # must not stop at an earlier, restored one
                ends = [e - lo + sum(len(smc._parse(f)[0]) for f in chain[:j])
                        for j in range(len(chain) + 1)]
                after = [j for j, q in enumerate(ends) if q > touched]
                k = len(chain) if h.rng.randrange(4) == 0 else h.rng.choice(after)
                at = ends[k]
                old = cur[at]
                cur[at] = 0xC3
                hook(wl, code_at, cur, at, kind="plant", value=0xC3, ip=u.ip_of(lo))
                if not one(mod, u, cs, lo, cur, e, cur, until_ret(cur, e - lo, forms), "T_RET",
                           f"warm step {step} ({kind}), RET after {k} cells", cold=False):
                    m.e.write(addr[f"{wl}_plant"], b"\0\0")   # not run (it stores over its cells)
                cur[at] = old
                hook(wl, code_at, cur, at, kind=h.rng.choice(("reg", "imm")), value=old,
                     ip=u.ip_of(lo))
            for e in h.rng.sample(entries, min(4, len(entries))):
                chain = cells(data, e - lo, forms)
                runs = [r for r in mov_runs(data, e - lo, chain) if r[2] >= 2]
                for q, w, k in runs[:3]:    # entered at the run's first cell
                    for j in sorted({1, 2, smc.FILL - 1, smc.FILL, smc.FILL + 1, k - 1, k} &
                                    set(range(1, k + 1))):
                        code = bytearray(data)
                        code[q + 4 * j] = 0xC3
                        one(mod, u, cs, lo, data, lo + q, code, j + 1, "T_RET",
                            f"RET {j} cells into a run of {k}", edge=True)
                    code = bytearray(data)
                    code[q + 4 * k] = 0xC3
                    for j in sorted({0, k // 2, k - 1}):
                        bx = (0xFFFF - w - j) & 0xFFFF      # cell j stores at FFFFh
                        for entry in ("", "_x"):
                            one(mod, u, cs, lo, data, lo + q, code, k + 1, "T_RET",
                                f"run of {k}, offset FFFFh at cell {j}", force={"bx": bx},
                                edge=True, entry=entry)
                if chain[:3] == [smc.MOV] * 3:   # the entry DS: cell 0 plants at cell 2
                    w0 = int.from_bytes(data[e - lo + 2:e - lo + 4], "little")
                    for ds in (cs, cs - 0x100):
                        bx = (u.ip_of(e) + 8 + (cs - ds) * 16 - w0) & 0xFFFF
                        one(mod, u, cs, lo, data, e, data, 3, "T_RET", f"entry DS {ds:04x} plants",
                            force={"ds": ds, "bx": bx, "ax": 0xC3}, self_write=True, edge=True)
                rl = [j for j, f in enumerate(chain) if f == smc.RELOAD]
                if rl and chain[rl[0] + 1:rl[0] + 3] == [smc.MOV] * 2:  # DS from a reload
                    at = e - lo + sum(len(smc._parse(f)[0]) for f in chain[:rl[0]])
                    w1, w2, wn = (int.from_bytes(data[at + k:at + k + 2], "little") for k in (3, 8, 12))
                    bx = (u.ip_of(lo) + at + 14 - wn) & 0xFFFF
                    words = {cs * 16 + w1: bx, cs * 16 + w2: cs}
                    inside = any(code_at - 1 <= a < code_at + len(data) for a in words)
                    if abs(w1 - w2) >= 2 and not inside:
                        one(mod, u, cs, lo, data, lo + at, data, 4, "T_RET", "reload DS plants",
                            force={"ax": 0xC3},
                            memory=[(a, v.to_bytes(2, "little")) for a, v in words.items()],
                            self_write=True, edge=True)
                if chain[:1] == [smc.MOV]:      # inside a cached cell: the exact walk decides
                    code = bytearray(data)
                    code[e - lo + 4] = 0xC3     # one cell cached
                    one(mod, u, cs, lo, data, e, code, 2, "T_RET", "warms the cache")
                    for d in (1, 2, 3):
                        if code[e - lo + d] in (0x88, 0x2E, 0xC3):
                            continue
                        one(mod, u, cs, lo, data, e + d, code, 0, "rt_stop_unknown",
                            f"entry {d} bytes into a cached cell", cold=False, edge=True)

        # A restore must be observed before another plant or exposure can hide
        # it. Exercise both the shared hook and an actual lowered byte store,
        # with all non-CS segments outside the code region throughout.
        e = entries[0]
        q = e - lo
        force = dict(ds=0x3000, es=0x3000, ss=0x3000, sp=0x8000, bx=0x1000, ax=0x5A)
        for lowered in (False, True):
            code = bytearray(images[0])
            code[q:q + 13] = bytes.fromhex("888700008887010088870200c3")
            one(mod, u, cs, lo, code, e, code, 4, "T_RET", "restore control warms", force=force)
            code[q + 4] = 0xC3
            hook(wl, code_at, code, q + 4)
            one(mod, u, cs, lo, code, e, code, 2, "T_RET", "restore control planted",
                cold=False, force=force)
            code[q + 4] = 0x88
            if lowered:
                assert any(site_store("reg", u.ip_of(e) + 4, 0x88, code_at, code)
                           for _ in range(32)), "no lowered register restore exercised"
            else:
                hook(wl, code_at, code, q + 4)
            one(mod, u, cs, lo, code, e, code, 4, "T_RET",
                f"restore control restored ({'lowered' if lowered else 'hook'})",
                cold=False, force=force)

        # A zero store just before the region has hook index zero, also the
        # invalid-cache tag. It must not revive records retained after exposure.
        # The neighbouring lower and upper addresses are outside-region controls.
        size = smc.span(u.ip_of(lo), u.ip_of(hi))
        for delta in (-2, -1, size, size + 1):
            code = bytearray(images[0])
            code[q:q + 13] = bytes.fromhex("888700008887010088870200c3")
            one(mod, u, cs, lo, code, e, code, 4, "T_RET", "boundary control warms", force=force)
            run_aux(addr["smc_expose"], {}, [], {})
            code[q + 2:q + 4] = b"\x10\x00"  # unseen patch while the cache is invalid
            assert any(site_store("reg", u.ip_of(lo) + delta, 0, code_at, code)
                       for _ in range(32)), "no lowered zero store exercised"
            one(mod, u, cs, lo, code, e, code, 4, "T_RET",
                f"zero store outside region at {delta}", cold=False, force=force)


def walk_entry(u, run, reg: str) -> dict | None:
    """Entry registers that bring `reg` to a chosen value at the block's last
    instruction: {"target": entry register to set, others: 0}, through mov and
    add/sub of registers; None for any other writer."""
    force = {}
    for o in reversed(run[:-1]):
        i = u.insns[o]
        if not i.operands or not isinstance(i.operands[0], Reg) or i.operands[0].name != reg:
            continue
        src = i.operands[1] if len(i.operands) > 1 else None
        if i.op == "mov" and isinstance(src, Reg) and src.width == 16:
            reg = src.name
        elif i.op in ("add", "sub") and isinstance(src, Reg) and src.name != reg:
            force[src.name] = 0
        else:
            return None
    return dict(force, target=reg)


PROBE = D.STUB + 0x800  # move.w ccr,(PROBE+$100).l: the CCR the CPU computes


def ccr_at_stop(m) -> int:
    """The 68k CCR where the run stopped. Unicorn's SR register read can miss
    lazily computed condition codes, so a probe instruction stores the CCR."""
    m.e.write(PROBE, bytes.fromhex("42f9") + (PROBE + 0x100).to_bytes(4, "big"))
    saved = m.extra_stops, m.inside
    m.extra_stops, m.inside, m.entry = {}, set(), None
    m.e.start(PROBE, PROBE + 6, 1)
    m.extra_stops, m.inside = saved
    return int.from_bytes(m.e.read(PROBE + 0x100, 2), "big") & 0x1F


def cross_entry_cases():
    from cross_flags_cases import run
    n, bad, _stats = run()
    return n, bad


def flag_helper_entries():
    """R18: POPF and IRET callers, then both predecessors of the DF block.

    IF clear takes the helper's branch; IF set falls through IRQ re-arming.
    TF, DF and CF vary independently; the original x86 is the oracle.
    """
    h = D.Harness(18)
    for opcode in (0x9d, 0xcf):
        for bits in range(16):
            word = 0xf8d6 | (bits & 1) | ((bits >> 1) << 8)
            stack = word.to_bytes(2, "little")
            if opcode == 0xcf:
                stack = bytes.fromhex("00020020") + stack
            h.case(bytes([opcode]), "b:flag-helper-entry", overrides={
                "regs": dict(cs=0x2000, ss=0x7000, sp=0x100), "ip": 0x100,
                "mem": [(0x70100, stack)]})
    h.flush()
    result = sum(h.count.values()), list(h.bad)
    D.Harness.tidy()
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--blocks", type=int, default=0, help="sample size (0: every block)")
    ap.add_argument("--states", type=int, default=2)
    ap.add_argument("--only", default="", help="MODULE+offset of one block (prints its code)")
    ap.add_argument("--walks", type=int, default=40, help="walk cases per region image")
    args = ap.parse_args(argv)
    p = emit.Program()
    mods = image.load()
    cache = image.REPO / "tmp/m68k"
    cache.mkdir(parents=True, exist_ok=True)
    img, addr = program_image(p, cache)
    by_addr: dict[int, list[str]] = {}
    aux = set(aux_labels(p))
    for x, a in addr.items():
        if not x.endswith(("_bpg", "_bpr")) and x not in aux:   # R6 guards run inside a block
            by_addr.setdefault(a, []).append(x)
    stop_names = {a: xs[0] for a, xs in by_addr.items()}
    text_next = {}
    for mod in p.units:
        offs = sorted(p.units[mod].insns)
        for o, nx in zip(offs, offs[1:]):
            text_next[(mod, o)] = addr[emit.label(mod, nx)]
    node_of = {emit.label(m, o): (m, o) for m in p.units for o in p.units[m].insns}
    copy_next = {}
    for _ws, _starts, nodes, _rng in p.comps:
        ns = sorted(nodes)
        node_of.update((emit.copy_label(*n), n) for n in ns)
        copy_next.update((a, addr[emit.copy_label(*b)]) for a, b in zip(ns, ns[1:]))
    executed = M.executed(M.runs())
    allb = list(blocks(p, executed))
    rng = random.Random(args.seed)
    picks = rng.sample(allb, min(args.blocks or len(allb), len(allb)))
    if args.only:
        mo, of = args.only.split("+")
        picks = [b for b in allb if b[0] == mo and b[1][0] == int(of, 16)]
        lines, _ = p.module_text(mo)
        first = emit.label(mo, picks[0][1][0])
        k = lines.index(next(x for x in lines if x.startswith(first + ":")))
        print("\n".join(lines[k:k + 400]).split(emit.label(mo, picks[0][1][-1]) + ":")[0][-6000:])
    h = X.Harness(args.seed)
    upper_rng = random.Random(5)
    m = D.M68k(h.bg, STUB_AT)
    m.load(img)
    reloc = {name: relocated(mods[name]) for name in p.units}
    count, bad, skipped, exits = Counter(), [], Counter(), Counter()
    walks_at = {emit.walk_label(mo, lo) for mo, lo, _ in p.smc_forms}

    def block_cases(mod, run, states, force=None, posted=None, copy=False, memory=(), expected=None,
                    forced_flags=None):
        """`states` cases of one block; `force`: registers set after the random
        state; `posted` (at a poll point): an interrupt posted, rt_irq modelled as
        taking it ("taken") or as the bench watch leaving it set ("watch"); the
        poll must call it once with its CS:IP. `memory` adds fixture bytes;
        `expected` additionally requires the named generated entry."""
        u = p.units[mod]
        data = reloc[mod]
        last = u.insns[run[-1]]
        lo, hi = run[0], run[-1] + last.size
        code = bytes(data[lo:hi])
        cs = (LOADSEG + u.cs[run[0]]) & 0xFFFF
        ip = u.insns[run[0]].ip
        lab = emit.copy_label if copy else emit.label
        # first address after the block's code
        end = (copy_next if copy else text_next).get((mod, run[-1]))
        m.inside = {addr[lab(mod, o)] for o in run[1:]} - {end}
        m.extra_stops = stops = stop_names
        empty = end == addr[lab(mod, run[0])]  # lowers to no code (bra to next)
        for _ in range(states):
            regs, flags, flagsx, _ = h.state({"regs": {"cs": cs}, "ip": ip})
            # keep CX small so REP blocks stay short
            regs["cx"] &= 0x3F
            regs.update(force or {})
            flags.update(forced_flags or {})
            patches = list(memory)
            sp_lin = regs["ss"] * 16 + regs["sp"]
            stack = bytearray(h.rng.randrange(256) for _ in range(8))
            for k in (1, 3, 5, 7):
                stack[k] &= 0xFE
            patches.append((sp_lin, bytes(stack)))
            patches.append((cs * 16 + ip, code))
            case = (regs, flags, flagsx, ip, patches)
            s = State(dict(regs, flagsx=flagsx), dict(flags), h.mem, ip)
            s.port_in = lambda port, w: X.port_value(port, w // 8)
            for a, d in patches:
                h.mem[a:a + len(d)] = d
            try:
                for _k in range(len(run)):
                    ex, _i = step(s)
                    if ex.kind in ("int", "fault"):
                        break
            except (UndefinedFlag, DecodeError) as e:
                skipped["IR reads an undefined flag" if isinstance(e, UndefinedFlag)
                        else "block rewrites its own bytes"] += 1
                h.reset(patches, s.writes, set())
                continue
            undef = set(s.undef)
            h.reset(patches, s.writes, set())
            err, out, fl, umem, ints, outs, uwrites = h.oracle.run(case, len(run))
            if set(range(cs * 16 + ip, cs * 16 + ip + len(code))) & uwrites:
                skipped["writes its own code"] += 1
                h.oracle.restore(uwrites | {a for a0, d in patches for a in range(a0, a0 + len(d))})
                continue
            if last.op in ("retf",) and regs["sp"] >= 0xFFF0:
                skipped["oracle: retf SP wrap"] += 1
                h.oracle.restore(uwrites | {a for a0, d in patches for a in range(a0, a0 + len(d))})
                continue
            umem = {a: umem.get(a, h.oracle.e.read(a, 1)[0]) for a in set(umem) | uwrites}
            h.oracle.restore(uwrites | {a for a0, d in patches for a in range(a0, a0 + len(d))})
            entry = addr[lab(mod, run[0])]
            if posted:
                m.irq_calls, m.irq_keep = [], posted == "watch"
            mo, mf, mfx, mmem, mouts, mwrites, info = m.run(entry, case, h.rng,
                                                            skip_entry=not empty, irq=False,
                                                            posted=bool(posted))
            calls, m.irq_calls = m.irq_calls, None
            stop = info["stop"]
            pc = m.r("pc")
            if stop in node_of:  # labels sharing the address: take the one x86 reached
                for x in by_addr[pc]:
                    nd = node_of.get(x)
                    if nd and (LOADSEG + p.units[nd[0]].cs[nd[1]]) & 0xFFFF == out["cs"] and \
                            p.units[nd[0]].insns[nd[1]].ip == out["ip"]:
                        stop = x
                        break
            diffs = []
            if expected is not None and stop != expected:
                diffs.append(f"required entry {expected}, reached {stop}")
            if info["err"]:
                diffs.append(f"68k error {info['err']} stop={stop} pc={pc:x}")
            diffs += info["irq"]
            if posted and calls != [(cs << 16, ip)]:
                diffs.append(f"poll: rt_irq calls {[(hex(a), hex(b)) for a, b in calls]}, "
                             f"want one with d6={cs << 16:x} d7={ip:x}")
            # successor reached
            exc = ints[0] if ints else None
            live: set = set()
            if stop in node_of:
                node = node_of[stop]
                su = p.units[node[0]]
                mcs, mip = (LOADSEG + su.cs[node[1]]) & 0xFFFF, su.insns[node[1]].ip
                live = p.live_in[node]
                exits["label"] += 1
            elif stop == "T_RET":
                mip = info["d7"]
                mcs = info["d6"] if last.op in ("retf", "iret") else cs
                live = p.ret_live_of((mod, run[-1])) if last.op != "iret" else set()
                exits["ret"] += 1
            elif stop in ("rt_dispatch_near", "rt_dispatch_far"):
                mip = info["d7"]
                mcs = info["d6"] if stop == "rt_dispatch_far" else cs
                live = set(p.unknown_live)
                exits["dispatch"] += 1
            elif stop in ("rt_int", "rt_fault"):
                mip, mcs = info["d7"], info["d6.l"] >> 16  # d6 = CS << 16 | vector
                live = p.live_out[(mod, run[-1])] if stop == "rt_int" else set()
                exits[stop] += 1
                if exc is None or info["d6"] != exc:
                    diffs.append(f"vector 68k={info['d6']} x86={exc}")
            elif stop in walks_at:  # call into a self-modified region (D16)
                mip, mcs = info["d7"], cs
                live = p.live_out[(mod, run[-1])]  # the walk reads no flags (smc.py)
                exits["walk"] += 1
            elif stop == "rt_stop_unknown":
                mip, mcs = info["d7"], cs
                exits["stop"] += 1
            else:
                diffs.append(f"stopped at {stop} pc={pc:x}")
                mip, mcs = -1, -1
            if stop not in ("rt_int", "rt_fault") and exc is not None:
                diffs.append(f"x86 raised {exc}, 68k {stop}")
            if mip != out["ip"] and stop != "rt_stop_unknown":
                diffs.append(f"ip 68k={mip:04x} x86={out['ip']:04x} ({stop})")
            if mcs != out["cs"] and stop != "rt_stop_unknown":
                diffs.append(f"cs 68k={mcs:04x} x86={out['cs']:04x}")
            for r in D.REGS:
                if mo[r] != out[r]:
                    diffs.append(f"{r} 68k={mo[r]:04x} x86={out[r]:04x}")
            for sname in ("es", "ss", "ds"):
                if mo[sname] != out[sname]:
                    diffs.append(f"{sname} 68k={mo[sname]:04x} x86={out[sname]:04x}")
            # flags a jump chain holds only in the CCR at the stop (R14d)
            if p.ccr_only.get(stop):
                ccr = ccr_at_stop(m)
                for f in p.ccr_only[stop]:
                    mf[f] = int(bool(ccr & CCR_BIT[f]))
            for f in sorted(live - undef):
                if mf[f] != fl >> FLAG_BIT[f] & 1:
                    diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
            for f in ("DF", "IF"):
                if mf[f] != fl >> FLAG_BIT[f] & 1:
                    diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
            patched = {a: d[a - a0] for a0, d in patches for a in range(a0, a0 + len(d))}
            for a in sorted(set(umem) | mwrites):
                want = umem.get(a, patched.get(a, h.bg[a]))
                got = mmem.get(a, m.gread(a, 1)[0])
                if got != want:
                    diffs.append(f"mem {a:05x} 68k={got:02x} x86={want:02x}")
                    break
            if mouts != outs:
                diffs.append(f"out 68k={mouts} x86={outs}")
            # return protocol after a call
            if (stop in node_of or stop in walks_at or stop == "rt_dispatch_near") \
                    and last.op in ("call", "callf") and not diffs:
                ret_ip = last.next_ip + (2 if run[-1] in u.manager_calls else 0)
                site = emit.label(mod, run[-1] + last.size + (2 if run[-1] in u.manager_calls else 0))
                if copy and site + "_bp" in addr:   # past the guard after the call (BP in range)
                    site += "_bp"
                # popped IP/CS with undefined upper words (speed-plan R4, R5)
                for good, bad_cs in ((True, False), (False, False)) + \
                        (((False, True),) if last.op == "callf" else ()):
                    a7 = m.r("a7")
                    native = int.from_bytes(m.e.read(a7, 4), "big")
                    m.e.reg_write(U.M68K["a7"], a7 + 4)
                    popped = ret_ip if good or bad_cs else ret_ip ^ 0x55
                    m.e.reg_write(U.M68K["d7"], upper_rng.randrange(0x10000) << 16 | popped)
                    m.e.reg_write(U.M68K["d6"], upper_rng.randrange(0x10000) << 16
                                  | (cs ^ 0x55 if bad_cs else cs))
                    m.extra_stops = {addr[site]: site} if site in addr else {}
                    saved_inside, m.inside = m.inside, set()
                    m.stop, m.entry = None, None
                    m.e.start(native, 0xFFFFFFFF, 1000)
                    want = site if good else "rt_ret_mismatch"
                    if m.stop != want:
                        diffs.append(f"return protocol: {'right' if good else 'wrong'} "
                                     f"{'CS' if bad_cs else 'IP'} reached {m.stop}, want {want}")
                    m.e.reg_write(U.M68K["a7"], a7)
                    m.e.write(a7, native.to_bytes(4, "big"))
                    m.inside = saved_inside
                count["return checks"] += 1
                m.extra_stops = stops
            count[mod] += 1
            if diffs:
                st = " ".join(f"{k}={v:04x}" for k, v in regs.items())
                bad.append(f"{mod}+{run[0]:05X}..{run[-1]:05X} [{st}]: {'; '.join(diffs[:6])}")
            m.restore(set(mwrites) | set(patched))

    for mod, run in picks:
        block_cases(mod, run, args.states)
    # R6: every executed block of a guarded copy with BP at both ends of the
    # range its guard admits and inside it; every guard just inside and outside
    if not args.only:
        for _ws, starts, nodes, rng in p.comps:
            bmin, bmax = 0x7FFF - rng[1], 0x7FFF - rng[0]
            for mod, run in copy_blocks(p, nodes, executed):
                for bp in (bmin, bmax, h.rng.randrange(bmin, bmax + 1)):
                    block_cases(mod, run, 1, {"bp": bp}, copy=True)
                count["copy blocks"] += 1
            guards = [(f"{emit.label(*n)}_bpg", n) for n in sorted(starts)]
            guards += [(f"{emit.label(*p.fall[n])}_bpr", p.fall[n]) for n in sorted(nodes)
                       if p.node_insn(n).op in region.REGUARD and p.fall.get(n) in nodes]
            for g, n in guards:
                fast, exact = emit.copy_label(*n), emit.label(*n)
                for bp in sorted({bmin - 1, bmin, bmax, bmax + 1} & set(range(0x10000))):
                    want = fast if bmin <= bp <= bmax else exact
                    m.e.reg_write(U.M68K["d5"], upper_rng.randrange(0x10000) << 16 | bp ^ 0x7FFF)
                    m.extra_stops = {addr[fast]: fast, addr[exact]: exact}
                    m.inside, m.stop, m.entry = set(), None, None
                    m.e.start(addr[g], 0xFFFFFFFF, 1000)
                    if m.stop != want:
                        bad.append(f"guard {g} at BP {bp:04x} (admits {bmin:04x}..{bmax:04x}) "
                                   f"reached {m.stop}, want {want}")
                    count["guard decisions"] += 1
        m.extra_stops = stop_names
    if not args.only:
        n, wbad = walks(p, h, m, addr, stop_names, args.walks)
        count["walks"] += n
        bad += wbad
    n, failures = cross_entry_cases()
    count["cross predecessors"] += n
    bad += failures
    n, failures = flag_helper_entries()
    count["flag helper predecessors"] += n
    bad += failures
    # every executed indirect call or jump through a register that can enter a
    # self-modified region, with the register in each region (walk entry)
    if not args.only:
        for mod, run in allb:
            i = p.units[mod].insns[run[-1]]
            if i.op in ("call", "jmp") and isinstance(i.operands[0], Reg):
                for lo, hi, _walk in p.ctx(mod, run[-1], Counter()).smc_targets:
                    force = walk_entry(p.units[mod], run, i.operands[0].name)
                    if force:
                        force[force.pop("target")] = h.rng.randrange(lo, hi + 1)
                        block_cases(mod, run, 2, force)
    # every executed block at a poll point with an interrupt posted (R2)
    polls = Counter()
    if not args.only:
        before = Counter(count)
        for mod, run in allb:
            if (mod, run[0]) in p.loop_heads:
                for posted in ("taken", "watch"):
                    block_cases(mod, run, 1, posted=posted)
        polls = count - before
        count -= polls
    # Regression: the original's CS:A2B2 table, including every untraced row.
    # Enter at the call so SI selects each word; compare the x86 transfer and
    # require a generated entry, not merely a dispatcher with matching CS:IP.
    if not args.only:
        mod, site, table = M.ROOT, 0xEC5B, 0xEC62
        u = p.units[mod]
        cs = LOADSEG + u.cs[site]
        words = bytes(reloc[mod][table:table + 16])
        for k in range(8):
            target = u.off_of(u.cs[site], int.from_bytes(words[2*k:2*k+2], "little"))
            block_cases(mod, [site], 2, {"si": 2*k},
                        memory=[(cs*16 + 0xA2B2, words)], expected=emit.label(mod, target))
    # The table discovers eight routine bodies: exercise every block, including
    # rows not selected by the recorded demo, against original x86 bytes.
    if not args.only:
        discovered = {M.ROOT: set(range(0xEC72, 0xEE71))}
        for mod, run in blocks(p, discovered):
            block_cases(mod, run, 2)
    # Untraced call-DX sites in the same CS must also reach the cell walk.
    # Include both range edges (annotations/self-modifying.csv), the reported
    # entry, and both fallback edges.
    if not args.only:
        mod = M.ROOT
        (first, last), = image.smc_regions()[mod]
        lo, hi = p.units[mod].ip_of(first), p.units[mod].ip_of(last)
        for site in (0x4F7B, 0x50A5, 0xEC17):
            for target in (lo - 1, lo, 0x2BDE, hi, hi + 1):
                want = (emit.walk_label(mod, first) if lo <= target <= hi
                        else "rt_dispatch_near")
                block_cases(mod, [site], 2, {"dx": target}, expected=want)
    # Item 14: every curated table row, then every reachable generated block.
    # Read the actual table words, not the translator's target list, for the
    # required entry. Unknown/return/SMC exits remain checked by block_cases.
    if not args.only:
        roots = set()
        table_rows = 0
        for row in image.rows("tables.csv"):
            mod, site = row["module"], int(row["site"], 16)
            u = p.units[mod]
            operand = u.insns[site].operands[0]
            assert operand.seg == "cs" and operand.width == 16
            assert operand.base and not operand.index
            entries = int(row["entries"])
            offset = u.off_of(u.cs[site], operand.disp)
            words = bytes(reloc[mod][offset:offset + 2 * entries])
            assert len(words) == 2 * entries
            targets = set()
            for k in range(entries):
                target = (mod, u.off_of(u.cs[site], int.from_bytes(words[2*k:2*k+2], "little")))
                targets.add(target)
                before = count[mod]
                block_cases(mod, [site], 2, {operand.base: 2*k},
                            memory=[((LOADSEG + u.cs[site])*16 + operand.disp, words)],
                            expected=emit.label(*target))
                assert count[mod] - before == 2, ("table row not compared", row, k)
                table_rows += 1
            assert targets == set(p.succ[(mod, site)]), ("table target set", row)
            roots.update(targets)
        reached, todo = set(), list(roots)
        while todo:
            node = todo.pop()
            if node in reached:
                continue
            reached.add(node)
            successors = list(p.succ[node])
            if p.node_insn(node).op in ("call", "callf"):
                successors.append(p.fall[node])
            todo.extend(n for n in successors if n in p.succ and n not in reached)
        discovered = {mod: {off for m, off in reached if m == mod} for mod in p.units}
        table_blocks = list(blocks(p, discovered))
        for mod, run in table_blocks:
            before = count[mod]
            block_cases(mod, run, 2)
            assert count[mod] > before, ("table block not compared", mod, run[0])
        print(f"annotated tables: {table_rows} rows, {len(roots)} targets, "
              f"{sum(off not in executed.get(mod, ()) for mod, off in roots)} untraced targets, "
              f"{len(table_blocks)} reachable blocks checked")
    # R21: every emitted string entry, including guarded copies, can enter
    # either direction body and must return to its own continuation. Existing
    # whole-block cases above retain the original incoming guest edges.
    if not args.only:
        for mod, u in p.units.items():
            for off, insn in u.insns.items():
                if insn.op not in ("movs", "cmps", "stos", "lods", "scas"):
                    continue
                copies = [False] + ([True] if emit.copy_label(mod, off) in addr else [])
                for copy in copies:
                    for df in (0, 1):
                        for cx in (0, 3):
                            block_cases(mod, [off], 1,
                                        {"cx": cx, "si": 0xFFFF, "di": 0xFFFF,
                                         "ds": 0x5000, "es": 0x6000}, copy=copy,
                                        forced_flags={"DF": df})
    # R22: every affected call entry and every guard edge. The complete
    # predecessor blocks above still enter with their own live flag contracts.
    if not args.only:
        for mod, u in p.units.items():
            for off, insn in u.insns.items():
                ctx = p.ctx(mod, off, Counter())
                if insn.op != "call" or not ctx.smc_targets:
                    continue
                operand = insn.operands[0]
                for lo, hi, walk in ctx.smc_targets:
                    for target in sorted({0, lo-1, lo, hi, hi+1, 0xFFFF}):
                        if not 0 <= target <= 0xFFFF:
                            continue
                        force, memory = {"ss": 0x7000, "sp": 0x1000}, []
                        if isinstance(operand, Reg):
                            force[operand.name] = target
                        else:
                            assert isinstance(operand, Mem)
                            force.update({r: 0 for r in (operand.base, operand.index) if r})
                            if operand.seg != "cs":
                                force[operand.seg] = 0x5000
                            seg = ((LOADSEG + u.cs[off]) & 0xFFFF) if operand.seg == "cs" else 0x5000
                            memory = [(seg*16+operand.disp, target.to_bytes(2, "little"))]
                        expected = next((wl for a, b, wl in ctx.smc_targets if a <= target <= b), None)
                        if expected is None:
                            expected = ctx.near(target) if target in ctx.near_targets else None
                            expected = expected or ("rt_stop_unknown" if ctx.complete else "rt_dispatch_near")
                        block_cases(mod, [off], 1, force, memory=memory, expected=expected)
                        if emit.copy_label(mod, off) in addr:
                            block_cases(mod, [off], 1, force, memory=memory, expected=expected, copy=True)
    total = sum(v for k, v in count.items() if k != "return checks")
    print(f"blocks {len(picks)} of {len(allb)} executed; cases {total}", dict(count))
    print(f"poll cases {sum(polls.values()) - polls['return checks']} (interrupt posted)")
    print("exits", dict(exits))
    if skipped:
        print("not compared:", dict(skipped))
    for b in bad[:30]:
        print(b)
    print(f"{len(bad)} mismatches")
    return 1 if bad or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
