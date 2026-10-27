; Normalise/project D5A6 up to its projection call: the user's TFH slave
; xpnorm20 / XP_COUNT20 (89425f3f), adapted to the generated register ABI.
; U6 2026-10-22; whole prefix and suffix irq-plan I10 (user 2026-10-26).
; Pushes BP, DI, SI; arguments AX:BX, CX:DX, SI:DI at SP+4, SP+8, SP+12 of
; the far call; AX and CX stored at 2399h/239Bh; AX:BX and CX:DX made
; unsigned (NEG/NEG/SBB is a long negate); the three magnitudes shift until
; their OR is below 8000h: max(0,17-BFFFO). BX and DX take the stored signs
; back, and BX, DX, DI are stored at 22BAh/22BEh/22C2h. The CALL to the
; projection (B017, its own row) stays generated: the row ends at D618.
; BP is the low OR, AX, CX, SI are 0. No status flags are live at D618.
; Frame SP-6 .. SP+15 inside the stack segment without 16-bit wrap:
; d4.w = 7FFFh - SP, so each slot is a fixed displacement from it.

	xdef rt_hle_point_normalise
rt_hle_point_normalise:
	cmp.w #-$7ff2,d4
	blt .decline
	cmp.w #$7ff9,d4
	bgt .decline
	move.w d5,d7
	eori.w #$7fff,d7
	move.w d7,1(a2,d4.w)
	move.w a5,3(a2,d4.w)
	move.w a4,5(a2,d4.w)
	move.w -7(a2,d4.w),($5c65,a3)
	move.w -11(a2,d4.w),($5c63,a3)
	move.l -7(a2,d4.w),d0
	bpl.s .bx
	neg.l d0
.bx:
	move.l -11(a2,d4.w),d1
	bpl.s .dx
	neg.l d1
.dx:
	move.l -15(a2,d4.w),d2
	move.l d0,d7
	or.l d1,d7
	or.l d2,d7
	bfffo d7{0:32},d7
	neg.l d7
	add.l #17,d7
	ble.b .ready
	lsr.l d7,d0
	lsr.l d7,d1
	lsr.l d7,d2
.ready:
	movea.w d2,a5
	move.w d0,d3
	move.w d0,d5
	or.w d1,d5
	or.w d2,d5
	eori.w #$7fff,d5
	tst.b -7(a2,d4.w)
	bpl.s .sbx
	neg.w d3
.sbx:
	move.w d1,d2
	tst.b -11(a2,d4.w)
	bpl.s .sdx
	neg.w d2
.sdx:
	move.w d3,($5d44,a3)
	move.w d2,($5d40,a3)
	move.w a5,($5d3c,a3)
	moveq #0,d0
	moveq #0,d1
	suba.l a4,a4
	addq.w #6,d4
	moveq #1,d7
	rts
.decline:
	moveq #0,d7
	rts
