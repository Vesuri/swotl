"""Program mode: global flag liveness, block leaders and the 68020 `.s` of every
module (Motorola syntax, vasm). Generated text is G1-guarded like the IR listing.

Successors: fall-through (a PLINK manager call returns 2 bytes later), direct
near/far targets (cfg), statically resolved switch tables; a `ret`/`retf`
continues at the return sites of the calls whose targets reach it without
crossing a call (native rts; a mismatch stops; a call through the dispatcher
returns from any ret reached by a row it may dispatch to: one of its own CS
for a near call, a far row for a far one (R14e: rt_dispatch_far stops at a
row only indirect near jmp/call sites target), and on through the rows those
leave to; a ret no call target reaches falls back
to every return site), an
unresolved indirect transfer at some row of the runtime dispatch table (the
cfg seeds: MZ entry, PLINK thunks, runtime.csv, indirect.csv targets; any
other target stops), so each sees the live-in union of that set; a divide
error continues in the guest INT 00h handler; a flag-preserving cell walk passes its caller continuation's live flags
through (other self-modified flow sees every flag live); an annotated PUSHF/POPF save reads what is live after
its POPF. Leaders: seeds, call and far targets, transfer targets, return
sites and starts without a fall-through predecessor.
"""

from __future__ import annotations

import bisect
import re
from collections import Counter

from . import cfg, compute, image, region, smc
from .decode import Far, Rel
from .flags import ALL, plan, transfer
from .lower import GREG, LOADSEG, MIRROR, Ctx, LowerError, hx

M = image.M
TAG = {"SWOTL.EXE": "R", "SPAZ.OVL": "SPZ", "RTSVGA.OVL": "VGA", "FRONTEND.OVL": "FE",
       "CAMPAIGN.OVL": "CMP", "NOTCAMP.OVL": "NCP", "FLIGHT.OVL": "FLT", "REPLAY.OVL": "RPL",
       "PANEL.OVL": "PNL", "DATA.OVL": "DAT"}
RET, UNKNOWN, SMC = "ret", "unknown", "smc"
TERMINAL = {"jmp", "jmpf", "ret", "retf", "iret", "hlt"}
RUNTIME = ("rt_int", "rt_irq", "rt_fault", "rt_halt", "rt_trap", "rt_in8", "rt_in16", "rt_out8", "rt_out16",
           "rt_ret_mismatch", "rt_ret_far_mismatch", "rt_dispatch_near", "rt_dispatch_far", "rt_stop_unknown",
           "rt_vram_mark", "rt_vdrv_depth", "rt_vdrv_return", "rt_irq_pending")
# G3 native replacements (annotations/hle.csv): runtime service rt_hle_<service>
# at a range's first instruction; NE skips the range to the instruction after
# `last`, EQ runs the guest code. `args`: up to two guest word registers, in
# d7 and d6 for the service.
HLE_SERVICES = tuple(sorted({"rt_hle_" + r["service"] for r in image.rows("hle.csv")}))
# D9: the graphics driver in scope. Only it writes video memory
# (docs/external-surface.md); a return from a call into it through its PLINK
# thunks publishes a frame.
GRAPHICS_DRIVER = "RTSVGA.OVL"


def retried(i) -> bool:
    """A divide error branches back to the instruction after rt_fault, from
    its out-of-line path (lower.exit_fault)."""
    return i.op in ("div", "idiv") or i.op == "aam" and i.operands[0].value == 0


def copy_exits(p, nodes: set) -> set:
    """Where a copy run falls out of its component into the exact code
    (run_text): another way into those instructions."""
    return {p.fall[n] for n in nodes if p.node_insn(n).op not in TERMINAL
            and p.fall.get(n) not in nodes | {None}}


def label(mod: str, off: int) -> str:
    return f"{TAG[mod]}_{off:05X}"


def smc_label(mod: str, off: int) -> str:
    return f"{TAG[mod]}_{off:05X}_smc"


def walk_label(mod: str, first: int) -> str:
    return f"{TAG[mod]}_{first:05X}_walk"


def stop_label(mod: str, off: int) -> str:
    return f"{TAG[mod]}_{off:05X}_stop"


def poll(lab: str) -> list[str]:
    """D8 safe point at a loop head (a block leader: live flags are in the state
    block, so the CCR is free): a posted interrupt branches to the poll's stub
    (poll_stub), the common case falls through."""
    return ["\ttst.b G_IRQ(a6)", f"\tbne {lab}_irq", f"{lab}_np:"]


def poll_stub(lab: str, ip: int, cs: str) -> list[str]:
    """Out of line, after an unconditional transfer: rt_irq takes a pending
    hardware interrupt with d6 = CS << 16, d7 = the poll point's IP, then back
    past the test (`{lab}_np`; tools fold it into `lab`): a return to the label
    would be another visit, and loop while the bench watch keeps G_IRQ set."""
    return [f"{lab}_irq:", f"\tmove.l #{hx(ip)},d7", f"\tmove.l #({cs})<<16,d6",
            "\tjsr rt_irq", f"\tbra {lab}_np"]


# A return check's mismatch branch (lower.return_check) targets a module-local
# trampoline, so vasm can encode it as bne.s/bne.w instead of bne.l to the
# runtime (speed-plan R5). The lowering emits RM; module_text names the
# trampoline nearest by estimated bytes, placed after a run that cannot fall
# through. Any choice is correct: vasm sizes the branch.
RM = "__ret_mismatch"
RMF = "__ret_far_mismatch"
NEAR = 96  # estimated bytes within which bne.s is chosen (real 0.69-1.18x; reach 126)
SIZED = ".?"  # a guarded copy's branch (R6), sized at the end of module_text (same rule)


