"""D16: a self-modified region as a run-time cell walk (option c), with a
cell cache (D3, open-work 32).

The region's writers produce a closed set of cell forms
(annotations/self-modifying.csv, kind `form`): opcode bytes fixed, `ww` a
word operand patched at run time. The exact walk (`_x`) starts at the entry
IP in d7, matches the guest bytes at each cell (descending in host memory,
D1; a0 one byte below the cell's first byte, so its first word is (a0))
against the forms, runs the matched form with its operand words read from
guest RAM and returns at the planted RET; any other byte, or a cell past the
region, stops (rt_stop_unknown). Each form's text is checked against the
decoder, so the lowering below is the lowering of the decoded instruction
with the run-time operand. Mov cells run as a counted run (R7): the mov
cells that fit before the bound are counted once, and each cell is still
matched from guest RAM when it runs (one long read: opcode word low,
operand word high); the first other cell leaves the run for the other forms.

The walk itself runs cached cells (D3). A cell is matched once, from the
guest bytes, when a walk first reaches it (`_decode`: mov and reload cells
up to the bound, a cached cell, a RET or any other byte); its bytes are then
covered (`_cov`: the first byte's value at a cell start, 1 inside). A mov
cell's record (`_rec`) holds its operand and the end of its run of
consecutive destinations, which the walk stores AL to a long at a time
(fewer than FILL bytes one at a time; a run whose offsets wrap at 16 bits
one by one). Exactness rests on seeing every store that may change a covered
byte:
- CS-segment stores (the RET plants and restores, operand patches) call the
  region's store hook (`_wb`, `_ww`; lower.code_store): a RET at a cell
  start becomes the walk's stop (`_plant`, one at a time), the cell's first
  byte back ends it, any other change drops the cache (`_plant` 0).
- A DS, ES or SS value whose 64 KiB window reaches a region (below the
  segment limit) drops every cache (`smc_expose`) at each segment load
  (lower.putseg, the reload cells, the runtime's register reload); a reload
  that does so continues exactly. Runtime stores into a region do the same
  (runtime.h rt_wrote).
- A dropped cache is cleared at the next walk entry with no segment
  reaching a region; until then walks are exact. So a valid cache means no
  segment reaches a region, and the walk's own stores cannot.
Bytes that are not covered are read when a walk reaches them: a RET there
returns, another byte is decoded or walked exactly.
No poll point: the block has no loop, and the reference takes no
interrupt inside it.
"""

from __future__ import annotations

from . import decode, flags
from .lower import LowerError, hx

HOLE = 0x1234


MOV = "8887ww"
UNROLL = 4


def _mov_run(code: bytes, bound: str, other: str) -> list[str]:
    """Mov cells from a0 (checked against the bound) while they match: d6 =
    the cells after this one up to the bound, d1 = the opcode word, d2 =
    7FFFh - BX (the store's index is d2 - w, as 7FFFh - (BX + w) for DS:BX+w);
    a0 two bytes above the cell, so -(a0) reads the cell's 4 bytes and steps
    to the next. d1/d2 are guest registers, saved around the run."""
    part = ["\tmove.l -(a0),d7", "\tcmp.w d1,d7", "\tbne.s .mx", "\tswap d7",
            "\tneg.w d7", "\tadd.w d2,d7", "\tmove.b d0,0(a3,d7.w)"]
    lines = ["\tsub.l a0,d6", "\tneg.l d6", "\tlsr.l #2,d6",
             "\tmovem.l d1-d2,-(sp)", f"\tmove.w #{hx(code[1] << 8 | code[0])},d1",
             "\tmove.w #$7fff,d2", "\tsub.w d3,d2", "\taddq.l #2,a0",
             f"\tmoveq #{UNROLL - 1},d7", "\tand.w d6,d7", f"\tlsr.w #{UNROLL.bit_length() - 1},d6",
             "\tadd.w d7,d7", "\tmove.w .mt(pc,d7.w),d7", "\tjmp .mt(pc,d7.w)",
             ".mt:\tdc.w " + ",".join(f".m{k}-.mt" for k in reversed(range(UNROLL)))]
    for k in range(UNROLL):
        lines += [f".m{k}:"] + part
    return lines + ["\tdbra d6,.m0", "\tsubq.l #2,a0", "\tmovem.l (sp)+,d1-d2", "\tbra .stop",
                    ".mx:", "\taddq.l #2,a0", "\tmovem.l (sp)+,d1-d2",
                    "\tmove.l a6,d6", f"\tsub.l #{bound},d6"] + (
                        [f"\tbra {other}"] if other == ".stop" else [])   # else falls into .f1


