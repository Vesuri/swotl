; Sprite packet to spans. U6 authorization 2026-10-22; poll-free since
; irq-plan I9. SWOTL x86 is the oracle; no imported TFH bytes.
; Every table read and output write stays in original order, including
; tables overlapped by the output. Declines leave all guest state unchanged.

	xdef rt_hle_sprite_packet
rt_hle_sprite_packet:
	moveq #0,d7
	move.w G_DS(a6),d7
	cmp.w #$9000,d7
	bhi sprite_packet_decline
	add.l #$1000,d6
	cmp.l d6,d7
	bcs sprite_packet_decline
	moveq #0,d6
	move.w ($776f,a3),d6
	beq sprite_packet_decline
	moveq #0,d7
	move.w a4,d7
	cmp.w #$891,d7
	bcs.s sprite_packet_decline
	lsl.l #2,d6
	add.l d6,d7
	cmp.l #$ffff,d7
	bhi.s sprite_packet_decline
	move.w #$7fff,d7
	sub.w a4,d7
	lea (0,a3,d7.w),a0
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
sprite_packet_done:
	moveq #1,d7
	rts
sprite_packet_decline:
	moveq #0,d7
	rts
