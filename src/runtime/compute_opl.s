; OPL port delay loops (F9). U9 authorization 2026-10-23; poll-free since
; irq-plan I9. SPAZ x86 is the oracle. Every iteration and stack-slot store
; stays: the loop count and CX are the original's (O(1) is irq-plan I10).
; PUSH AX / POP AX leave SP and AX unchanged, so only the stores remain.
; a0 = the slot below SP, addressed as the generated push does (d4 + 2,
; wrapping in the word index). Flags are untouched, as LOOP leaves them.

	xdef rt_hle_opl_wait_index
rt_hle_opl_wait_index:
	move.w d4,d7
	addq.w #2,d7
	lea -1(a2,d7.w),a0
	move.w d0,(a0)
	bra.s opl_wait_index_count
opl_wait_index_loop:
	move.w d0,(a0)
opl_wait_index_count:
	subq.w #1,d1
	bne.s opl_wait_index_loop
	moveq #1,d7
	rts

	xdef rt_hle_opl_wait_data
rt_hle_opl_wait_data:
	move.w d4,d7
	addq.w #2,d7
	lea -1(a2,d7.w),a0
	move.w d0,(a0)
	move.w d0,(a0)
	move.w d0,(a0)
	bra.s opl_wait_data_count
opl_wait_data_loop:
	move.w d0,(a0)
	move.w d0,(a0)
	move.w d0,(a0)
opl_wait_data_count:
	subq.w #1,d1
	bne.s opl_wait_data_loop
	moveq #1,d7
	rts