def size_branches(lines: list[str]) -> None:
    """Resolve SIZED branches to .s within NEAR estimated bytes of their label,
    else .w (vasm runs out of passes relaxing them itself)."""
    at, pos = {}, [0]
    for x in lines:
        if not x.startswith("\t"):
            at[x.split(":")[0]] = len(pos) - 1
        pos.append(pos[-1] + est_bytes(x))
    for k, x in enumerate(lines):
        if SIZED + " " in x:
            dist = abs(pos[at[x.split()[-1]]] - pos[k])
            lines[k] = x.replace(SIZED, ".s" if dist <= NEAR else ".w")


UNCONDITIONAL = re.compile(r"^\t(bra\S*|jmp|rts|rte)(\s|$)")
LABEL_ONLY = re.compile(r"^[^\s;][^:\s]*:\s*(;.*)?$")
ALIGN = "\tds.b\t0\t; align "   # an unexecuted even-sized pad, set by gen.pad (R8)


BRANCH = re.compile(r"^\t(bra(\.[swl])?|jmp)\s+([\w.]+)\s*(;.*)?$")


def skippable(line: str) -> bool:
    """A line that emits no code: a label alone, blank, or a comment."""
    return bool(LABEL_ONLY.match(line)) or not line.strip() or line.strip().startswith(";")


def drop_next_branches(lines: list[str], stats: Counter) -> None:
    """A `bra`/`jmp` to a label that follows it with no code between goes:
    execution falls through to the same instruction. vasm runs out of passes
    on some images that have one (speed-plan R7, R9). Backwards, so a chain of
    them goes too (outlined ranges ending in jumps to one target, R27). Before
    `align`, so no pad follows a dropped branch."""
    dropped = 0
    for k in range(len(lines) - 1, -1, -1):
        m = BRANCH.match(lines[k])
        if not m:
            continue
        j = k + 1
        while j < len(lines) and skippable(lines[j]):
            if LABEL_ONLY.match(lines[j]) and lines[j].split(":")[0] == m.group(3):
                del lines[k]
                dropped += 1
                break
            j += 1
    stats["branch to the next line dropped"] += dropped


def align(lines: list[str], residues: dict[str, int], stats: Counter) -> None:
    """R8: an alignment pad before each listed label that only transfers reach
    (the instruction before it, past label-only and comment lines, is
    unconditional), so the pad never runs (annotations/align.csv,
    tools/align_targets.py). gen.pad sizes the pads (vasm's cnop does not
    converge in this program)."""
    at = []
    for k, x in enumerate(lines):
        if not LABEL_ONLY.match(x):
            continue
        name = x.split(":")[0]
        r = residues.get(name)
        if r is None:
            continue
        j = k - 1
        while j >= 0 and skippable(lines[j]):
            j -= 1
        if j >= 0 and UNCONDITIONAL.match(lines[j]):
            at.append((j + 1, f"{r} {name}"))
            stats["alignment pad"] += 1
        else:
            stats["alignment not applied"] += 1
    for j, r in reversed(at):
        lines.insert(j, ALIGN + r)


# R27: a forward jcc listed in annotations/outline.csv branches, inverted, to its
# fall-through range, placed out of line; the range ends in cold_return.
INVERT = {"eq": "ne", "ne": "eq", "cs": "cc", "cc": "cs", "vs": "vc", "vc": "vs", "mi": "pl",
          "pl": "mi", "lt": "ge", "ge": "lt", "le": "gt", "gt": "le", "hi": "ls", "ls": "hi"}
BCC = re.compile(r"^\tb(" + "|".join(INVERT) + r")(\.[swl])?\s+(\S+)$")


def fuse_jumps(lines: list[str], candidates: dict, stats: Counter) -> dict:
    """Invert a conditional over a sole non-entry JMP. Candidates are proved
    from the guest CFG; the text check also preserves every intervening hook,
    guard and out-of-line body. Keep the unused JMP label as a zero-code alias.
    """
    fused = {}
    for k in range(len(lines) - 1, -1, -1):
        branch = BCC.match(lines[k])
        if not branch:
            continue
        j, labels = k + 1, []
        while j < len(lines) and skippable(lines[j]):
            if LABEL_ONLY.match(lines[j]):
                labels.append(lines[j].split(":")[0])
            j += 1
        if len(labels) != 1 or labels[0] not in candidates or j == len(lines):
            continue
        source, skip, target = candidates[labels[0]]
        jump = BRANCH.match(lines[j])
        if not jump or jump.group(3) != target or branch.group(3) != skip:
            continue
        # The branch must belong to the proved conditional, not a later stub.
        before = k - 1
        while before >= 0 and not LABEL_ONLY.match(lines[before]):
            before -= 1
        if before < 0 or lines[before].split(":")[0] != source:
            continue
        after, following = j + 1, []
        while after < len(lines) and skippable(lines[after]):
            if LABEL_ONLY.match(lines[after]):
                following.append(lines[after].split(":")[0])
            after += 1
        if skip not in following:
            continue
        lines[k] = f"\tb{INVERT[branch.group(1)]} {target}"
        del lines[j]
        fused[source] = labels[0]
    stats["conditional over jump fused"] += len(fused)
    return fused


def retarget_jump_aliases(lines: list[str], fused: dict, candidates: dict) -> None:
    """A bypassed JMP's zero-code entry means its original destination. Move
    its label there so direct entry retains exactly the JMP's semantics.
    Targets cannot themselves be bypassed JMPs: a jump target is a leader.
    """
    destinations = {jump: candidates[jump][2] for jump in fused.values()}
    assert not destinations.keys() & set(destinations.values())
    aliases, body = {}, []
    for line in lines:
        name = line.split(":")[0] if LABEL_ONLY.match(line) else None
        if name in destinations:
            aliases.setdefault(destinations[name], []).append(line)
        else:
            body.append(line)
    assert sum(map(len, aliases.values())) == len(destinations)
    out = []
    for line in body:
        name = line.split(":")[0] if LABEL_ONLY.match(line) else None
        out.extend(aliases.pop(name, []))
        out.append(line)
    assert not aliases, aliases  # never silently discard an unresolved entry
    lines[:] = out


