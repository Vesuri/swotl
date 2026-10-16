"""Translator-emitted 68020 support: state-block equates and the flag/BCD helpers
the lowering calls (`jsr __name`). Generic x86 semantics, no guest routine.

Contract: helpers read and write guest flags in the state block (lower.py
docstring), take and return values in d7 (and AL/AH in d0), and preserve every
other register; the CCR is clobbered.
"""

from __future__ import annotations

from .lower import LOADSEG, STATE_EQU


def equates() -> str:
    lines = [f"LOADSEG\tequ\t${LOADSEG:04x}"]
    lines += [f"{n}\tequ\t{v}" for n, v in STATE_EQU]
    return "\n".join(lines) + "\n"


def _table(label: str, size: str, values) -> list[str]:
    values = list(values)
    return [f"{label}:"] + [f"\tdc.{size}\t" + ",".join(f"${v:x}" for v in values[k:k + 16])
                            for k in range(0, len(values), 16)]


# FLAGS bit 2 (PF) per result byte: even parity
_PARITY = [0 if bin(v).count("1") & 1 else 4 for v in range(256)]
# FLAGS CF, OF, ZF, SF per CCR image (C, V, Z, N)
_CCR_FLAGS = [(c & 1) | (c & 2) << 10 | (c & 4) << 4 | (c & 8) << 4 for c in range(16)]
# CCR image (C, Z, N) per FLAGS byte bits CF << 2 | SF << 1 | ZF (`and #$c1`, `rol.b #2`)
_SAHF_CCR = [(i >> 2 & 1) | (i & 1) << 2 | (i >> 1 & 1) << 3 for i in range(8)]
# (code ends word-aligned: the word table first)
TABLES = [";", "; tables of the flag helpers"] + _table("__ccr_flags", "w", _CCR_FLAGS) + \
    _table("__sahf_ccr", "b", _SAHF_CCR) + _table("__parity", "b", _PARITY)


