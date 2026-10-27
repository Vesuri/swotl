; Terrain polygons FDE0 (native-plan F6). U6 authorized 2026-10-22; deferred
; R45 under exact polls; irq-plan I10, user 2026-10-26 (go-ahead for each
; native), poll-free (RC5). Original SWOTL x86 is the oracle. Per view ring
; (SI 0..3) the tiles of its span, per tile its polygons (5 per cell), per
; polygon its vertices: transformed (B52D) into a 25-entry cache, projected
; (D5A6) into 2445h.., clipped into C398h.. (169E:0666), classified (BB70)
; and submitted (BD68). Every call stays generated as a continuation exit
; (FF65, 10066, 10086, 100B3, 10199, 101E1, 101F1, 1020C); the row re-enters
; after each returns (hle.csv entries: d7 = 0 at FDE0, then 1 + k). The
; transform (B52D) and classify (BB70) rows' natives are called directly: the
; CALLF's CS:IP stored, the RETF stepped; their exits are taken only when the
; callee declines (before any mutation). The
; epilogue from FEA6 stays generated.
; Guest registers live in their ABI registers throughout; a0 = the frame
; (byte [BP+k] at -k(a0), word at -1-k(a0)). DS words at X are
; ($7FFE-X,a3), bytes ($7FFF-X,a3). ES loads as generated code loads it
; (smc_expose below smc_seg_limit). Admission: DS and SS inside
; CS+1000h..9000h (no code or VRAM stores), BP 500h..FF00h (the frame, its
; indexed slots and the argument pushes without 16-bit wrap); at FDE0 also
; DF = 0 (REP STOSW) and a non-zero object count [BEFDh] (LOOP never runs
; 65,536 times). A zero ring divisor resumes at the ring loop head FE5A, where
; the generated DIV faults.

	xref smc_expose
	xref smc_seg_limit
	xref rt_hle_point_transform

; Resume ids: endpoints ascending (compute.resume_dispatch).
RP_FEA6	equ 1
RP_FF65	equ 2
RP_10066	equ 3
RP_10086	equ 4
RP_100B3	equ 5
RP_10199	equ 6
RP_101E1	equ 7
RP_101F1	equ 8
RP_1020C	equ 9
RP_FE5A	equ 11			; root loop head (after the endpoints)

PG_FRAME macro	; d7.w = 7FFFh - BP: BP 500h..FF00h
	cmp.w #-$7f01,d7
	blt polygons_decline
	cmp.w #$7aff,d7
	bgt polygons_decline
	endm
PG_REENTER macro	; BP range, the frame
	move.w d5,d7
	PG_FRAME
	movea.w d5,a0
	adda.l a2,a0
	endm
PG_PUSH	macro
	addq.w #2,d4
	move.w \1,-1(a2,d4.w)
	endm
PG_POP	macro
	move.w -1(a2,d4.w),\1
	subq.w #2,d4
	endm
PG_ADDSP macro	; ADD SP,\1 with its CF (live at the next exit)
	move.w #$7fff,d7
	sub.w d4,d7
	add.w #\1,d7
	move.w ccr,G_FL(a6)
	sub.w #\1,d4
	endm
PG_CALL	macro	; CALLF to a native row (\1): its resume, then the RETF to \2;
	; a decline takes the exit \3 unchanged
	addq.w #4,d4			; CALLF: CS:IP at SP-4, stored if handled
	move.l #LOADSEG+$49b,d6
	jsr \1
	subq.w #4,d4			; RETF
	tst.l d7
	bne.s .h\@
	PG_EXIT \3
.h\@:
	move.l #((LOADSEG+$49b)<<16)|\2,1(a2,d4.w)
	movea.w d5,a0
	adda.l a2,a0
	endm
PG_EXIT	macro
	moveq #\1,d7
	rts
	endm
PG_ES	macro	; ES = d7 (zero-extended), as the generated segment load
	cmp.w G_ES(a6),d7
	beq.s .es\@
	move.w d7,G_ES(a6)
	cmp.w smc_seg_limit,d7
	bcc.s .ex\@
	jsr smc_expose
