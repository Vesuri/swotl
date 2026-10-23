; Edge ordering and equal-edge merging. U6 scope approved 2026-10-23.
; Original SWOTL x86 is the oracle. Cache only the wrapping reversed BX
; index in a0. Reads, writes, SI/DI wrap handling and all polls stay exact.
; Pending delivery abandons this invocation; resume reconstructs a0.

	xdef rt_hle_edge_ordering
rt_hle_edge_ordering:
	movea.l d7,a0
	moveq #0,d7
	move.w G_DS(a6),d7
	cmp.w #$9000,d7
	bhi.w edge_ordering_decline
	add.l #$1000,d6
	cmp.l d6,d7
	bcs.w edge_ordering_decline
	moveq #0,d7
	move.w G_ES(a6),d7
	cmp.w #$9000,d7
	bhi.w edge_ordering_decline
	cmp.l d6,d7
	bcs.w edge_ordering_decline
	move.l a0,d6
	beq.s edge_ordering_start
	move.w #$7fff,d7
	sub.w d3,d7
	movea.w d7,a0
	cmp.l #1,d6
	beq.s edge_ordering_pass_body
	cmp.l #2,d6
	beq.s edge_ordering_compare_body
	cmp.l #3,d6
	beq.w edge_ordering_swap_body
	bra.w edge_ordering_loop_body
edge_ordering_start:
	move.w d0,($5ad1,a3)
	bra.s edge_ordering_pass_poll
edge_ordering_pending_pass:
	rt_hle_edge_ordering_poll_0_tail
edge_ordering_pending_compare:
	rt_hle_edge_ordering_poll_1_tail
edge_ordering_pass_poll:
	rt_hle_edge_ordering_poll_0_local edge_ordering_pending_pass
edge_ordering_pass_body:
	eor.w d2,d2
	move.w ($5ad1,a3),d1
	subq.w #1,d1
	move.w #$4062,d3
	move.w #$7fff,d7
	sub.w d3,d7
	movea.w d7,a0
edge_ordering_compare_poll:
	rt_hle_edge_ordering_poll_1_local edge_ordering_pending_compare
edge_ordering_compare_body:
	movea.w -1(a1,a0.w),a4
	addq.w #2,d3
	subq.w #2,a0
	movea.w -1(a1,a0.w),a5
	move.w #$7ff9,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	move.w #$7ff9,d7
	sub.w a5,d7
	cmp.w -1(a1,d7.w),d0
	blt.w edge_ordering_loop_poll
	bne.w edge_ordering_swap_poll
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b 0(a1,d7.w),d0
	move.w #$7ffa,d7
	sub.w a5,d7
	move.b 0(a1,d7.w),d6
	bfins d6,d0{16:8}
	btst #7,d0
	bne.w edge_ordering_priority
	btst #15,d0
	bne.w edge_ordering_priority
	move.w d0,d6
	lsr.w #8,d6
	and.b d6,d0
	and.b #3,d0
	bne.w edge_ordering_priority
	move.w #$7ff7,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	move.w #$7ff7,d7
	sub.w a5,d7
	cmp.w -1(a1,d7.w),d0
	bne.w edge_ordering_priority
	move.w #$7fff,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	move.w #$7fff,d7
	sub.w a5,d7
	cmp.w -1(a1,d7.w),d0
	bne.w edge_ordering_priority
	move.w #$7ffd,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	move.w #$7ffd,d7
	sub.w a5,d7
	cmp.w -1(a1,d7.w),d0
	beq.w edge_ordering_merge
	bra.w edge_ordering_loop_poll
edge_ordering_swap_poll:
	rt_hle_edge_ordering_poll_2_local edge_ordering_pending_swap
edge_ordering_swap_body:
	move.w a0,d7
	cmp.w #32765,d7
	bgt.s edge_ordering_swap_wrap
	movea.w -1(a1,a0.w),a4
	movea.w 1(a1,a0.w),a5
	bra.s edge_ordering_swap_store
edge_ordering_swap_wrap:
	movea.w -1(a1,a0.w),a4
	addq.w #2,d7
	movea.w -1(a1,d7.w),a5
