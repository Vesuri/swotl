; The translated program's native stack: amiga_guest_call switches a7 to a
; private stack and enters the guest; plat_exit unwinds back to its caller.

	xdef	amiga_guest_call
	xdef	plat_exit
	xdef	amiga_input_stub
	xref	rt_run_guest
	xref	amiga_input

	section	.text,code

; int32_t amiga_guest_call(void *stack_top)
amiga_guest_call:
	movea.l	4(a7),a0
	movem.l	d2-d7/a2-a6,-(a7)
	move.l	a7,saved_sp
	movea.l	a0,a7
	jsr	rt_run_guest
	moveq	#-1,d0
	bra.s	unwind

; void plat_exit(int32_t code)
plat_exit:
	move.l	4(a7),d0
unwind:
	movea.l	saved_sp,a7
	movem.l	(a7)+,d2-d7/a2-a6
	rts

; input.device handler: a0 = event list, a1 = is_Data; returns the list in d0.
; struct InputEvent *amiga_input(struct InputEvent *events)
amiga_input_stub:
	move.l	a0,-(a7)
	jsr	amiga_input
	addq.l	#4,a7
	rts

	section	.bss,bss
saved_sp:
	ds.l	1