.ex\@:
	lsl.l #4,d7
	lea -$7fff(a6),a1
	suba.l d7,a1
.es\@:
	endm
PG_LES	macro	; LES DI,[\1]
	move.w ($7ffe-\1,a3),a5
	moveq #0,d7
	move.w ($7ffe-\1-2,a3),d7
	PG_ES
	endm
PG_ESB	macro	; AL = ES:[DI], DI+1
	move.w #$7fff,d7
	sub.w a5,d7
	move.b (a1,d7.w),d0
	addq.w #1,a5
	endm
PG_IX	macro	; d7 = -K - reg: byte [BP+reg+K] at (a0,d7.w)
	move.w #-(\1),d7
	sub.w \2,d7
	endm
PG_DX	macro	; d6 = 7FFFh - K - reg: DS word [reg+K] at -1(a3,d6.w)
	move.w #$7fff-\1,d6
	sub.w \2,d6
	endm
; push ES, 0, 0, CX, 0, BX, 0: the transform's arguments
PG_TARGS macro	; (SP-2 .. SP-14 at 1(a2,d4) .. $d(a2,d4): no wrap below BP)
	move.w G_ES(a6),1(a2,d4.w)
	moveq #0,d2			; SUB DX,DX: CF = 0
	clr.w G_FL(a6)
	move.l d2,3(a2,d4.w)
	move.w d1,d7
	swap d7
	clr.w d7
	move.l d7,7(a2,d4.w)		; CX, 0
	move.w d3,d7
	swap d7
	clr.w d7
	move.l d7,$b(a2,d4.w)		; BX, 0
	add.w #14,d4
	endm
; SI = SI*2, BX = [SI+BAB0h], CX = [SI+BC40h]
PG_TLOAD macro
	move.w a4,d7
	add.w d7,d7
	movea.w d7,a4
	PG_DX $bab0,a4
	move.w -1(a3,d6.w),d3
	move.w -1-($bc40-$bab0)(a3,d6.w),d1
	endm
; BX = ([BP-0Ah] - [BP-0Ch]) << 2
PG_CLIPBX macro
	move.w 9(a0),d3
	sub.w $b(a0),d3
	add.w d3,d3
	add.w d3,d3			; CF as SHL BX,1 leaves it
	move.w ccr,G_FL(a6)
	endm

	xdef rt_hle_terrain_polygons
rt_hle_terrain_polygons:
	add.w d7,d7
	movea.w d7,a0			; entry index * 2
	add.w #$1000,d6			; CS+1000h (below 10000h)
	move.l G_DS(a6),d7		; DS:SS
	cmp.w #$9000,d7
	bhi.s polygons_decline
	cmp.w d6,d7
	bcs.s polygons_decline
	swap d7
	cmp.w #$9000,d7
	bhi.s polygons_decline
	cmp.w d6,d7
	bcs.s polygons_decline
	move.w a0,d7
	move.w .entries(pc,d7.w),d7
	jmp .entries(pc,d7.w)
.entries:
	dc.w x_fde0-.entries,x_ff6a-.entries,x_1006b-.entries,x_1008b-.entries
	dc.w x_100b8-.entries,x_1019e-.entries,x_101e6-.entries,x_101f6-.entries
	dc.w x_10211-.entries

polygons_decline:
	moveq #0,d7
	rts

x_fde0:
	tst.b G_DF(a6)
	bne.s polygons_decline
	tst.b ($7fff-$befd,a3)
	beq.s polygons_decline
	move.w d4,d7
	addq.w #2,d7			; BP after PUSH BP
	PG_FRAME
	move.w d5,d7
	eori.w #$7fff,d7
	PG_PUSH d7			; PUSH BP
	move.w d4,d5			; MOV BP,SP
	movea.w d5,a0
	adda.l a2,a0
	add.w #$3fc,d4			; SUB SP,3FCh
	PG_PUSH a5
	PG_PUSH a4
	moveq #0,d0
	move.w d0,($7ffe-$22fe,a3)
	move.w d0,3(a0)			; [BP-4]
	move.w d0,5(a0)			; [BP-6]
	move.w #1,($7ffe-$22fc,a3)
	move.w #1,($7ffe-$2300,a3)
	move.w #$10,($7ffe-$c450,a3)
	moveq #0,d3
	move.w G_SS(a6),d3		; MOV BX,SS
	move.l d3,d7			; MOV ES,BX
	PG_ES
	lea $203(a0),a5			; REP STOSW: 0FFh zero words at BP-202h
	moveq #126,d7
