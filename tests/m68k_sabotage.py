#!/usr/bin/env python3
"""Sabotage the 68020 differential (translation-lessons #42): each planted fault in
the lowering's output must produce mismatches. Exit 1 if one passes unnoticed.
Corpus "program" runs the generated-program block differential (m68k_blocks).
The plants run in parallel, one at a time per worker process, stopping after
the first caught batch. Uncaught plants exhaust their corpus and fail. The x86 side of
make test's boundary run (RECORD) is reused wherever a plant's case matches it.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m68k_blocks as B  # noqa: E402
import m68k_diff as D  # noqa: E402
from translator import emit as E, flags as F, lower as L, region as R, reuse as U, smc as S  # noqa: E402

real_run = L.Lowering.run
real_helpers = D.HELPERS
real_poll_stub = E.poll_stub
real_mismatch_stub = E.mismatch_stub
real_bp_range = R.bp_range
real_carry_ccr = F.carry_ccr
real_flags_dead = L.Lowering.flags_dead
real_walk = S.walk
real_muldiv_source = L.Lowering.muldiv_source
real_written = U.written
real_op_jcc = L.Lowering.op_jcc
real_plan = F.plan
real_reuse = U.reuse
real_fold = U.fold
real_guard_lines = U.guard_lines
real_slow_path = U.slow_path
real_base_written = U.base_written
real_bp_native = U.bp_native
real_stack_runs = U.stack_runs
real_invert = E.INVERT
real_fuse_jumps = E.fuse_jumps
real_retarget_aliases = E.retarget_jump_aliases
real_outline_cold = E.Program.outline_cold
real_cold_return = E.cold_return
real_retried = E.retried
real_copy_exits = E.copy_exits
RECORD = Path(__file__).resolve().parent.parent / "tmp/test/x86-side-boundary.pkl"


def text(fn):
    def run(self):
        out = real_run(self)
        self.out = fn(self, out)
        self.cold = fn(self, self.cold) if self.cold else self.cold
        return self.out
    return run


def guard_one_past(ds, slow):
    """R14f: each fold guard admits one value past its limit."""
    out = real_guard_lines(ds, slow)
    for k, x in enumerate(out):
        m = re.match(r"^\tcmp\.w #(-?\d+),d7$", x)
        if m:
            out[k] = f"\tcmp.w #{int(m.group(1)) + (1 if 'bgt' in out[k + 1] else -1)},d7"
    return out


def kept_x_restored_late(self, out):
    """R28: X kept across an operand setup comes back after the load into d6."""
    out = list(out)
    for k in range(len(out) - 2, -1, -1):
        if out[k] == "\tadd.b d6,d6":
            out[k], out[k + 1] = out[k + 1], out[k]
    return out


def far_exact_cs_low(self, out):
    """R29: the wrapped far push's exact path stores CS a word low."""
    return ["\tsubq.w #4,d4" if x == "\tsubq.w #2,d4" and k and re.match(r"^\w+_pf\d+:$", out[k - 1])
            else x for k, x in enumerate(out)]


def seg_compare_other_slot(self, out):
    """R30: the repeat compare reads another segment's slot."""
    other = {"G_ES": "G_DS", "G_DS": "G_ES", "G_SS": "G_ES"}
    return [re.sub(r"^\tcmp\.w (G_[EDS]S)\(a6\),", lambda m: f"\tcmp.w {other[m.group(1)]}(a6),", x)
            for x in out]


def seg_changed_keeps_upper(self, out):
    """R30: a changed segment's out-of-line path skips the zero-extension."""
    res, cold = [], False
    for x in out:
        cold = bool(re.match(r"^\w+_gx\d+:$", x)) or cold and x.startswith("\t")
        res.append("\tnop" if cold and re.match(r"^\tand\.l #\$ffff,d[67]$", x) else x)
    return res


def sub(pattern, repl):
    rx = re.compile(pattern)
    return lambda self, out: [rx.sub(repl, line) for line in out]


def drop_after(first, second):
    def f(self, out):
        res, k = [], 0
        while k < len(out):
            res.append(out[k])
            if out[k].strip() == first and k + 1 < len(out) and out[k + 1].strip() == second:
                k += 1
            k += 1
        return res
    return f


def no_merge(self, out):
    """Partial flag merges become full CCR stores (inc/dec lose CF)."""
    res, k = [], 0
    while k < len(out):
        if out[k].strip() == "move.w ccr,d7" and k + 3 < len(out) and "G_FL+1" in out[k + 3]:
            res.append("\tmove.w ccr,G_FL(a6)")
            k += 4
            continue
        res.append(out[k])
        k += 1
    return res


def no_wrap_guard(self, out):
    """REP fast path taken whatever SI/DI (the 16-bit wrap guard removed)."""
    return [x for k, x in enumerate(out)
            if not (x.startswith("\tbcc ") and k and out[k - 1].startswith("\tcmp.l #$10000,"))]


def no_runout_fix(self, out):
    """REPE/REPNE fast path: CX left at FFFFh when the count runs out."""
    return [x for k, x in enumerate(out)
            if not (x == "\taddq.w #1,d1" and k and out[k - 1].startswith(("\tbne.s ", "\tbeq.s ")))]


def drop_fused_store(self, out):
    """A setter that leaves flags in the CCR stores nothing (flags lost across blocks)."""
    if self.ccr:
        return [x for x in out if "ccr,G_FL" not in x]
    return out


