; D69C pixel loops, U6 authorization 2026-10-22; poll-free since irq-plan I9,
; BP written once at the end since I10 (user 2026-10-26).
; Original x86 is the oracle. Scratch d6 holds real BP, d7 the wrapping
; reversed DI index. Ordinary memory guards decline unchanged.

	xdef rt_hle_line_right
rt_hle_line_right:
	moveq #0,d7
	move.w G_ES(a6),d7
	cmp.w #$9000,d7
	bhi.s line_right_decline
	add.l #$1000,d6
	cmp.l d6,d7
	bcs.s line_right_decline
	cmp.w #$9000,G_DS(a6)
	bhi.s line_right_decline
	move.w d5,d6
	eori.w #$7fff,d6
	move.w #$7fff,d7
	sub.w a5,d7
	addq.w #1,d1
	bra.s line_right_store
line_right_step:
	addq.w #1,a5
	subq.w #1,d7
	add.w ($5adb,a3),d6
	bcc.s line_right_no_row
	adda.w ($5a7b,a3),a5
	sub.w ($5a7b,a3),d7
line_right_no_row:
line_right_store:
	move.b d3,0(a1,d7.w)
	subq.w #1,d1
	bne.s line_right_step
	move.w d6,d5
	eori.w #$7fff,d5
	moveq #1,d7
	rts
line_right_decline:
	moveq #0,d7
	rts

	xdef rt_hle_line_left
rt_hle_line_left:
	moveq #0,d7
	move.w G_ES(a6),d7
	cmp.w #$9000,d7
	bhi.s line_left_decline
	add.l #$1000,d6
	cmp.l d6,d7
	bcs.s line_left_decline
	cmp.w #$9000,G_DS(a6)
	bhi.s line_left_decline
	move.w d5,d6
	eori.w #$7fff,d6
	move.w #$7fff,d7
	sub.w a5,d7
	addq.w #1,d1
	bra.s line_left_store
line_left_step:
	subq.w #1,a5
	addq.w #1,d7
	add.w ($5adb,a3),d6
	bcc.s line_left_no_row
	adda.w ($5a7b,a3),a5
	sub.w ($5a7b,a3),d7
line_left_no_row:
line_left_store:
	move.b d3,0(a1,d7.w)
	subq.w #1,d1
	bne.s line_left_step
	move.w d6,d5
	eori.w #$7fff,d5
	moveq #1,d7
	rts
line_left_decline:
	moveq #0,d7
	rts
