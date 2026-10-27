; Terrain tile and scenery selection F290 (native-plan F6). U6 authorized
; 2026-10-22; deferred R41 under exact polls; irq-plan I10, user 2026-10-26
; (go-ahead for each native), poll-free (RC5). Original SWOTL x86 is the
; oracle. Per view ring (SI 0..7) the tile window, per tile its map cell,
; per scenery cell its objects: positions to C380h..C387h, type to C440h.
; The object calls (F600, 169E:064E) stay generated as continuation exits
; (F40F, F46B, F5E3); the row re-enters after each returns (hle.csv entries:
; d7 = 0 at F290, then F414, F470, F5E8). Two paths no fixture reaches stay
; generated (exits F484, F4C9). The epilogue from F318 stays generated.
; Guest registers live in their ABI registers, except BP (in the frame, as
; d5 holds it: BP ^ 7FFFh) and ES: a1 is the current ES window, G_ES is
; written at the exits only (the type segment; at F318 the window's). In the
; tile loop d5 = [26D7h] << 8 | [5492h+SI], a0 the map window. DS words at X
; are ($7FFE-X,a3), bytes ($7FFF-X,a3). Admission: DS and SS inside
; CS+1000h..9000h (no code or VRAM stores, as edge_submit), the tile, map and
; type segments ([8692h], [8658h], [ABA2h]) at CS+1000h or above; at a
; re-entry also the ES to pop equal to the type segment and [26DFh] equal to
; [8692h]. A ring whose divisor ([54B6h+2SI]) is zero (DIV DI faults) runs
; generated from its loop head F2BD. The one dynamic segment (the object
; table's, F436) drops the cell caches as generated code does (smc_expose
; below smc_seg_limit).

	xref smc_expose
	xref smc_seg_limit

; Resume ids: endpoints ascending (compute.resume_dispatch).
RT_F318	equ 1
RT_F40F	equ 2
RT_F46B	equ 3
RT_F484	equ 4
RT_F4C9	equ 5
RT_F5E3	equ 6
RT_F2BD	equ 7		; the first root loop head

; native frame
TF_T	equ 0		; tile window base
TF_O	equ 4		; type window base
TF_OS	equ 8		; type segment
TF_BP	equ 10		; BP ^ 7FFFh
TF_SIZE	equ 12

TS_SEG	macro	; a written segment: CS+1000h (d6) .. 9000h
	moveq #0,d7
	move.w \1,d7
	cmp.w #$9000,d7
	bhi.w terrain_drop
	cmp.l d6,d7
	bcs.w terrain_drop
	endm
TS_BASE	macro	; DS offset of a read segment (CS+1000h or above), [frame slot] -> a0
	moveq #0,d7
	move.w ($7ffe-\1,a3),d7
	cmp.l d6,d7
	bcs.w terrain_drop
	ifnb \2
	move.w d7,\2(sp)
	endif
	lsl.l #4,d7
	lea -$7fff(a6),a0
	suba.l d7,a0
	endm
TS_PUSH	macro
	addq.w #2,d4
	move.w \1,-1(a2,d4.w)
	endm
TS_POP	macro
	move.w -1(a2,d4.w),\1
	subq.w #2,d4
	endm
; an exit with ES the type window
TS_LEAVE macro
	move.w TF_OS(sp),G_ES(a6)
	move.w TF_BP(sp),d5
	lea TF_SIZE(sp),sp
	moveq #\1,d7
	rts
	endm
; d7 = index of the ES word or byte at offset [\2 + \1]
TS_IX	macro	; K, reg
	move.w #$7fff-\1,d7
	sub.w \2,d7
	endm
; d5 = [26D7h] << 8 | [5492h+SI]
TS_TILE	macro
	move.b ($7fff-$26d7,a3),d5
	lsl.w #8,d5
	TS_IX $5492,a4
	move.b (a3,d7.w),d5
	endm
; one position: AX = ES word << 3, BX = its top three bits + DS word \2,
; stored at \3/\4
TS_XY	macro	; K, cell, ax at, bx at
	TS_IX \1,a5
	move.w -1(a1,d7.w),d0
	move.w d0,d3
	lsr.w #8,d3
	lsr.w #5,d3
	lsl.w #3,d0
	add.w ($7ffe-\2,a3),d3
	move.w d0,($7ffe-\3,a3)
	move.w d3,($7ffe-\4,a3)
	endm
; [C380h..C387h] from the object at ES:DI, BL its type
TS_POS	macro
	TS_XY 1,$26d9,$c380,$c382
	TS_XY 3,$26db,$c384,$c386
	TS_IX 0,a5
	move.b (a1,d7.w),d3
	endm
; 26D9h = (CL + [A9BCh]) << 3 + 60h, 26DBh = (CH + [AA9Ah]) << 3 + 40h
TS_CELL	macro
	moveq #0,d0
	move.b d1,d0
	add.w ($7ffe-$a9bc,a3),d0
	lsl.w #3,d0
	add.w #$60,d0
	move.w d0,($7ffe-$26d9,a3)
	move.w d1,d0
	lsr.w #8,d0
	add.w ($7ffe-$aa9a,a3),d0
	lsl.w #3,d0
	add.w #$40,d0
	move.w d0,($7ffe-$26db,a3)
	endm
; ES:DI = the type record of cell AL (ES the type window)
TS_TYPE	macro
	movea.w ($7ffe-$aba0,a3),a5
	movea.l TF_O(sp),a1
	moveq #0,d3
	move.b d0,d3
	add.w d3,d3
	move.w #$7ffe-$bf36,d7
	sub.w d3,d7
	adda.w (a3,d7.w),a5
	endm

	xdef rt_hle_terrain_select
rt_hle_terrain_select:
	lea -TF_SIZE(sp),sp
	move.w d5,TF_BP(sp)
	move.w d7,d5			; entry index
	add.l #$1000,d6
	TS_SEG G_DS(a6)
	TS_SEG G_SS(a6)
	TS_BASE $aba2,TF_OS
	move.l a0,TF_O(sp)
	TS_BASE $8692
	move.l a0,(sp)
	TS_BASE $8658			; a0 = the map window
	move.w d5,d6
	beq f290
	move.w d4,d7			; the ES to pop: SP+2, or SP+4 at F470
	subq.w #2,d7
	cmp.w #2,d6
	bne .es
	subq.w #2,d7
.es:
	move.w -1(a2,d7.w),d7
	cmp.w TF_OS(sp),d7
	bne terrain_drop
	move.w ($7ffe-$26df,a3),d7	; the tile window's LES segment
	cmp.w ($7ffe-$8692,a3),d7
	bne terrain_drop
	TS_TILE
	subq.w #2,d6
	bcs f414
	beq f470
	bra f5e8

terrain_drop:
	move.w TF_BP(sp),d5
	lea TF_SIZE(sp),sp
	moveq #0,d7
	rts

f290:
	move.w TF_BP(sp),d7
	eori.w #$7fff,d7
	TS_PUSH d7			; PUSH BP
	move.w d4,TF_BP(sp)		; MOV BP,SP
	TS_PUSH a5
	TS_PUSH a4
	move.w ($7ffe-$645c,a3),d0
	sub.w #$60,d0
	lsr.w #3,d0
	sub.w ($7ffe-$a9bc,a3),d0
	move.b d0,($7fff-$26d6,a3)
	move.w ($7ffe-$658e,a3),d0
	sub.w #$40,d0
	lsr.w #3,d0
	sub.w ($7ffe-$aa9a,a3),d0
	move.b d0,($7fff-$26d7,a3)
	suba.l a4,a4
f2bd:	; ring SI: tile window and its span DH, start DL
	move.w a4,d6
	add.w d6,d6
	move.w #$7ffe-$54b6,d7
	sub.w d6,d7
	tst.w (a3,d7.w)
	beq ring_fault			; DIV DI would fault: generated from F2BD
	move.w d6,d3
	movea.w (a3,d7.w),a5
	move.w a5,d6
	move.w a5,d0
	lsr.w #1,d0
	add.w ($7ffe-$6902,a3),d0
	andi.l #$ffff,d0
	divu.w d6,d0
	TS_IX $54aa,a4
	sub.b (a3,d7.w),d0
	TS_TILE
	cmp.b #$80,d0
	bcs .f2dd
	add.b d5,d0
.f2dd:
	move.w #$7ffe-$54cc,d7
	sub.w d3,d7
	movea.w (a3,d7.w),a5
	adda.w ($7ffe-$8690,a3),a5
	move.w ($7ffe-$8692,a3),d2
	move.w a5,($7ffe-$26dd,a3)
	move.w d2,($7ffe-$26df,a3)
	move.b d0,d2
	move.w a4,d1
	tst.b d1
	beq .f304
	subq.b #1,d1
	lsl.b #3,d1
	addq.b #4,d1
.f304:
	move.b d1,($7fff-$26d8,a3)
	TS_IX $549e,a4
	move.b (a3,d7.w),d6
	bfins d6,d2{16:8}
	bra.w f30c

; the tile loop: common paths fall through, rare ones out of line
f31a:	; one tile: DL clipped to the ring's width
	cmp.b d5,d2
	bcc.w f320
f322:
	moveq #0,d3
	move.b d2,d3
	add.w d3,d3
	move.w #$7fff,d7
	sub.w d3,d7
	sub.w ($7ffe-$26dd,a3),d7
	movea.l (sp),a5
	move.w -1(a5,d7.w),d1		; CX = tile (ES:[DI+BX])
	move.w d5,d6
	clr.b d6
	add.w d6,d1			; CH += [26D7h]
	cmp.w #$3200,d1
	bcc f322_out
	add.b ($7fff-$26d6,a3),d1
	cmp.b #$32,d1
	bcc f322_out
	move.w d1,d0
	lsr.w #8,d0
	moveq #0,d6
	move.b ($7fff-$26e1,a3),d6
	mulu.w d6,d0
	moveq #0,d6
	move.b d1,d6
	add.w d6,d0
	movea.w ($7ffe-$8656,a3),a5
	movea.l a0,a1			; ES = the map window
	adda.w d0,a5
	TS_IX 0,a5
	move.b (a1,d7.w),d0		; map cell
	beq f47d
	cmp.b #$df,d0
	bcs.w f362
	move.b ($7fff-$26d8,a3),d3	; F543: object cells in the near rings
	cmp.b #4,d3
	ble.w f54f
f47d:
	addq.b #1,d2
	sub.w #$100,d2
f30c:
	cmp.w #$ff,d2
	bhi f31a
	move.w a4,d6			; next ring
	addq.w #1,d6
	movea.w d6,a4
	cmp.w #8,d6
	bne.w f2bd
	TS_POP d6			; POP SI, POP DI
	movea.w d6,a4
	TS_POP d6
	movea.w d6,a5
	moveq #RT_F318,d6
terrain_es:	; leave with ES the window last loaded (d6 = resume id)
	move.w ($7ffe-$8692,a3),d7
	cmpa.l (sp),a1
	beq .es
	move.w ($7ffe-$8658,a3),d7
	cmpa.l a0,a1
	beq .es
	move.w TF_OS(sp),d7
	cmpa.l TF_O(sp),a1
	bne .keep
.es:
	move.w d7,G_ES(a6)
.keep:
	move.w TF_BP(sp),d5
	lea TF_SIZE(sp),sp
	move.l d6,d7
	rts
ring_fault:
	moveq #RT_F2BD,d6
	bra terrain_es
f322_out:	; off the map: AL = CH, DI = [26DDh], ES = the tile window
	move.w d1,d6
	lsr.w #8,d6
	move.b d6,d0
	movea.w ($7ffe-$26dd,a3),a5
	movea.l (sp),a1
	bra f47d
f320:
	clr.b d2
	bra.w f322

f362:	; scenery cell: its objects within the ring's range
	TS_TYPE
	move.b ($7fff-$26d8,a3),d0
	TS_IX 2,a5
	cmp.b (a1,d7.w),d0
	bhi.w f47d
	move.b ($7fff-$9db0,a3),d0
	TS_IX 1,a5
	cmp.b (a1,d7.w),d0
	bcs.w f47d
	TS_CELL
	TS_IX 0,a5
	move.b (a1,d7.w),d1		; CL = objects
	addq.w #4,a5
	tst.b d1
	beq.w f47d
	bra f3b4
f476:
	subq.b #1,d1
	beq f47d
; the object loop. A sprite object in a far ring only leaves its position,
; type and AL behind, which the next object overwrites: it is skipped on its
; type byte (d7 = the index of DI), and when the loop ends on one, its stores
; and registers are made.
f3b4:
	cmp.b #4,($7fff-$26d8,a3)
	ble f3b8			; a near ring: no object skipped
	TS_IX 0,a5
.next:
	move.b (a1,d7.w),d6
	cmp.b #$df,d6
	bls .full
	subq.w #5,d7
	subq.b #1,d1
	bne .next
	addq.w #5,d7			; the last object, skipped
	move.w #$7fff,d6
	sub.w d7,d6
	movea.w d6,a5
	TS_POS
	move.b d3,($7fff-$c440,a3)
	addq.w #5,a5
	move.b ($7fff-$26d8,a3),d0
	bra f47d
.full:
	move.w #$7fff,d6
	sub.w d7,d6
	movea.w d6,a5
f3b8:	; a full object
	TS_POS
	move.b d3,($7fff-$c440,a3)
	addq.w #5,a5
	cmp.b #$df,d3
	bls f41c
	move.b ($7fff-$26d8,a3),d0	; F3FD: a sprite object in a near ring
f404:
	sub.b #$e0,d3
	andi.w #$ff,d3
	TS_PUSH d1
	TS_PUSH d2
	TS_PUSH TF_OS(sp)
	TS_PUSH d3
	TS_LEAVE RT_F40F
f41c:
	andi.w #$ff,d3
	add.w d3,d3
	move.w ($7ffe-$acb2,a3),d6
	move.w ($7ffe-$acb4,a3),d0
	move.w #$7ffe-$c136,d7
	sub.w d3,d7
	add.w (a3,d7.w),d6
	moveq #0,d7
	addx.w d7,d0			; ADC AX,0
	move.w d6,d3
	or.w d0,d6			; OR BP,AX
	bne .f42e
	move.w #$7fff,TF_BP(sp)		; BP = 0
	bra f476
.f42e:
	move.w TF_OS(sp),d7		; MOV BP,ES
	eori.w #$7fff,d7
	move.w d7,TF_BP(sp)
	moveq #0,d7			; MOV ES,AX
	move.w d0,d7
	cmp.w smc_seg_limit,d7
	bcc .f436
	jsr smc_expose
.f436:
	lsl.l #4,d7
	lea -$7fff(a6),a1
	suba.l d7,a1
	move.w #$7fff,d7
	sub.w d3,d7
	move.b (a1,d7.w),d6
	bfins d6,d0{16:8}		; AH = ES:[BX]
	subq.w #1,d7
	move.b (a1,d7.w),d6
	bfins d6,d1{16:8}		; CH = ES:[BX+1]
	movea.l TF_O(sp),a1		; MOV ES,BP
	move.w d0,d6
	lsr.w #8,d6
	move.b d6,d0			; AL = AH
	andi.w #$07ff,d0
	move.w d0,d6
	lsr.w #8,d6
	cmp.b ($7fff-$9db0,a3),d6
	bhi f476
	cmpi.b #$7f,($7fff-$c440,a3)
	bhi .f4c9
	btst #3,d0
	bne .f484
	move.b ($7fff-$26d8,a3),d0
	move.w d1,d6
	lsr.w #8,d6
	cmp.b d6,d0
	bhi.w f476
	moveq #0,d3
	andi.w #$ff,d0
	clr.b ($7fff-$c441,a3)
	TS_PUSH d1
	TS_PUSH d2
	TS_PUSH TF_OS(sp)
	TS_PUSH d0
	TS_PUSH d3
	moveq #0,d6			; CF live at the call: SUB AH,AH's,
	move.w ccr,G_FL(a6)		; kept as generated code keeps it
	TS_LEAVE RT_F46B
.f484:
	TS_LEAVE RT_F484
.f4c9:
	TS_LEAVE RT_F4C9
f414:
	subq.w #2,d4			; ADD SP,2
	bra f417
f470:
	subq.w #4,d4			; ADD SP,4
f417:
	subq.w #2,d4			; POP ES (the type segment: checked)
	movea.l TF_O(sp),a1
	TS_POP d2
	TS_POP d1
	bra.w f476

f54f:	; object cell in a near ring: every object a sprite call
	TS_TYPE
	move.b ($7fff-$9db0,a3),d0
	TS_IX 1,a5
	cmp.b (a1,d7.w),d0
	bcs.w f47d
	TS_CELL
	TS_IX 0,a5
	move.b (a1,d7.w),d1
	addq.w #4,a5
	tst.b d1
	beq.w f47d
f598:
	TS_POS
	addq.w #5,a5
	sub.b #$e0,d3
	andi.w #$ff,d3
	TS_PUSH d1
	TS_PUSH d2
	TS_PUSH TF_OS(sp)
	TS_PUSH d3
	TS_LEAVE RT_F5E3
f5e8:
	subq.w #4,d4			; ADD SP,2; POP ES (checked)
	movea.l TF_O(sp),a1
	TS_POP d2
	TS_POP d1
	subq.b #1,d1
	bne f598
	bra.w f47d
