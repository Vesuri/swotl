; Runtime entries of the generated-code contract (docs/translator-design.md):
; guest registers d0-d5/a4/a5 (SP/BP mirrored: offset ^ 7FFFh), segment bases
; a1-a3 = a6 - seg*16 - 7FFFh, guest RAM reversed below a6 (translator/lower.py),
; d6/d7/a0 scratch. C (gcc, 68020 ABI) clobbers d0/d1/a0/a1 only.

; State block offsets (translator/lower.py STATE_EQU)
G_IRQ	equ	9
G_ES	equ	5
G_SS	equ	3
G_DS	equ	1

	xdef	rt_int
	xdef	rt_irq
	xdef	rt_irq_back
	xdef	rt_exit
	xdef	rt_exit_guest
	xdef	rt_bios_int08
	xdef	rt_fault
	xdef	rt_halt
	xdef	rt_trap
	xdef	rt_in8
	xdef	rt_in16
	xdef	rt_out8
	xdef	rt_out16
	xdef	rt_ret_mismatch
	xdef	rt_dispatch_near
	xdef	rt_dispatch_far
	xdef	rt_stop_unknown
	xdef	rt_run_guest
	xdef	rt_vram_mark
	xdef	rt_vdrv_return

	xref	rt_r
	xref	rt_guest
	xref	rt_entry_cs
	xref	rt_entry_ip
	xref	rt_deliver_cs
	xref	rt_deliver_ip
	xref	rt_deliver_code
	xref	rt_int_c
	xref	rt_irq_c
	xref	rt_bios_int08_c
	xref	rt_fault_c
	xref	rt_halt_c
	xref	rt_trap_c
	xref	rt_port_in
	xref	rt_port_out
	xref	rt_lookup
	xref	rt_ret_mismatch_c
	xref	rt_stop_unknown_c
	xref	rt_vram_rows
	xref	rt_vram_top
	xref	rt_vram_bottom
	xref	rt_vdrv_depth
	xref	rt_vram_stray
	xref	rt_video_publish
	xref	rt_opl
	xref	rt_opl_index

	ifd SWOTL_REPLAY
	xref rt_replay_enter,rt_replay_return
	endif

	section	.text,code

; guest registers -> rt_r (SP and BP as offsets)
save_regs:
	move.l	a0,-(a7)
	lea	rt_r,a0
	movem.w	d0-d5/a4-a5,(a0)
	eori.w	#$7fff,8(a0)
	eori.w	#$7fff,10(a0)
	movea.l	(a7)+,a0
	rts

; rt_r and the state-block segments -> guest registers (upper words
; undefined: sign-extended) and segment bases
load_regs:
	lea	rt_r,a0
	movem.w	(a0),d0-d5/a4-a5
	eori.w	#$7fff,d4
	eori.w	#$7fff,d5
	moveq	#0,d7
	move.w	G_ES(a6),d7
	lsl.l	#4,d7
	lea	-$7fff(a6),a1
	suba.l	d7,a1
	moveq	#0,d7
	move.w	G_SS(a6),d7
	lsl.l	#4,d7
	lea	-$7fff(a6),a2
	suba.l	d7,a2
	moveq	#0,d7
	move.w	G_DS(a6),d7
	lsl.l	#4,d7
	lea	-$7fff(a6),a3
	suba.l	d7,a3
	rts

; Software interrupt: d6 = CS << 16 | vector, d7 = next IP. A machine service
; runs in C; a vector the guest owns runs its handler on the frame C pushed.
rt_int:
	ifd SWOTL_REPLAY
	jsr rt_replay_enter
	endif
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
	ifd SWOTL_REPLAY
	jsr rt_replay_return
	endif
	rts
deliver_guest:	; d7 = CS << 16 | IP of the pushed frame; the handler's IRET pops it
	move.l	d7,-(a7)
	moveq	#0,d6
	move.w	rt_deliver_cs,d6
	moveq	#0,d7
	move.w	rt_deliver_ip,d7
	movea.l	rt_deliver_code,a0	; rt_lookup's far entry (deliver)
	jsr	(a0)
	cmp.w	2(a7),d7
	bne	rt_ret_mismatch
	cmp.w	(a7),d6
	bne	rt_ret_mismatch
	addq.l	#4,a7