.clear:
	clr.l -(a5)
	dbra d7,.clear
	clr.w -(a5)
	move.w d5,d7
	eori.w #$7fff,d7
	subq.w #4,d7
	movea.w d7,a5			; DI = BP-4
	moveq #0,d1			; CX = 0
	tst.b ($7fff-$9f4c,a3)
	bne x_fe2e
	move.b ($7fff-$befd,a3),d1	; CX = object count (non-zero)
	suba.l a4,a4
.count:
	move.w #$7fff-$be98,d7
	sub.w a4,d7
	cmp.b #1,(a3,d7.w)
	beq.s .counted
	PG_IX -$202,a4
	addq.b #1,(a0,d7.w)
.counted:
	addq.w #1,a4
	subq.w #1,d1
	bne.s .count
x_fe2e:
	move.w ($7ffe-$645c,a3),d0
	sub.w #$60,d0
	lsr.w #6,d0
	move.b d0,($7fff-$26d6,a3)
	move.w ($7ffe-$658e,a3),d0
	sub.w #$40,d0
	lsr.w #6,d0
	move.b d0,($7fff-$26d7,a3)
	suba.l a4,a4
x_fe5a:	; ring SI: tile window, its span DH and start DL
	move.w a4,d7
	add.w d7,d7
	PG_DX $54b6,d7
	move.w -1(a3,d6.w),d6		; the divisor
	beq.s .zero
	move.w d7,d3			; BX = SI*2
	movea.w d6,a5			; DI = divisor
	move.w a5,d0
	lsr.w #1,d0
	add.w ($7ffe-$6902,a3),d0
	moveq #0,d7
	move.w d0,d7
	move.w a5,d6
	divu.w d6,d7			; DX = 0: no overflow
	move.w d7,d0			; AX = quotient
	swap d7
	move.w d7,d2			; DX = remainder
	PG_DX $54aa,a4
	sub.b (a3,d6.w),d0
	cmp.b #$80,d0
	bcs.s .start
	PG_DX $5492,a4
	add.b (a3,d6.w),d0
.start:
	PG_DX $54cc,d3
	move.w -1(a3,d6.w),d7
	add.w ($7ffe-$8690,a3),d7
	movea.w d7,a5
	move.w ($7ffe-$8692,a3),d2
	move.w d7,($7ffe-$26dd,a3)
	move.w d2,($7ffe-$26df,a3)
	bra.s .span
.zero:					; at FE5A: the generated DIV faults
	PG_EXIT RP_FE5A
.span:
	move.b d0,d2			; DL = start
	PG_DX $549e,a4
	move.b (a3,d6.w),d7
	bfins d7,d2{16:8}		; DH = span
x_fe94:
	cmp.w #$100,d2			; DH = 0: next ring
	bcc x_feac
	addq.w #1,a4
	cmp.w #4,a4
	bne.w x_fe5a
	moveq #0,d0
	move.w d0,($7ffe-$22fc,a3)
	move.w d0,($7ffe-$2300,a3)
	PG_EXIT RP_FEA6
x_feac:	; tile DL of the ring
	PG_DX $5492,a4
	cmp.b (a3,d6.w),d2
	bcs.s .tile
	clr.b d2
