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


HELPERS = r"""
; d7 := PF (0/1): even parity of G_PF
__getpf:
	move.l	d6,-(a7)
	move.b	G_PF(a6),d7
	move.b	d7,d6
	lsr.b	#4,d6
	eor.b	d6,d7
	move.b	d7,d6
	lsr.b	#2,d6
	eor.b	d6,d7
	move.b	d7,d6
	lsr.b	#1,d6
	eor.b	d6,d7
	not.b	d7
	and.l	#1,d7
	move.l	(a7)+,d6
	rts

; d7.w := FLAGS (bit 1 set, bits 12-15 from G_FX)
__flags_word:
	move.l	d6,-(a7)
	jsr	__getpf
	lsl.w	#2,d7
	or.w	#2,d7
	move.b	G_FL+1(a6),d6
	btst	#0,d6
	beq	.1
	or.w	#1,d7
.1:	btst	#2,d6
	beq	.2
	or.w	#$40,d7
.2:	btst	#3,d6
	beq	.3
	or.w	#$80,d7
.3:	btst	#1,d6
	beq	.4
	or.w	#$800,d7
.4:	move.b	G_AF(a6),d6
	and.w	#$10,d6
	or.w	d6,d7
	tst.b	G_TF(a6)
	beq	.5
	or.w	#$100,d7
.5:	tst.b	G_IF(a6)
	beq	.6
	or.w	#$200,d7
.6:	tst.b	G_DF(a6)
	beq	.7
	or.w	#$400,d7
.7:	or.w	G_FX(a6),d7
	move.l	(a7)+,d6
	rts

; CF PF AF ZF SF from the low byte of d7 (SAHF); OF kept
__set_flags_lo:
	move.l	d6,-(a7)
	moveq	#0,d6
	btst	#0,d7
	beq	.1
	or.b	#1,d6
.1:	btst	#6,d7
	beq	.2
	or.b	#4,d6
.2:	btst	#7,d7
	beq	.3
	or.b	#8,d6
.3:	and.b	#2,G_FL+1(a6)
	or.b	d6,G_FL+1(a6)
	move.b	d7,d6
	and.b	#$10,d6
	move.b	d6,G_AF(a6)
	btst	#2,d7
	seq	d6
	and.b	#1,d6
	move.b	d6,G_PF(a6)
	move.l	(a7)+,d6
	rts

; all flags from d7.w (POPF, IRET); G_FX := bits 12-14
__set_flags:
	move.l	d6,-(a7)
	jsr	__set_flags_lo
	and.b	#$fd,G_FL+1(a6)
	btst	#11,d7
	beq	.1
	or.b	#2,G_FL+1(a6)
.1:	btst	#8,d7
	sne	d6
	neg.b	d6
	move.b	d6,G_TF(a6)
	btst	#9,d7
	sne	d6
	neg.b	d6
	move.b	d6,G_IF(a6)
	beq	.2
	move.b	rt_irq_pending,G_IRQ(a6)	; re-arm (runtime.h)
.2:	btst	#10,d7
	sne	d6
	neg.b	d6
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
	bhi	.adj
	btst	#4,G_AF(a6)
	beq	.noadj
.adj:	addq.b	#6,d0
	move.b	#$10,G_AF(a6)
	bra	.hi
.noadj:	clr.b	G_AF(a6)
.hi:	cmp.b	#$99,d6
	bhi	.adj2
	btst	#0,G_FL+1(a6)
	beq	.nocf
.adj2:	add.b	#$60,d0
	or.b	#1,G_FL+1(a6)
	bra	.done
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
	bhi	.adj
	btst	#4,G_AF(a6)
	beq	.noadj
.adj:	moveq	#0,d7
	cmp.b	#6,d0
	bcc	.nb
	moveq	#1,d7
.nb:	btst	#0,G_FL+1(a6)
	beq	.nc
	moveq	#1,d7
.nc:	subq.b	#6,d0
	move.b	#$10,G_AF(a6)
	bra	.hi
.noadj:	moveq	#0,d7
	clr.b	G_AF(a6)
.hi:	cmp.b	#$99,d6
	bhi	.adj2
	btst	#0,G_FL+1(a6)
	beq	.done
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
	bhi	.adj
	btst	#4,G_AF(a6)
	beq	.no
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
	bhi	.adj
	btst	#4,G_AF(a6)
	beq	.no
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
"""