def _reload_cell(base: str, limit: int) -> list[str]:
    def word(p: int, dst: str) -> list[str]:      # CS word operand at cell byte p
        return ["\tmoveq #0,d7", f"\tmove.w -{p}(a0),d7", "\tneg.l d7",
                f"\tmove.w (-{base}-1,a6,d7.l),{dst}"]
    return (word(3, "d3") + word(8, "d7")
            + ["\tand.l #$ffff,d7", "\tmove.w d7,G_DS(a6)"] + expose_check("d7", limit, ".rk")
            + ["\tlsl.l #4,d7", "\tlea -$7fff(a6),a3", "\tsuba.l d7,a3", "\tlea -10(a0),a0"])


def expose_check(reg: str, limit: int, skip: str) -> list[str]:
    """A segment value in `reg` whose window reaches a region drops the caches."""
    if not limit:
        return []
    return [f"\tcmp.w #{hx(limit)},{reg}", f"\tbcc.s {skip}", "\tjsr smc_expose", f"{skip}:"]


def _ret_cell(base: str, limit: int) -> list[str]:
    return ["\tmove.w -1(a2,d4.w),d7", "\tsubq.w #2,d4", "\trts"]


# form -> (decoded text with HOLE in each word, lowering)
FORMS = {
    MOV: (["mov byte ds:[bx+0x1234], al"], _mov_run),
    "2e8b1eww2e8e1eww": (["mov bx, word cs:[0x1234]", "mov ds, word cs:[0x1234]"],
                         _reload_cell),
    "c3": (["ret"], _ret_cell),
}


def _parse(form: str) -> tuple[bytes, list[int]]:
    """Code bytes with HOLE in each `ww` word, and the positions of the fixed bytes."""
    code, fixed = bytearray(), []
    for k in range(0, len(form), 2):
        tok = form[k:k + 2]
        if tok == "ww":
            code += bytes((HOLE & 0xff, HOLE >> 8))
        else:
            fixed.append(len(code))
            code.append(int(tok, 16))
    return bytes(code), fixed


def _check(form: str) -> tuple[bytes, list[int]]:
    if form not in FORMS:
        raise LowerError(f"self-modified form {form}: no lowering")
    code, fixed = _parse(form)
    texts, p = [], 0
    while p < len(code):
        i = decode.decode(code, p, p)
        texts.append(str(i))
        p += i.size
    if texts != FORMS[form][0]:
        raise LowerError(f"self-modified form {form} decodes as {texts}")
    return code, fixed


def preserves_flags(forms: list[str]) -> bool:
    """Prove flag identity from every decoded instruction of the matched forms.
    Checking empty and full live sets establishes no reads and no definitions;
    unsupported forms still fail through the normal decoder check."""
    for form in forms:
        code, _ = _check(form)
        pos = 0
        while pos < len(code):
            i = decode.decode(code, pos, pos)
            if any(flags.transfer(i, set(live), program=True) != live
                   for live in (set(), set(flags.ALL))):
                return False
            pos += i.size
    return True


RELOAD = "2e8b1eww2e8e1eww"
RET = "c3"
CACHED = {MOV, RELOAD, RET}     # the forms the cell cache knows
FILL = 8                         # a run of destinations this long is stored by longs


def span(first_ip: int, last_ip: int) -> int:
    """Bytes a region's cells may cover: cells start up to last_ip, the longest is
    10 bytes."""
    return last_ip - first_ip + max(len(_parse(f)[0]) for f in FORMS)