def trust_x_across_ea(self, out):
    """T4: bypass the proof that operand setup preserves incoming carry in X."""
    if getattr(self.c, "x_in", False):
        for reg in ("d6", "d7"):
            out = drop_after(f"move.b G_FL+1(a6),{reg}", f"lsr.b #1,{reg}")(self, out)
            out = [s for s in out if s != f"\tmove.b G_FL+1(a6),{reg}"]
    return out


def no_predecessor_store(self, out):
    """T4: skip a predecessor store needed by another successor's reload."""
    if self.i.op == "cmp":
        return [s for s in out if "ccr,G_FL" not in s]
    return out


def trust_dirty_upper_word(self, out):
    """T6: replace every word mask even when its upper word is unknown."""
    return [re.sub(r"^\tand\.l #\$ffff,(d[0-7])$", r"\ttst.l \1", line) for line in out]


def drop_live_dx(self, out):
    """T7: discard every word high/remainder result without a liveness proof."""
    if self.i.width != 16:
        return out
    if self.i.op in ("mul", "imul"):
        return [s for s in out if s not in ("\tmove.l d0,d2", "\tswap d2")]
    if self.i.op in ("div", "idiv"):
        # R9: the remainder's swap after the quotient is read
        return [x for k, x in enumerate(out) if not (x == "\tswap d2" and out[k - 1] == "\tmove.w d2,d0")]
    return out


def fault_keeps_dx_swapped(self, out):
    """R9: a divide fault leaves DX:AX in d2 (the fault path's swap back dropped)."""
    return [x for k, x in enumerate(out) if not (x == "\tswap d2" and out[k - 1].endswith(":"))]


def high_byte_written_low(self, out):
    """T8: corrupt the neighboring byte instead of writing the high byte."""
    result = list(out)
    for reg in ("d0", "d1", "d2", "d3"):
        for src in ("d6", "d7"):
            old = [f"\tror.w #8,{reg}", f"\tmove.b {src},{reg}", f"\trol.w #8,{reg}"]
            k = 0
            while k + 2 < len(result):
                if result[k:k+3] == old:
                    result[k:k+3] = [f"\tmove.b {src},{reg}"]
                k += 1
    return [line.replace("{16:8}", "{24:8}") if line.startswith("\tbfins ") else line for line in result]

def byte_copy_uses_destination(self, out):
    """T10: copy the old destination instead of the source byte."""
    from translator.decode import Reg
    if self.i.op != "mov" or self.i.width != 8:
        return out
    a, b = self.i.operands
    if not all(isinstance(o, Reg) and o.name in L.HALF for o in (a, b)):
        return out
    ar, ah = L.HALF[a.name]
    br, bh = L.HALF[b.name]
    if ah != bh:
        return out
    ar, br = L.GREG[ar], L.GREG[br]
    return [re.sub(r"^(\tmove\.[bwl] )" + br + r",(d6|" + ar + r")$",
                   lambda m: m[1] + ar + "," + m[2], line) for line in out]


def stale_address_offset(self, out):
    """T12: trust scratch d7 without proving its value or address inputs."""
    if self.i.op != "mov" or self.i.width != 16:
        return out
    result = []
    skipping = False
    for line in out:
        if re.fullmatch(r"\tmove.w (d[45]|#\S+),d7", line):
            skipping = True
            continue
        if skipping and re.match(r"\t(sub|subq|addq)\.w .*,d7$", line):
            continue
        skipping = False
        result.append(line)
    return result


def shift_disp(line: str, k: int) -> str:
    """Displacements of direct segment-relative operands (v,aN) plus k."""
    def one(m):
        v = m[1]
        neg = v.startswith("-")
        v = v.lstrip("-")
        n = int(v[1:], 16) if v.startswith("$") else int(v)
        return f"({(-n if neg else n) + k},{m[2]})"
    return re.sub(r"\((-?\$?[0-9a-f]+),(a[1-3])\)", one, line)


def top_off_by_one(self, out):
    """D1: guest linear L read at TOP - L - 1 (direct offsets off by one byte)."""
    return [shift_disp(line, -1) for line in out]


def word_at_byte_address(self, out):
    """D1: a word read or written at its low byte's host address, not one below."""
    return [shift_disp(line, 1).replace("-1(a", "0(a") if line.startswith("\t") and
            line.split()[0].endswith(".w") else line for line in out]


def rmw_word_at_byte_address(self, out):
    """D1: a read-modify-write word operand addressed at its low byte."""
    if self.i.width != 16:
        return out
    return [line.replace("lea -1(a", "lea 0(a") for line in out]


def word_store_swapped(self, out):
    """D1: a register stored to a memory word in swapped byte order."""
    from translator.decode import Mem, Reg
    if self.i.op != "mov" or self.i.width != 16:
        return out
    a, b = self.i.operands
    if not (isinstance(a, Mem) and isinstance(b, Reg)):
        return out
    result = []
    for line in out:
        m = re.fullmatch(r"\tmove\.w (d[0-7]),(.*\(.*)", line)
        if m:
            result += [f"\tror.w #8,{m[1]}", line, f"\tror.w #8,{m[1]}"]
        else:
            result.append(line)
    return result


def folded_word_as_byte(self, out):
    """R1d: a folded word read-modify-write applied to one byte (an immediate
    cut to its low byte, so the line still assembles)."""
    if self.i.width != 16 or not self.i.operands or not hasattr(self.i.operands[0], "disp"):
        return out

    def one(m):
        src = re.sub(r"^#(\$[0-9a-f]+|\d+)(?=,)",
                     lambda k: f"#${int(k.group(1).lstrip('$'), 16 if k.group(1)[0] == '$' else 10) & 0xFF:x}",
                     m.group(2))
        return f"\t{m.group(1)}.b {src}"
    return [re.sub(r"^\t(add|sub|and|or|eor|addq|subq|neg|not|addi|subi|andi|ori|eori)\.w (.*\()",
                   one, line) for line in out]