def cold_return(lab: str) -> list[str]:
    """The end of an outlined fall-through range (R27): on to the jcc's target."""
    return [f"\tbra {lab}"]


def mismatch_stub(lab: str, far: bool = False) -> list[str]:
    return [f"{lab}:", "\tjmp " + ("rt_ret_far_mismatch" if far else "rt_ret_mismatch")]


def est_bytes(line: str) -> int:
    """Rough encoded size of one emitted line (labels 0): picks trampolines only."""
    if not line.startswith("\t"):
        return 0
    op, _, args = line.strip().partition(" ")
    n = 2 + 2 * args.count("#") + 2 * args.count("(") + 2 * args.count("G_")
    if op.endswith(".l") and "#" in args:
        n += 2
    if op.split(".")[0] in ("jsr", "jmp", "bra", "bsr") or op[0] == "b" and "." not in op:
        n = max(n, 4)
    return n


def copy_label(mod: str, off: int) -> str:
    """The instruction in its BP component's guarded copy (R6)."""
    return f"{TAG[mod]}_{off:05X}_bp"


def cs_expr(cs: int) -> str:
    return f"LOADSEG+{hx(cs)}"


class Program:
    hle: dict = {}   # (mod, first) -> ((mod, resume), service); set from hle.csv
    sync_poll_first = True  # U5: a sync site's visit precedes its hook (sabotage turns it off)
    polled_resumes: dict = {}  # U5 hook -> its resumes (return, sync sites); set in __init__

    def __init__(self, units: dict[str, cfg.Unit] | None = None, components: bool = True,
                 diagnostic_hooks: dict[tuple[str, int], int] | None = None,
                 diagnostic_reps: dict[tuple[str, int], int] | None = None):
        self.diagnostic_hooks = diagnostic_hooks or {}
        self.diagnostic_reps = diagnostic_reps or {}
        self.units = units or cfg.build()
        self.align = {r["label"]: int(r["residue"]) for r in image.rows("align.csv")}
        self.outline = {r["label"] for r in image.rows("outline.csv")}
        self.seg_repeat = {r["label"] for r in image.rows("seg-repeat.csv")}
        self.outline_sites: dict[str, tuple] = {}  # R27, outline_cold
        self.offsets: dict[str, list[int]] = {}   # sorted instruction offsets (outline_cold)
        self.run_last: dict[str, dict[int, int]] = {}  # each run's last offset by its first
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
        seeds = [(m, o, why) for m, o, why in cfg.seeds(image.load())
                 if m in self.units and o in self.units[m].insns]
        self.dispatch = {(m, o) for m, o, _ in seeds}
        # R14e: rows a far transfer may enter: every seed but those that are only
        # targets of indirect near jmp/call sites (rt_dispatch_far stops at the rest)
        self.far_rows = {(m, o) for m, o, why in seeds if not self.near_only(why)}
        # PUSHF ... POPF pairs that only save and restore FLAGS (annotations/flags.csv):
        # the save reads what is live after the restore.
        self.saves = {(r["module"], int(r["save"], 16)): (r["module"], int(r["restore"], 16))
                      for r in image.rows("flags.csv")}
        self.hle: dict[tuple[str, int], tuple[tuple[str, int], str]] = {}
        self.hle_args: dict[tuple[str, int], list[str]] = {}
        self.compute_rows: set[tuple[str, int]] = set()
        self.sync_sites: dict[tuple[str, int], tuple] = {}  # U5 rows: first -> sync sites
        for r in image.rows("hle.csv"):
            mod, first, last = r["module"], int(r["first"], 16), int(r["last"], 16)
            u = self.units[mod]
            resume = last + u.insns[last].size if last in u.insns else None
            if first not in u.insns or resume not in u.insns:
                raise LowerError(f"hle.csv: {mod}+{first:05X}..{last:05X} is no instruction range")
            self.hle[(mod, first)] = ((mod, resume), "rt_hle_" + r["service"])
            args = (r.get("args") or "").split()
            if len(args) > 2 or any(a not in GREG or a in MIRROR for a in args):
                raise LowerError(f"hle.csv: {mod}+{first:05X} args {args}: two plain word registers at most")
            self.hle_args[(mod, first)] = args
            kind = r.get('kind') or 'hook'
            if kind not in {'hook', 'compute'}:
                raise LowerError(f'hle.csv: unknown kind {kind}')
            if kind == 'compute':
                if args or not r.get('reason') or not r.get('oracle'):
                    raise LowerError('hle.csv: compute needs reason/oracle and no args')
                self.compute_rows.add((mod, first))
                polls = (r.get('polls') or '').split()
                if polls:   # U5: 'return' and the sync sites' offsets
                    if polls[0] != 'return':
                        raise LowerError(f"hle.csv: {mod}+{first:05X} polls must start with 'return'")
                    sites = tuple((mod, int(x, 16)) for x in polls[1:])
                    if any(o not in u.insns for _, o in sites):
                        raise LowerError(f"hle.csv: {mod}+{first:05X} sync site is no instruction")
                    self.sync_sites[(mod, first)] = sites
            elif r.get('polls'):
                raise LowerError(f"hle.csv: {mod}+{first:05X} polls need kind compute")
        int0 = [r for r in image.rows("runtime.csv") if r["name"] == "__cintDIV"]
        self.int0 = (int0[0]["module"], int(int0[0]["offset"], 16)) if int0 else None
        # D16: self-modified regions, each lowered as one cell walk
        self.smc_forms = image.smc_forms()
        self.walk_preserves_flags = all(smc.preserves_flags(forms)
                                        for forms in self.smc_forms.values())
        self.cell_regions()
        # D9: the `jmp far` of each PLINK thunk into the graphics driver
        # (thunk: call far manager, dw id, jmp far)
        self.driver_jumps = {at + 7 for at, mod, _ in M.thunks(image.load()) if mod == GRAPHICS_DRIVER}
        self.build_edges()
        # D8 poll points: targets of backward branches in the same module
        # (loop heads); a pending hardware interrupt is taken there
        self.loop_heads = {s for n, ss in self.succ.items()
                           if self.node_insn(n).op not in ("call", "callf")
                           for s in ss if isinstance(s, tuple) and s not in (RET, UNKNOWN, SMC)
                           and s[0] == n[0] and s[1] <= n[1]}
        self.live_in: dict = {}
        self.live_out: dict = {}
        self.fused_jumps: dict = {}    # conditional label -> removed direct JMP
        self.ccr_only: dict = {}    # label -> live flags only the CCR holds there (R14d)
        self.ret_of: dict = {}
        self.returns()
        self.compute_bodies = {n: compute.validate_polled(self, n, self.hle[n][0], self.sync_sites[n])
                               if n in self.sync_sites else compute.validate(self, n, self.hle[n][0])
                               for n in self.compute_rows}
        # U5: each row's chosen polls replace the polls reachable only through it
        # (both arms); its return and sync sites are polls. Sync sites are hook
        # entries too, and every hook may resume at the return or a sync site.
        self.polled_resumes: dict[tuple[str, int], list] = {}
        for n, sites in self.sync_sites.items():
            row = self.compute_bodies[n]
            self.loop_heads = (self.loop_heads - row.removed) | set(sites) | {row.resume}
            for s in sites:
                self.hle[s] = self.hle[n]
                self.hle_args[s] = []
            for h in (n, *sites):
                self.polled_resumes[h] = [row.resume, *sites]
            self.compute_rows |= set(sites)
        self.liveness()
        self.leaders = self.find_leaders()
        for mod, off in self.diagnostic_hooks:
            if mod not in self.units or off not in self.units[mod].insns:
                raise ValueError(f"diagnostic hook is not an instruction: {(mod, off)}")
        # A diagnostic stop/input inside a block needs the exact guest state,
        # so lowering may not fuse across it. Production leaders are unchanged.
        self.leaders.update(self.diagnostic_hooks)
        # An HLE hook clobbers the CCR and branches: both ends are leaders.
        for n, (resume, _) in self.hle.items():
            self.leaders |= {n, resume}
        self.hle_resumes = {resume for resume, _ in self.hle.values()}
        self.components(components)

    # -- graph ----------------------------------------------------------------
    def near_only(self, why: str) -> bool:
        kind, _, site = why.partition(" ")
        if kind not in ("switch", "traced"):
            return False
        mod, _, off = site.partition("+")
        i = self.units[mod].insns.get(int(off, 16)) if mod in self.units else None
        return bool(i) and i.op in ("jmp", "call")

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
                self.succ[n] = [x if x in (RET, UNKNOWN, SMC) or self.node_insn(x) else SMC
                                for x in s]
                self.fall[n] = fall if fall and self.node_insn(fall) else None

    def indirect_succ(self, mod: str, off: int, far: bool) -> list:
        sw, tr = self.indirect.get((mod, off), ([], []))
        self.entries.update(sw + tr)
        return list(sw) if sw else [UNKNOWN] + ([SMC] if not far and self.near_walks(mod, off) else [])

    def reach(self, t, cache: dict) -> tuple[set, set]:
        """rets reachable from entry t without entering a call (a call continues at
        its return site), and the dispatch keys (dispatch_key) of the unresolved
        transfers that leave the walk."""
        if t in cache:
            return cache[t]
        seen, stack, rets, escapes = {t}, [t], set(), set()
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
                    escapes.add(self.dispatch_key(n))
                elif x not in (RET, SMC) and x not in seen and x in self.succ:
                    seen.add(x)
                    stack.append(x)
        cache[t] = (rets, escapes)
        return cache[t]

    def dispatch_key(self, n) -> int | None:
        """The rows an unresolved transfer at n may reach through the runtime
        table: a near one looks up its own CS (the link CS), a far one any far
        row (None)."""
        return None if self.node_insn(n).op in ("jmpf", "callf") else self.units[n[0]].cs[n[1]]

    def returns(self) -> None:
        """ret node -> the return sites it can continue at."""
        self.call_site = {c: site for c, site, _ in self.calls}
        cache: dict = {}
        ret_of: dict = {}
        # R14e: return sites of calls that may run dispatch-table entries, by the
        # entries' link CS (None: the far rows); an entry that leaves through the
        # table passes its sites on to the entries it may reach
        seeds = [e for e in self.dispatch if e in self.succ]
        by_cs: dict = {}
        for e in seeds:
            by_cs.setdefault(self.units[e[0]].cs[e[1]], []).append(e)
        far = [e for e in seeds if e in self.far_rows]

        def rows(keys):
            out = far if None in keys else []
            return out + [e for k in keys if k is not None for e in by_cs.get(k, ())]

        sites_of = {e: set() for e in seeds}
        for c, site, targets in self.calls:
            for t in targets:
                if t == SMC:
                    continue
                keys = {self.dispatch_key(c)} if t == UNKNOWN else self.reach(t, cache)[1]
                if t != UNKNOWN:
                    for r in self.reach(t, cache)[0]:
                        ret_of.setdefault(r, set()).add(site)
                for e in rows(keys):
                    sites_of[e].add(site)
        changed = True
        while changed:
            changed = False
            for e in seeds:
                for e2 in rows(self.reach(e, cache)[1]):
                    if not sites_of[e] <= sites_of[e2]:
                        sites_of[e2] |= sites_of[e]
                        changed = True
        for e in seeds:
            for r in self.reach(e, cache)[0]:
                ret_of.setdefault(r, set()).update(sites_of[e])
        every = frozenset(self.ret_sites)
        self.ret_fallback = 0
        for n in self.succ:
            if self.node_insn(n).op in ("ret", "retf"):
                sites = ret_of.get(n)
                if not sites:
                    self.ret_fallback += 1
                self.ret_of[n] = tuple(sites) if sites else tuple(every)

    def taken_live(self, n) -> set | None:
        """Live-in of a conditional jump's target (R14d); None for other nodes."""
        if self.node_insn(n).op != "jcc":
            return None
        t = self.succ[n][0]
        return set(ALL) if t in (RET, UNKNOWN, SMC) else set(self.live_in[t])

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
                        # A matched walk that defines/reads no flags passes its
                        # caller's requirements through unchanged. The return
                        # check stops if it does not return to that call site.
                        out |= (self.live_in.get(self.call_site[n], ALL)
                                if n in self.call_site and self.walk_preserves_flags else ALL)
                    else:
                        out |= self.live_in[s]
                i = self.node_insn(n)
                new = transfer(i, out, program=True)
                if n in self.saves:
                    new = (new - ALL) | out | self.live_out.get(self.saves[n], set())
                if n in self.hle:   # the hook may skip to the resume instruction
                    new |= self.live_in[self.hle[n][0]]
                for r in self.polled_resumes.get(n, ()):
                    new |= self.live_in[r]
                self.live_out[n] = out
                if new != self.live_in[n]:
                    self.live_in[n] = new
                    changed = True

    def components(self, enabled: bool) -> None:
        """R6: the BP-stable components chosen by profile (annotations/bp-regions.csv)
        get a guarded copy; their entries and the instructions after a call or
        software interrupt in them become leaders (a guard clobbers the CCR)."""
        chosen = {(r["module"], int(r["writer"], 16))
                  for r in (image.rows("bp-regions.csv") if enabled else ())}
        for n in chosen - region.writers(self) if chosen else ():
            raise LowerError(f"bp-regions.csv: {n[0]}+{n[1]:05X} is no BP write")
        self.comps = []
        for ws, starts, nodes in region.components(self, chosen):
            rng = region.bp_range([self.node_insn(n) for n in nodes])
            if rng is None:
                raise LowerError(f"bp-regions.csv: {sorted(ws)} has no direct access")
            self.comps.append((ws, starts, nodes, rng))
        self.guard_at = {w: k for k, c in enumerate(self.comps) for w in c[0]}
        for ws, starts, nodes, _ in self.comps:
            self.leaders |= starts
            self.leaders |= {self.fall[n] for n in nodes if self.node_insn(n).op in region.REGUARD
                             and self.fall.get(n) in nodes}
            self.leaders |= copy_exits(self, nodes)

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
            if jump_preds[n] or not fall_preds[n] or retried(self.node_insn(n)):
                leaders.add(n)
        return leaders

    # -- generation -------------------------------------------------------------
    def cell_regions(self) -> None:
        """D3 cell caches: per region its segment, first IP and covered bytes; the
        lowest segment whose 64 KiB window (the byte past it too) reaches none."""
        self.cells = []     # (walk label, segment, first IP, span)
        for mod, lo, hi in sorted(self.smc_forms):
            u = self.units.get(mod)
            if not u or u.segment(lo) != u.segment(hi):
                continue
            first, last = u.ip_of(lo), u.ip_of(hi)
            if first + smc.span(first, last) > 0x10000:
                raise LowerError(f"{mod}+{lo:05X}: cell cache past its segment")
            self.cells.append((walk_label(mod, lo), u.segment(lo), first, smc.span(first, last)))
        lins = [((LOADSEG + seg) * 16 + first, (LOADSEG + seg) * 16 + first + n - 1)
                for _, seg, first, n in self.cells]
        self.smc_bounds = (min(a for a, _ in lins), max(b for _, b in lins)) if lins else (1, 0)
        if lins and self.smc_bounds[0] > 0x10000:
            raise LowerError("cell cache: a segment check from below is not lowered")
        self.smc_limit = (self.smc_bounds[1] >> 4) + 1 if lins else 0

    def code_regions(self, cs: int) -> tuple:
        """Cell caches a CS-segment store in segment `cs` may reach: (offset to
        region offset, span, walk label), region offset = offset + the first."""
        out = []
        for lab, seg, first, n in self.cells:
            delta = (cs - seg) * 16 - first
            if delta < n and delta + 0x10000 >= 0:
                out.append((delta, n, lab))
        return tuple(out)

    def smc_text(self) -> tuple[list[str], list[str]]:
        """Code (smc_expose, the runtime's bounds and segment limit) and cache data."""
        lo, hi = self.smc_bounds
        code = smc.expose([lab for lab, *_ in self.cells]) + [
            "\tcnop\t0,4", f"smc_lo:\tdc.l\t{hx(lo)}", f"smc_hi:\tdc.l\t{hx(hi)}",
            f"smc_seg_limit:\tdc.w\t{hx(self.smc_limit)}"]
        data = []
        for (mod, lo_, hi_) in sorted(self.smc_forms):
            u = self.units.get(mod)
            if u and any(lab == walk_label(mod, lo_) for lab, *_ in self.cells):
                data += smc.tables(walk_label(mod, lo_), u.ip_of(lo_), u.ip_of(hi_))
        return code, data

    def region(self, mod: str, off: int) -> tuple[int, int] | None:
        return next(((lo, hi) for m, lo, hi in self.smc_forms if m == mod and lo <= off <= hi),
                    None)

    def dispatch_rows(self) -> list[tuple[int, int, int, int, str]]:
        """Run-time dispatch table: (link CS, IP, overlay id (root 0), far (R14e),
        label) of every decoded entry, sorted by CS:IP. Overlays sharing an area share
        CS:IP, so the runtime picks the row whose overlay is resident."""
        out = []
        for mod, off in self.dispatch:
            u = self.units.get(mod)
            if not u or off not in u.insns:
                continue
            out.append((u.cs[off], u.ip_of(off), u.module.index + 1,
                        int((mod, off) in self.far_rows), label(mod, off)))
        return sorted(out)

    def program_text(self, files: list[str]) -> str:
        """Assembly root of the Amiga/host link: equates, runtime imports, the module
        files and the dispatch table."""
        lines = ["\txref\t" + r for r in RUNTIME]
        if self.diagnostic_hooks:
            lines.append("\txref\trt_replay_point")
        if self.diagnostic_reps:
            lines.append("\txref\trt_replay_rep")
        lines += ["\txref\t" + s for s in sorted({s for _, s in self.hle.values()})]
        lines += ["\txdef\tdispatch_table", "\txdef\tdispatch_count", "\txdef\tload_segment",
                  "\txdef\toverlay_table", "\txdef\tsmc_expose", "\txdef\tsmc_lo",
                  "\txdef\tsmc_hi", "\txdef\tsmc_seg_limit", "\tsection\t.text,code"]
        lines += [f'\tinclude\t"{f}"' for f in files]
        code, data = self.smc_text()
        lines += code
        rows = self.dispatch_rows()
        lines += ["\tcnop\t0,4", "load_segment:\tdc.l\tLOADSEG",
                  f"overlay_table:\tdc.l\t{hx(M.OVL_TABLE)}\t; PLINK records, id 1 first (root offset)",
                  "dispatch_count:", f"\tdc.l\t{len(rows)}", "dispatch_table:"]
        lines += [f"\tdc.w\t{cs_expr(cs)},{hx(ip)},{oid},{far}\n\tdc.l\t{lab}"
                  for cs, ip, oid, far, lab in rows]
        lines += ["\tsection\t.bss,bss"] + data
        return "\n".join(lines) + "\n"

    def near_walks(self, mod: str, off: int) -> set[tuple[int, int]]:
        """Walks reachable by a near indirect transfer. An incomplete target census
        cannot exclude a modified region in the same CS; a proved table can."""
        u = self.units[mod]
        sw, tr = self.indirect.get((mod, off), ([], []))
        if sw:
            return {r for m, o in sw + tr if m == mod and (r := self.region(m, o))}
        return {(lo, hi) for m, lo, hi in self.smc_forms
                if m == mod and u.segment(lo) == u.segment(hi) == u.cs[off]}

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
        near_t, far_t, smc_t = (), (), set()
        sw, tr = self.indirect.get((mod, off), ([], []))
        if i.op in ("jmp", "call") and not isinstance(i.operands[0], Rel):
            near_t = tuple(u.ip_of(o) for m, o in sw + tr if m == mod and not self.region(m, o))
            smc_t = self.near_walks(mod, off)
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
                   smc_targets=tuple(sorted((u.ip_of(lo), u.ip_of(hi), walk_label(mod, lo))
                                            for lo, hi in smc_t)),
                   code_regions=self.code_regions(cs), seg_limit=self.smc_limit,
                   seg_repeat=label(mod, off) in self.seg_repeat,
                   manager=off in u.manager_calls, program=True, vram=mod == GRAPHICS_DRIVER,
                   driver_call=mod == M.ROOT and off in self.driver_jumps, ret_mismatch=RM,
                   far_ret_mismatch=RMF,
                   rep_hook=((self.diagnostic_reps[(mod, off)], label(mod, off))
                             if (mod, off) in self.diagnostic_reps else None))

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

    def copy_ctx(self, mod: str, off: int, stats: Counter, comp: int) -> Ctx:
        """A guarded copy's instruction (R6): targets in the component stay in
        the copy, [bp+d] is direct, a divide error re-executes in the exact code."""
        c = self.ctx(mod, off, stats)
        u, nodes, near = self.units[mod], self.comps[comp][2], c.near
        cs = u.cs[off]

        def near_copy(ip):
            t = u.off_of(cs, ip)
            return copy_label(mod, t) if (mod, t) in nodes else near(ip)

        c.near, c.label, c.retry, c.bp_direct = near_copy, copy_label(mod, off), label(mod, off), True
        return c

    def copy_runs(self, mod: str, comp: int) -> list[list[int]]:
        out, cur = [], []
        for o in sorted(o for _, o in self.comps[comp][2]):
            if cur and self.fall.get((mod, cur[-1])) != (mod, o):
                out.append(cur)
                cur = []
            cur.append(o)
        return out + [cur]

    def run_text(self, mod: str, run: list[int], stats: Counter, stubs: list[str],
                 comp: int | None = None) -> tuple[list[str], bool]:
        """One run (exact, or in component `comp`'s copy): its lines and whether it
        ends without falling through. Poll stubs and out-of-line code go to `stubs`."""
        u = self.units[mod]
        insns = [u.insns[o] for o in run]
        lives = [self.live_out[(mod, o)] for o in run]
        taken = [self.taken_live((mod, o)) for o in run]
        leaders = {k for k, o in enumerate(run) if (mod, o) in self.leaders}
        ctx = ((lambda k: self.ctx(mod, run[k], stats)) if comp is None
               else (lambda k: self.copy_ctx(mod, run[k], stats, comp)))
        fences = {k + 1 for k, o in enumerate(run)
                  if (comp is None and (mod, o) in self.guard_at)
                  or (comp is not None and u.insns[o].op in region.REGUARD)}
        try:
            lws = plan(insns, lives, leaders, ctx, program=True, fences=fences, taken=taken)
        except LowerError as e:
            raise LowerError(f"{mod}+{run[0]:05X} run: {e}") from None
        lab = label if comp is None else copy_label
        lines: list[str] = []
        starts: list[int] = []      # each instruction's first line

        def visit(o):   # D8 poll point
            assert (mod, o) in self.leaders, (mod, o)
            lines.extend(poll(lab(mod, o)))
            stub = poll_stub(lab(mod, o), u.ip_of(o), cs_expr(u.cs[o]))
            if comp is not None:    # a handler may change BP: on in the exact code
                stub[-1] = f"\tbra {label(mod, o)}_np"
            stubs.extend(stub)
            stats["interrupt poll"] += 1

        at = len(stubs)             # this run's stubs start here
        for o, lw in zip(run, lws):
            n = u.insns[o]
            starts.append(len(lines))
            lines.append(f"{lab(mod, o)}:\t; {u.cs[o]:04X}:{n.ip:04X} {n}")
            if (mod, o) in self.diagnostic_hooks:
                point = self.diagnostic_hooks[(mod, o)]
                assert 0 <= point < 32768
                # Diagnostic build only. The hook preserves registers/CCR;
                # the original poll and every production guard remain below.
                lines += [f"\tpea {point}.w", "\tjsr rt_replay_point"]
                if comp is not None and (mod, o) in self.loop_heads:
                    # As in poll_stub: an IRQ handler may change BP, so a
                    # delivered diagnostic IRQ must leave the guarded copy.
                    lines += ["\ttst.l (sp)+", f"\tbne {label(mod, o)}_np"]
                else:
                    lines.append("\tlea 4(sp),sp")
            polled = self.polled_resumes.get((mod, o))
            # U5 sync site: the visit (poll) precedes re-entering the callback
            early = polled and (mod, o) in self.loop_heads and self.sync_poll_first
            if early:
                visit(o)
            if polled:
                _, service = self.hle[(mod, o)]
                entry = 0 if (mod, o) not in polled else polled.index((mod, o))
                lines += compute.polled_hook(service, entry, f"{lab(mod, o)}_cx", cs_expr(u.cs[o]))
                stubs += compute.polled_dispatch(f"{lab(mod, o)}_cx", [label(*x) for x in polled],
                                                 hx(u.ip_of(o)))
                stats["HLE hook"] += 1
            elif (mod, o) in self.hle:
                resume, service = self.hle[(mod, o)]
                if (mod, o) in self.compute_rows:
                    lines += compute.hook(service, label(*resume), cs_expr(u.cs[o]))
                else:
                    lines += [f"\tmove.w {GREG[a]},{d}" for a, d in zip(self.hle_args[(mod, o)], ("d7", "d6"))]
                    lines += [f"\tjsr {service}", f"\tbne {label(*resume)}"]
                stats["HLE hook"] += 1
            if ((mod, o) in self.hle or (mod, o) in self.hle_resumes) and lw.ccr_only:
                raise LowerError(f"{mod}+{o:05X}: HLE hook where the CCR holds live flags")
            if (mod, o) in self.loop_heads and not early:
                visit(o)
            lines.extend(lw.out)
            stubs += lw.cold
            if lw.ccr_only:
                self.ccr_only[lab(mod, o)] = set(lw.ccr_only)
            stats.update(lw.stats)
            f = self.fall.get((mod, o))
            if comp is None and (mod, o) in self.guard_at:
                k = self.guard_at[(mod, o)]
                lines.append(f"{label(*f)}_bpg:")
                lines += region.entry(self.comps[k][3], copy_label(*f), label(*f), SIZED)
                stats["region guard"] += 1
            elif comp is not None and n.op in region.REGUARD and f in self.comps[comp][2]:
                lines.append(f"{label(*f)}_bpr:")   # guest code ran: BP may have changed
                lines += region.guard(self.comps[comp][3], label(*f), SIZED)
                stats["region guard"] += 1
        opened = False
        if comp is None:
            lines, opened = self.outline_cold(mod, run, starts, lines, stubs, at, stats)
        # fall-through out of the run into something not decoded here (or, from a
        # copy, into the exact code)
        last = run[-1]
        i = u.insns[last]
        closed = i.op in TERMINAL and not opened
        if not closed and not opened:
            nxt = last + i.size + (2 if last in u.manager_calls else 0)
            if nxt not in u.insns:
                lines.append(f"\tbra {smc_label(mod, nxt) if nxt in u.smc_entries else stop_label(mod, last)}")
                closed = True
            elif comp is not None:
                lines.append(f"\tbra{SIZED} {label(mod, nxt)}")
                closed = True
        return lines, closed

    def outline_cold(self, mod: str, run: list[int], starts: list[int], lines: list[str],
                     stubs: list[str], at: int, stats: Counter) -> tuple[list[str], bool]:
        """R27: a jcc listed in annotations/outline.csv (tools/outline_sites.py: the
        meter takes it more often than not) whose target follows its fall-through
        range F, in the run or (F ending in a transfer) as the next run's first
        instruction, branches, inverted, to F. F moves out of line, first among
        the run's stubs (after the next closing transfer), and goes on to the
        target (cold_return) unless it ends in a transfer. Every instruction keeps
        its lowering: both edges see the same registers and CCR. Each eligible
        site goes to outline_sites (gen.py writes them for the tool), with the
        instruction whose run's end receives F. Returns the lines and whether
        they now fall into the next run."""
        u = self.units[mod]
        pos = {o: k for k, o in enumerate(run)}
        offs = self.offsets.setdefault(mod, sorted(u.insns))
        nxt = bisect.bisect_right(offs, run[-1])
        place = {}
        if u.insns[run[-1]].op in TERMINAL and nxt < len(offs):
            pos[offs[nxt]] = len(run)   # the next run starts at the target
            lasts = self.run_last.setdefault(mod, {r[0]: r[-1] for r in self.runs(mod)})
            place[len(run)] = label(mod, lasts[offs[nxt]])
        starts = starts + [len(lines)]
        cuts, end = [], 0
        for k, o in enumerate(run):
            if u.insns[o].op != "jcc":
                continue
            t = self.succ[(mod, o)][0]
            j = pos.get(t[1]) if t in self.succ and t[0] == mod else None
            m = BCC.match(lines[starts[k + 1] - 1])
            if j is None or j <= k + 1 or not m or m.group(3) != label(*t) \
                    or any((mod, x) in self.guard_at for x in run[k:j]):
                continue
            on = label(mod, o) in self.outline and k >= end
            self.outline_sites[label(mod, o)] = (label(mod, run[k + 1]), label(mod, run[j - 1]),
                                                 label(*t), u.insns[run[j - 1]].op in TERMINAL,
                                                 place.get(j, label(mod, run[-1])), on)
            if on:
                cuts.append((k, j, m.group(1)))
                end = j
        if not cuts:
            return lines, False
        out, last, chunks = [], 0, []
        for k, j, cc in cuts:
            b = starts[k + 1]
            out += lines[last:b - 1] + [f"\tb{INVERT[cc]} {label(mod, run[k + 1])}"]
            chunks += lines[b:starts[j]]
            if u.insns[run[j - 1]].op not in TERMINAL:
                chunks += cold_return(label(*self.succ[(mod, run[k])][0]))
            last = starts[j]
        stubs[at:at] = chunks
        stats["cold side outlined"] += len(cuts)
        return out + lines[last:], end == len(run)

    def module_text(self, mod: str) -> tuple[list[str], Counter]:
        u = self.units[mod]
        stats = Counter()
        lines: list[str] = []
        stubs: list[str] = []  # poll stubs, cold code: after the next run that cannot fall through
        copies: list[int] = []  # guarded copies (R6), placed there too
        copied: set[int] = set()
        tramps = 0             # return-check trampolines placed (RM)
        last_tramp = {}        # marker -> (line index, label) of its latest stub
        pending = {RM: [], RMF: []}

        def place(start: int, closed: bool) -> None:
            nonlocal tramps
            for marker in pending:
                pending[marker] += [k for k in range(start, len(lines))
                                    if lines[k] == f"\tbne {marker}"]
            for marker, waiting in pending.items():
                if not closed or not waiting:
                    continue
                previous = last_tramp.get(marker)
                base = waiting[0] if previous is None else previous[0]
                at = [0]  # estimated byte position of lines[base + j]
                for x in lines[base:]:
                    at.append(at[-1] + est_bytes(x))
                here = f"{TAG[mod]}_rm{tramps}"
                for k in waiting:
                    back = at[k - base] if previous is not None else 1 << 30
                    fwd = at[-1] - at[k - base]
                    lines[k] = f"\tbne.{'s' if min(back, fwd) <= NEAR else 'w'} " \
                               f"{previous[1] if back < fwd else here}"
                last_tramp[marker] = (len(lines), here)
                lines.extend(mismatch_stub(here, marker == RMF))
                tramps += 1
                waiting.clear()

        for run in self.runs(mod):
            start = len(lines)
            text, closed = self.run_text(mod, run, stats, stubs)
            lines += text
            copies += [self.guard_at[(mod, o)] for o in run if (mod, o) in self.guard_at
                       and self.guard_at[(mod, o)] not in copies]
            place(start, closed)
            if closed:
                start = len(lines)
                lines += stubs      # outlined ranges (R27) may hold return checks
                stubs = []
                place(start, True)
                for k in copies:
                    if k in copied:
                        continue
                    copied.add(k)
                    for crun in self.copy_runs(mod, k):
                        start = len(lines)
                        text, cclosed = self.run_text(mod, crun, stats, stubs, k)
                        assert cclosed, (mod, crun)
                        lines += text
                        place(start, True)
                    lines += stubs
                    stubs = []
                    stats["guarded copy"] += 1
                copies = []
        assert not copies, (mod, copies)
        start = len(lines)
        lines += stubs  # after the last run, with the entries below
        place(start, False)
        for marker, waiting in pending.items():
            if not waiting:
                continue
            here = f"{TAG[mod]}_rm{tramps}"
            for k in waiting:
                lines[k] = f"\tbne.w {here}"
            lines += mismatch_stub(here, marker == RMF)
            tramps += 1
        for off in sorted(u.smc_entries):
            lo, _ = self.region(mod, off)
            lines += [f"{smc_label(mod, off)}:\t; self-modified code (D16)",
                      f"\tmove.l #{hx(u.ip_of(off))},d7", f"\tbra {walk_label(mod, lo)}"]
        for (m, lo, hi), forms in sorted(self.smc_forms.items()):
            if m == mod:
                if u.ip_of(lo) > u.ip_of(hi) or u.segment(lo) != u.segment(hi):
                    raise LowerError(f"{mod}+{lo:05X}: self-modified region crosses a segment")
                lines += smc.walk(walk_label(mod, lo), cs_expr(u.segment(lo)), u.ip_of(lo),
                                  u.ip_of(hi), forms, self.smc_limit)
                stats["self-modified walk"] += 1
        stops = {w.strip("()") for x in lines for w in x.replace(",", " ").split()
                 if w.endswith("_stop")}
        for s in sorted(stops):
            off = int(s.split("_")[1], 16)
            lines += [f"{s}:\t; transfer out of the translated modules",
                      f"\tmove.l #{hx(u.ip_of(off))},d7", "\tjmp rt_stop_unknown"]
            stats["stop_unknown site"] += 1
        candidates = {}
        for node in self.succ:
            if node[0] != mod or self.node_insn(node).op != "jcc":
                continue
            jump = self.fall.get(node)
            if jump not in self.succ or jump in self.leaders:
                continue
            ji = self.node_insn(jump)
            if ji.op != "jmp" or not isinstance(ji.operands[0], Rel):
                continue
            skip = (mod, jump[1] + ji.size)
            if self.succ[node][0] != skip or skip not in self.succ:
                continue
            for lab, ctx in ((label, self.ctx), (copy_label, None)):
                if ctx is None:
                    comp = next((k for k, c in enumerate(self.comps) if node in c[2] and jump in c[2]), None)
                    if comp is None:
                        continue
                    target = self.copy_ctx(mod, jump[1], stats, comp).near(ji.operands[0].target)
                    skip_label = self.copy_ctx(mod, node[1], stats, comp).near(self.node_insn(node).operands[0].target)
                else:
                    target = ctx(mod, jump[1], stats).near(ji.operands[0].target)
                    skip_label = label(*skip)
                candidates[lab(*jump)] = (lab(*node), skip_label, target)
        fused = fuse_jumps(lines, candidates, stats)
        retarget_jump_aliases(lines, fused, candidates)
        self.fused_jumps.update(fused)
        drop_next_branches(lines, stats)
        align(lines, self.align, stats)
        size_branches(lines)
        stats["guest instructions"] += len(u.insns)
        stats["68k lines"] += sum(1 for x in lines if x.startswith("\t"))
        return lines, stats