.tile:
	moveq #0,d3
	move.b d2,d3
	add.w d3,d3			; BX = DL*2
	PG_LES $26dd
	move.w #$7fff,d7
	sub.w d3,d7
	sub.w a5,d7
	move.w -1(a1,d7.w),d1		; CX = ES:[BX+DI]
	move.b ($7fff-$26d7,a3),d7
	lsl.w #8,d7
	add.w d7,d1			; CH += [26D7h]
	move.w d1,d7
	lsr.w #8,d7
	move.b d7,d0			; AL = CH
	cmp.b #$d,d0
	bcc.w x_10229
	add.b ($7fff-$26d6,a3),d1
	cmp.b #$d,d1
	bcc.w x_10229
	moveq #0,d7
	move.b d0,d7
	moveq #0,d6
	move.b ($7fff-$270e,a3),d6
	mulu.w d6,d7
	move.w d7,d0			; AX = AL * [270Eh]
	moveq #0,d7
	move.b d1,d7
	add.w d7,d0
	lsl.b #2,d1
	move.b d1,d7
	add.w d7,d0
	move.w d0,($7ffe-$270f,a3)	; the cell's first polygon
	moveq #0,d0
	move.w d0,($7ffe-$2711,a3)
x_fef1:	; polygon [270Fh] + [2711h]
	move.w ($7ffe-$270f,a3),d0
	add.w ($7ffe-$2711,a3),d0
	PG_LES $bf02
	adda.w d0,a5
	move.w #$7fff,d7
	sub.w a5,d7
	moveq #0,d0
	move.b (a1,d7.w),d0
	cmp.b #$ff,d0
	beq.w x_10229
	movea.w d0,a5
	PG_IX -$202,a5
	tst.b (a0,d7.w)
	bne.w x_1021b
	move.b #1,(a0,d7.w)
	PG_PUSH d2
	PG_PUSH a4
	PG_DX $be98,a5
	moveq #0,d0
	move.b (a3,d6.w),d0
	move.w d0,7(a0)			; [BP-8] = type
	move.w a5,d7
	add.w d7,d7
	movea.w d7,a5
	PG_DX $bdd0,a5
	move.w -1(a3,d6.w),d0
	PG_LES $baac
	adda.w d0,a5
	moveq #0,d0
	PG_ESB
	move.w d0,9(a0)			; [BP-0Ah] = vertex count
	move.w d0,$b(a0)		; [BP-0Ch]
	clr.b d0
	move.w d0,$d(a0)		; [BP-0Eh] = 0
x_ff40:	; vertex: transform unless cached
	moveq #0,d0
	PG_ESB
	movea.w d0,a4
	PG_IX -$d6,a4
	tst.b (a0,d7.w)
	bne x_ffc5
	PG_TLOAD
	PG_TARGS
	PG_CALL rt_hle_point_transform,$b5ba,RP_FF65
	sub.w #14,d4			; ADD SP,0Ch; POP ES: the pushed ES (B52D keeps it)
x_ff6a_in:
	cmp.b #$19,6(a0)
	bcc x_ffb8
	addq.b #1,6(a0)			; INC BYTE [BP-6]
	move.w 5(a0),d0
	move.w a4,d7
	lsr.w #1,d7
	movea.w d7,a4
	PG_IX -$d6,a4
	move.b d0,(a0,d7.w)		; the vertex's cache slot
	subq.b #1,d0
	add.w d0,d0
	add.w d0,d0
	movea.w d0,a4
	PG_IX -$2ca,a4
	move.l ($7ffc-$c38c,a3),-$67(a0,d7.w)	; [BP+SI-266h], -264h
	move.l ($7ffc-$c390,a3),-3(a0,d7.w)	; -2CAh, -2C8h
	move.l ($7ffc-$c394,a3),$61(a0,d7.w)	; -32Eh, -32Ch
	move.w ($7ffe-$c396,a3),d0
	bmi x_ffda
	bra x_ffdd
x_ffb8:
	tst.w ($7ffe-$c396,a3)
	bpl x_ffdd
	bra x_ffda
x_ffc5:	; cached: its z sign
	moveq #0,d3
	move.b (a0,d7.w),d3
	subq.w #1,d3
	add.w d3,d3
	add.w d3,d3
	movea.w d3,a4
	PG_IX -$32c,a4
	tst.w -1(a0,d7.w)
	bpl x_ffdd
x_ffda:
	addq.b #1,$e(a0)		; INC BYTE [BP-0Eh]: behind the eye
