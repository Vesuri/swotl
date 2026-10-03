#!/usr/bin/env python3
"""Block differential of the generated program (gate 4, step 4.2): the module code
as `make gen` emits it (program mode: real labels, fused flags, liveness-elided
stores, return checks, compare chains), run from traced block entries in
Unicorn 68020 against the original bytes in Unicorn x86-16.

A block runs from an executed leader to its first transfer (or the next
leader). The 68k side stops at the first label outside the block or at a
runtime entry. Compared: registers, segment registers, written bytes, OUT
sequence, interrupt/fault, the successor reached (CS:IP), and the flags live
at that successor (flags.py; undefined ones masked by the IR). Calls also check
the return protocol: resuming at the native return address with the right
guest IP reaches the return site, with a wrong one rt_ret_mismatch.
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
import uc as U  # noqa: E402
import x86_diff as X  # noqa: E402
from translator import emit, image  # noqa: E402
from translator.decode import DecodeError  # noqa: E402
from translator.interp import State, UndefinedFlag, step  # noqa: E402
from translator.ir import FLAG_BIT, STATUS  # noqa: E402
from translator.lower import LOADSEG  # noqa: E402
from translator.support import HELPERS, equates  # noqa: E402

M = image.M
STUBS = emit.RUNTIME + ("T_RET",)
STUB_AT = {n: D.STUB + 4 * k for k, n in enumerate(STUBS)}
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
    src = [equates()] + [f"{n}\tequ\t${a:x}" for n, a in STUB_AT.items()]
    src += [f"\torg\t${D.CODE:x}", "labels:"] + [f"\tdc.l\t{x}" for x in order]
    src += body + [HELPERS]
    text = "\n".join(src) + "\n"
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    out = cache / f"program-{key}.bin"
    image_ = out.read_bytes() if out.exists() else D.assemble(text, out)
    addr = {x: int.from_bytes(image_[4 * k:4 * k + 4], "big") for k, x in enumerate(order)}
    return image_, addr


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--blocks", type=int, default=0, help="sample size (0: every block)")
    ap.add_argument("--states", type=int, default=2)
    ap.add_argument("--only", default="", help="MODULE+offset of one block (prints its code)")
    args = ap.parse_args(argv)
    p = emit.Program()
    mods = image.load()
    cache = image.REPO / "tmp/m68k"
    cache.mkdir(parents=True, exist_ok=True)
    img, addr = program_image(p, cache)
    by_addr: dict[int, list[str]] = {}
    for x, a in addr.items():
        by_addr.setdefault(a, []).append(x)
    stop_names = {a: xs[0] for a, xs in by_addr.items()}
    text_next = {}
    for mod in p.units:
        offs = sorted(p.units[mod].insns)
        for o, nx in zip(offs, offs[1:]):
            text_next[(mod, o)] = addr[emit.label(mod, nx)]
    node_of = {emit.label(m, o): (m, o) for m in p.units for o in p.units[m].insns}
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
    m = D.M68k(h.bg, STUB_AT)
    m.load(img)
    reloc = {name: relocated(mods[name]) for name in p.units}
    count, bad, skipped, exits = Counter(), [], Counter(), Counter()
    for mod, run in picks:
        u = p.units[mod]
        data = reloc[mod]
        last = u.insns[run[-1]]
        lo, hi = run[0], run[-1] + last.size
        code = bytes(data[lo:hi])
        cs = (LOADSEG + u.cs[run[0]]) & 0xFFFF
        ip = u.insns[run[0]].ip
        end = text_next.get((mod, run[-1]))  # first address after the block's code
        m.inside = {addr[emit.label(mod, o)] for o in run[1:]} - {end}
        m.extra_stops = stops = stop_names
        empty = end == addr[emit.label(mod, run[0])]  # lowers to no code (bra to next)
        for _ in range(args.states):
            regs, flags, flagsx, _ = h.state({"regs": {"cs": cs}, "ip": ip})
            # keep CX small so REP blocks stay short
            regs["cx"] &= 0x3F
            patches = []
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
            entry = addr[emit.label(mod, run[0])]
            mo, mf, mfx, mmem, mouts, mwrites, info = m.run(entry, case, h.rng,
                                                            skip_entry=not empty)
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
            if info["err"]:
                diffs.append(f"68k error {info['err']} stop={stop} pc={pc:x}")
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
                if mo[r] & 0xFFFF != out[r]:
                    diffs.append(f"{r} 68k={mo[r] & 0xFFFF:04x} x86={out[r]:04x}")
                if mo[r] >> 16:
                    diffs.append(f"{r} upper {mo[r] >> 16:04x}")
            for sname in ("es", "ss", "ds"):
                if mo[sname] != out[sname]:
                    diffs.append(f"{sname} 68k={mo[sname]:04x} x86={out[sname]:04x}")
            for f in sorted(live - undef):
                if mf[f] != fl >> FLAG_BIT[f] & 1:
                    diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
            for f in ("DF", "IF"):
                if mf[f] != fl >> FLAG_BIT[f] & 1:
                    diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
            patched = {a: d[a - a0] for a0, d in patches for a in range(a0, a0 + len(d))}
            for a in sorted(set(umem) | mwrites):
                want = umem.get(a, patched.get(a, h.bg[a]))
                got = mmem.get(a, m.e.read(D.GUEST + a, 1)[0])
                if got != want:
                    diffs.append(f"mem {a:05x} 68k={got:02x} x86={want:02x}")
                    break
            if mouts != outs:
                diffs.append(f"out 68k={mouts} x86={outs}")
            # return protocol after a call
            if stop in node_of and last.op in ("call", "callf") and not diffs:
                ret_ip = last.next_ip + (2 if run[-1] in u.manager_calls else 0)
                site = emit.label(mod, run[-1] + last.size + (2 if run[-1] in u.manager_calls else 0))
                for good in (True, False):
                    a7 = m.r("a7")
                    native = int.from_bytes(m.e.read(a7, 4), "big")
                    m.e.reg_write(U.M68K["a7"], a7 + 4)
                    m.e.reg_write(U.M68K["d7"], ret_ip if good else ret_ip ^ 0x55)
                    m.e.reg_write(U.M68K["d6"], cs)
                    m.extra_stops = {addr[site]: site} if site in addr else {}
                    saved_inside, m.inside = m.inside, set()
                    m.stop, m.entry = None, None
                    m.e.start(native, 0xFFFFFFFF, 1000)
                    want = site if good else "rt_ret_mismatch"
                    if m.stop != want:
                        diffs.append(f"return protocol: {'right' if good else 'wrong'} IP "
                                     f"reached {m.stop}, want {want}")
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
    total = sum(v for k, v in count.items() if k != "return checks")
    print(f"blocks {len(picks)} of {len(allb)} executed; cases {total}", dict(count))
    print("exits", dict(exits))
    if skipped:
        print("not compared:", dict(skipped))
    for b in bad[:30]:
        print(b)
    print(f"{len(bad)} mismatches")
    return 1 if bad or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