def tables(label: str, first_ip: int, last_ip: int) -> list[str]:
    """A region's cache, zero at start (`_plant` 0: not valid). `_rec`, a pad that
    stays zero (the hooks look one or two bytes below `_cov`) and `_cov`, one
    clear."""
    n = (span(first_ip, last_ip) + 3) & ~3
    return ["\tcnop\t0,4", f"{label}_rec:\tds.l\t{n}", "\tds.l\t1", f"{label}_cov:\tds.b\t{n}",
            f"{label}_tmp:\tds.w\t{n // 4 + 1}", f"{label}_plant:\tds.w\t1"]


def expose(labels: list[str]) -> list[str]:
    """smc_expose: a store may have reached a region; every cache is dropped.
    Keeps every register (the runtime calls it too)."""
    return (["smc_expose:\t; D3: a store may reach a self-modified region"]
            + [f"\tclr.w {lab}_plant" for lab in labels] + ["\trts"])


def walk(label: str, cs: str, first_ip: int, last_ip: int, forms: list[str],
         limit: int = 0) -> list[str]:
    """Cell walk of one region: d7 = entry IP (zero-extended); called with the
    guest return IP pushed, like the call target it replaces. `limit`: the
    lowest segment whose window reaches no region (0: no cache)."""
    if not limit or set(forms) != CACHED:
        return exact(label, cs, first_ip, last_ip, forms, limit)
    return cached(label, cs, first_ip, last_ip, limit) + exact(
        f"{label}_x", cs, first_ip, last_ip, forms, limit)


