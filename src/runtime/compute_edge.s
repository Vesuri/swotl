; Edge submission BD68: a polygon's left and right edge chains, then the
; flat span records. U6 authorized 2026-10-22; deferred R43 (exact polls);
; irq-plan I10, user 2026-10-26 (go-ahead for each native). Original SWOTL
; x86 is the oracle. The edge setup call (C962) and the span-record call
; (CD00) stay generated as continuation exits; the row re-enters after
; each returns (hle.csv entries; d7 = 0 at BD68, then BE1B, BEDB, BF97,
; BFB4). The epilogue from BF04 stays generated. BP is held mirrored in d5
; (BP ^ 7FFFh, as generated code holds it); DS words at X are
; ($7FFE-X,a3), bytes ($7FFF-X,a3). Every address is the generated one, so
; segments need no admission; ES loads as generated code loads it
; (smc_expose below smc_seg_limit). A chain record [R+2445h..244Ch] is
; addressed from one base, exact while R stays within 1800h of 0: the
; chains step R by 8 at most 256 times from 0..80h, and a re-entry whose
; popped SI or BP lies outside +-1000h resumes at its loop head in
; generated code. Admission at the span-record re-entries: DF = 0 and DI
; at most FFF0h (eight STOSW without a wrap).

	xref smc_expose
	xref smc_seg_limit

; Resume ids: exits ascending, then the root loop heads (compute.resume_dispatch).
RZ_BE18	equ 1
RZ_BED8	equ 2
RZ_BF04	equ 3
RZ_BF94	equ 4
RZ_BFB1	equ 5
RZ_BDC6	equ 7
RZ_BE87	equ 9

EDGE_PUSH macro	; src
	addq.w #2,d4
	move.w \1,-1(a2,d4.w)
	endm
EDGE_PUSH_BP macro
	move.w d5,d7
	eori.w #$7fff,d7
	EDGE_PUSH d7
	endm
; POP BP, POP SI; either outside +-1000h resumes at \1 in generated code
EDGE_POP_BP_SI macro	; resume id
	move.w -1(a2,d4.w),d5
	eori.w #$7fff,d5
	subq.w #2,d4
	movea.w -1(a2,d4.w),a4
	subq.w #2,d4
	move.w a4,d7
	add.w #$1000,d7
	cmp.w #$2000,d7
	bhi.s .r\@
	move.w d5,d7
	sub.w #$6fff,d7
	cmp.w #$2000,d7
	bls.s .k\@
.r\@:
	moveq #\1,d7
	rts
.k\@:
	endm
; The record bases: a0 = the SI record ([SI+2449h] at (a0), +244Bh -2,
; +2447h 2, +2445h 4), d6 = the BP record index ([BP+2449h] at
; -1(a3,d6.w), -3, 1, 3). A chain step moves them with SI and BP.
EDGE_BASES macro
	move.w #$7fff-$2449,d7
	sub.w a4,d7
	lea -1(a3,d7.w),a0
	move.w d5,d6
	sub.w #$2449,d6
	endm
