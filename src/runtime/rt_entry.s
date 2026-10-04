; Runtime entries of the generated-code contract (docs/translator-design.md):
; guest registers d0-d5/a4/a5, segment bases a1-a3 = a6 + seg*16, guest RAM a6,
; d6/d7/a0 scratch. C (gcc, 68020 ABI) clobbers d0/d1/a0/a1 only.

; State block offsets (translator/lower.py STATE_EQU)
G_IRQ	equ	-8
G_ES	equ	-12
G_SS	equ	-14
G_DS	equ	-16

	xdef	rt_int
	xdef	rt_irq
	xdef	rt_irq_back
	xdef	rt_exit
	xdef	rt_exit_guest
	xdef	rt_bios_int08
	xdef	rt_fault
	xdef	rt_halt
	xdef	rt_in8
	xdef	rt_in16
	xdef	rt_out8
	xdef	rt_out16
	xdef	rt_ret_mismatch
	xdef	rt_dispatch_near
	xdef	rt_dispatch_far
	xdef	rt_stop_unknown
	xdef	rt_run_guest

	xref	rt_r
	xref	rt_guest
	xref	rt_entry_cs
	xref	rt_entry_ip
	xref	rt_deliver_cs
	xref	rt_deliver_ip
	xref	rt_int_c
	xref	rt_irq_c
	xref	rt_bios_int08_c
	xref	rt_fault_c
	xref	rt_halt_c
	xref	rt_port_in
	xref	rt_port_out
	xref	rt_lookup
	xref	rt_ret_mismatch_c
	xref	rt_stop_unknown_c

	section	.text,code

; guest registers -> rt_r
save_regs:
	move.l	a0,-(a7)
	lea	rt_r,a0
	move.w	d0,(a0)
	move.w	d1,2(a0)
	move.w	d2,4(a0)
	move.w	d3,6(a0)
	move.w	d4,8(a0)
	move.w	d5,10(a0)
	move.w	a4,12(a0)
	move.w	a5,14(a0)
	movea.l	(a7)+,a0
	rts

; rt_r and the state-block segments -> guest registers and segment bases
load_regs:
	lea	rt_r,a0
	moveq	#0,d0
	move.w	(a0),d0
	moveq	#0,d1
	move.w	2(a0),d1
	moveq	#0,d2
	move.w	4(a0),d2
	moveq	#0,d3
	move.w	6(a0),d3
	moveq	#0,d4
	move.w	8(a0),d4
	moveq	#0,d5
	move.w	10(a0),d5
	moveq	#0,d7
	move.w	12(a0),d7
	movea.l	d7,a4
	moveq	#0,d7
	move.w	14(a0),d7
	movea.l	d7,a5
	moveq	#0,d7
	move.w	G_ES(a6),d7
	lsl.l	#4,d7
	lea	(a6,d7.l),a1
	moveq	#0,d7
	move.w	G_SS(a6),d7
	lsl.l	#4,d7
	lea	(a6,d7.l),a2
	moveq	#0,d7
	move.w	G_DS(a6),d7
	lsl.l	#4,d7
	lea	(a6,d7.l),a3
	rts

; Software interrupt: d6 = CS << 16 | vector, d7 = next IP. A machine service
; runs in C; a vector the guest owns runs its handler on the frame C pushed.
rt_int:
	bsr	save_regs
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_int_c
	addq.l	#8,a7
deliver_or_return:
	move.l	d0,-(a7)
	bsr	load_regs
	move.l	(a7)+,d7
	bne.s	deliver_guest
rt_exit:	; back to generated code (tests/host_run.py: service returns)
	rts
deliver_guest:	; d7 = CS << 16 | IP of the pushed frame; the handler's IRET pops it
	move.l	d7,-(a7)
	moveq	#0,d6
	move.w	rt_deliver_cs,d6
	moveq	#0,d7
	move.w	rt_deliver_ip,d7
	jsr	rt_dispatch_far
	cmp.w	2(a7),d7
	bne	rt_ret_mismatch
	cmp.w	(a7),d6
	bne	rt_ret_mismatch
	addq.l	#4,a7
