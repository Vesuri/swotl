; User's TFH slave xpnorm20 / XP_COUNT20 (89425f3f), adapted to the
; generated register ABI. U6 and continuation endpoint approved 2026-10-22.
; Three unsigned magnitudes, split high:low AX:BX, CX:DX, SI:DI.
; The original shifts until their OR is below 8000h: max(0,17-BFFFO).
; No guest memory access. Preserve the final BP OR and all six word results.
; No status flags are live at the continuation; control flags stay untouched.
; U5 poll and all stores/calls/returns remain in generated code.

	xdef rt_hle_point_normalise
rt_hle_point_normalise:
	swap d0
	move.w d3,d0
	swap d1
	move.w d2,d1
	move.l a4,d2
	swap d2
	move.w a5,d2
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
	move.w d2,a5
	move.w d0,d3
	move.w d0,d5
	or.w d1,d5
	or.w d2,d5
	eori.w #$7fff,d5
	move.w d1,d2
	clr.w d0
	clr.w d1
	suba.l a4,a4
	moveq #1,d7
	rts