rt_exit_guest:
	ifd SWOTL_REPLAY
	jsr rt_replay_return
	endif
	rts

; Poll point with G_IRQ set (D8): d6 = CS << 16, d7 = IP of the loop head.
; Posted interrupts run in order: a guest handler on the frame C pushed, then
; the next; BIOS handlers in C.
; rt_irq_c changes no guest register but SP (the frame it pushes) and no
; segment, so only C's d0/d1/a1 are kept around it and SP reloaded (rt_r
; stays current for a stop's register dump).
rt_irq:
	bsr	save_regs
	movem.l	d0-d1/a1,-(a7)
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_irq_c
	addq.l	#8,a7
	movea.l	d0,a0
	movem.l	(a7)+,d0-d1/a1
	cmpa.w	#0,a0
	beq.s	irq_done
	move.w	rt_r+8,d4		; SP below the frame, mirrored
	eori.w	#$7fff,d4
	movem.l	d6-d7,-(a7)
	move.l	a0,d7
	bsr	deliver_guest		; the guest handler, IRET checked
rt_irq_back:				; back at the poll point (host run: next interrupt)
	movem.l	(a7)+,d6-d7
	tst.b	G_IRQ(a6)
	bne.s	rt_irq			; more posted at this poll point
irq_done:	rts

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

; TF set by POPF/IRET: d7 = IP of the instruction.
rt_trap:
	bsr	save_regs
	move.l	d7,-(a7)
	jsr	rt_trap_c

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

; AdLib byte writes and the PIC's non-specific EOI here (ports.c); d7
; clobbered.
rt_out8:
	cmp.w	#$389,d7
	beq.s	.opl_data
	cmp.w	#$388,d7
	beq.s	.opl_index
	cmp.w	#$20,d7
	bne.s	.port
	cmp.b	#$20,d6
	bne.s	.port
	rts
.opl_index:
	move.b	d6,rt_opl_index
	rts
.opl_data:
	lea	rt_opl,a0
	moveq	#0,d7
	move.b	rt_opl_index,d7
	move.b	d6,(a0,d7.w)
	rts
.port:	movem.l	d0-d1/a1,-(a7)
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
	movem.l	d0-d1/a1,-(a7)
	moveq	#0,d0
	bra.s	dispatch
rt_dispatch_far:	; stops at a row no far transfer may enter
	movem.l	d0-d1/a1,-(a7)
	moveq	#1,d0
dispatch:
	move.l	d0,-(a7)
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_lookup
	lea	12(a7),a7
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

; D9 display. Before a graphics driver store to segment A000h: bytes
; [d7.w, d7.w + d6.l) (the offset wraps at 64 KiB) widen the changed rows,
; clipped to the 320x200 frame. Per row (rt_vram_rows) the changed columns
; [lo, hi), hi = 0 for none; a store spanning rows marks them whole.
; d6/d7/a0 clobbered.
rt_vram_mark:
	tst.w	rt_vdrv_depth
	beq.l	rt_vram_stray		; video memory outside a driver call
	movem.l	d0-d2,-(a7)
	and.l	#$ffff,d7
	move.l	d7,d0
	add.l	d6,d0			; end, exclusive
	cmp.l	#$10000,d0
	bls.s	.last
	sub.l	#$10000,d0		; wrapped: [d7, 64 KiB), then [0, d0)
	move.l	d0,-(a7)
	move.l	#$10000,d0
	bsr.s	vram_span
	moveq	#0,d7
	move.l	(a7)+,d0
.last:	bsr.s	vram_span
	movem.l	(a7)+,d0-d2
	rts

; [d7, d0) with d0 <= 64 KiB
vram_span:
	cmp.l	#64000,d0
	bls.s	.clip
	move.l	#64000,d0