def cached(label: str, cs: str, first_ip: int, last_ip: int, limit: int) -> list[str]:
    """The walk over cached cells (module docstring). Registers: d0 AL, d1
    7FFFh - BX (AL in each byte while a run is stored by longs), d2 the stop
    (offset of the planted RET, FFFFh none), d3 BX, d7 the offset of the cell,
    a0 `_rec`; d5, d6, a4 scratch. d1/d2/d5/a4 are saved around the walk. A
    valid cache implies no segment reaches a region (every load checks)."""
    base = f"({cs})*16"
    lin = f"({base}+{hx(first_ip)})"
    last = last_ip - first_ip
    n = (span(first_ip, last_ip) + 3) & ~3
    mov, _ = _parse(MOV)
    rel, rfixed = _parse(RELOAD)
    save = "d1-d2/d5/a4"
    ret = f"{label}_ret"
    lines = [f"{ret}:\tmovem.l (sp)+,{save}"] + _ret_cell(base, limit) + [
             f"{label}:\t; self-modified cells {first_ip:04X}..{last_ip:04X} (D16): cell cache (D3)",
             f"\tmove.w {label}_plant,d6", f"\tbeq {label}_reset",
             f"{label}_go:\tsub.w #{hx(first_ip)},d7", f"\tcmp.w #{hx(last + 1)},d7", f"\tbcc {label}_xo",
             f"\tmovem.l {save},-(sp)",
             "\tmove.w d6,d2", "\tsubq.w #1,d2", "\tcmp.w d7,d2", "\tbcs .s0",
             ".s1:\tmove.w #$7fff,d1", "\tsub.w d3,d1", f"\tlea {label}_rec,a0",
             # one cell record: a mov cell starts a run of destinations to its end
             ".next:\tcmp.w d2,d7", f"\tbeq {ret}", "\tmove.l (a0,d7.w*4),d6", "\tbmi .reload",
             "\tbeq .miss",
             "\tmove.w d1,d5", "\tsub.w d6,d5", "\tswap d6", "\tcmp.w d2,d6", "\tbls.s .e1",
             "\tmove.w d2,d6", ".e1:\tsub.w d7,d6", "\tadd.w d6,d7", "\tlsr.w #2,d6",
             "\tsubq.w #1,d6", "\tsub.w d6,d5", "\tbvs .wrap", "\tlea 0(a3,d5.w),a4",
             f"\tcmp.w #{FILL - 1},d6", "\tbcc.s .long", "\tneg.w d6", "\tjmp .b1(pc,d6.w*2)"]
    lines += ["\tmove.b d0,(a4)+"] * (FILL - 2)
    lines += [".b1:\tmove.b d0,(a4)", "\tbra .next",
              # offsets that wrap at 16 bits: one by one from the first
              ".wrap:\tadd.w d6,d5", ".w1:\tmove.b d0,0(a3,d5.w)", "\tsubq.w #1,d5",
              "\tdbra d6,.w1", "\tbra .next",
              # AL to the destinations from a4 up: to a long boundary, longs, the rest
              ".long:\taddq.w #1,d6", "\tmove.w a4,d5", "\tneg.w d5", "\tand.w #3,d5",
              "\tsub.w d5,d6", "\tneg.w d5", "\tjmp .h0(pc,d5.w*2)"]
    lines += ["\tmove.b d0,(a4)+"] * 3
    lines += [".h0:\tmove.b d0,d1", "\tlsl.w #8,d1", "\tmove.b d0,d1", "\tmove.w d1,d5",
              "\tswap d1", "\tmove.w d5,d1",
              "\tmove.w d6,d5", "\tlsr.w #4,d5", "\tbeq.s .l4", "\tsubq.w #1,d5"]
    lines += [".l16:\tmove.l d1,(a4)+"] + ["\tmove.l d1,(a4)+"] * 3
    lines += ["\tdbra d5,.l16", ".l4:\tmoveq #12,d5", "\tand.w d6,d5", "\tlsr.w #1,d5",
              "\tneg.w d5", "\tjmp .lz(pc,d5.w)"]
    lines += ["\tmove.l d1,(a4)+"] * 3
    lines += [".lz:\tand.w #3,d6", "\tneg.w d6", "\tjmp .tz(pc,d6.w*2)"]
    lines += ["\tmove.b d0,(a4)+"] * 3
    lines += [".tz:\tmove.w #$7fff,d1", "\tsub.w d3,d1", "\tbra .next",
              # mov bx, word cs:[w1]; mov ds, word cs:[w2] (w2: the next record's low word)
              ".reload:\tmoveq #0,d5", "\tmove.w d6,d5", "\tneg.l d5",
             f"\tmove.w (-{base}-1,a6,d5.l),d3", "\tmoveq #0,d5", "\tmove.w (6,a0,d7.w*4),d5",
             "\tneg.l d5", "\tmoveq #0,d6", f"\tmove.w (-{base}-1,a6,d5.l),d6",
             "\tmove.w d6,G_DS(a6)", "\tmove.w d6,d5", "\tlsl.l #4,d6", "\tlea -$7fff(a6),a3",
             "\tsuba.l d6,a3", "\tmove.w #$7fff,d1", "\tsub.w d3,d1", f"\tadd.w #{len(rel)},d7",
             f"\tcmp.w #{hx(limit)},d5", "\tbcc .next", "\tjsr smc_expose", "\tbra.s .xo",
             # no record: inside a cached cell (exact), a RET, or cells to decode
             f".miss:\tlea {label}_cov,a4", "\ttst.b (a4,d7.w)", "\tbne.s .xo",
             f"\tlea (-{lin},a6),a4", "\tsuba.w d7,a4", f"\tcmp.b #{hx(_parse(RET)[0][0])},(a4)",
             f"\tbeq {ret}", f"\tbsr {label}_decode", "\ttst.l (a0,d7.w*4)", "\tbne .next",
             f".xo:\tmovem.l (sp)+,{save}", f"\tadd.w #{hx(first_ip)},d7", f"\tbra {label}_x",
             ".s0:\tmoveq #-1,d2", "\tbra .s1"]     # the planted RET lies before the entry
    lines += [f"{label}_xo:\tadd.w #{hx(first_ip)},d7", f"\tbra {label}_x",
              # a dropped cache: cleared when no segment reaches a region
              f"{label}_reset:\tcmp.w #{hx(limit)},G_DS(a6)", f"\tbcs {label}_x",
              f"\tcmp.w #{hx(limit)},G_ES(a6)", f"\tbcs {label}_x",
              f"\tcmp.w #{hx(limit)},G_SS(a6)", f"\tbcs {label}_x",
              f"\tlea {label}_rec,a0", f"\tmove.w #{hx(n * 5 // 4)},d6",
              ".c:\tclr.l (a0)+", "\tdbra d6,.c", "\tmoveq #-1,d6", f"\tmove.w #$ffff,{label}_plant",
              f"\tbra {label}_go"]
    lines += _decode(label, lin, last, mov, rel, rfixed)
    lines += _hooks(label, lin, span(first_ip, last_ip))
    return lines


