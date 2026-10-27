; Sprite row: packet spans, span bounds and the walk setup. U6 authorization
; 2026-10-22; widened at irq-plan I10 (user 2026-10-26). SWOTL x86 is the
; oracle; no imported TFH bytes. Every table read and output write stays in
; original order, including tables overlapped by the output; tables read after
; the packet loop come from memory. Declines leave all guest state unchanged.
; d7 = 1..4 resumes at the walk setup without [2581] (EGA/Tandy), the span walk
; loop, the clipped spans and the row tail.

	xdef rt_hle_sprite_row
rt_hle_sprite_row:
	moveq #0,d7
	move.w G_DS(a6),d7
	cmp.w #$9000,d7
	bhi sprite_row_decline
	sub.l d6,d7
	cmp.l #$1000,d7
	blt sprite_row_decline
	cmp.w #$3dd0,d1
	bhi sprite_row_decline
	tst.w d1
	beq sprite_row_tail
	move.w d1,($7771,a3)
	tst.w ($7641,a3)
	bmi sprite_row_tail
	move.l d6,-(sp)
	move.w ($7784,a3),d2
	move.w #0,($7782,a3)
	tst.w d0
	beq.s sprite_row_spans
	subq.w #1,d0
	move.w d0,d7
	add.w d7,d7
	movea.w d7,a4
	move.w #$7059,d7
	sub.w a4,d7
	move.w -1(a3,d7.w),d0
	move.w #$6f59,d7
	sub.w a4,d7
	add.w d0,($7782,a3)
	move.w -1(a3,d7.w),d6
	addx.w d6,d2
sprite_row_spans:
	move.w d2,($7743,a3)
	movea.w #$8bd,a4
	move.w ($7771,a3),d0
	move.w d0,($776f,a3)
	addq.w #2,d4
	move.w d3,-1(a2,d4.w)
	lea ($7742,a3),a0
sprite_packet_body:
	move.w #$7fff,d7
	sub.w a5,d7
	move.b (0,a1,d7.w),d1
	move.b d1,d3
	and.w #$f,d1
	move.w d1,d5
	add.w d5,d5
	eori.w #$7fff,d5
	lsr.w #3,d3
	and.w #$1e,d3
	move.b d3,-1(a0)
	move.w #$7226,d7
	sub.w d3,d7
	move.w -1(a3,d7.w),d3
	move.b d3,(a0)
	move.w (-$fa7,a3,d5.w),d0
	add.w d0,($7782,a3)
	move.w (-$10a7,a3,d5.w),d6
	addx.w d6,d2
	move.w d2,-3(a0)
	addq.w #4,a4
	subq.l #4,a0
	adda.w ($7791,a3),a5
	subq.w #1,($776f,a3)
	bne.s sprite_packet_body
	move.w -1(a2,d4.w),d3
	subq.w #2,d4
	move.w 1(a0),d0
	move.w d0,($763d,a3)
	movea.w #$8bb,a4
	move.w ($7771,a3),d1
	tst.w d0
	bmi.s sprite_row_clipped
	cmp.w ($7641,a3),d0
	bcc.s sprite_row_clipped
	move.w ($7743,a3),d0
	bmi.s sprite_row_clipped
	cmp.w ($7643,a3),d0
	bcs.s sprite_row_clipped
	tst.w ($5a7d,a3)
	beq.s sprite_row_ega
	movea.w d0,a5
	move.l (sp)+,d6
	lsl.l #4,d6
	movea.l a6,a0
	suba.l d6,a0
	tst.w ($5a36,a3)
	bne.s sprite_row_near
	cmp.w ($5a3e,a3),d0
	bcs.s sprite_row_near
	addq.w #2,d4
	move.w (-$9b37,a0),-1(a2,d4.w)
	move.w (-$9b39,a0),d3
	bra.s sprite_row_walk
sprite_row_near:
	addq.w #2,d4
	move.w (-$9b33,a0),-1(a2,d4.w)
	move.w (-$9b35,a0),d3
sprite_row_walk:
	addq.w #2,a4
	move.w a5,d6
	add.w d6,d6
	add.w ($7745,a3),d6
	move.w #$7fff,d7
	sub.w d6,d7
	movea.w -1(a3,d7.w),a5
	adda.w ($7751,a3),a5
	moveq #2,d7
	rts
sprite_row_ega:
	addq.l #4,sp
	moveq #1,d7
	rts
sprite_row_clipped:
	addq.l #4,sp
	moveq #3,d7
	rts
sprite_row_tail:
	moveq #4,d7
	rts
sprite_row_decline:
	moveq #0,d7
	rts
