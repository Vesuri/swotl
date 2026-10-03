"""Program mode: global flag liveness, block leaders and the 68020 `.s` of every
module (Motorola syntax, vasm). Generated text is G1-guarded like the IR listing.

Successors: fall-through (a PLINK manager call returns 2 bytes later), direct
near/far targets (cfg), statically resolved switch tables; a `ret`/`retf`
continues at the return sites of the calls whose targets reach it without
crossing a call (native rts; a mismatch stops; calls through the dispatcher
return from any ret a seed reaches; a ret no call target reaches falls back
to every return site), an
unresolved indirect transfer at some row of the runtime dispatch table (the
cfg seeds: MZ entry, PLINK thunks, runtime.csv, indirect.csv targets; any
other target stops), so each sees the live-in union of that set; a divide
error continues in the guest INT 00h handler; flow into self-modified code
sees every flag live; an annotated PUSHF/POPF save reads what is live after
its POPF. Leaders: seeds, call and far targets, transfer targets, return
sites and starts without a fall-through predecessor.
"""

from __future__ import annotations

from collections import Counter

from . import cfg, image
from .decode import Far, Rel
from .flags import ALL, plan, transfer
from .lower import Ctx, LowerError, hx

M = image.M
TAG = {"SWOTL.EXE": "R", "SPAZ.OVL": "SPZ", "RTSVGA.OVL": "VGA", "FRONTEND.OVL": "FE",
       "CAMPAIGN.OVL": "CMP", "NOTCAMP.OVL": "NCP", "FLIGHT.OVL": "FLT", "REPLAY.OVL": "RPL",
       "PANEL.OVL": "PNL", "DATA.OVL": "DAT"}
RET, UNKNOWN, SMC = "ret", "unknown", "smc"
TERMINAL = {"jmp", "jmpf", "ret", "retf", "iret", "hlt"}
RUNTIME = ("rt_int", "rt_fault", "rt_halt", "rt_in8", "rt_in16", "rt_out8", "rt_out16",
           "rt_ret_mismatch", "rt_dispatch_near", "rt_dispatch_far", "rt_stop_unknown")


def label(mod: str, off: int) -> str:
    return f"{TAG[mod]}_{off:05X}"


def smc_label(mod: str, off: int) -> str:
    return f"{TAG[mod]}_{off:05X}_smc"


def stop_label(mod: str, off: int) -> str:
    return f"{TAG[mod]}_{off:05X}_stop"


def cs_expr(cs: int) -> str:
    return f"LOADSEG+{hx(cs)}"