def _fixed_checks(code: bytes, fixed: list[int], miss: str) -> list[str]:
    """Compare the fixed bytes of a form at a4 (the cell's first byte; byte p at
    a4 - p), pairs as words."""
    out, p = [], 0
    while p < len(fixed):
        off = fixed[p]
        if p + 1 < len(fixed) and fixed[p + 1] == off + 1:
            out += [f"\tcmp.w #{hx(code[off + 1] << 8 | code[off])},{-off - 1}(a4)", f"\tbne {miss}"]
            p += 2
        else:
            out += [f"\tcmp.b #{hx(code[off])},{-off}(a4)", f"\tbne {miss}"]
            p += 1
    return out


def _decode(label: str, lin: str, last: int, mov: bytes, rel: bytes, rfixed: list[int]) -> list[str]:
    """Match cells from offset d7 (not covered) while each is a mov or reload
    cell starting by the bound whose bytes are not covered; then each new mov
    cell's run end, last first, and the runs of the cells before d7 that now
    continue. Keeps every register."""
    words = [k for k in range(len(rel) - 1) if k not in rfixed and k + 1 not in rfixed]
    w1, w2 = words[0], words[-1]
    cov = ["\ttst.l (a1,d5.w)", "\tbne .de", "\ttst.l (4,a1,d5.w)", "\tbne .de",
           "\ttst.w (8,a1,d5.w)", "\tbne .de"] if len(rel) == 10 else None
    if cov is None or len(mov) != 4:
        raise LowerError("cell cache: mov cells of 4 bytes and reload cells of 10 expected")
    return ([f"{label}_decode:\t; cells from offset d7 into the cache",
             "\tmovem.l d0-d6/a0-a5,-(sp)", f"\tlea {label}_rec,a2", f"\tlea {label}_cov,a1",
             f"\tlea {label}_tmp,a5", "\tmovea.l a5,a3", "\tmove.w d7,d5",
             f".dl:\tcmp.w #{hx(last)},d5", "\tbhi .de", f"\tlea (-{lin},a6),a4", "\tsuba.w d5,a4"]
            + _fixed_checks(mov, [0, 1], ".dr")
            + ["\ttst.l (a1,d5.w)", "\tbne .de", f"\tmove.l #${mov[0]:02x}010101,(a1,d5.w)",
               "\tmove.w d5,d0", "\taddq.w #4,d0", "\tswap d0", "\tmove.w -3(a4),d0",
               "\tmove.l d0,(a2,d5.w*4)", "\tmove.w d5,(a5)+", "\taddq.w #4,d5", "\tbra .dl",
               ".dr:"]
            + _fixed_checks(rel, rfixed, ".de") + cov
            + [f"\tmove.l #${rel[0]:02x}010101,(a1,d5.w)", "\tmove.l #$01010101,(4,a1,d5.w)",
               "\tmove.w #$0101,(8,a1,d5.w)", "\tmoveq #-1,d0", f"\tmove.w {-w1 - 1}(a4),d0",
               "\tmove.l d0,(a2,d5.w*4)", f"\tmove.w {-w2 - 1}(a4),(6,a2,d5.w*4)",
               f"\tadd.w #{len(rel)},d5", "\tbra .dl",
               ".de:\tcmpa.l a3,a5", "\tbeq.s .dx",
               ".df:\tmove.w -(a5),d6", "\tbsr.s .chain", "\tcmpa.l a3,a5", "\tbne.s .df",
               "\tmove.w d7,d6",
               ".do:\tsubq.w #4,d6", "\tbmi.s .dx", "\ttst.l (a2,d6.w*4)", "\tble.s .dx",
               "\tbsr.s .chain", "\tbeq.s .do",
               ".dx:\tmovem.l (sp)+,d0-d6/a0-a5", "\trts",
               # mov cell d6: its run ends where its successor's does if that one stores
               # the next destination (Z set), else after it (as decoded)
               ".chain:\tmove.l (a2,d6.w*4),d0", "\tmove.l (16,a2,d6.w*4),d1", "\tble.s .cn",
               "\tmove.w d0,d2", "\taddq.w #1,d2", "\tcmp.w d1,d2", "\tbne.s .cn",
               "\tmove.w d0,d1", "\tmove.l d1,(a2,d6.w*4)", "\tmoveq #0,d2", "\trts",
               ".cn:\tmoveq #1,d2", "\trts"])