def walk_low_endpoint_rejected(self, out):
    bounds = {f"cmp.w #{L.hx(span[0])},d7" for span in self.c.smc_targets}
    return [line.replace("blo ", "bls ") if k and out[k-1].strip() in bounds else line
            for k, line in enumerate(out)]


def walk_guard_omitted(edge):
    """Drop one exact region bound; out-of-range transfers must not enter a walk."""
    def fault(self, out):
        bounds = {f"cmp.w #{L.hx(span[edge])},d7" for span in self.c.smc_targets}
        result, k = [], 0
        while k < len(out):
            if out[k].strip() in bounds and k + 1 < len(out) and out[k+1].strip().startswith(
                    "blo " if edge == 0 else "bhi "):
                k += 2
            else:
                result.append(out[k])
                k += 1
        return result
    return fault


def table_target_omitted(self, out):
    """A proved near table routes its first row to the fail-loud fallback."""
    if not self.c.complete or not self.c.near_targets:
        return out
    lab = self.c.near(self.c.near_targets[0])
    return [line.replace(f"jsr {lab}", "jsr rt_stop_unknown").replace(
            f"jmp {lab}", "jmp rt_stop_unknown") for line in out]


def untraced_table_row_omitted(self, out):
    """The last row of the untraced selector table must reach native output."""
    if self.c.label != E.label("SWOTL.EXE", 0x0534a):
        return out
    assert self.c.complete and self.c.near_targets
    lab = self.c.near(self.c.near_targets[-1])
    return [line.replace(f"jsr {lab}", "jsr rt_stop_unknown") for line in out]


def walk_entry_flag(self, out):
    """A live flag wrong on entry to a cell walk (D16): CF flipped in the state
    block just before the walk is called."""
    return [x for line in out for x in
            (["\teori.b #1,G_FL+1(a6)", line] if re.match(r"^\tjsr \w+_walk$", line) else [line])]


def wrong_mirror(self, out):
    """D1: SP/BP converted with a wrong mirror constant."""
    return [line.replace("eori.w #$7fff,", "eori.w #$7ffe,") for line in out]


def no_native_conversion(self, out):
    """D1: SP/BP used as a value (moves, flag-live arithmetic) without conversion."""
    return [line for line in out if not re.fullmatch(r"\teori\.w #\$7fff,d[67]", line)]


def mirror_not_restored(self, out):
    """D1: a value written to SP/BP left native (the mirror not re-applied)."""
    return [line for line in out if not re.fullmatch(r"\teori\.w #\$7fff,d[45]", line)]


def unbiased_segment_base(self, out):
    """D1: a segment base loaded as a6 - seg*16 without the 7FFFh bias."""
    return [line.replace("lea -$7fff(a6),", "lea (a6),") for line in out]


def native_index_added(self, out):
    """D1: a native index register added to the mirrored offset."""
    return [re.sub(r"^\tsub\.w (d3|a4|a5),d7$", r"\tadd.w \1,d7", line) for line in out]


def linear_retf_stack(self, out):
    """Independent-oracle plant: lose 16-bit SP wrap in RETF's pops (R4: SP's
    upper word is undefined, so the wrap lives in the word index)."""
    if self.i.op == "retf":
        return [line.replace("(a2,d4.w)", "(a2,d4.l)") for line in out]
    return out


def address_copy_from_stale_scratch(self, out):
    """T15: copy the address/result scratch instead of the restored word."""
    return [re.sub(r"^\tmovea\.l d6,(a[45])$", r"\tmovea.l d7,\1", line) for line in out]


def provenance_any_move(lines, ccr, res, nz):
    """R3b: N and Z trusted after a move of any data register, at any width."""
    if res:
        lines = [re.sub(r"^\tmove\.[bw] d[0-7],", f"\tmove.{L.SZ[res[1]]} {res[0]},", x)
                 for x in lines]
    return real_carry_ccr(lines, ccr, res, nz)



def trust_register_upper_word(self, out):
    """R4: a 32-bit consumer copies the guest register whole instead of zero-extending."""
    result = []
    for line in out:
        m = re.match(r"^\tmove\.w ([ad][0-5]),(d[67])$", line)
        if m and m.group(1) in ("d0", "d1", "d2", "d3", "d4", "d5", "a4", "a5") \
                and result and result[-1] == f"\tmoveq #0,{m.group(2)}":
            result[-1] = f"\tmove.l {m.group(1)},{m.group(2)}"
        else:
            result.append(line)
    return result


def pair_odd_dropped(self, out):
    """R12/R24/R26: the pair loops skip an odd element (STOSW's last, CMPSW's last)."""
    return [x.replace("\tbcc.s ", "\tbra.s ") if out[k - 1:k] == ["\tlsr.w #1,d7"]
            and out[k - 2].startswith("\tdbf d1,")
            else x.replace("\tbeq.s ", "\tbra.s ") if out[k - 1:k] == ["\tcmpa.l d7,a5"]
            else x for k, x in enumerate(out)]


def compare_remainder_skipped(self, out):
    """R26: REPE CMPSW compares no remainder pair before its eight-pair passes."""
    return ["\tandi.w #0,d1" if x == "\tandi.w #7,d1" and out[k + 1:k + 2] == ["\tsubq.w #1,d1"]
            else x for k, x in enumerate(out)]