x_ffdd:
	subq.b #1,$c(a0)
	bne.w x_ff40
	move.b $a(a0),d0
	cmp.b $e(a0),d0
	beq.w x_10219			; all behind
	move.b d0,$c(a0)
	andi.w #$ff,d0
	suba.w d0,a5			; back to the first vertex
	moveq #0,d0
	move.w d0,($7ffe-$cf6a,a3)
	move.w d0,($7ffe-$c3fa,a3)
	tst.b $e(a0)
	bne.w x_1012f
x_10008:	; all in front: project
	moveq #0,d0
	PG_ESB
	movea.w d0,a4
	PG_IX -$19e,a4
	tst.b (a0,d7.w)
	beq x_1004b
	moveq #0,d3
	move.b (a0,d7.w),d3
	subq.w #1,d3
	add.w d3,d3
	add.w d3,d3
	movea.w d3,a4
	move.w ($7ffe-$cf6a,a3),d3
	PG_IX -$392,a4
	PG_DX $2445,d3
	move.l -3(a0,d7.w),-3(a3,d6.w)	; [BX+2445h], 2447h
	move.l $61(a0,d7.w),-7(a3,d6.w)	; 2449h, 244Bh
	move.w $61(a0,d7.w),d0
	bra.w x_10119
x_1004b:
	PG_IX -$d6,a4
	move.b (a0,d7.w),d0
	bne x_10091
	PG_TLOAD
	PG_TARGS
	PG_CALL rt_hle_point_transform,$b6bb,RP_10066
x_1006b_in:
	PG_ADDSP 12
	PG_PUSH ($7ffe-$c396,a3)
	PG_PUSH ($7ffe-$c394,a3)
	PG_PUSH ($7ffe-$c392,a3)
	PG_PUSH ($7ffe-$c390,a3)
	PG_PUSH ($7ffe-$c38e,a3)
	PG_PUSH ($7ffe-$c38c,a3)
	PG_EXIT RP_10086
x_1008b:
x_100b8:
	PG_REENTER
	moveq #0,d7
	move.w -13(a2,d4.w),d7		; ADD SP,0Ch; POP ES
	sub.w #14,d4
	PG_ES
	bra x_100bc
x_10091:	; cached: project it
	andi.w #$ff,d0
	subq.w #1,d0
	add.w d0,d0
	add.w d0,d0			; CF as SHL AX,1 leaves it
	move.w ccr,G_FL(a6)
	movea.w d0,a4
	PG_PUSH G_ES(a6)
	PG_IX -$32c,a4
	PG_PUSH -1(a0,d7.w)
	PG_IX -$32e,a4
	PG_PUSH -1(a0,d7.w)
	PG_IX -$2c8,a4
	PG_PUSH -1(a0,d7.w)
	PG_IX -$2ca,a4
	PG_PUSH -1(a0,d7.w)
	PG_IX -$264,a4
	PG_PUSH -1(a0,d7.w)
	PG_IX -$266,a4
	PG_PUSH -1(a0,d7.w)
	PG_EXIT RP_100B3
x_100bc:	; the projected vertex
	move.w ($7ffe-$cf6a,a3),d3
	PG_DX $2445,d3
	move.l ($7ffc-$22de,a3),-3(a3,d6.w)	; [BX+2445h], 2447h
	move.l ($7ffc-$22e2,a3),-7(a3,d6.w)	; 2449h, 244Bh
	move.w ($7ffe-$22e4,a3),d0
	move.b 4(a0),d0
	cmp.b #$19,d0
	bcc x_10119
	andi.w #$ff,d0
	add.w d0,d0
	add.w d0,d0
	movea.w d0,a4
	PG_IX -$392,a4
	move.l ($7ffc-$22de,a3),-3(a0,d7.w)	; [BP+SI-392h], -390h
	move.l ($7ffc-$22e2,a3),$61(a0,d7.w)	; -3F6h, -3F4h
	addq.b #1,4(a0)			; INC BYTE [BP-4]
	move.b 4(a0),d0
	move.w #-$8000,d7		; BL = ES:[DI-1]
	sub.w a5,d7
	moveq #0,d3
	move.b (a1,d7.w),d3
	movea.w d3,a4
	PG_IX -$19e,a4
	move.b d0,(a0,d7.w)
