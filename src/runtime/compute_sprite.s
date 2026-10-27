; Sprite row: packet spans, span bounds, the walk setup and the span walk loop.
; U6 authorization 2026-10-22; widened at irq-plan I10 (user 2026-10-26); the
; walk loop 4FD3..5032 by the user 2026-10-27 ("extend the native contract for
; the sprite decoder's walk loop"; native-compute "Code writes and the cell
; walk"). SWOTL x86 is the oracle; no imported TFH bytes. Every table read and
; output write stays in original order, including tables overlapped by the
; output; tables read after the packet loop come from memory. Declines leave
; all guest state unchanged.
; The walk loop: per span the RET plant and restore through the cell cache's
; store bookkeeping (lower.code_store, inline; smc_walk_wb otherwise), the
; sprite DS popped (smc_expose below smc_seg_limit) and restored, and the
; generated cell walk called with the guest return 0649h pushed; a return
; elsewhere stops as the generated call does. A span start outside the cells
; or DF set resumes at the loop head 4FD3 (the generated call dispatches).
; Resume ids (compute.resume_dispatch: endpoints, then root loop heads):

	xref smc_walk
	xref smc_walk_wb
	xref smc_walk_plant
	xref smc_walk_cov
	xref smc_expose
	xref smc_seg_limit
	xref rt_ret_mismatch

SR_EGA		equ 1		; 4F3C: walk setup without [2581] (EGA/Tandy)
SR_CLIPPED	equ 2		; 5036: clipped spans
SR_TAIL		equ 3		; 5153: row tail
SR_WALK		equ 5		; 4FD3: the span walk loop head

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
	bmi sprite_row_clipped
	cmp.w ($7641,a3),d0
	bcc sprite_row_clipped
	move.w ($7743,a3),d0
	bmi sprite_row_clipped
	cmp.w ($7643,a3),d0
	bcs sprite_row_clipped
	tst.w ($5a7d,a3)
	beq sprite_row_ega
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
	tst.b G_DF(a6)
	bne sprite_span_resume
; 4FD3..5032. Frame: 0(sp) BP form of DS (MOV BP,DS), 2(sp) DS, 4(sp) its base,
; 8(sp) a6 - CS*16 - 7FFFh, 12(sp) smc_walk_cov - 1, 16(sp) smc_seg_limit.
; SI runs as a pointer: a4 = DS base + 8000h - SI (CX <= 3DD0h: SI never wraps),
; so -(a4) reads DS:SI and steps SI by 2; SI is set back on leaving.
	move.w smc_seg_limit,-(sp)
	pea smc_walk_cov-1
	lea -$7fff(a0),a0
	move.l a0,-(sp)
	move.l a3,-(sp)
	move.w G_DS(a6),d7
	move.w d7,-(sp)
	eori.w #$7fff,d7
	move.w d7,-(sp)
	moveq #0,d7
	move.w a4,d7
	lea (a3),a4
	adda.l #$8000,a4
	suba.l d7,a4
sprite_span_head:
	move.w a5,d7			; DX in the cells, else the generated dispatch
	sub.w #$209d,d7
	cmp.w #$23e0,d7
	bcc sprite_span_leave
	move.w a5,d2			; MOV DX,DI
	move.w -(a4),d0			; LODSW
	move.w d0,d6			; CMP AH,[871]
	lsr.w #8,d6
	cmp.b ($778e,a3),d6
	beq sprite_span_clip
	move.w -(a4),d6			; MOV DI,[SI]; ADD SI,2
	add.w d6,d6			; SHL DI,1; ADD DI,[8B9]
	add.w ($7745,a3),d6
	move.w #$7fff,d7		; MOV DI,[DI]; ADD DI,[8AD]
	sub.w d6,d7
	move.w -1(a3,d7.w),d6
	add.w ($7751,a3),d6
	movea.w d6,a5
	move.w #$7fff,d7		; MOV AH,CS:[DI]; MOV BYTE CS:[DI],C3
	sub.w d6,d7
	movea.l 8(sp),a0
	lea (a0,d7.w),a0
	rol.w #8,d0
	move.b (a0),d0
	rol.w #8,d0
	move.b #$c3,(a0)
	sub.w #$209c,d6			; the plant (lower.code_store)
	cmp.w #$23ea,d6
	bcc.s sprite_span_planted
	movea.l 12(sp),a0
	move.b (a0,d6.w),d7
	beq.s sprite_span_planted			; not cached
	cmp.w #-1,smc_walk_plant
	bne sprite_span_planthook		; dropped, or one is planted
	subq.b #1,d7
	beq sprite_span_planthook		; inside a cell
	move.w d6,smc_walk_plant
sprite_span_planted:
	move.w (sp),d5			; MOV BP,DS
	moveq #0,d6			; POP DS; CALL DX (the same stack word)
	move.w -1(a2,d4.w),d6
	move.w #$649,-1(a2,d4.w)
	move.w d6,G_DS(a6)
	cmp.w 16(sp),d6
	bcs sprite_span_expose
sprite_span_ds:	lsl.l #4,d6
	lea -$7fff(a6),a3
	suba.l d6,a3
	moveq #0,d7
	move.w d2,d7
	jsr smc_walk
	cmp.w #$649,d7
	bne sprite_span_mismatch
	addq.w #2,d4			; PUSH DS
	move.w G_DS(a6),-1(a2,d4.w)
	move.w 2(sp),G_DS(a6)		; MOV DS,BP (above smc_seg_limit: admitted)
	movea.l 4(sp),a3
	move.w #$7fff,d7		; MOV CS:[DI],AH
	sub.w a5,d7
	movea.l 8(sp),a0
	rol.w #8,d0
	move.b d0,(a0,d7.w)
	rol.w #8,d0
	move.w a5,d6			; the restore (lower.code_store)
	sub.w #$209c,d6
	cmp.w #$23ea,d6
	bcc.s sprite_span_restored
	movea.l 12(sp),a0
	cmp.w smc_walk_plant,d6
	bne sprite_span_restorehook
	tst.w d6
	beq.s sprite_span_restored
	move.w d0,d7
	lsr.w #8,d7
	cmp.b (a0,d6.w),d7
	bne sprite_span_restorehook
	move.w #-1,smc_walk_plant
sprite_span_restored:
	subq.w #1,d1			; LOOP
	bne sprite_span_head
sprite_span_done:
	move.w -1(a2,d4.w),d0		; POP AX, JMP 7A3
	subq.w #2,d4
	bsr.s sprite_span_si
	moveq #SR_TAIL,d7
	rts
sprite_span_planthook:
	jsr smc_walk_wb
	bra sprite_span_planted
sprite_span_expose:
	jsr smc_expose
	bra sprite_span_ds
sprite_span_restorehook:
	jsr smc_walk_wb
	bra sprite_span_restored
sprite_span_clip:			; 5005
	move.w -(a4),d6			; MOV DI,[SI]; ADD SI,2
	movea.w d6,a5
	tst.w ($5a36,a3)		; [25C8]
	bne.s .index
	cmp.w ($5a3e,a3),d6		; [25C0]
	bcs.s .index
	move.w -1(a2,d4.w),d0		; POP AX; PUSH CS:[9B36]; MOV BX,CS:[9B38]
	movea.l 8(sp),a0
	move.w (-$9b37+$7fff,a0),-1(a2,d4.w)
	move.w (-$9b39+$7fff,a0),d3
.index:	add.w d6,d6			; 5023
	add.w ($7745,a3),d6
	move.w #$7fff,d7
	sub.w d6,d7
	movea.w -1(a3,d7.w),a5
	adda.w ($7751,a3),a5
	subq.w #1,d1
	bne sprite_span_head
	bra.s sprite_span_done
sprite_span_si:				; SI back from the pointer; drops the frame
	move.l 4+4(sp),d7
	add.l #$8000,d7
	sub.l a4,d7
	movea.w d7,a4
	move.l (sp)+,a0
	lea 18(sp),sp
	jmp (a0)
sprite_span_leave:
	bsr.s sprite_span_si
sprite_span_resume:
	moveq #SR_WALK,d7
	rts
sprite_span_mismatch:			; the generated call's return check
	bsr.s sprite_span_si
	addq.l #4,sp
	jmp rt_ret_mismatch
sprite_row_ega:
	addq.l #4,sp
	moveq #SR_EGA,d7
	rts
sprite_row_clipped:
	addq.l #4,sp
	moveq #SR_CLIPPED,d7
	rts
sprite_row_tail:
	moveq #SR_TAIL,d7
	rts
sprite_row_decline:
	moveq #0,d7
	rts