def compare_pass_exit_dropped(self, out):
    """R26: the eight-pair pass ignores a mismatch before its last pair."""
    return ["\tnop" if re.fullmatch(r"\tbne\.s \.\d+", x) and out[k - 1] == "\tcmp.l -(a5),d6"
            else x for k, x in enumerate(out)]


def fill_remainder_skipped(self, out):
    """R24: REP STOSW enters its eight-long loop at the dbf whatever the remainder."""
    return ["\tmoveq #0,d6" if x == "\tneg.w d6" and out[k + 1:k + 2]
            and out[k + 1].startswith("\tjmp ") and out[k + 1].endswith("(pc,d6.w*2)") else x
            for k, x in enumerate(out)]


def copy_overlap_ignored(self, out):
    """F2: REP MOVSW copies by longs when DI is 1-3 bytes above SI."""
    return ["\tnop" if x.startswith("\tbls.s ") and out[k - 3:k] == [
        "\tsubq.l #1,d6", "\tmoveq #2,d7", "\tcmp.l d7,d6"] else x for k, x in enumerate(out)]


def pair_half_store(self, out):
    """R12: REP STOSW stores AX in one word of each long only."""
    return [x for k, x in enumerate(out)
            if not (x == "\tswap d6" and out[k - 1:k] == ["\tmove.w d0,d6"]
                    and out[k + 1:k + 2] == ["\tmove.w d0,d6"])]


def string_pointer_32(self, out):
    """R4: the REP fast path converts SI/DI to pointers with all 32 bits."""
    result, k = [], 0
    while k < len(out):
        m = re.match(r"^\tmove\.w (a[45]),d6$", out[k])
        if m and out[k + 1:k + 4] == ["\teori.w #$8000,d6", out[k + 2], f"\tsuba.w d6,{m.group(1)}"]:
            base = re.match(r"^\tmovea\.l (a[0-7]),", out[k + 2]).group(1)
            result += ["\tmove.l #$8000,d6", f"\tadd.l {base},d6", f"\tsub.l {m.group(1)},d6",
                       f"\tmovea.l d6,{m.group(1)}"]
            k += 4
        else:
            result.append(out[k])
            k += 1
    return result


def return_check_32(self, out):
    """R5: a return check compares all 32 bits of the popped IP."""
    return [x.replace("cmp.w", "cmp.l", 1) if x.startswith("\tcmp.w #") and x.endswith(",d7")
            and out[k + 1:k + 2] == [f"\tbne {E.RM}"] else x for k, x in enumerate(out)]

def far_return_check_word(self, out):
    return [re.sub(r"^\tcmp\.l #(.+),d7$", r"\tcmp.w #((\1)&$ffff),d7", x)
            if x.startswith("\tcmp.l #") and x.endswith(",d7")
            and out[k + 1:k + 2] == [f"\tbne {E.RMF}"] else x for k, x in enumerate(out)]


def far_return_exact_cs_lost(self, out):
    if self.i.op == "retf" and any(re.match(r"^\w+_rf\d+:$", x) for x in out):
        return ["\tnop" if x == "\tmove.w d6,d7" else x for x in out]
    return out


def direct_bp_off_by_one(self, out):
    """R6: a guarded copy's direct [bp+d] one byte off."""
    def fix(m):
        return f"({int(m.group(1).replace('$', '0x'), 0) + 1},{m.group(2)},d5.w)"
    return [re.sub(r"\((-?\$?[0-9a-f]+),(a[0-3]),d5\.w\)", fix, x) for x in out]


def test_mask_dropped(self, out):
    """R14c: TEST of memory trusts every immediate as all ones (its AND dropped)."""
    if self.i.op == "test":
        return [x for x in out if not re.match(r"^\tand\.[bw] #", x)]
    return out


def index_self_test_unset(self, out):
    """R14g: OR/AND/TEST of SI or DI with itself sets no flags (its move dropped)."""
    a = self.i.operands
    if self.i.op in ("or", "and", "test") and L.areg(a[0]) and a[1] == a[0]:
        return [x for x in out if not re.match(r"^\tmove\.w a[45],d6$", x)]
    return out


def jump_passes_every_flag(self):
    """R14b: a conditional jump claims every flag (and X) in the CCR it passes on."""
    real_op_jcc(self)
    if self.ccr or self.c.ccr_in:
        self.ccr = set(L.ALLC) | {"X"}


def chain_ignores_targets(insns, lives, leaders, ctx_for, program=False, fences=(), taken=None):
    """R14d: a jump chain's targets taken to need no flags."""
    taken = [None if t is None else set() for t in (taken or [None] * len(insns))]
    return real_plan(insns, lives, leaders, ctx_for, program, fences, taken)


def walk_plant(old, new):
    """R7: the cell walk with one line replaced (smc.walk)."""
    def walk(*a):
        out = real_walk(*a)
        assert old in out
        return [new if x == old else x for x in out]
    return walk


def walk_regex(pattern, new):
    """D3: the cell walk with every line matching `pattern` replaced (smc.walk)."""
    rx = re.compile(pattern)
    def walk(*a):
        out = real_walk(*a)
        assert any(rx.fullmatch(x) for x in out), pattern
        return [rx.sub(new, x) if rx.fullmatch(x) else x for x in out]
    return walk