; One chain's end-point compare (BDA5/BE66): AX:DX = [SI+2449h] - [BP+2449h]
; with the minuend stored at 23FF/23FD; branches to \1 (the edge setup, out
; of line) when the difference is positive (SBB's SF, ZF; OR AX,AX), else
; falls through to the chain step.
EDGE_CMP macro	; setup
	move.w (a0),d0
	move.w d0,($7ffe-$23ff,a3)
	move.w -2(a0),d2
	move.w d2,($7ffe-$23fd,a3)
	move.w -3(a3,d6.w),d7
	sub.w -1(a3,d6.w),d0
	subx.w d7,d2
	tst.w d2
	bmi.s .s\@
	bne.w \1
	tst.w d0
	bne.w \1
.s\@:
	endm
; The edge parameters for C962 (BDD5/BE95): BL = \1
EDGE_SETUP macro
	move.w d2,($7ffe-$240d,a3)
	move.w d0,($7ffe-$240f,a3)
	move.w -1(a3,d6.w),($7ffe-$236e,a3)
	move.w -3(a3,d6.w),($7ffe-$236c,a3)
	move.w 4(a0),($7ffe-$2366,a3)
	move.w 2(a0),($7ffe-$2364,a3)
	move.w 3(a3,d6.w),($7ffe-$236a,a3)
	move.w 1(a3,d6.w),d3
	move.w d3,($7ffe-$2368,a3)
	move.b #\1,d3
	move.b d3,($7fff-$2370,a3)
	EDGE_PUSH a4
	EDGE_PUSH_BP
	endm
; Mark the polygon's first record (BE1F/BEDF): ES = [2360],
; ES:[(ES:[0] - 1) * 16 + 2] += 1, its byte 5 |= \1.
EDGE_MARK macro
	move.w ($7ffe-$2360,a3),d7
	cmp.w G_ES(a6),d7
	beq.s .es\@
	and.l #$ffff,d7
	move.w d7,G_ES(a6)
	cmp.w smc_seg_limit,d7
	bcc.s .ex\@
	jsr smc_expose
.ex\@:
	lsl.l #4,d7
	lea -$7fff(a6),a1
	suba.l d7,a1
.es\@:
	suba.w a4,a4
	move.w ($7ffe,a1),d3
	subq.w #1,d3
	lsl.w #4,d3
	addq.w #2,d3
	move.w #$7fff,d7
	sub.w d3,d7
	addq.w #1,-1(a1,d7.w)
	or.b #\1,-5(a1,d7.w)
	endm

	xdef rt_hle_edge_submit
rt_hle_edge_submit:
	subq.w #1,d7
	bcs.s edge_bd68
	beq.w edge_be1b
	subq.w #1,d7
	beq.w edge_bedb
	tst.b G_DF(a6)		; BF97/BFB4: eight STOSW from ES:DI without a wrap
	bne.s .decline
	move.w a5,d6
	cmp.w #$fff0,d6
	bhi.s .decline
	subq.w #1,d7
	beq.w edge_bf97
	bra.w edge_bfb4
.decline:
	moveq #0,d7
	rts

edge_bd68:
	EDGE_PUSH_BP
	move.w d4,d5		; MOV BP,SP
	EDGE_PUSH a5
	EDGE_PUSH a4
	EDGE_PUSH G_ES(a6)
	move.w d5,d7
	sub.w #$c,d7
	move.w -1(a2,d7.w),d0
	move.w d0,($7ffe-$252f,a3)
	move.w d5,d7
	subq.w #8,d7
	move.w -1(a2,d7.w),d0
	cmp.w #$10,d0
	bge.s .bd85
	add.w d0,d0
	movea.w #$2342,a4
	adda.w d0,a4
	move.w #$7fff,d7
	sub.w a4,d7
	move.w -1(a3,d7.w),d0
.bd85:
	move.w d0,($7ffe-$23d9,a3)
	move.w d5,d7
	sub.w #$a,d7
	move.w -1(a2,d7.w),d0
	move.w d0,($7ffe-$c3f8,a3)
	and.b #$f,d0
	cmp.b #$f,d0
	beq.w edge_bf09
	move.b d0,($7fff-$2372,a3)
	suba.w a4,a4
	move.w #$7fff-8,d5	; BP = 8
	clr.b ($7fff-$2371,a3)

; ---- left chain: SI, BP = SI + 8 step up -------------------------------

edge_bda5:
	EDGE_BASES
edge_bda5_b:
	EDGE_CMP edge_bdd5
	addq.w #8,a4		; BDC6
	subq.w #8,d5		; BP += 8
	subq.w #8,a0
	subq.w #8,d6
	subq.b #1,($7fff-$2372,a3)
	bne.s edge_bda5_b
	bra.w edge_be1f
edge_bdd5:
	EDGE_SETUP 1
	moveq #RZ_BE18,d7
	rts
edge_be1b:
	EDGE_POP_BP_SI RZ_BDC6
	addq.w #8,a4		; BDC6
	subq.w #8,d5
	subq.b #1,($7fff-$2372,a3)
	bne.w edge_bda5
edge_be1f:
	tst.b ($7fff-$2371,a3)
	beq.s edge_be44
	EDGE_MARK $11

; ---- right chain: BP = (C3F8h & F0h) / 2 - 8, SI = BP, step down -------

edge_be44:
	move.w ($7ffe-$c3f8,a3),d0
	and.w #$f0,d0
	lsr.w #1,d0
	move.w d0,d5
	eori.w #$7fff,d5
	addq.w #8,d5		; BP -= 8
	suba.w a4,a4
	lsr.w #3,d0
	sub.b ($7fff-$2372,a3),d0
	move.b d0,($7fff-$2372,a3)
	clr.b ($7fff-$2371,a3)
edge_be66:
	EDGE_BASES
edge_be66_b:
	EDGE_CMP edge_be95
	move.w d5,d7		; BE87: SI = BP
	eori.w #$7fff,d7
	movea.w d7,a4
	lea -1(a3,d6.w),a0
	addq.w #8,d5		; BP -= 8
	addq.w #8,d6
	subq.b #1,($7fff-$2372,a3)
	bne.s edge_be66_b
	bra.w edge_bedf
edge_be95:
	EDGE_SETUP 2
	moveq #RZ_BED8,d7
	rts
edge_bedb:
	EDGE_POP_BP_SI RZ_BE87
	move.w d5,d7		; BE87
	eori.w #$7fff,d7
	movea.w d7,a4
	addq.w #8,d5
	subq.b #1,($7fff-$2372,a3)
	bne.w edge_be66
edge_bedf:
	tst.b ($7fff-$2371,a3)
	beq.s edge_bf04
	EDGE_MARK $12
edge_bf04:
	moveq #RZ_BF04,d7
	rts

; ---- flat polygon: Y range over the CX points from DS:2445 -------------

edge_bf09:
	movea.w #$2445,a4
	moveq #0,d3
	move.w ($7ffe-$2379,a3),d1
	move.w ($7ffe-$2445,a3),d0
	move.w ($7ffe-$2447,a3),d2
	bra.s .bf2b
.bf1b:				; DX:AX = the lowest point (signed high, unsigned low)
	move.w #$7fff-$2447,d7	; BX = 8k: D7 never wraps by 2
	sub.w d3,d7
	cmp.w -1(a3,d7.w),d2
	blt.s .bf2b
	bgt.s .bf26
	cmp.w 1(a3,d7.w),d0
	bls.s .bf2b
.bf26:
	move.w 1(a3,d7.w),d0
	move.w -1(a3,d7.w),d2
.bf2b:
	addq.w #8,d3
	subq.w #1,d1
	bne.s .bf1b
	tst.w d2
	bmi.s .bf41
	bne.s edge_bf04
	cmp.w ($7ffe-$233c,a3),d0
	bge.s edge_bf04
	bra.s .bf44
.bf41:
	moveq #0,d0
.bf44:
	move.w d0,($7ffe-$2413,a3)
	moveq #0,d3
	move.w ($7ffe-$2379,a3),d1
	move.w ($7ffe-$2445,a3),d0
	move.w ($7ffe-$2447,a3),d2
	bra.s .bf66
.bf56:				; DX:AX = the highest point
	move.w #$7fff-$2447,d7
	sub.w d3,d7
	cmp.w -1(a3,d7.w),d2
	bgt.s .bf66
	blt.s .bf61
	cmp.w 1(a3,d7.w),d0
	bcc.s .bf66
.bf61:
	move.w 1(a3,d7.w),d0
	move.w -1(a3,d7.w),d2
.bf66:
	addq.w #8,d3
	subq.w #1,d1
	bne.s .bf56
	tst.w d2
	bmi.w edge_bf04
	bne.s .bf79
	cmp.w ($7ffe-$233c,a3),d0
	ble.s .bf7c
.bf79:
	move.w ($7ffe-$233c,a3),d0
.bf7c:
	move.w d0,($7ffe-$2433,a3)
	tst.w ($7ffe-$244b,a3)
	bne.w edge_bf04
	move.w ($7ffe-$2449,a3),d0
	move.w d0,($7ffe-$23ff,a3)
	cmp.w ($7ffe-$2338,a3),d0
	bge.w edge_bf04
	moveq #RZ_BF94,d7
	rts

; Span records after CD00 returns ES:DI: eight STOSW (DF = 0, no wrap: the
; entry guard), ID \1, Y \2.
EDGE_RECORD macro
	move.w #$7fff,d7
	sub.w a5,d7
	lea 1(a1,d7.w),a0
	clr.w -(a0)
	move.w ($7ffe-$252f,a3),-(a0)
	move.b ($7fff-$23d9,a3),-(a0)	; AL (low byte, higher address)
	move.b #\1,-(a0)		; AH
	move.w ($7ffe-\2,a3),-(a0)
	moveq #0,d0
	move.l d0,-(a0)
	move.w d0,-(a0)
	move.w ($7ffe-$23ff,a3),d0
	move.w d0,-(a0)
	adda.w #16,a5
	endm

edge_bf97:
	EDGE_RECORD $81,$2413
	moveq #RZ_BFB1,d7
	rts
edge_bfb4:
	EDGE_RECORD $82,$2433
	bra.w edge_bf04