x_10119:
	addq.w #8,($7ffe-$cf6a,a3)
	move.w ccr,G_FL(a6)		; CF of the ADD (live at 101F1)
	subq.b #1,$c(a0)
	bne.w x_10008
	move.w 9(a0),d0
	move.w d0,($7ffe-$c3fa,a3)
	bra.w x_101e9
x_1012f:	; some behind: clip
	moveq #0,d0
	PG_ESB
	movea.w d0,a4
	PG_IX -$d6,a4
	tst.b (a0,d7.w)
	beq x_10186
	moveq #0,d0
	move.b (a0,d7.w),d0
	subq.w #1,d0
	add.w d0,d0
	add.w d0,d0
	move.w a4,d7			; XCHG SI,AX
	movea.w d0,a4
	move.w d7,d0
	PG_CLIPBX
	PG_IX -$2ca,a4
	PG_DX $c398,d3
	move.l -$67(a0,d7.w),-3(a3,d6.w)	; [BX+C398h], C39Ah
	move.l -3(a0,d7.w),-$23(a3,d6.w)	; C3B8h, C3BAh
	move.l $61(a0,d7.w),-$43(a3,d6.w)	; C3D8h, C3DAh
	move.w $61(a0,d7.w),d0
	bra x_101d6
x_10186:
	PG_TLOAD
	PG_TARGS
	PG_CALL rt_hle_point_transform,$b7ee,RP_10199
	sub.w #14,d4			; ADD SP,0Ch; POP ES: the pushed ES (B52D keeps it)
x_1019e_in:
	PG_CLIPBX
	PG_DX $c398,d3
	move.l ($7ffc-$c38c,a3),-3(a3,d6.w)	; [BX+C398h], C39Ah
	move.l ($7ffc-$c390,a3),-$23(a3,d6.w)	; C3B8h, C3BAh
	move.l ($7ffc-$c394,a3),-$43(a3,d6.w)	; C3D8h, C3DAh
	move.w ($7ffe-$c396,a3),d0
x_101d6:
	subq.b #1,$c(a0)
	bne.w x_1012f
	PG_PUSH 9(a0)			; PUSH [BP-0Ah]
	PG_EXIT RP_101E1
x_101e6:
	PG_REENTER
	PG_ADDSP 2
x_101e9:
	PG_PUSH ($7ffe-$c3fa,a3)
	move.w #$2445,d0
	PG_PUSH d0
	PG_CALL rt_hle_polygon_classify,$b846,RP_101F1
x_101f6_in:
	subq.w #4,d4			; ADD SP,4
	tst.w d0			; OR AX,AX: CF = 0
	beq x_10219
	move.w ccr,G_FL(a6)
	PG_PUSH ($7ffe-$c450,a3)
	PG_PUSH ($7ffe-$c3f8,a3)
	PG_PUSH 7(a0)			; PUSH [BP-8]
	move.w #$2445,d0
	PG_PUSH d0
	PG_EXIT RP_1020C
x_10211:
	PG_REENTER
	subq.w #8,d4			; ADD SP,8
	addq.w #2,($7ffe-$c450,a3)
x_10219:
	PG_POP a4
	PG_POP d2
x_1021b:
	addq.w #1,($7ffe-$2711,a3)
	cmp.w #5,($7ffe-$2711,a3)
	blt.w x_fef1
x_10229:
	addq.b #1,d2			; INC DL
	sub.w #$100,d2			; DEC DH
	bra.w x_fe94
; re-entries after a declined direct call's exit
x_ff6a:
	PG_REENTER
	moveq #0,d7
	move.w -13(a2,d4.w),d7		; ADD SP,0Ch; POP ES
	sub.w #14,d4
	PG_ES
	bra x_ff6a_in
x_1006b:
	PG_REENTER
	bra x_1006b_in
x_1019e:
	PG_REENTER
	moveq #0,d7
	move.w -13(a2,d4.w),d7		; ADD SP,0Ch; POP ES
	sub.w #14,d4
	PG_ES
	bra x_1019e_in
x_101f6:
	PG_REENTER
	bra x_101f6_in