def cache_zero_tag_admitted(self, out):
    """Let an outside zero store revive an invalid cache via its zero tag."""
    return ["\tnop" if k and out[k - 1] == "\ttst.w d6" and
            re.fullmatch(r"\tbeq \w+_hr\d+", line) else line
            for k, line in enumerate(out)]


def bp_native_line(old, new):
    """R25: reuse.bp_native with one source line changed."""
    source = inspect.getsource(real_bp_native)
    assert source.count(old) == 1, old
    scope = dict(U.__dict__)
    exec(source.replace(old, new), scope)
    return scope["bp_native"]


BP_PLANTS = {
    "bp exit": ("D5.search(x) or EXIT.match(x)", "D5.search(x)"),
    "bp source": ("w is None or nat in w or", "w is None or"),
    "bp reader": ("w is None or D5.search(x) or EXIT.match(x)", "w is None or EXIT.match(x)"),
}


def stack_runs_line(old, new):
    """R31: reuse.stack_runs with one source line changed."""
    source = inspect.getsource(real_stack_runs)
    assert source.count(old) == 1, old
    scope = dict(U.__dict__)
    exec(source.replace(old, new), scope)
    return scope["stack_runs"]


STACK_PLANTS = {
    "stack wrap": (', f"\\tbvs {cold}"] if j == 0', '] if j == 0'),
    "stack push slot": ("{2 * (j - n) + 1}(a2", "{2 * (j - n) + 3}(a2"),
    "stack pop order": ("{2 * (n - j) - 1}(a2", "{2 * j + 1}(a2"),
    "stack undo": ('[f"{cold}:", f"\\t{sub}{q}.w #{size},d4"]', '[f"{cold}:"]'),
}


def wide_bp_range(insns):
    """R6: the region guard admits BP one past each end of its range."""
    r = real_bp_range(insns)
    return r and (max(r[0] - 1, -0x8000), min(r[1] + 1, 0x7FFF))