rt_exit_guest:
	rts

; Poll point with G_IRQ set (D8): d6 = CS << 16, d7 = IP of the loop head.
; Posted interrupts run in order: a guest handler on the frame C pushed, then
; the next; BIOS handlers in C.
rt_irq:
	bsr	save_regs
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_irq_c
	addq.l	#8,a7
	tst.l	d0
	beq	deliver_or_return
	movem.l	d6-d7,-(a7)
	bsr	deliver_or_return	; the guest handler, IRET checked
rt_irq_back:				; back at the poll point (host run: next interrupt)
	movem.l	(a7)+,d6-d7
	tst.b	G_IRQ(a6)
	bne.s	rt_irq			; more posted at this poll point
	rts

; The BIOS INT 08h handler, reached by a guest handler chaining to the vector
; it replaced (jmp far): the tick, then IRET; d7/d6 = popped IP/CS for the
; return check of the code that delivered the interrupt.
rt_bios_int08:
	bsr	save_regs
	jsr	rt_bios_int08_c
	move.l	d0,-(a7)
	bsr	load_regs
	moveq	#0,d7
	move.w	2(a7),d7
	moveq	#0,d6
	move.w	(a7)+,d6
	addq.l	#2,a7
	rts

; Divide error: d6 = CS << 16 | 0, d7 = IP of the faulting instruction; the
; generated code re-executes it after the guest INT 00h handler returns.
rt_fault:
	bsr	save_regs
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_fault_c
	addq.l	#8,a7
	bra	deliver_or_return

rt_halt:
	bsr	save_regs
	move.l	d7,-(a7)
	jsr	rt_halt_c

; Ports: d7 port, d6 value (out) / result (in).
rt_in8:
	movem.l	d0-d1/a1,-(a7)
	pea	8.w
	bra.s	port_in
rt_in16:
	movem.l	d0-d1/a1,-(a7)
	pea	16.w
port_in:
	move.l	d7,-(a7)
	jsr	rt_port_in
	addq.l	#8,a7
	move.l	d0,d6
	movem.l	(a7)+,d0-d1/a1
	rts

rt_out8:
	movem.l	d0-d1/a1,-(a7)
	pea	8.w
	bra.s	port_out
rt_out16:
	movem.l	d0-d1/a1,-(a7)
	pea	16.w
port_out:
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	rt_port_out
	lea	12(a7),a7
	movem.l	(a7)+,d0-d1/a1
	rts

; Indirect transfer outside the compiled compare chain: d6 CS, d7 IP. Jumps to
; the translated entry (a jsr caller's return address stays on a7).
rt_dispatch_near:
rt_dispatch_far:
	movem.l	d0-d1/a1,-(a7)
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_lookup
	addq.l	#8,a7
	movea.l	d0,a0
	movem.l	(a7)+,d0-d1/a1
	jmp	(a0)

; Return site reached with another guest IP (d7) / CS (d6).
rt_ret_mismatch:
	bsr	save_regs
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	rt_ret_mismatch_c

; Transfer into code that is not translated: d7 IP, d6 CS (when known).
rt_stop_unknown:
	bsr	save_regs
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	rt_stop_unknown_c

; Enter the guest at rt_entry_cs:rt_entry_ip with the registers in rt_r and
; the state block. Returns only if the guest's outermost frame returns.
rt_run_guest:
	movem.l	d2-d7/a2-a6,-(a7)
	movea.l	rt_guest,a6
	bsr	load_regs
	moveq	#0,d6
	move.w	rt_entry_cs,d6
	moveq	#0,d7
	move.w	rt_entry_ip,d7
	jsr	rt_dispatch_far
	movem.l	(a7)+,d2-d7/a2-a6
	rts