.clip:	cmp.l	d0,d7
	bhs.s	.done
	subq.l	#1,d0			; last byte
	lea	vram_row(pc),a0		; offset / 320 = (offset >> 6) / 5
	move.w	d7,d1
	lsr.w	#6,d1
	moveq	#0,d2
	move.b	(a0,d1.w),d2		; first row
	move.w	d2,d1
	lsl.w	#6,d1
	sub.w	d1,d7
	lsl.w	#2,d1
	sub.w	d1,d7			; first column
	move.w	d0,d1
	lsr.w	#6,d1
	moveq	#0,d6
	move.b	(a0,d1.w),d6		; last row
	move.w	d6,d1
	lsl.w	#6,d1
	sub.w	d1,d0
	lsl.w	#2,d1
	sub.w	d1,d0			; last column
	cmp.w	rt_vram_top,d2
	bhs.s	.top
	move.w	d2,rt_vram_top
.top:	cmp.w	rt_vram_bottom,d6
	blo.s	.bottom
	move.w	d6,d1
	addq.w	#1,d1
	move.w	d1,rt_vram_bottom
.bottom:
	lea	rt_vram_rows,a0
	lea	(a0,d2.l*4),a0		; row entry: lo.w, hi.w
	cmp.w	d2,d6
	bne.s	.rows
	addq.w	#1,d0			; column end
	tst.w	2(a0)
	beq.s	.new
	cmp.w	(a0),d7
	bhs.s	.lo
	move.w	d7,(a0)
.lo:	cmp.w	2(a0),d0
	bls.s	.done
	move.w	d0,2(a0)
.done:	rts
.new:	move.w	d7,(a0)+
	move.w	d0,(a0)
	rts
.rows:	sub.w	d2,d6			; rows - 1
.row:	move.l	#320,(a0)+		; lo 0, hi 320
	dbf	d6,.row
	rts