def _hooks(label: str, lin: str, n: int) -> list[str]:
    """Store hooks (lower.code_store): d6.w = 1 + region offset of the stored
    byte (`_wb`), of a word's second byte (`_ww`). `_plant`: 0 the cache
    dropped, FFFFh valid with no RET planted, else 1 + the planted cell's
    offset. Keep every register but d6, d7, a0."""
    return [f"{label}_ww:\t; a CS word store: its bytes at d6 - 2 and d6 - 1",
            f"\tcmp.w #{hx(n + 1)},d6", "\tbcc.s .w1", f"\tbsr.s {label}_wb",
            ".w1:\tsubq.w #1,d6", f"\tbgt.s {label}_wb", "\trts",
            f"{label}_wb:\t; a CS byte store at offset d6 - 1",
            f"\tlea {label}_cov-1,a0", "\tmove.b (a0,d6.w),d7", "\tbeq.s .r",
            "\tsubq.b #1,d7", "\tbeq.s .inv", "\taddq.b #1,d7",
            f"\tlea (-{lin}+1,a6),a0", "\tsuba.w d6,a0", "\tcmp.b (a0),d7", "\tbeq.s .same",
            f"\tcmp.b #{hx(_parse(RET)[0][0])},(a0)", "\tbne.s .inv",
            f"\tcmp.w {label}_plant,d6", "\tbeq.s .r", f"\tcmp.w #-1,{label}_plant",
            "\tbne.s .inv", f"\tmove.w d6,{label}_plant", "\trts",
            f".same:\tcmp.w {label}_plant,d6", "\tbne.s .r", f"\tmove.w #-1,{label}_plant",
            "\trts", f".inv:\tclr.w {label}_plant", ".r:\trts"]


def exact(label: str, cs: str, first_ip: int, last_ip: int, forms: list[str],
          limit: int = 0) -> list[str]:
    """The exact cell walk (module docstring); entered like the walk."""
    base = f"({cs})*16"
    lines = [f"{label}:\t; self-modified cells {first_ip:04X}..{last_ip:04X} (D16)",
             f"\tlea (-{base}-{hx(last_ip)}-1,a6),a0", "\tmove.l a0,d6",
             f"\tlea (-{base}-1,a6),a0", "\tsuba.l d7,a0",
             f"\tcmp.w #{hx(first_ip)},d7", "\tblo .stop",
             ".cell:", "\tcmpa.l d6,a0", "\tblo .stop"]
    # the mov cells first: they are nearly every cell
    order = sorted(forms, key=lambda f: f != MOV)
    for k, form in enumerate(order):
        code, fixed = _check(form)
        nxt = f".f{k + 1}" if k + 1 < len(order) else ".stop"
        lines.append(f".f{k}:")
        if form == MOV:
            lines += _mov_run(code, f"{base}+{hx(last_ip)}+1", nxt)
            continue
        p = 0
        while p < len(fixed):
            off = fixed[p]
            if p + 1 < len(fixed) and fixed[p + 1] == off + 1:
                lines += [f"\tcmp.w #{hx(code[off + 1] << 8 | code[off])},{-off}(a0)",
                          f"\tbne {nxt if p == 0 else '.stop'}"]
                p += 2
            else:
                lines += [f"\tcmp.b #{hx(code[off])},{1 - off}(a0)", f"\tbne {nxt if p == 0 else '.stop'}"]
                p += 1
        body = FORMS[form][1](base, limit)
        lines += body
        if body[-1] != "\trts":
            lines.append("\tbra .cell")
    lines += [".stop:", "\tmove.l a6,d7", "\tsub.l a0,d7", f"\tsub.l #{base}+1,d7",
              f"\tmove.l #{cs},d6", "\tjmp rt_stop_unknown"]
    return lines
