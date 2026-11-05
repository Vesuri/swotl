; RTSEGA's view converters as device rows (docs/ecs-plan.md E6, D5: user
; 2026-11-04; docs/native-compute.md "Device rows"). 4AC3 (ega_convert_all)
; turns the game's packed 4-bit view (two pixels per byte, `words` words per
; row) into the draw page's planes; 4BD0 (ega_convert_changed) only the words
; that differ from the previous view (repe cmpsw against the shadow buffer).
; Per destination byte the original sets the bit mask from the mask table
; (CS:13C0, one byte per two words), then per plane p the map mask and
; `xchg es:[di]` of T0_p[b0 + par] | T1_p[b1 + par] (b0, b1 the word's bytes,
; par CS:34E8/34EA by row parity) in write mode 0. The EGA model's effect
; (src/runtime/ega.c): plane p = (v & mask) | (old & ~mask), the latches of
; the last xchg read, the D9 mark of the byte, and the guest RAM byte the
; instruction stored (the bounce: v of plane 3). Oracle: tests/test_ega_convert.py
; (original x86 with tools/ega_model.py).
;
; Admission (decline unchanged otherwise): a driver call in progress, the
; planes allocated, data rotate and enable set/reset 0 (as the mode set
; leaves them), rows >= 1, 1 <= words <= 80, every loaded segment at or above
; smc_seg_limit (no cell-cache exposure), no 16-bit offset wrap (stack,
; buffers, destination), the destination inside A0000h-AFFFFh, the mask
; table below the CS variables, par <= BD00h, and no read range (buffers,
; DS variables, CS tables, 4BD0's stack arguments) meeting a written range
; (stack slots, CS variables, EGA memory).

	xref rt_ega_planes
	xref rt_ega_regs
	xref rt_vram_rows
	xref rt_vram_top
	xref rt_vram_bottom
	xref rt_vdrv_depth
	xref smc_seg_limit

EGA_SEQ_INDEX	equ 0		; struct rt_ega_regs (runtime.h)
EGA_MAP_MASK	equ 1
EGA_GC_INDEX	equ 2
EGA_ENABLE_SR	equ 4
EGA_ROTATE	equ 6
EGA_MODE	equ 8
EGA_BIT_MASK	equ 11
EGA_LATCH	equ 12

L_CMP	equ 0		; 1: 4BD0
L_ROWS	equ 2
L_WORDS	equ 4
L_HALF	equ 6		; words >> 1
L_DEST	equ 8
L_PAGE	equ 10
L_SRCSEG equ 12
L_SRCOFF equ 14
L_SHSEG	equ 16
L_SHOFF	equ 18
L_PARA	equ 20		; CS:34E8 (row parity 0)
L_PARB	equ 22		; CS:34EA (parity 1)
L_CSL	equ 24		; CS linear
L_SSP	equ 28		; SS:SP linear at entry
L_Y	equ 32		; the row's first byte: page 0 row, column
L_X	equ 34
L_R	equ 36		; rows left (parity = L_R & 1)
L_BX	equ 38
L_ANY	equ 40		; 4BD0: a word differed
L_BM	equ 42		; last bit mask (byte)
L_OLD3	equ 44		; last plane-3 byte before its write (latch 3)
L_LAST	equ 46		; last byte's plane-0 address (long)
L_A1	equ 50		; shadow pointer after the last differing word (long)
L_DSL	equ 54
L_BYTES	equ 58		; rows * words * 2 (long)
L_IV	equ 62		; intervals [lo, hi) linear, 8 bytes each
IV_WIN	equ 0
IV_STK	equ 1
IV_CSV	equ 2
IV_CST	equ 3
IV_SRC	equ 4
IV_SH	equ 5
IV_DSV	equ 6
IV_ARG	equ 7
L_SIZE	equ L_IV+8*8
S_D0	equ L_SIZE		; movem.l d0-d5/a0-a5 above the locals
S_D1	equ L_SIZE+4
S_D2	equ L_SIZE+8
S_D3	equ L_SIZE+12
S_D4	equ L_SIZE+16
S_D5	equ L_SIZE+20
S_A1	equ L_SIZE+28
S_A2	equ L_SIZE+32
S_A4	equ L_SIZE+40
S_A5	equ L_SIZE+44

; One destination byte: d1 = the source word (b1:b0), d0 = k, d2.l = par,
; a2 = CS (byte o at -o), a3 = the row's plane-0 byte, a4 = the row's bounce
; byte (k at -k), a5 = the row's mask byte (k at -(k >> 1)).
EGA_BYTE macro
	moveq #0,d4
	move.b d1,d4
	add.l d2,d4
	move.w d4,L_BX(a7)	; bx = b0 + par
	neg.l d4
	moveq #0,d5
	move.w d1,d5
	lsr.w #8,d5
	add.l d2,d5
	neg.l d5		; -(b1 + par)
	move.w d0,d7
	lsr.w #1,d7
	neg.w d7
	moveq #0,d3
	move.b (a5,d7.w),d3	; mask table byte m
	add.w d3,d3
	neg.w d3
	btst #0,d0
	bne.s .odd\@
	subq.w #1,d3		; even k: the high byte of CS:32E6[m]
.odd\@:
	move.b (-$32e6,a2,d3.w),d3	; bit mask
	move.b d3,L_BM(a7)
	move.w d0,d1
	neg.w d1
	move.b (-$34ec,a2,d4.l),d6
	or.b (-$35ec,a2,d5.l),d6
	move.b (0,a3,d0.w),d7
	eor.b d7,d6
	and.b d3,d6
	eor.b d6,d7
	move.b d7,(0,a3,d0.w)
	move.b (-$38ec,a2,d4.l),d6
	or.b (-$39ec,a2,d5.l),d6
	move.b ($10000,a3,d0.w),d7
	eor.b d7,d6
	and.b d3,d6
	eor.b d6,d7
	move.b d7,($10000,a3,d0.w)
	move.b (-$3cec,a2,d4.l),d6
	or.b (-$3dec,a2,d5.l),d6
	move.b ($20000,a3,d0.w),d7
	eor.b d7,d6
	and.b d3,d6
	eor.b d6,d7
	move.b d7,($20000,a3,d0.w)
	move.b (-$40ec,a2,d4.l),d6
	or.b (-$41ec,a2,d5.l),d6
	move.b d6,(a4,d1.w)	; the stored byte at ES:DI
	move.b ($30000,a3,d0.w),d7
	move.b d7,L_OLD3(a7)
	eor.b d7,d6
	and.b d3,d6
	eor.b d6,d7
	move.b d7,($30000,a3,d0.w)
	move.l a3,d7
	add.l d0,d7
	move.l d7,L_LAST(a7)
	move.w L_X(a7),d6	; D9 mark (ega.c mark): page 0 only
	add.w d0,d6
	move.w L_Y(a7),d7
	cmp.w #80,d6
	bcs.s .col\@
	sub.w #80,d6
	addq.w #1,d7
.col\@:
	cmp.w #200,d7
	bcc.s .done\@
	tst.w (rt_vram_rows+2,d7.w*4)
	bne.s .grow\@
	move.w d6,(rt_vram_rows,d7.w*4)
	addq.w #1,d6
	move.w d6,(rt_vram_rows+2,d7.w*4)
	bra.s .rows\@
.grow\@:
	cmp.w (rt_vram_rows,d7.w*4),d6
	bcc.s .lo\@
	move.w d6,(rt_vram_rows,d7.w*4)
.lo\@:
	addq.w #1,d6
	cmp.w (rt_vram_rows+2,d7.w*4),d6
	bls.s .rows\@
	move.w d6,(rt_vram_rows+2,d7.w*4)
.rows\@:
	cmp.w rt_vram_top,d7
	bcc.s .top\@
	move.w d7,rt_vram_top
.top\@:
	addq.w #1,d7
	cmp.w rt_vram_bottom,d7
	bls.s .done\@
	move.w d7,rt_vram_bottom
.done\@:
	endm

	xdef rt_hle_ega_convert_all
rt_hle_ega_convert_all:
	moveq #0,d7
	bra.s ega_convert
	xdef rt_hle_ega_convert_changed
rt_hle_ega_convert_changed:
	moveq #1,d7
ega_convert:
	movem.l d0-d5/a0-a5,-(a7)
	lea -L_SIZE(a7),a7
	move.w d7,L_CMP(a7)
	tst.w rt_vdrv_depth
	beq .decline
	tst.l rt_ega_planes
	beq .decline
	tst.b rt_ega_regs+EGA_ROTATE
	bne .decline
	tst.b rt_ega_regs+EGA_ENABLE_SR
	bne .decline
	lsl.l #4,d6
	move.l d6,L_CSL(a7)
	moveq #0,d7
	move.w G_DS(a6),d7
	cmp.w smc_seg_limit,d7
	bcs .decline
	lsl.l #4,d7
	move.l d7,L_DSL(a7)
	moveq #0,d7
	move.w d4,d7
	eori.w #$7fff,d7	; SP
	cmp.w #12,d7
	bcs .decline
	cmp.w #$fff4,d7
	bhi .decline
	moveq #0,d6
	move.w G_SS(a6),d6
	lsl.l #4,d6
	add.l d7,d6
	move.l d6,L_SSP(a7)
	move.w ($7ffe-$2591,a3),d0	; rows
	beq .decline
	move.w ($7ffe-$258b,a3),d1	; words
	beq .decline
	cmp.w #80,d1
	bhi .decline
	move.w d0,L_ROWS(a7)
	move.w d1,L_WORDS(a7)
	lsr.w #1,d1
	move.w d1,L_HALF(a7)
	move.w ($7ffe-$257f,a3),L_DEST(a7)
	move.w ($7ffe-$287c,a3),d7	; draw page
	cmp.w smc_seg_limit,d7
	bcs .decline
	move.w d7,L_PAGE(a7)
	tst.w L_CMP(a7)
	bne.s .args
	move.w ($7ffe-$2579,a3),L_SRCSEG(a7)
	move.w ($7ffe-$257b,a3),L_SRCOFF(a7)
	clr.w L_SHSEG(a7)
	clr.w L_SHOFF(a7)
	bra.s .src
.args:	; 4BD0: lds si, [bp+6]; les di, [bp+0Ah] (bp = SP - 2)
	move.w d4,d7
	subq.w #4,d7
	move.w -1(a2,d7.w),L_SRCOFF(a7)
	subq.w #2,d7
	move.w -1(a2,d7.w),L_SRCSEG(a7)
	subq.w #2,d7
	move.w -1(a2,d7.w),L_SHOFF(a7)
	subq.w #2,d7
	move.w -1(a2,d7.w),d6
	cmp.w smc_seg_limit,d6
	bcs .decline
	move.w d6,L_SHSEG(a7)
.src:
	move.w L_SRCSEG(a7),d7
	cmp.w smc_seg_limit,d7
	bcs .decline
	move.w L_ROWS(a7),d0
	mulu.w L_WORDS(a7),d0
	add.l d0,d0
	move.l d0,L_BYTES(a7)
	moveq #0,d1
	move.w L_SRCOFF(a7),d1
	add.l d0,d1
	cmp.l #$10000,d1
	bhi .decline
	moveq #0,d1
	move.w L_SHOFF(a7),d1
	add.l d0,d1
	cmp.l #$10000,d1
	bhi .decline
	move.w L_ROWS(a7),d1
	mulu.w L_HALF(a7),d1
	cmp.l #$32c4-$13c0,d1
	bhi .decline
	move.w L_ROWS(a7),d1	; the last destination byte
	subq.w #1,d1
	mulu.w #80,d1
	moveq #0,d2
	move.w L_DEST(a7),d2
	add.l d2,d1
	moveq #0,d3
	move.w L_WORDS(a7),d3
	add.l d3,d1
	subq.l #1,d1
	cmp.l #$ffff,d1
	bhi .decline
	moveq #0,d3
	move.w L_PAGE(a7),d3
	lsl.l #4,d3
	add.l d3,d1
	cmp.l #$affff,d1
	bhi .decline
	add.l d3,d2
	cmp.l #$a0000,d2
	bcs .decline
	move.l a6,a0
	suba.l L_CSL(a7),a0
	move.w (-$34e8-1,a0),d1
	move.w (-$34ea-1,a0),d2
	cmp.w #$bd00,d1
	bhi .decline
	cmp.w #$bd00,d2
	bhi .decline
	move.w d1,L_PARA(a7)
	move.w d2,L_PARB(a7)
	cmp.w d1,d2
	bcc.s .parmax
	move.w d1,d2
.parmax:
	and.l #$ffff,d2
	lea L_IV(a7),a0
	move.l #$a0000,(a0)+		; IV_WIN
	move.l #$b0000,(a0)+
	move.l L_SSP(a7),d7		; IV_STK
	moveq #-12,d6
	add.l d7,d6
	move.l d6,(a0)+
	move.l d7,(a0)+
	move.l L_CSL(a7),d7		; IV_CSV
	move.l d7,d6
	add.l #$32c4,d6
	move.l d6,(a0)+
	move.l d7,d6
	add.l #$34e8,d6
	move.l d6,(a0)+
	move.l d7,d6			; IV_CST
	add.l #$13c0,d6
	move.l d6,(a0)+
	add.l #$42ec,d7
	add.l d2,d7
	move.l d7,(a0)+
	moveq #0,d7			; IV_SRC
	move.w L_SRCSEG(a7),d7
	lsl.l #4,d7
	moveq #0,d6
	move.w L_SRCOFF(a7),d6
	add.l d6,d7
	move.l d7,(a0)+
	add.l L_BYTES(a7),d7
	move.l d7,(a0)+
	moveq #0,d7			; IV_SH (empty for 4AC3)
	moveq #0,d6
	tst.w L_CMP(a7)
	beq.s .sh
	move.w L_SHSEG(a7),d7
	lsl.l #4,d7
	move.w L_SHOFF(a7),d6
	add.l d6,d7
	move.l d7,d6
	add.l L_BYTES(a7),d6
.sh:
	move.l d7,(a0)+
	move.l d6,(a0)+
	move.l L_DSL(a7),d7		; IV_DSV
	move.l d7,d6
	add.l #$2579,d6
	move.l d6,(a0)+
	add.l #$287e,d7
	move.l d7,(a0)+
	moveq #0,d7			; IV_ARG (4BD0)
	moveq #0,d6
	tst.w L_CMP(a7)
	beq.s .arg
	move.l L_SSP(a7),d7
	addq.l #4,d7
	moveq #8,d6
	add.l d7,d6
.arg:
	move.l d7,(a0)+
	move.l d6,(a0)+
	lea ega_pairs(pc),a0
	moveq #EGA_PAIRS-1,d7
.pair:
	moveq #0,d0
	move.b (a0)+,d0
	lea (L_IV,a7,d0.w*8),a1
	move.b (a0)+,d0
	lea (L_IV,a7,d0.w*8),a4
	move.l (a1),d1
	cmp.l 4(a4),d1
	bcc.s .apart
	move.l (a4),d1
	cmp.l 4(a1),d1
	bcs .decline
.apart:
	dbra d7,.pair

	; admitted: from here on the guest state changes
	move.l a6,a2			; CS: byte o at -o(a2)
	suba.l L_CSL(a7),a2
	move.l IV_SRC*8+L_IV(a7),d7
	move.l a6,a0
	suba.l d7,a0
	addq.l #1,a0			; -(a0).w: the next source word
	move.l IV_SH*8+L_IV(a7),d7
	move.l a6,a1
	suba.l d7,a1
	addq.l #1,a1
	moveq #0,d7
	move.w L_PAGE(a7),d7
	lsl.l #4,d7
	moveq #0,d6
	move.w L_DEST(a7),d6
	add.l d6,d7
	move.l a6,a4
	suba.l d7,a4
	sub.l #$a0000,d7
	move.l rt_ega_planes,a3
	adda.l d7,a3
	divu.w #80,d7
	move.w d7,L_Y(a7)
	swap d7
	move.w d7,L_X(a7)
	lea (-$13c0,a2),a5
	move.w L_ROWS(a7),L_R(a7)
	clr.w L_ANY(a7)
	moveq #0,d2
.row:
	move.w L_PARA(a7),d2
	btst #0,L_R+1(a7)
	beq.s .par
	move.w L_PARB(a7),d2
.par:
	move.w d2,L_BX(a7)
	moveq #0,d0
	tst.w L_CMP(a7)
	bne .cword
.aword:
	move.w -(a0),d1
	EGA_BYTE
	addq.w #1,d0
	cmp.w L_WORDS(a7),d0
	bcs .aword
	bra .rowend
.cword:
	move.w -(a0),d1
	cmp.w -(a1),d1
	bne .diff
.cnext:
	addq.w #1,d0
	cmp.w L_WORDS(a7),d0
	bcs.s .cword
	bra .rowend
.diff:
	move.l a1,L_A1(a7)
	st L_ANY(a7)
	EGA_BYTE
	bra .cnext
.rowend:
	adda.w #80,a3
	suba.w #80,a4
	move.w L_HALF(a7),d7
	suba.w d7,a5
	addq.w #1,L_Y(a7)
	subq.w #1,L_R(a7)
	bne .row

	; the CS variables as the original leaves them (word o at -o-1(a2))
	clr.w (-$32c6-1,a2)
	move.w L_WORDS(a7),(-$32c4-1,a2)
	move.w L_ROWS(a7),d7
	mulu.w #80,d7
	add.w L_DEST(a7),d7
	move.w d7,(-$32c8-1,a2)
	move.w L_ROWS(a7),d7
	mulu.w L_HALF(a7),d7
	add.w #$13c0,d7
	move.w d7,(-$32ca-1,a2)
	move.w L_PARB(a7),(-$34e6-1,a2)	; the last row's parity is 1
	tst.w L_CMP(a7)
	bne.s .cvars
	clr.w (-$32d4-1,a2)
	bra.s .stack
.cvars:
	move.w L_HALF(a7),(-$32e3-1,a2)
	move.w L_PAGE(a7),(-$32e1-1,a2)
.stack:	; push bp, ds, si, di (and 4BD0's push di, es of its last difference)
	move.l S_A2(a7),a0
	move.w S_D4+2(a7),d6
	addq.w #2,d6
	move.w S_D5+2(a7),d7
	eori.w #$7fff,d7
	move.w d7,-1(a0,d6.w)
	addq.w #2,d6
	move.w G_DS(a6),-1(a0,d6.w)
	addq.w #2,d6
	move.w S_A4+2(a7),-1(a0,d6.w)
	addq.w #2,d6
	move.w S_A5+2(a7),-1(a0,d6.w)
	lea rt_ega_regs,a1
	move.b #2,EGA_SEQ_INDEX(a1)
	move.b #$0f,EGA_MAP_MASK(a1)
	move.b #5,EGA_GC_INDEX(a1)
	move.b #2,EGA_MODE(a1)
	tst.w L_CMP(a7)
	beq.s .latch
	tst.w L_ANY(a7)
	beq.s .regs
	addq.w #2,d6
	move.l a6,d7			; di after the word: TOP + 1 - a1 - ES * 16
	addq.l #1,d7
	sub.l L_A1(a7),d7
	sub.l IV_SH*8+L_IV(a7),d7
	add.w L_SHOFF(a7),d7
	move.w d7,-1(a0,d6.w)
	addq.w #2,d6
	move.w L_SHSEG(a7),-1(a0,d6.w)
.latch:
	move.b L_BM(a7),EGA_BIT_MASK(a1)
	move.l L_LAST(a7),a0
	move.b (a0),EGA_LATCH(a1)
	move.b ($10000,a0),EGA_LATCH+1(a1)
	move.b ($20000,a0),EGA_LATCH+2(a1)
	move.b L_OLD3(a7),EGA_LATCH+3(a1)
.regs:
	move.w L_BX(a7),S_D3+2(a7)
	; CF and ZF are live at the RETF: ZF of the last row's dec (0), CF of the
	; add before it (4AC3: [32C8] += 50h; 4BD0: [32CA] += words >> 1, no
	; carry under the mask table bound)
	moveq #4,d6
	tst.w L_CMP(a7)
	bne.s .flags
	move.w L_ROWS(a7),d7
	mulu.w #80,d7
	moveq #0,d5
	move.w L_DEST(a7),d5
	add.l d5,d7
	cmp.l #$ffff,d7
	bls.s .flags
	moveq #5,d6
.flags:
	move.w d6,G_FL(a6)
	moveq #0,d7
	tst.w L_CMP(a7)
	bne.s .cregs
	move.w #$0f02,S_D0+2(a7)	; AX
	move.w L_WORDS(a7),d6
	and.w #1,d6
	move.w d6,S_D1+2(a7)		; CX: the word parity
	move.w #$03cf,S_D2+2(a7)	; DX
	move.w L_PAGE(a7),d7		; ES: the draw page
	bra.s .es
.cregs:
	move.w #$0205,S_D0+2(a7)
	clr.w S_D1+2(a7)
	move.w #$03ce,S_D2+2(a7)
	clr.b G_DF(a6)			; cld
	move.w L_SHSEG(a7),d7		; ES: the shadow buffer
.es:
	move.w d7,G_ES(a6)
	lsl.l #4,d7
	move.l a6,d6
	sub.l #$7fff,d6
	sub.l d7,d6
	move.l d6,S_A1(a7)
	lea L_SIZE(a7),a7
	movem.l (a7)+,d0-d5/a0-a5
	moveq #1,d7
	rts
.decline:
	lea L_SIZE(a7),a7
	movem.l (a7)+,d0-d5/a0-a5
	moveq #0,d7
	rts

ega_pairs:	; (read, written) interval pairs that must not meet
	dc.b IV_SRC,IV_WIN, IV_SRC,IV_STK, IV_SRC,IV_CSV
	dc.b IV_SH,IV_WIN, IV_SH,IV_STK, IV_SH,IV_CSV
	dc.b IV_DSV,IV_WIN, IV_DSV,IV_STK, IV_DSV,IV_CSV
	dc.b IV_ARG,IV_WIN, IV_ARG,IV_CSV
	dc.b IV_CST,IV_WIN, IV_CST,IV_STK
	dc.b IV_STK,IV_WIN
EGA_PAIRS equ (*-ega_pairs)/2
	even