SABOTAGE = [
    ("jb/jae swapped", sub(r"\bbcs\b", "bcc"), "forms,boundary"),
    ("TOP off by one", top_off_by_one, "boundary"),
    ("word at its byte address", word_at_byte_address, "boundary"),
    ("adc/rcl ignore CF", drop_after("move.b G_FL+1(a6),d7", "lsr.b #1,d7"), "boundary"),
    ("adc/sbb Z preset dropped while ZF live", sub(r"^\tori\.b #4,ccr$", "\tnop"), "boundary"),
    ("SP not 16-bit", sub(r"\(a2,d4\.w\)", "(a2,d4.l)"), "boundary"),
    ("DF ignored", sub(r"^\ttst\.b G_DF\(a6\)$", "\tcmp.b d0,d0"), "boundary"),
    ("partial flag merge as full store", no_merge, "boundary"),
    ("shift count mod 16", sub(r"moveq #\$1f,d7", "moveq #$f,d7"), "boundary"),
    ("fused setter stores nothing", drop_fused_store, "program"),
    ("RMW word at its byte address", rmw_word_at_byte_address, "forms"),
    ("sti does not re-arm G_IRQ", sub(r"^\tmove\.b rt_irq_pending,G_IRQ\(a6\)$", "\tnop"), "boundary"),
    ("popf/iret do not re-arm G_IRQ", ("helpers", "\tmove.b\trt_irq_pending,G_IRQ(a6)", "\tnop"),
     "boundary"),
    ("REP fast path without wrap guard", no_wrap_guard, "boundary"),
    ("REPE/REPNE run-out leaves CX FFFFh", no_runout_fix, "boundary"),
    ("carry X trusted across EA clobber", trust_x_across_ea, "boundary"),
    ("word store in swapped byte order", word_store_swapped, "boundary"),
    ("predecessor drops successor flag store", no_predecessor_store, "cross-block"),
    ("live flag wrong at a walk entry", walk_entry_flag, "program"),
    ("poll stub returns to the poll's label", "poll stub", "program"),
    ("mask trusts dirty upper word", trust_dirty_upper_word, "boundary"),
    ("DX result dropped while live", drop_live_dx, "boundary"),
    ("high-byte write corrupts low byte", high_byte_written_low, "boundary"),
    ("byte copy uses destination", byte_copy_uses_destination, "boundary"),
    ("folded word op on one byte", folded_word_as_byte, "boundary"),
    ("wrong mirror constant", wrong_mirror, "boundary"),
    ("SP/BP value without native conversion", no_native_conversion, "boundary"),
    ("wrapped offset trusted without proof", stale_address_offset, "boundary"),
    ("native index added", native_index_added, "boundary"),
    ("SP/BP mirror not restored", mirror_not_restored, "boundary"),
    ("unbiased segment base", unbiased_segment_base, "boundary"),
    ("RETF CS pop uses linear SP", linear_retf_stack, "boundary"),
    ("address restoration copies stale scratch", address_copy_from_stale_scratch, "boundary"),
    ("N/Z provenance trusts a move of another value", "provenance", "boundary"),
    ("32-bit consumer trusts a register's upper word", trust_register_upper_word, "boundary"),
    ("SI/DI in place with flags live", "flags dead", "boundary"),
    ("REP fast path converts SI/DI as 32 bits", string_pointer_32, "boundary"),
    ("return check compares 32 bits", return_check_32, "program"),
    ("return-check trampoline falls through", "mismatch stub", "program"),
    ("region guard admits one past its range", "bp range", "boundary"),
    ("direct [bp+d] one byte off", direct_bp_off_by_one, "boundary"),
    ("mov run counts one cell past the bound", walk_plant("\tlsr.l #2,d6", "\tlsr.l #2,d6\n\taddq.l #1,d6"),
     "walk"),
    ("mov run skips the opcode compare", walk_plant("\tcmp.w d1,d7", "\tcmp.w d7,d7"), "walk"),
    ("divide fault leaves DX:AX swapped", fault_keeps_dx_swapped, "boundary"),
    ("divide reads DX from the dividend", "divide source", "boundary"),
    ("pair mismatch blames the second element", sub(r"^\tcmp\.w 2\(a5\),d6$", "\tcmp.w d6,d6"),
     "boundary"),
    ("pair loop skips the odd element", pair_odd_dropped, "boundary"),
    ("pair store writes AX in one word", pair_half_store, "boundary"),
    ("fill skips the remainder longs", fill_remainder_skipped, "boundary"),
    ("fill aligning word not counted", drop_after("move.w d0,-(a5)", "subq.w #1,d1"), "boundary"),
    ("fill passes of sixteen longs", sub(r"^\tlsr\.w #3,d1$", "\tlsr.w #4,d1"), "boundary"),
    ("pair count keeps the even part", sub(r"^\tlsr\.l #1,d1$", "\tlsr.l #1,d1\n\tbclr #0,d1"),
     "boundary"),
    ("copy by longs ignores overlap", copy_overlap_ignored, "boundary"),
    ("copy aligning word not counted", drop_after("move.w -(a4),-(a5)", "subq.w #1,d1"), "boundary"),
    ("compare skips the remainder pairs", compare_remainder_skipped, "boundary"),
    ("compare pass ignores an early mismatch", compare_pass_exit_dropped, "boundary"),
    ("held index survives register writes", "reuse writes", "boundary"),
    ("BP mirror store dropped across an exit", "bp exit", "program"),
    ("native BP kept after its source changes", "bp source", "boundary"),
    ("BP mirror store dropped before a d5 read", "bp reader", "boundary"),
    ("fused conditional keeps its condition", "jump condition", "program"),
    ("fused jump aliases fall-through", "jump alias", "program"),
    ("outlined jcc keeps its condition", "outline condition", "program"),
    ("outlined range falls through", "outline return", "program"),
    ("carry X kept across a setup not restored", sub(r"^\tadd\.b d6,d6$", "\tnop"), "boundary"),
    ("carry X kept across a setup restored after the load", kept_x_restored_late, "boundary"),
    ("far push long ignores the SP wrap", sub(r"^\tbvs \w+_pf\d+$", "\tnop"), "boundary"),
    ("far push long swaps CS and IP",
     sub(r"^\tmove\.l #\(\((.+)\)<<16\)\|(\S+),-3\(a2,d4\.w\)$", r"\tmove.l #((\2)<<16)|\1,-3(a2,d4.w)"),
     "boundary"),
    ("far push exact path stores CS a word low", far_exact_cs_low, "boundary"),
    ("far pop long ignores the SP wrap", sub(r"^\tbvs \w+_rf\d+$", "\tnop"), "boundary"),
    ("far pop long reads a word low",
     sub(r"^\tmove\.l 1\(a2,d4\.w\),d7$", "\tmove.l -1(a2,d4.w),d7"), "boundary"),
    ("far pop exact path loses CS", far_return_exact_cs_lost, "boundary"),
    ("far return check ignores CS", far_return_check_word, "program"),
    ("changed segment load treated as a repeat", sub(r"^\tbne \w+_gx\d+$", "\tnop"), "boundary"),
    ("segment repeat compares another segment", seg_compare_other_slot, "boundary"),
    ("changed segment keeps the upper word", seg_changed_keeps_upper, "boundary"),
    ("stack run ignores the SP wrap", "stack wrap", "boundary"),
    ("stack run push slots one step off", "stack push slot", "boundary"),
    ("stack run pops in reverse order", "stack pop order", "boundary"),
    ("stack run exact path keeps the step", "stack undo", "boundary"),
    ("stack run spans a block leader", "stack leaders", "program"),
    ("held index survives a block leader", "reuse leaders", "program"),
    ("divide retry enters no leader", "retry leaders", "program"),
    ("copy exit enters no leader", "copy exit leaders", "program"),
    ("high-byte clear keeps bit 8", sub(r"^\tand\.w #\$ff,(d[0-3])$", r"\tand.w #$1ff,\1"),
     "boundary"),
    ("high-byte zero flags from 1", sub(r"^\tmoveq #0,d6$", "\tmoveq #1,d6"), "boundary"),
    ("high-byte self-test flags of the word", sub(r"^\tand\.w #\$ff00,d6$", "\tand.w #$ffff,d6"),
     "cross-block"),
    ("high-byte AND immediate clears the low byte",
     sub(r"^\tand\.w #\$([0-9a-f]*)ff,(d[0-3])$", r"\tand.w #$\g<1>00,\2"), "boundary"),
    ("jump passes every flag in the CCR", "jcc ccr", "cross-block"),
    ("jump chain ignores its targets' flags", "chain taken", "cross-block"),
    ("TEST of memory trusts all ones", test_mask_dropped, "boundary"),
    ("SI/DI self-test sets no flags", index_self_test_unset, "boundary"),
    ("divide error branch dropped", sub(r"^\tbvs \w+_dz$", "\tnop"), "boundary"),
    ("folded index guard admits one past", "fold guard", "boundary"),
    ("folded index slow path skipped", "fold slow", "boundary"),
    ("folded index survives a base write", "fold base", "boundary"),
    ("folded index survives a block leader", "fold leaders", "program"),
    ("parity table one entry off", ("helpers", "__parity(pc,", "__parity+1(pc,"), "boundary"),
    ("CCR-to-FLAGS table one entry off", ("helpers", "__ccr_flags(pc,", "__ccr_flags+2(pc,"),
     "boundary"),
    ("FLAGS-to-CCR table one entry off", ("helpers", "__sahf_ccr(pc,", "__sahf_ccr+1(pc,"),
     "boundary"),
    ("proved near table omits a target", table_target_omitted, "program"),
    ("untraced annotated table row omitted", untraced_table_row_omitted, "program"),
    ("cell cache: a run stores one cell more", walk_plant("\tlsr.w #2,d6", "\tlsr.w #2,d6\n\taddq.w #1,d6"),
     "walk"),
    ("cell cache: offsets wrapping at 16 bits stored as one run", walk_plant("\tbvs .wrap", "\tnop"),
     "walk"),
    ("cell cache: a run continues past an operand gap", walk_plant("\tcmp.w d1,d2", "\tcmp.w d2,d2"),
     "walk"),
    ("cell cache: decode covers no bytes", walk_regex(r"\tmove\.l #\$[0-9a-f]{2}010101,\(a1,d5\.w\)", "\tnop"),
     "walk"),
    ("cell cache: store hook drops a RET plant", walk_regex(r"\tmove\.w d6,\w+_walk_plant", "\tnop"),
     "walk"),
    ("cell cache: store hook keeps a restored RET", walk_regex(r"\tmove\.w #-1,\w+_walk_plant", "\tnop"),
     "walk"),
    ("cell cache: store hook keeps a changed cell", walk_regex(r"\.inv:\tclr\.w \w+_walk_plant", ".inv:"),
     "walk"),
    ("cell cache: a dropped cache walked", walk_regex(r"\tbeq \w+_walk_reset", "\tnop"), "walk"),
    ("cell cache: a reload's DS reaching a region kept cached",
     walk_regex(r"\tcmp\.w #\$[0-9a-f]+,d5", "\tcmp.w d5,d5"), "walk"),
    ("segment load keeps the cell caches", sub(r"^\tjsr smc_expose$", "\tnop"), "program"),
    ("CS store skips its cell cache hook", sub(r"^\tjsr \w+_walk_w[bw]$", "\tnop"), "program"),
    ("CS store drops its RET plant", sub(r"^\tmove\.w d6,\w+_walk_plant$", "\tnop"), "program"),
    ("CS store keeps a restored RET", sub(r"^\tmove\.w #-1,\w+_walk_plant$", "\tnop"), "program"),
    ("CS store revives invalid cache at zero tag", cache_zero_tag_admitted, "program"),
    ("walk lower bound omitted", walk_guard_omitted(0), "program"),
    ("walk upper bound omitted", walk_guard_omitted(1), "program"),
    ("flag extraction reads DF as IF", ("helpers", "\tbfextu\td7{22:1},d6",
                                        "\tbfextu\td7{21:1},d6"), "boundary"),
    ("walk lower endpoint rejected", walk_low_endpoint_rejected, "program"),
    ("string direction reads CX instead of DF",
     sub(r"^\ttst\.b G_DF\(a6\)$", "\ttst.b d1"), "boundary"),
]


