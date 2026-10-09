"""D16: a self-modified region as a run-time cell walk (option c).

The region's writers produce a closed set of cell forms
(annotations/self-modifying.csv, kind `form`): opcode bytes fixed, `ww` a
word operand patched at run time. The walk starts at the entry IP in d7,
matches the guest bytes at each cell (descending in host memory, D1; a0 one
byte below the cell's first byte, so its first word is (a0)) against the
forms, runs the matched
form with its operand words read from guest RAM and returns at the planted
RET; any other byte, or a cell past the region, stops (rt_stop_unknown).
Each form's text is checked against the decoder, so the lowering below is
the lowering of the decoded instruction with the run-time operand.
No poll point: the block has no loop, and the reference takes no
interrupt inside it.
"""

from __future__ import annotations

from . import decode
from .lower import LowerError, hx

HOLE = 0x1234


def _mov_cell(base: str) -> list[str]:
    return ["\tmove.w #$7fff,d7", "\tsub.w -2(a0),d7", "\tsub.w d3,d7",
            "\tmove.b d0,0(a3,d7.w)", "\tsubq.l #4,a0"]


def _reload_cell(base: str) -> list[str]:
    def word(p: int, dst: str) -> list[str]:      # CS word operand at cell byte p
        return ["\tmoveq #0,d7", f"\tmove.w -{p}(a0),d7", "\tneg.l d7",
                f"\tmove.w (-{base}-1,a6,d7.l),{dst}"]
    return (word(3, "d3") + word(8, "d7")
            + ["\tand.l #$ffff,d7", "\tmove.w d7,G_DS(a6)", "\tlsl.l #4,d7",
               "\tlea -$7fff(a6),a3", "\tsuba.l d7,a3", "\tlea -10(a0),a0"])


def _ret_cell(base: str) -> list[str]:
    return ["\tmoveq #0,d7", "\tmove.w -1(a2,d4.w),d7", "\tsubq.w #2,d4", "\trts"]


# form -> (decoded text with HOLE in each word, lowering)
FORMS = {
    "8887ww": (["mov byte ds:[bx+0x1234], al"], _mov_cell),
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


def walk(label: str, cs: str, first_ip: int, last_ip: int, forms: list[str]) -> list[str]:
    """Cell walk of one region: d7 = entry IP (zero-extended); called with the
    guest return IP pushed, like the call target it replaces."""
    base = f"({cs})*16"
    lines = [f"{label}:\t; self-modified cells {first_ip:04X}..{last_ip:04X} (D16)",
             f"\tlea (-{base}-{hx(last_ip)}-1,a6),a0", "\tmove.l a0,d6",
             f"\tlea (-{base}-1,a6),a0", "\tsuba.l d7,a0",
             f"\tcmp.w #{hx(first_ip)},d7", "\tblo .stop",
             ".cell:", "\tcmpa.l d6,a0", "\tblo .stop"]
    # the mov cell first: it is nearly every cell
    order = sorted(forms, key=lambda f: f != "8887ww")
    for k, form in enumerate(order):
        code, fixed = _check(form)
        nxt = f".f{k + 1}" if k + 1 < len(order) else ".stop"
        lines.append(f".f{k}:")
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
        body = FORMS[form][1](base)
        lines += body
        if body[-1] != "\trts":
            lines.append("\tbra .cell")
    lines += [".stop:", "\tmove.l a6,d7", "\tsub.l a0,d7", f"\tsub.l #{base}+1,d7",
              f"\tmove.l #{cs},d6", "\tjmp rt_stop_unknown"]
    return lines
