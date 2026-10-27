; OPL port delay loops (F9). U9 authorization 2026-10-23; poll-free since
; irq-plan I9, O(1) since I10 (speed-plan §2.9 delay-loop exception, user
; 2026-10-24). SPAZ x86 is the oracle. Every PUSH AX / POP AX pair stores AX
; into the same slot and leaves SP and AX unchanged, and LOOP ends with
; CX = 0 (also from CX = 0: 65,536 passes), so one store and CX = 0 remain.
; The slot below SP is addressed as the generated push does (d4 + 2,
; wrapping in the word index). Flags are dead at the hook.

	xdef rt_hle_opl_wait_index
rt_hle_opl_wait_index:
	xdef rt_hle_opl_wait_data
rt_hle_opl_wait_data:
	move.w d4,d7
	addq.w #2,d7
	move.w d0,-1(a2,d7.w)
	moveq #0,d1
	moveq #1,d7
	rts