class CaughtBatch(Exception):
    """Only a completed differential batch with mismatches may stop a plant."""


class CaughtProgram(Exception):
    pass


def completed_program_batch(total, failures):
    if failures:
        raise CaughtProgram(len(failures), total, 0, 0)


class PlantHarness(D.Harness):
    def flush(self):
        super().flush()
        if self.bad:
            raise CaughtBatch(self)


def plant(k: int) -> tuple[int, int, int, int]:
    """Plant SABOTAGE[k] and run its corpus: (mismatches, cases, x86 sides replayed, of)."""
    name, fn, corpus = SABOTAGE[k]
    D.Harness.keep_failing = False      # planted mismatches: no batch is kept
    if isinstance(fn, tuple):   # flag helpers (translator/support.py)
        D.HELPERS = real_helpers.replace(fn[1], fn[2])
        assert D.HELPERS != real_helpers
    elif fn == "poll stub":     # emit.poll_stub (R2)
        E.poll_stub = lambda lab, ip, cs, *a: [f"\tbra {lab}" if t == f"\tbra {lab}_np" else t
                                               for t in real_poll_stub(lab, ip, cs, *a)]
    elif fn == "provenance":    # flags.carry_ccr (R3b)
        F.carry_ccr = provenance_any_move
    elif fn == "flags dead":    # Lowering.flags_dead (R4)
        L.Lowering.flags_dead = lambda self, kind: True
    elif fn == "mismatch stub":     # emit.mismatch_stub (R5)
        E.mismatch_stub = lambda lab, far=False: [f"{lab}:"]
    elif fn == "bp range":  # region.bp_range (R6)
        R.bp_range = wide_bp_range
    elif fn in BP_PLANTS:           # reuse.bp_native (R25)
        U.bp_native = bp_native_line(*BP_PLANTS[fn])
    elif fn in STACK_PLANTS:        # reuse.stack_runs (R31)
        U.stack_runs = stack_runs_line(*STACK_PLANTS[fn])
    elif fn == "stack leaders":     # reuse.stack_runs (R31)
        U.stack_runs = lambda outs, resets, labels, colds: real_stack_runs(outs, set(), labels, colds)
    elif fn == "jump alias":
        E.retarget_jump_aliases = lambda *args: None
    elif fn == "jump condition":
        def wrong_fusion(lines, candidates, stats):
            saved = E.INVERT
            E.INVERT = {cc: cc for cc in saved}
            try:
                return real_fuse_jumps(lines, candidates, stats)
            finally:
                E.INVERT = saved
        E.fuse_jumps = wrong_fusion
    elif fn == "outline condition":     # R27 only: do not plant R32 too
        def wrong_outline(*args, **kwargs):
            saved = E.INVERT
            E.INVERT = {cc: cc for cc in saved}
            try:
                return real_outline_cold(*args, **kwargs)
            finally:
                E.INVERT = saved
        E.Program.outline_cold = wrong_outline
    elif fn == "outline return":        # emit.cold_return (R27)
        E.cold_return = lambda lab: []
    elif fn == "retry leaders":         # emit.retried (leaders)
        E.retried = lambda i: False
    elif fn == "copy exit leaders":     # emit.copy_exits (leaders)
        E.copy_exits = lambda p, nodes: set()
    elif fn == "reuse writes":      # reuse.written (R13)
        U.written = lambda line: None if real_written(line) is None else set()
    elif fn == "reuse leaders":     # reuse.reuse (R13)
        U.reuse = lambda outs, resets: real_reuse(outs, set())
    elif fn == "fold guard":        # reuse.guard_lines (R14f)
        U.guard_lines = guard_one_past
    elif fn == "fold slow":         # reuse.slow_path (R14f)
        U.slow_path = lambda slow, join, lines: real_slow_path(slow, join, [])
    elif fn == "fold base":         # reuse.base_written (R14f)
        U.base_written = lambda w, regs: "d7" in w
    elif fn == "fold leaders":      # reuse.fold (R14f)
        U.fold = lambda outs, resets, labels, colds: real_fold(outs, set(), labels, colds)
    elif fn == "chain taken":       # flags.plan (R14d)
        F.plan = chain_ignores_targets
    elif fn == "jcc ccr":           # Lowering.op_jcc (R14b)
        L.Lowering.op_jcc = jump_passes_every_flag
    elif fn == "divide source":     # Lowering.muldiv_source (R9)
        L.Lowering.muldiv_source = lambda self, o, div: real_muldiv_source(self, o, False)
    elif corpus == "walk":  # smc.walk (R7)
        S.walk = fn
    else:
        L.Lowering.run = text(fn)
    try:
        if corpus == "cross-block":
            total, failures = B.cross_entry_cases()
            return len(failures), total, 0, 0
        if corpus in ("program", "walk"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                B.main(["--blocks", "1500", "--states", "1"], on_batch=completed_program_batch)
            return (int(re.search(r"(\d+) mismatches", out.getvalue()).group(1)),
                    int(re.search(r"cases (\d+)", out.getvalue()).group(1)), 0, 0)
        D.REPLAY = RECORD
        h = D.X.run(["--only", corpus, "--states", "1", "--space", "2", "--blocks", "1500"],
                    quiet=True, harness=PlantHarness)
        h.flush()
        return len(h.bad), sum(h.count.values()), h.replayed, h.ncases
    except CaughtProgram as caught:
        return caught.args
    except CaughtBatch as caught:
        h = caught.args[0]
        return len(h.bad), sum(h.count.values()), h.replayed, h.ncases
    finally:
        D.Harness.tidy()
        D.REPLAY = None
        L.Lowering.run = real_run
        D.HELPERS = real_helpers
        E.poll_stub = real_poll_stub
        E.mismatch_stub = real_mismatch_stub
        E.INVERT = real_invert
        E.fuse_jumps = real_fuse_jumps
        E.retarget_jump_aliases = real_retarget_aliases
        E.Program.outline_cold = real_outline_cold
        E.cold_return = real_cold_return
        E.retried = real_retried
        E.copy_exits = real_copy_exits
        R.bp_range = real_bp_range
        S.walk = real_walk
        F.carry_ccr = real_carry_ccr
        L.Lowering.flags_dead = real_flags_dead
        L.Lowering.muldiv_source = real_muldiv_source
        U.written = real_written
        U.reuse = real_reuse
        U.fold = real_fold
        U.guard_lines = real_guard_lines
        U.slow_path = real_slow_path
        U.base_written = real_base_written
        U.bp_native = real_bp_native
        U.stack_runs = real_stack_runs
        L.Lowering.op_jcc = real_op_jcc
        F.plan = real_plan


def slow_first(k: int) -> tuple:
    """Submission order: plants that run two corpora or patch more than the lowered
    text may stray from the recording (live x86 side), then boundary plants."""
    _name, fn, corpus = SABOTAGE[k]
    return ("," not in corpus and callable(fn), "boundary" not in corpus)


def main() -> int:
    missed = []
    replayed = cases = 0
    with ProcessPoolExecutor(min(len(SABOTAGE), os.cpu_count() or 1)) as pool:
        futures = {k: pool.submit(plant, k) for k in sorted(range(len(SABOTAGE)), key=slow_first)}
        for k, (name, _fn, corpus) in enumerate(SABOTAGE):
            bad, total, r, n = futures[k].result()
            replayed, cases = replayed + r, cases + n
            print(f"{name:36} {corpus:15} mismatches {bad} of {total}", flush=True)
            if not bad:
                missed.append(name)
    print(f"x86 side replayed from {RECORD.name}: {replayed} of {cases} cases")
    if missed:
        print("not caught:", ", ".join(missed))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