# Local helper branches have explicit short encodings: leaving these to
# vasm adds a relaxation cascade after the combined block-test image.
HELPERS = r"""
; d7 := PF (0/1): even parity of G_PF
__getpf:
	moveq	#0,d7
	move.b	G_PF(a6),d7
	move.b	__parity(pc,d7.w),d7
	lsr.b	#2,d7
	rts

; d7.w := FLAGS (bit 1 set, bits 12-15 from G_FX)
__flags_word:
	move.l	d6,-(a7)
	moveq	#0,d6
	move.b	G_PF(a6),d6
	moveq	#2,d7
	or.b	__parity(pc,d6.w),d7
	moveq	#$0f,d6
	and.b	G_FL+1(a6),d6
	or.w	__ccr_flags(pc,d6.w*2),d7
	move.b	G_AF(a6),d6
	and.w	#$10,d6
	or.w	d6,d7
	tst.b	G_TF(a6)
	beq.s	.1
	or.w	#$100,d7
.1:	tst.b	G_IF(a6)
	beq.s	.2
	or.w	#$200,d7
.2:	tst.b	G_DF(a6)
	beq.s	.3
	or.w	#$400,d7
.3:	or.w	G_FX(a6),d7
	move.l	(a7)+,d6
	rts

; CF PF AF ZF SF from the low byte of d7 (SAHF); OF kept
__set_flags_lo:
	move.l	d6,-(a7)
	move.w	d7,d6
	and.w	#$c1,d6
	rol.b	#2,d6
	move.b	__sahf_ccr(pc,d6.w),d6
	and.b	#2,G_FL+1(a6)
	or.b	d6,G_FL+1(a6)
	move.b	d7,d6
	and.b	#$10,d6
	move.b	d6,G_AF(a6)
	btst	#2,d7
	seq	d6
	neg.b	d6
	move.b	d6,G_PF(a6)
	move.l	(a7)+,d6
	rts

; all flags from d7.w (POPF, IRET); G_FX := bits 12-14
__set_flags:
	move.l	d6,-(a7)
	move.w	d7,d6
	and.w	#$c1,d6
	rol.b	#2,d6
	move.b	__sahf_ccr(pc,d6.w),d6
	btst	#11,d7
	beq.s	.1
	addq.b	#2,d6
.1:	move.b	d6,G_FL+1(a6)
	move.b	d7,d6
	and.b	#$10,d6
	move.b	d6,G_AF(a6)
	btst	#2,d7
	seq	d6
	neg.b	d6
	move.b	d6,G_PF(a6)
	bfextu	d7{23:1},d6
	move.b	d6,G_TF(a6)
	bfextu	d7{22:1},d6
	move.b	d6,G_IF(a6)
	beq.s	.2
	move.b	rt_irq_pending,G_IRQ(a6)	; re-arm (runtime.h)
.2:	bfextu	d7{21:1},d6
	move.b	d6,G_DF(a6)
	move.w	d7,d6
	and.w	#$7000,d6
	move.w	d6,G_FX(a6)
	move.l	(a7)+,d6
	rts

; ZF SF PF from AL (CF OF kept)
__szp_al:
	move.l	d6,-(a7)
	tst.b	d0
	move.w	ccr,d6
	and.b	#$0c,d6
	and.b	#$f3,G_FL+1(a6)
	or.b	d6,G_FL+1(a6)
	move.b	d0,G_PF(a6)
	move.l	(a7)+,d6
	rts

__daa:
	move.l	d6,-(a7)
	move.b	d0,d6
	move.b	d0,d7
	and.b	#$0f,d7
	cmp.b	#9,d7
	bhi.s	.adj
	btst	#4,G_AF(a6)
	beq.s	.noadj
.adj:	addq.b	#6,d0
	move.b	#$10,G_AF(a6)
	bra.s	.hi
.noadj:	clr.b	G_AF(a6)
.hi:	cmp.b	#$99,d6
	bhi.s	.adj2
	btst	#0,G_FL+1(a6)
	beq.s	.nocf
.adj2:	add.b	#$60,d0
	or.b	#1,G_FL+1(a6)
	bra.s	.done
.nocf:	and.b	#$fe,G_FL+1(a6)
.done:	jsr	__szp_al
	move.l	(a7)+,d6
	rts

__das:
	move.l	d6,-(a7)
	move.b	d0,d6
	move.b	d0,d7
	and.b	#$0f,d7
	cmp.b	#9,d7
	bhi.s	.adj
	btst	#4,G_AF(a6)
	beq.s	.noadj
.adj:	moveq	#0,d7
	cmp.b	#6,d0
	bcc.s	.nb
	moveq	#1,d7
.nb:	btst	#0,G_FL+1(a6)
	beq.s	.nc
	moveq	#1,d7
.nc:	subq.b	#6,d0
	move.b	#$10,G_AF(a6)
	bra.s	.hi
.noadj:	moveq	#0,d7
	clr.b	G_AF(a6)
.hi:	cmp.b	#$99,d6
	bhi.s	.adj2
	btst	#0,G_FL+1(a6)
	beq.s	.done
.adj2:	sub.b	#$60,d0
	moveq	#1,d7
.done:	and.b	#$fe,G_FL+1(a6)
	or.b	d7,G_FL+1(a6)
	jsr	__szp_al
	move.l	(a7)+,d6
	rts

__aaa:
	move.b	d0,d7
	and.b	#$0f,d7
	cmp.b	#9,d7
	bhi.s	.adj
	btst	#4,G_AF(a6)
	beq.s	.no
.adj:	add.w	#$106,d0
	and.b	#$0f,d0
	move.b	#$10,G_AF(a6)
	or.b	#1,G_FL+1(a6)
	rts
.no:	and.b	#$0f,d0
	clr.b	G_AF(a6)
	and.b	#$fe,G_FL+1(a6)
	rts

__aas:
	move.b	d0,d7
	and.b	#$0f,d7
	cmp.b	#9,d7
	bhi.s	.adj
	btst	#4,G_AF(a6)
	beq.s	.no
.adj:	sub.w	#$106,d0
	and.b	#$0f,d0
	move.b	#$10,G_AF(a6)
	or.b	#1,G_FL+1(a6)
	rts
.no:	and.b	#$0f,d0
	clr.b	G_AF(a6)
	and.b	#$fe,G_FL+1(a6)
	rts

; AAM: d7 = base (non-zero)
__aam:
	move.l	d6,-(a7)
	moveq	#0,d6
	move.b	d0,d6
	divu.w	d7,d6
	move.w	d6,d7
	lsl.w	#8,d7
	swap	d6
	move.b	d6,d7
	move.w	d7,d0
	jsr	__szp_al
	move.l	(a7)+,d6
	rts

; AAD: d7 = base
__aad:
	move.l	d6,-(a7)
	move.w	d0,d6
	lsr.w	#8,d6
	mulu.w	d7,d6
	add.b	d0,d6
	and.w	#$ff,d6
	move.w	d6,d0
	jsr	__szp_al
	move.l	(a7)+,d6
	rts
""" + "\n".join(TABLES) + "\n"
