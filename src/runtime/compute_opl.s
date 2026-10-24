; OPL port delay loops (F9). U9 authorization 2026-10-23. SPAZ x86 is the
; oracle. Every iteration, poll visit and stack-slot store stays: the loop
; count, CX, IRQ delivery and each byte's write history are the original's.
; PUSH AX / POP AX leave SP and AX unchanged, so only the stores remain.
; a0 = the slot below SP, addressed as the generated push does (d4 + 2,
; wrapping in the word index). Flags are untouched, as LOOP leaves them.

	xdef rt_hle_opl_wait_index
rt_hle_opl_wait_index:
	move.w d4,d7
	addq.w #2,d7
	lea -1(a2,d7.w),a0
	; Entry and resume both follow the generated hook's visit of the poll:
	; start below its execution alias.
	move.w d0,(a0)
	bra.s opl_wait_index_count
opl_wait_index_poll:
	rt_hle_opl_wait_index_poll_0_local opl_wait_index_pending
	move.w d0,(a0)
opl_wait_index_count:
	subq.w #1,d1
	bne.s opl_wait_index_poll
	moveq #1,d7
	rts
opl_wait_index_pending:
	rt_hle_opl_wait_index_poll_0_tail

	xdef rt_hle_opl_wait_data
rt_hle_opl_wait_data:
	move.w d4,d7
	addq.w #2,d7
	lea -1(a2,d7.w),a0
	move.w d0,(a0)
	move.w d0,(a0)
	move.w d0,(a0)
	bra.s opl_wait_data_count
opl_wait_data_poll:
	rt_hle_opl_wait_data_poll_0_local opl_wait_data_pending
	move.w d0,(a0)
	move.w d0,(a0)
	move.w d0,(a0)
opl_wait_data_count:
	subq.w #1,d1
	bne.s opl_wait_data_poll
	moveq #1,d7
	rts
opl_wait_data_pending:
	rt_hle_opl_wait_data_poll_0_tail