class Program:
    def __init__(self, units: dict[str, cfg.Unit] | None = None):
        self.units = units or cfg.build()
        self.indirect: dict[tuple[str, int], tuple[list, list]] = {}
        for r in image.rows("indirect.csv"):
            def parse(col):
                return [(t.split("+")[0], int(t.split("+")[1], 16)) for t in r[col].split()
                        if t != "(isr)"]
            self.indirect[(r["module"], int(r["offset"], 16))] = (parse("switch_targets"),
                                                                  parse("traced_targets"))
        self.succ: dict[tuple[str, int], list] = {}
        self.fall: dict[tuple[str, int], tuple[str, int] | None] = {}
        self.ret_sites: set[tuple[str, int]] = set()
        self.calls: list[tuple[tuple[str, int], tuple[str, int], list]] = []  # node, site, targets
        self.seeds = {(n, off) for n, u in self.units.items() for off in u.seeds}
        self.entries: set = set(self.seeds)
        # run-time dispatch table rows: the static seeds (cfg.seeds)
        self.dispatch = {(m, o) for m, o, _ in cfg.seeds(image.load())
                         if m in self.units and o in self.units[m].insns}
        # PUSHF ... POPF pairs that only save and restore FLAGS (annotations/flags.csv):
        # the save reads what is live after the restore.
        self.saves = {(r["module"], int(r["save"], 16)): (r["module"], int(r["restore"], 16))
                      for r in image.rows("flags.csv")}
        int0 = [r for r in image.rows("runtime.csv") if r["name"] == "__cintDIV"]
        self.int0 = (int0[0]["module"], int(int0[0]["offset"], 16)) if int0 else None
        self.build_edges()
        self.live_in: dict = {}
        self.live_out: dict = {}
        self.ret_of: dict = {}
        self.returns()
        self.liveness()
        self.leaders = self.find_leaders()

    # -- graph ----------------------------------------------------------------
    def node_insn(self, n):
        return self.units[n[0]].insns.get(n[1])

    def near_node(self, mod: str, off: int, ip: int):
        u = self.units[mod]
        return (mod, u.off_of(u.cs[off], ip))

    def build_edges(self) -> None:
        for mod, u in self.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                nxt = off + i.size + (2 if off in u.manager_calls else 0)
                fall = (mod, nxt) if i.op not in TERMINAL else None
                s: list = []
                op = i.op
                t = i.operands[0] if i.operands else None
                if op in ("ret", "retf"):
                    s = [RET]
                elif op in ("iret", "hlt"):
                    s = []
                elif isinstance(t, Rel):
                    s = [self.near_node(mod, off, t.target)]
                    if op == "call":
                        self.ret_sites.add((mod, nxt))
                        self.entries.add(s[0])
                elif op in ("jmpf", "callf"):
                    if isinstance(t, Far) and off in u.far_targets:
                        s = [u.far_targets[off]]
                        self.entries.add(s[0])
                    elif isinstance(t, Far):
                        s = []  # out-of-scope overlay: stops
                    else:
                        s = self.indirect_succ(mod, off, far=True)
                    if op == "callf":
                        self.ret_sites.add((mod, nxt))
                elif op in ("jmp", "call"):
                    s = self.indirect_succ(mod, off, far=False)
                    if op == "call":
                        self.ret_sites.add((mod, nxt))
                if op in ("call", "callf"):
                    self.calls.append((n, (mod, nxt), list(s)))
                if fall and op != "call" and op != "callf":
                    s = s + [fall]
                if (op in ("div", "idiv") or op == "aam" and i.operands[0].value == 0) \
                        and self.int0:
                    s = s + [self.int0]
                self.succ[n] = [x if x in (RET, UNKNOWN) or self.node_insn(x) else SMC
                                for x in s]
                self.fall[n] = fall if fall and self.node_insn(fall) else None

    def indirect_succ(self, mod: str, off: int, far: bool) -> list:
        sw, tr = self.indirect.get((mod, off), ([], []))
        self.entries.update(sw + tr)
        return list(sw) if sw else [UNKNOWN]

    def reach(self, t, cache: dict) -> tuple[set, bool]:
        """rets reachable from entry t without entering a call (a call continues at
        its return site), and whether an unresolved transfer leaves the walk."""
        if t in cache:
            return cache[t]
        seen, stack, rets, escapes = {t}, [t], set(), False
        call_site = self.call_site
        while stack:
            n = stack.pop()
            if self.node_insn(n).op in ("ret", "retf"):
                rets.add(n)
                continue
            # a call continues at its return site; the divide-error edge is an
            # interrupt (the INT 00h handler returns with IRET), not flow
            nexts = [call_site[n]] if n in call_site else self.succ[n]
            for x in nexts:
                if x == self.int0 and self.node_insn(n).op in ("div", "idiv", "aam"):
                    continue
                if x == UNKNOWN:
                    escapes = True
                elif x not in (RET, SMC) and x not in seen and x in self.succ:
                    seen.add(x)
                    stack.append(x)
        cache[t] = (rets, escapes)
        return cache[t]

    def returns(self) -> None:
        """ret node -> the return sites it can continue at."""
        self.call_site = {c: site for c, site, _ in self.calls}
        cache: dict = {}
        ret_of: dict = {}
        dynamic = set()  # return sites of calls that may run any dispatch-table entry
        for c, site, targets in self.calls:
            for t in targets:
                if t == UNKNOWN:
                    dynamic.add(site)
                    continue
                if t == SMC:
                    continue
                rets, escapes = self.reach(t, cache)
                for r in rets:
                    ret_of.setdefault(r, set()).add(site)
                if escapes:
                    dynamic.add(site)
        for e in self.dispatch:
            if e in self.succ:
                for r in self.reach(e, cache)[0]:
                    ret_of.setdefault(r, set()).update(dynamic)
        every = frozenset(self.ret_sites)
        self.ret_fallback = 0
        for n in self.succ:
            if self.node_insn(n).op in ("ret", "retf"):
                sites = ret_of.get(n)
                if not sites:
                    self.ret_fallback += 1
                self.ret_of[n] = tuple(sites) if sites else tuple(every)

    def ret_live_of(self, n) -> set:
        out = set()
        for r in self.ret_of[n]:
            out |= self.live_in.get(r, ALL)
        return out

    def liveness(self) -> None:
        nodes = sorted(self.succ, key=lambda n: (n[0], -n[1]))
        for n in nodes:
            self.live_in[n] = set()
        entries = [e for e in self.dispatch if e in self.live_in]
        changed = True
        while changed:
            changed = False
            unknown = set()
            for e in entries:
                unknown |= self.live_in[e]
            self.unknown_live = unknown
            for n in nodes:
                out = set()
                for s in self.succ[n]:
                    if s == RET:
                        out |= self.ret_live_of(n)
                    elif s == UNKNOWN:
                        out |= unknown
                    elif s == SMC:
                        out |= ALL
                    else:
                        out |= self.live_in[s]
                i = self.node_insn(n)
                new = transfer(i, out, program=True)
                if n in self.saves:
                    new = (new - ALL) | out | self.live_out.get(self.saves[n], set())
                self.live_out[n] = out
                if new != self.live_in[n]:
                    self.live_in[n] = new
                    changed = True

    def find_leaders(self) -> set:
        jump_preds = Counter()
        fall_preds = Counter()
        for n, ss in self.succ.items():
            for s in ss:
                if s in (RET, UNKNOWN, SMC):
                    continue
                if s == self.fall[n]:
                    fall_preds[s] += 1
                else:
                    jump_preds[s] += 1
        leaders = set(self.ret_sites) | self.entries
        for (mod, off), (sw, tr) in self.indirect.items():
            leaders.update(sw)
            leaders.update(tr)
        for n in self.succ:
            if jump_preds[n] or not fall_preds[n]:
                leaders.add(n)
        return leaders

    # -- generation -------------------------------------------------------------
    def dispatch_rows(self) -> list[tuple[int, int, int, str]]:
        """Run-time dispatch table: (link CS, IP, overlay id (root 0), label) of every
        decoded entry, sorted by CS:IP. Overlays sharing an area share CS:IP, so the
        runtime picks the row whose overlay is resident."""
        out = []
        for mod, off in self.dispatch:
            u = self.units.get(mod)
            if not u or off not in u.insns:
                continue
            out.append((u.cs[off], u.ip_of(off), u.module.index + 1, label(mod, off)))
        return sorted(out)

    def program_text(self, files: list[str]) -> str:
        """Assembly root of the Amiga/host link: equates, runtime imports, the module
        files and the dispatch table."""
        lines = ["\txref\t" + r for r in RUNTIME]
        lines += ["\txdef\tdispatch_table", "\txdef\tdispatch_count", "\txdef\tload_segment",
                  "\txdef\toverlay_table", "\tsection\t.text,code"]
        lines += [f'\tinclude\t"{f}"' for f in files]
        rows = self.dispatch_rows()
        lines += ["\tcnop\t0,4", "load_segment:\tdc.l\tLOADSEG",
                  f"overlay_table:\tdc.l\t{hx(M.OVL_TABLE)}\t; PLINK records, id 1 first (root offset)",
                  "dispatch_count:", f"\tdc.l\t{len(rows)}", "dispatch_table:"]
        lines += [f"\tdc.w\t{cs_expr(cs)},{hx(ip)},{oid},0\n\tdc.l\t{lab}"
                  for cs, ip, oid, lab in rows]
        return "\n".join(lines) + "\n"

    def ctx(self, mod: str, off: int, stats: Counter) -> Ctx:
        u = self.units[mod]
        i = u.insns[off]
        cs = u.cs[off]

        def near(ip):
            t = u.off_of(cs, ip)
            if t in u.insns:
                return label(mod, t)
            if t in u.smc_entries:
                return smc_label(mod, t)
            return None

        site = u.far_targets.get(off)

        def far(key):
            if key in far_map:
                return far_map[key]
            if site:
                return label(*site) if self.node_insn(site) else smc_label(*site)
            return stop_label(mod, off)

        far_map = {}
        near_t, far_t = (), ()
        sw, tr = self.indirect.get((mod, off), ([], []))
        if i.op in ("jmp", "call") and not isinstance(i.operands[0], Rel):
            near_t = tuple(self.units[m].ip_of(o) for m, o in sw + tr if m == mod)
        if i.op in ("jmpf", "callf") and not isinstance(i.operands[0], Far):
            keys = []
            for m, o in sw + tr:
                if m not in self.units or o not in self.units[m].insns:
                    continue
                k = (cs_expr(self.units[m].cs[o]), self.units[m].ip_of(o))
                far_map[k] = label(m, o)
                keys.append(k)
            far_t = tuple(keys)
        rel = frozenset(f - off for f in u.module.fixups if off <= f < off + i.size)
        return Ctx(cs=cs_expr(cs), label=label(mod, off), reloc=rel, near=near, far=far,
                   near_targets=near_t, complete=bool(sw), far_targets=far_t,
                   manager=off in u.manager_calls, program=True)

    def runs(self, mod: str) -> list[list[int]]:
        u = self.units[mod]
        out, cur = [], []
        for off in sorted(u.insns):
            if cur and (self.fall.get((mod, cur[-1])) != (mod, off)):
                out.append(cur)
                cur = []
            cur.append(off)
        if cur:
            out.append(cur)
        return out

    def module_text(self, mod: str) -> tuple[list[str], Counter]:
        u = self.units[mod]
        stats = Counter()
        lines: list[str] = []
        for run in self.runs(mod):
            insns = [u.insns[o] for o in run]
            lives = [self.live_out[(mod, o)] for o in run]
            leaders = {k for k, o in enumerate(run) if (mod, o) in self.leaders}
            try:
                lws = plan(insns, lives, leaders, lambda k: self.ctx(mod, run[k], stats),
                           program=True)
            except LowerError as e:
                raise LowerError(f"{mod}+{run[0]:05X} run: {e}") from None
            for o, lw in zip(run, lws):
                n = u.insns[o]
                lines.append(f"{label(mod, o)}:\t; {u.cs[o]:04X}:{n.ip:04X} {n}")
                lines.extend(lw.out)
                stats.update(lw.stats)
            # fall-through out of the run into something not decoded here
            last = run[-1]
            i = u.insns[last]
            if i.op not in TERMINAL:
                nxt = last + i.size + (2 if last in u.manager_calls else 0)
                if nxt not in u.insns:
                    lines.append(f"\tbra {smc_label(mod, nxt) if nxt in u.smc_entries else stop_label(mod, last)}")
        for off in sorted(u.smc_entries):
            ip = u.ip_of(off)
            lines += [f"{smc_label(mod, off)}:\t; self-modified code (D16)",
                      f"\tmove.l #{hx(ip)},d7", f"\tmove.l #{cs_expr(u.segment(off))},d6",
                      "\tjmp rt_stop_unknown"]
            stats["stop_unknown site"] += 1
        stops = {w.strip("()") for x in lines for w in x.replace(",", " ").split()
                 if w.endswith("_stop")}
        for s in sorted(stops):
            off = int(s.split("_")[1], 16)
            lines += [f"{s}:\t; transfer out of the translated modules",
                      f"\tmove.l #{hx(u.ip_of(off))},d7", "\tjmp rt_stop_unknown"]
            stats["stop_unknown site"] += 1
        stats["guest instructions"] += len(u.insns)
        stats["68k lines"] += sum(1 for x in lines if x.startswith("\t"))
        return lines, stats