edge_ordering_swap_store:
	move.w a5,-1(a1,a0.w)
	move.w a0,d7
	addq.w #2,d7
	move.w a4,-1(a1,d7.w)
	addq.w #1,d2
edge_ordering_loop_poll:
	rt_hle_edge_ordering_poll_3_local edge_ordering_pending_loop
edge_ordering_loop_body:
	subq.w #1,d1
	bne.w edge_ordering_compare_poll
	or.w d2,d2
	bne.w edge_ordering_pass_poll
	moveq #1,d7
	rts
edge_ordering_pending_swap:
	rt_hle_edge_ordering_poll_2_tail
edge_ordering_pending_loop:
	rt_hle_edge_ordering_poll_3_tail
edge_ordering_decline:
	moveq #0,d7
	rts
edge_ordering_priority:
	move.w #$7ffd,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	move.w #$7ffd,d7
	sub.w a5,d7
	cmp.w -1(a1,d7.w),d0
	blt.w edge_ordering_loop_poll
	bne.w edge_ordering_swap_poll
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b 0(a1,d7.w),d0
	move.w #$7ffa,d7
	sub.w a5,d7
	move.b 0(a1,d7.w),d6
	bfins d6,d0{16:8}
	move.w d0,d6
	lsr.w #8,d6
	and.b d6,d0
	and.b #3,d0
	beq.w edge_ordering_event_order
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b 0(a1,d7.w),d0
	move.w #$7fff,d7
	sub.w a4,d7
	tst.w -1(a1,d7.w)
	bne.s edge_ordering_other_life
	btst #14,d0
	bne.s edge_ordering_other_life
	eor.b d0,d0
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b d0,0(a1,d7.w)
	bra.w edge_ordering_loop_poll
edge_ordering_other_life:
	move.w #$7fff,d7
	sub.w a5,d7
	tst.w -1(a1,d7.w)
	bne.s edge_ordering_event_order
	btst #6,d0
	bne.s edge_ordering_event_order
	eor.b d0,d0
	move.w #$7ffa,d7
	sub.w a5,d7
	move.b d0,0(a1,d7.w)
	bra.w edge_ordering_loop_poll
edge_ordering_event_order:
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b 0(a1,d7.w),d0
	and.b #3,d0
	move.w #$7ffa,d7
	sub.w a5,d7
	move.b 0(a1,d7.w),d6
	bfins d6,d0{16:8}
	and.w #$3ff,d0
	move.w d0,d6
	lsr.w #8,d6
	cmp.b d6,d0
	bls.w edge_ordering_loop_poll
	bra.w edge_ordering_swap_poll
edge_ordering_merge:
	move.w #$7ffb,d7
	sub.w a4,d7
	move.b 0(a1,d7.w),d0
	move.w #$7ffb,d7
	sub.w a5,d7
	cmp.b 0(a1,d7.w),d0
	beq.s edge_ordering_cancel_both
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b 0(a1,d7.w),d0
	btst #1,d0
	bne.s edge_ordering_merge_flags
	exg a4,a5
edge_ordering_merge_flags:
	move.w #$7ffa,d7
	sub.w a4,d7
	or.b #1,0(a1,d7.w)
	eor.w d0,d0
	move.w #$7ffa,d7
	sub.w a5,d7
	move.b d0,0(a1,d7.w)
	move.w #$7fff,d7
	sub.w a5,d7
	move.w d0,-1(a1,d7.w)
	bra.w edge_ordering_loop_poll
edge_ordering_cancel_both:
	eor.w d0,d0
	move.w #$7ffa,d7
	sub.w a5,d7
	move.b d0,0(a1,d7.w)
	move.w #$7fff,d7
	sub.w a5,d7
	move.w d0,-1(a1,d7.w)
	move.w #$7ffa,d7
	sub.w a4,d7
	move.b d0,0(a1,d7.w)
	move.w #$7fff,d7
	sub.w a4,d7
	move.w d0,-1(a1,d7.w)
	bra.w edge_ordering_loop_poll
