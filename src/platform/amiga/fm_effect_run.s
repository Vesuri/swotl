; Prerendered effects' inner loop (fm_paula.c fx_run, docs/sound-plan.md R4):
; m samples of one channel added to mix, the C loop's arithmetic exactly
; (tests/test_fm_effect_asm.py: fm_effect with it on the 68020 core equals
; the C build). Registers: d0/d1 modulator/carrier phase (the 10-bit index
; in the high word), d2/a5 the modulator's last two outputs, d4/d5 the
; increments, d6 the feedback shift, a1/a2 the waves (sign at bit 13), a3/a4
; the exponent tables at each operator's attenuation, a0/a6 mix and its end.

	xdef	fx_run_asm

; \1 feedback on, \2 connection (1: the operators added, 0: FM)
	macro	FXLOOP
.l\@:
	ifne	\1
	move.l	a5,d7			; (prev1 + prev2) >> sh
	add.l	d2,d7
	asr.l	d6,d7
	move.l	d0,d3
	swap	d3
	add.w	d3,d7
	else
	move.l	d0,d7
	swap	d7
	endif
	and.w	#$3ff,d7
	move.w	(a1,d7.w*2),d7		; modulator
	movea.l	d2,a5
	move.w	(a3,d7.w*2),d2
	ext.l	d2
	move.l	d1,d3
	swap	d3
	ifeq	\2
	add.w	d2,d3			; FM: the modulator's output on the carrier's phase
	endif
	and.w	#$3ff,d3
	move.w	(a2,d3.w*2),d3		; carrier
	move.w	(a4,d3.w*2),d3
	ifne	\2
	add.w	d2,d3
	endif
	add.w	d3,(a0)+
	add.l	d4,d0
	add.l	d5,d1
	cmpa.l	a6,a0
	bne.s	.l\@
	bra	.done
	endm

	section	.text,code

; void fx_run_asm(struct fx_channel *x, int16_t *mix, uint32_t m,
;                 const uint16_t *wm, const uint16_t *wc, const int16_t *em,
;                 const int16_t *ec, uint32_t im, uint32_t ic, uint32_t sh,
;                 uint32_t mode)    mode: feedback on * 2 + connection
ARGS	equ	4+11*4
fx_run_asm:
	movem.l	d2-d7/a2-a6,-(a7)
	move.l	ARGS+8(a7),d7
	beq	.none
	movea.l	ARGS+0(a7),a6
	movem.l	(a6),d0-d2/a5		; pm, pc, prev1, prev2
	movea.l	ARGS+4(a7),a0
	movem.l	ARGS+12(a7),a1-a4	; wm, wc, em, ec
	movem.l	ARGS+28(a7),d4-d6	; im, ic, sh
	lea	(a0,d7.l*2),a6
	move.l	ARGS+40(a7),d7
	beq	.fm
	subq.l	#1,d7
	beq	.add
	subq.l	#1,d7
	beq	.fbfm
	FXLOOP	1,1
.fbfm:	FXLOOP	1,0
.add:	FXLOOP	0,1
.fm:	FXLOOP	0,0
.done:
	movea.l	ARGS+0(a7),a6
	movem.l	d0-d2/a5,(a6)
.none:
	movem.l	(a7)+,d2-d7/a2-a6
	rts