vram_row:	; row of each 64-byte block of the frame: k / 5
	dc.b	0,0,0,0,0,1,1,1,1,1,2,2,2,2,2,3,3,3,3,3
	dc.b	4,4,4,4,4,5,5,5,5,5,6,6,6,6,6,7,7,7,7,7
	dc.b	8,8,8,8,8,9,9,9,9,9,10,10,10,10,10,11,11,11,11,11
	dc.b	12,12,12,12,12,13,13,13,13,13,14,14,14,14,14,15,15,15,15,15
	dc.b	16,16,16,16,16,17,17,17,17,17,18,18,18,18,18,19,19,19,19,19
	dc.b	20,20,20,20,20,21,21,21,21,21,22,22,22,22,22,23,23,23,23,23
	dc.b	24,24,24,24,24,25,25,25,25,25,26,26,26,26,26,27,27,27,27,27
	dc.b	28,28,28,28,28,29,29,29,29,29,30,30,30,30,30,31,31,31,31,31
	dc.b	32,32,32,32,32,33,33,33,33,33,34,34,34,34,34,35,35,35,35,35
	dc.b	36,36,36,36,36,37,37,37,37,37,38,38,38,38,38,39,39,39,39,39
	dc.b	40,40,40,40,40,41,41,41,41,41,42,42,42,42,42,43,43,43,43,43
	dc.b	44,44,44,44,44,45,45,45,45,45,46,46,46,46,46,47,47,47,47,47
	dc.b	48,48,48,48,48,49,49,49,49,49,50,50,50,50,50,51,51,51,51,51
	dc.b	52,52,52,52,52,53,53,53,53,53,54,54,54,54,54,55,55,55,55,55
	dc.b	56,56,56,56,56,57,57,57,57,57,58,58,58,58,58,59,59,59,59,59
	dc.b	60,60,60,60,60,61,61,61,61,61,62,62,62,62,62,63,63,63,63,63
	dc.b	64,64,64,64,64,65,65,65,65,65,66,66,66,66,66,67,67,67,67,67
	dc.b	68,68,68,68,68,69,69,69,69,69,70,70,70,70,70,71,71,71,71,71
	dc.b	72,72,72,72,72,73,73,73,73,73,74,74,74,74,74,75,75,75,75,75
	dc.b	76,76,76,76,76,77,77,77,77,77,78,78,78,78,78,79,79,79,79,79
	dc.b	80,80,80,80,80,81,81,81,81,81,82,82,82,82,82,83,83,83,83,83
	dc.b	84,84,84,84,84,85,85,85,85,85,86,86,86,86,86,87,87,87,87,87
	dc.b	88,88,88,88,88,89,89,89,89,89,90,90,90,90,90,91,91,91,91,91
	dc.b	92,92,92,92,92,93,93,93,93,93,94,94,94,94,94,95,95,95,95,95
	dc.b	96,96,96,96,96,97,97,97,97,97,98,98,98,98,98,99,99,99,99,99
	dc.b	100,100,100,100,100,101,101,101,101,101,102,102,102,102,102,103,103,103,103,103
	dc.b	104,104,104,104,104,105,105,105,105,105,106,106,106,106,106,107,107,107,107,107
	dc.b	108,108,108,108,108,109,109,109,109,109,110,110,110,110,110,111,111,111,111,111
	dc.b	112,112,112,112,112,113,113,113,113,113,114,114,114,114,114,115,115,115,115,115
	dc.b	116,116,116,116,116,117,117,117,117,117,118,118,118,118,118,119,119,119,119,119
	dc.b	120,120,120,120,120,121,121,121,121,121,122,122,122,122,122,123,123,123,123,123
	dc.b	124,124,124,124,124,125,125,125,125,125,126,126,126,126,126,127,127,127,127,127
	dc.b	128,128,128,128,128,129,129,129,129,129,130,130,130,130,130,131,131,131,131,131
	dc.b	132,132,132,132,132,133,133,133,133,133,134,134,134,134,134,135,135,135,135,135
	dc.b	136,136,136,136,136,137,137,137,137,137,138,138,138,138,138,139,139,139,139,139
	dc.b	140,140,140,140,140,141,141,141,141,141,142,142,142,142,142,143,143,143,143,143
	dc.b	144,144,144,144,144,145,145,145,145,145,146,146,146,146,146,147,147,147,147,147
	dc.b	148,148,148,148,148,149,149,149,149,149,150,150,150,150,150,151,151,151,151,151
	dc.b	152,152,152,152,152,153,153,153,153,153,154,154,154,154,154,155,155,155,155,155
	dc.b	156,156,156,156,156,157,157,157,157,157,158,158,158,158,158,159,159,159,159,159
	dc.b	160,160,160,160,160,161,161,161,161,161,162,162,162,162,162,163,163,163,163,163
	dc.b	164,164,164,164,164,165,165,165,165,165,166,166,166,166,166,167,167,167,167,167
	dc.b	168,168,168,168,168,169,169,169,169,169,170,170,170,170,170,171,171,171,171,171
	dc.b	172,172,172,172,172,173,173,173,173,173,174,174,174,174,174,175,175,175,175,175
	dc.b	176,176,176,176,176,177,177,177,177,177,178,178,178,178,178,179,179,179,179,179
	dc.b	180,180,180,180,180,181,181,181,181,181,182,182,182,182,182,183,183,183,183,183
	dc.b	184,184,184,184,184,185,185,185,185,185,186,186,186,186,186,187,187,187,187,187
	dc.b	188,188,188,188,188,189,189,189,189,189,190,190,190,190,190,191,191,191,191,191
	dc.b	192,192,192,192,192,193,193,193,193,193,194,194,194,194,194,195,195,195,195,195
	dc.b	196,196,196,196,196,197,197,197,197,197,198,198,198,198,198,199,199,199,199,199
	even

; D9: the `jmp far` of a PLINK thunk into the graphics driver called the
; entry; its retf returns here (d6/d7 = the popped CS:IP for the caller's
; return check). The outermost return publishes what the driver drew.
rt_vdrv_return:
	subq.w	#1,rt_vdrv_depth
	bne.s	.inner
	tst.w	rt_vram_bottom
	beq.s	.inner
	movem.l	d0-d1/a0-a1,-(a7)
	jsr	rt_video_publish
	movem.l	(a7)+,d0-d1/a0-a1
.inner:	rts
