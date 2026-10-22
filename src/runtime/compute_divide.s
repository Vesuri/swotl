; Perspective divide: user's TFH slave xdiv20 (315dbd2c), adapted to
; SWOTL's generated ABI, including its intermediate BP and unsigned AX/DX.
; User U4 authorization 2026-10-22: SWOTL.EXE+B4E2.
; No stores, live status flags or polls. SI retains the signed input.
; |AX| <= 8000h: both original word divides fit for every nonzero divisor
; (first high word zero; second high word is the first remainder).
; A zero divisor follows the original explicit non-dividing path.

	xdef rt_hle_perspective_divide
rt_hle_perspective_divide:
	move.w d0,a4
	moveq #0,d6
	move.w d0,d6
	bpl.b .positive
	neg.w d6
.positive:
	swap d6
	moveq #0,d7
	move.w ($5d3c,a3),d7
	beq.b .multiply
	divu.l d7,d6
.multiply:
	moveq #0,d7
	move.w ($5d26,a3),d7
	; Retain BP: rounded product of the quotient's low half, high word.
	moveq #0,d5
	move.w d6,d5
	mulu.l d7,d5
	add.l #$8000,d5
	swap d5
	eori.w #$7fff,d5
	; xdiv20's full product, rounded, extracting bits 16..47.
	move.l d7,d3
	mulu.l d6,d2:d3
	add.l #$8000,d3
	bcc.b .carry
	addq.l #1,d2
.carry:
	swap d3
	swap d2
	move.w d3,d2
	move.l d2,d0
	swap d2
	move.l d0,d3
	move.l a4,d7
	tst.w d7
	bpl.b .result
	neg.l d3
.result:
	move.l d3,d1
	swap d1
	moveq #1,d7
	rts
