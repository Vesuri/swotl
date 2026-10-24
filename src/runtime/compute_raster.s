; Scanline rasterizer BFD1 from C000: add, order and merge, visibility and
; priority, expire, advance. U6 authorized 2026-10-22; F5 whole scope, user
; 2026-10-24 (range end with continuation exits). Original SWOTL x86 is the
; oracle. Every original poll is visited at its address (exact polls); the
; guest calls (span output CEB3/CD99/CE3C, slope C8E0) and the epilogue stay
; generated as continuation exits. Writes keep each byte's history; reads
; keep their order against writes; no guest value is cached across a poll.
; A record index (7FFFh - offset) is taken only after its poll proved the
; record does not wrap (offset <= FFF0h); otherwise resume at that poll,
; whose re-entry declines to the generated segment.

; Resume ids: exits ascending, then the polls (compute.polled_hook).
RZ_C02C	equ 1
RZ_C03A	equ 2
RZ_C040	equ 3
RZ_C043	equ 4
RZ_C2A5	equ 5
RZ_C2B3	equ 6
RZ_C2BD	equ 7
RZ_C3EB	equ 8
RZ_C0D1	equ 12
RZ_C1E2	equ 15
RZ_C3DF	equ 21

; DS words at X are ($7FFE-X,a3), bytes ($7FFF-X,a3).
DS_23FF	equ $5bff
DS_2537	equ $5ac7
DS_2531	equ $5acd
DS_2533	equ $5acb
DS_25A1	equ $5a5e
DS_2581	equ $5a7d
DS_233E	equ $5cc0
DS_252D	equ $5ad1
DS_2535	equ $5ac9
DS_253B	equ $5ac4
DS_253A	equ $5ac5
DS_233C	equ $5cc2
ES_4060	equ $3f9e		; ES word 4060h, ($7FFE-X,a1)

; A record pointer is peeked before its poll's segment commits anything.
RASTER_PEEK_C0D1 macro	; SI = ES:[BX], DI = ES:[BX+2] into d6, d7
	move.w #$7fff,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d6
	cmp.w #$fff0,d6
	bhi.w \1
	subq.w #2,d7
	move.w -1(a1,d7.w),d7
	cmp.w #$fff0,d7
	bhi.w \1
	endm
RASTER_PEEK_C1E2 macro	; DI = ES:[SI] into d6
	move.w #$7fff,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d6
	cmp.w #$fff0,d6
	bhi.w \1
	endm
RASTER_PEEK_C3DF macro	; DI = ES:[SI+2] into d6
	move.w #$7ffd,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d6
	cmp.w #$fff0,d6
	bhi.w \1
	endm

	xdef rt_hle_rasterize
rt_hle_rasterize:
	movea.l d7,a0
	tst.b G_DF(a6)
	bne.s raster_decline
	add.l #$1000,d6
	moveq #0,d7
	move.w G_DS(a6),d7
	cmp.w #$9000,d7
	bhi.s raster_decline
	cmp.l d6,d7
	bcs.s raster_decline
	move.w G_ES(a6),d7
	cmp.w #$9000,d7
	bhi.s raster_decline
	cmp.l d6,d7
	bcs.s raster_decline
	move.w G_SS(a6),d7
	cmp.w #$9000,d7
	bhi.s raster_decline
	cmp.l d6,d7
	bcs.s raster_decline
	; The add stage's POP DS rereads its stack slot after REP MOVSW.
	move.w G_ES(a6),d7
	sub.w G_SS(a6),d7
	bpl.s .apart
	neg.w d7
.apart:
	cmp.w #$1000,d7
	bcs.s raster_decline
	move.l a0,d7
	cmp.l #12,d7
	bhi.s raster_decline
	add.w d7,d7
	move.w .entry(pc,d7.w),d7
	jmp .entry(pc,d7.w)
.entry:
	dc.w raster_c000_entry-.entry,raster_c085_entry-.entry,raster_c0c5_entry-.entry
	dc.w raster_c0d1_entry-.entry,raster_c11a_entry-.entry,raster_c129_entry-.entry
	dc.w raster_c1e2_entry-.entry,raster_c27c_entry-.entry,raster_c2f2_entry-.entry
	dc.w raster_c306_entry-.entry,raster_c32d_entry-.entry,raster_c3a4_entry-.entry
	dc.w raster_c3df_entry-.entry

raster_decline:
	moveq #0,d7
	rts

raster_c0d1_entry:
	RASTER_PEEK_C0D1 raster_decline
	bra.w raster_c0d1_take
raster_c1e2_entry:
	RASTER_PEEK_C1E2 raster_decline
	bra.w raster_c1e2_take
raster_c3df_entry:
	RASTER_PEEK_C3DF raster_decline
	bra.w raster_c3df_take
raster_c2f2_entry:
	move.w #$7fff,d7
	sub.w d3,d7
	subq.w #2,d3
	bra.w raster_c2f2_1
raster_c32d_entry:
	move.w #$7fff,d7
	sub.w d3,d7
	subq.w #2,d3
	bra.w raster_c32d_1
; Entries start below each execution alias (*_native_np): the generated
; hook already executed the poll point, so the host counts it once.
raster_c000_entry:
	move.w (DS_23FF,a3),d0
	bra.w raster_c000_1
raster_c085_entry:
	move.w #$7fff,d7
	bra.w raster_c085_1
raster_c0c5_entry:
	moveq #0,d2
	bra.w raster_c0c5_1
raster_c11a_entry:
	move.w #$7fff,d7
	bra.w raster_c11a_1
raster_c129_entry:
	subq.w #1,d1
	bra.w raster_c129_1
raster_c27c_entry:
	cmp.b d1,d0
	bra.w raster_c27c_1
raster_c306_entry:
	bra.w raster_c372
raster_c3a4_entry:
	move.w #$7fff,d7
	bra.w raster_c3a4_1

; ---- scanline head, exits ----------------------------------------------

raster_c000_poll:
	rt_hle_rasterize_poll_0
raster_c000:
	move.w (DS_23FF,a3),d0
raster_c000_1:
	bne.s raster_c04b
	subq.w #1,(DS_23FF,a3)
	moveq #0,d0
	move.w d0,(DS_2537,a3)
	tst.w (DS_2531,a3)
	bne.s .c020
	move.w (DS_2533,a3),d0
	cmp.w (DS_23FF,a3),d0
	bne.s .c020
	moveq #RZ_C043,d7
	rts
.c020:
	move.b (DS_25A1,a3),d1
	tst.w (DS_2581,a3)
	bne.s .c032
	moveq #RZ_C02C,d7
	rts
.c032:
	tst.w (DS_233E,a3)
	beq.s .c040
	moveq #RZ_C03A,d7
	rts
.c040:
	moveq #RZ_C040,d7
	rts

; ---- add: bucket list onto the active list -----------------------------

; REP MOVSW with DS = ES (DF = 0 by the entry guard): ES:SI -> ES:DI.
RASTER_MOVSW macro
	addq.w #2,d4
	move.w G_DS(a6),-1(a2,d4.w)
	addq.w #2,d4
	move.w G_ES(a6),-1(a2,d4.w)
	subq.w #2,d4
	bra.s .t\@
.l\@:
	move.w #$7fff,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d6
	move.w #$7fff,d7
	sub.w a5,d7
	move.w d6,-1(a1,d7.w)
	addq.w #2,a4
	addq.w #2,a5
	subq.w #1,d1
.t\@:
	tst.w d1
	bne.s .l\@
	subq.w #2,d4
	endm

raster_c04b:
	subq.w #1,d0
	move.w d0,(DS_23FF,a3)
	lsl.w #4,d0
	add.w #$1f40,d0
	movea.w d0,a4
	move.w #$7fff,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	addq.w #2,a4
	tst.w d0
	beq.w raster_c0ab
	move.w d0,d2
	move.w d0,d1
	movea.w #$4060,a5
	move.w ES_4060(a1),d0
	move.w d0,d3
	add.w d1,d0
	move.w d0,ES_4060(a1)
	addq.w #2,a5
	add.w d3,d3
	adda.w d3,a5
	move.w d0,d3
	RASTER_MOVSW
	cmp.w #6,d2
	bne.s raster_c0ab
raster_c085_poll:
	rt_hle_rasterize_poll_1
raster_c085:
	move.w #$7fff,d7
raster_c085_1:
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	movea.w d0,a4
	move.w #$7fff,d7
	sub.w a4,d7
	move.w -1(a1,d7.w),d0
	addq.w #2,a4
	tst.w d0
	beq.s .c0a5
	move.w d0,d2
	move.w d0,d1
	add.w d0,d3
	RASTER_MOVSW
	cmp.w #$1e,d2
	beq.s raster_c085_poll
.c0a5:
	movea.w #$4060,a5
	move.w d3,ES_4060(a1)
raster_c0ab:
	movea.w #$4062,a4
	move.w ES_4060(a1),d0
	bne.s .c0ba
	bra.w raster_c000_poll
.c0ba:
	cmp.w #1,d0
	beq.w raster_c1c2

; ---- order and merge (R48 scope) ---------------------------------------

	move.w d0,(DS_252D,a3)
raster_c0c5_poll:
	rt_hle_rasterize_poll_2
raster_c0c5:
	moveq #0,d2
raster_c0c5_1:
	move.w (DS_252D,a3),d1
	subq.w #1,d1
	move.w #$4062,d3
raster_c0d1_poll:
	rt_hle_rasterize_poll_3
raster_c0d1:
	RASTER_PEEK_C0D1 raster_c0d1_bail
raster_c0d1_take:
	movea.w d6,a4
	movea.w d7,a5
	addq.w #2,d3
	move.w #$7fff,d7
	sub.w a4,d7
	lea 0(a1,d7.w),a0	; SI record: byte k at -k(a0)
	move.w #$7fff,d6
	sub.w a5,d6		; DI record: byte k at -k(a1,d6.w)
	move.w -7(a0),d0
	cmp.w -7(a1,d6.w),d0
	blt.s raster_c129_poll
	bne.s raster_c11a_poll
	move.b -5(a1,d6.w),d0
	lsl.w #8,d0
	move.b -5(a0),d0
	tst.b d0
	bmi.s raster_c132
	tst.w d0
	bmi.s raster_c132
	move.w d0,d7
	lsr.w #8,d7
	and.b d0,d7
	and.b #3,d7
	bne.s raster_c132
	move.w -9(a0),d0
	cmp.w -9(a1,d6.w),d0
	bne.s raster_c132
	move.w -1(a0),d0
	cmp.w -1(a1,d6.w),d0
	bne.s raster_c132
	move.w -3(a0),d0
	cmp.w -3(a1,d6.w),d0
	beq.w raster_c18a
	bra.s raster_c129_poll
raster_c11a_poll:
	rt_hle_rasterize_poll_4_local raster_c11a_pending
raster_c11a:
	move.w #$7fff,d7
raster_c11a_1:
	sub.w d3,d7
	movea.w -1(a1,d7.w),a4
	move.w d7,d6
	addq.w #2,d6		; BX - 2
	movea.w -1(a1,d6.w),a5
	move.w a5,-1(a1,d7.w)
	move.w a4,-1(a1,d6.w)
	addq.w #1,d2
raster_c129_poll:
	rt_hle_rasterize_poll_5_local raster_c129_pending
raster_c129:
	subq.w #1,d1
raster_c129_1:
	bne.w raster_c0d1_poll
	tst.w d2
	bne.w raster_c0c5_poll
	bra.w raster_c1c2
raster_c11a_pending:
	rt_hle_rasterize_poll_4_tail
raster_c129_pending:
	rt_hle_rasterize_poll_5_tail
raster_c0d1_bail:
	moveq #RZ_C0D1,d7
	rts
raster_c132:
	move.w -3(a0),d0
	cmp.w -3(a1,d6.w),d0
	blt.s raster_c129_poll
	bne.s raster_c11a_poll
	move.b -5(a1,d6.w),d0
	lsl.w #8,d0
	move.b -5(a0),d0
	move.w d0,d7
	lsr.w #8,d7
	and.b d7,d0
	and.b #3,d0
	beq.s .c177
	move.b -5(a0),d0
	tst.w -1(a0)
	bne.s .c164
	btst #14,d0
	bne.s .c164
	clr.b d0
	move.b d0,-5(a0)
	bra.s raster_c129_poll
.c164:
	tst.w -1(a1,d6.w)
	bne.s .c177
	btst #6,d0
	bne.s .c177
	clr.b d0
	move.b d0,-5(a1,d6.w)
	bra.s raster_c129_poll
.c177:
	move.b -5(a1,d6.w),d0
	andi.w #3,d0
	lsl.w #8,d0
	move.b -5(a0),d7
	andi.b #3,d7
	move.b d7,d0
	move.w d0,d7
	lsr.w #8,d7
	cmp.b d7,d0
	bls.w raster_c129_poll
	bra.w raster_c11a_poll
raster_c18a:
	move.b -4(a0),d0
	cmp.b -4(a1,d6.w),d0
	beq.s .c1af
	move.b -5(a0),d0
	btst #1,d0
	bne.s .c19e
	exg a4,a5
	move.w #$7fff,d7
	sub.w a4,d7
	lea 0(a1,d7.w),a0
	move.w #$7fff,d6
	sub.w a5,d6
.c19e:
	or.b #1,-5(a0)
	moveq #0,d0
	move.b d0,-5(a1,d6.w)
	move.w d0,-1(a1,d6.w)
	bra.w raster_c129_poll
.c1af:
	moveq #0,d0
	move.b d0,-5(a1,d6.w)
	move.w d0,-1(a1,d6.w)
	move.b d0,-5(a0)
	move.w d0,-1(a0)
	bra.w raster_c129_poll

; ---- visibility: priority table ES:41F0, 255 words ---------------------

raster_c1c2:
	lea $3e10(a1),a0	; past ES byte 41F0h; the clear runs down to 43EDh
	moveq #0,d6
	moveq #14,d7
.clear:
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	dbf d7,.clear
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.l d6,-(a0)
	move.w d6,-(a0)
	movea.w #$43ee,a5
	move.w ES_4060(a1),d0
	move.w d0,(DS_252D,a3)
	movea.w #$4062,a4
	moveq #0,d1
	move.b (DS_25A1,a3),d1
	move.b #1,(DS_253B,a3)
raster_c1e2_poll:
	rt_hle_rasterize_poll_6
raster_c1e2:
	RASTER_PEEK_C1E2 raster_c1e2_bail
raster_c1e2_take:
	movea.w d6,a5
	move.w #$7fff,d6
	sub.w a5,d6		; DI record: byte k at -k(a1,d6.w)
	move.w -7(a1,d6.w),d2
	cmp.w (DS_233C,a3),d2
	bge.w raster_c372
	move.b -5(a1,d6.w),d7
	andi.w #3,d7
	move.w d7,d0
	lsl.w #8,d0
	move.b -2(a1,d6.w),d0
	subq.b #1,d7
	beq.s .c215
	subq.b #1,d7
	beq.w raster_c2d7
	subq.b #1,d7
	beq.w raster_c353
	bra.w raster_c372
.c215:
	move.w d1,d7
	lsr.w #8,d7
	cmp.b d7,d0
	bhi.s .c245
	bne.s .c222
	addq.b #1,(DS_253B,a3)
	bra.s raster_c278
.c222:
	andi.w #$ff,d0
	add.w d0,d0
	move.w d0,d3
	add.w #$41f0,d3
	move.w #$7fff,d7
	sub.w d3,d7
	addq.b #1,0(a1,d7.w)
	beq.w raster_c372
	move.b -4(a1,d6.w),d0
	move.b d0,-1(a1,d7.w)
	cmp.w (DS_2535,a3),d3
	bls.w raster_c372
	move.w d3,(DS_2535,a3)
	bra.w raster_c372
.c245:
	moveq #0,d3
	move.b d0,d3
	add.w d3,d3
	add.w #$41f0,d3
	move.w #$7fff,d7
	sub.w d3,d7
	tst.b 0(a1,d7.w)
	bpl.s .c25b
	addq.b #1,0(a1,d7.w)
	bra.w raster_c372
.c25b:
	move.w d1,d3
	lsr.w #8,d3
	add.w d3,d3
	add.w #$41f0,d3
	move.w d3,(DS_2535,a3)
	ror.w #8,d1
	move.b d0,d1
	ror.w #8,d1
	move.b (DS_253B,a3),d0
	ror.w #8,d0
	move.b d1,d0
	ror.w #8,d0
	move.w #$7fff,d7
	sub.w d3,d7
	move.w d0,-1(a1,d7.w)
	move.b #1,(DS_253B,a3)
raster_c278:
	move.b -4(a1,d6.w),d0
raster_c27c_poll:
	rt_hle_rasterize_poll_7_local raster_c27c_pending
raster_c27c:
	cmp.b d1,d0
raster_c27c_1:
	beq.w raster_c372
	move.b d0,(DS_253A,a3)
	move.w d2,(DS_2537,a3)
	cmp.w (DS_2531,a3),d2
	bne.s .c29d
	move.w (DS_2533,a3),d3
	cmp.w (DS_23FF,a3),d3
	beq.s .c2c0
.c29d:
	tst.w (DS_2581,a3)
	bne.s .c2ab
	moveq #RZ_C2A5,d7
	rts
.c2ab:
	tst.w (DS_233E,a3)
	beq.s .c2bd
	moveq #RZ_C2B3,d7
	rts
.c2bd:
	moveq #RZ_C2BD,d7
	rts
.c2c0:
	move.b (DS_253A,a3),d1
	move.w (DS_2537,a3),d3
	move.w d3,(DS_2531,a3)
	move.w (DS_23FF,a3),d3
	move.w d3,(DS_2533,a3)
	bra.w raster_c372
raster_c27c_pending:
	rt_hle_rasterize_poll_7_tail
raster_c1e2_bail:
	moveq #RZ_C1E2,d7
	rts

; Close: a lower entry ends. Search down for the next live priority.
raster_c2d7:
	move.w d1,d7
	lsr.w #8,d7
	cmp.b d7,d0
	beq.s raster_c309
	andi.w #$ff,d0
	add.w d0,d0
	move.w d0,d3
	add.w #$41f0,d3
	move.w #$7fff,d7
	sub.w d3,d7
	subq.b #1,0(a1,d7.w)
	bne.w raster_c372
	cmp.w (DS_2535,a3),d3
	bne.s raster_c306_poll
raster_c2f2_poll:
	rt_hle_rasterize_poll_8
raster_c2f2:
	subq.w #2,d3
raster_c2f2_1:
	addq.w #2,d7		; 7FFFh - BX, wrapping like BX
	cmp.w #$41f0,d3
	beq.s .c302
	tst.b 0(a1,d7.w)
	beq.s raster_c2f2_poll
	bmi.s raster_c2f2_poll
.c302:
	move.w d3,(DS_2535,a3)
raster_c306_poll:
	rt_hle_rasterize_poll_9_local raster_c306_pending
raster_c306:
	bra.w raster_c372
raster_c309:
	subq.b #1,(DS_253B,a3)
	bne.s raster_c306_poll
	move.w (DS_2535,a3),d3
	cmp.w #$41f0,d3
	beq.s raster_c346
	move.w d3,d0
	sub.w #$41f0,d0
	lsr.w #1,d0
	ror.w #8,d1
	move.b d0,d1
	ror.w #8,d1
	move.w #$7fff,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d0
	move.b d0,(DS_253B,a3)
	clr.w -1(a1,d7.w)
raster_c32d_poll:
	rt_hle_rasterize_poll_10_local raster_c32d_pending
raster_c32d:
	subq.w #2,d3
raster_c32d_1:
	addq.w #2,d7
	cmp.w #$41f0,d3
	beq.s .c33d
	tst.b 0(a1,d7.w)
	beq.s raster_c32d_poll
	bmi.s raster_c32d_poll
.c33d:
	move.w d3,(DS_2535,a3)
	move.w d0,d7
	lsr.w #8,d7
	move.b d7,d0
	bra.w raster_c27c_poll
raster_c346:
	move.b #1,(DS_253B,a3)
	andi.w #$ff,d1
	move.b (DS_25A1,a3),d0
	bra.w raster_c27c_poll
raster_c306_pending:
	rt_hle_rasterize_poll_9_tail
raster_c32d_pending:
	rt_hle_rasterize_poll_10_tail

raster_c353:
	move.w d1,d7
	lsr.w #8,d7
	cmp.b d7,d0
	beq.s .c36b
	andi.w #$ff,d0
	add.w d0,d0
	move.w d0,d3
	add.w #$41f0,d3
	move.b -4(a1,d6.w),d0
	addq.w #1,d3
	move.w #$7fff,d7
	sub.w d3,d7
	move.b d0,0(a1,d7.w)
	bra.s raster_c372
.c36b:
	move.b -4(a1,d6.w),d0
	bra.w raster_c27c_poll

raster_c372:
	addq.w #2,a4
	subq.w #1,(DS_252D,a3)
	beq.s .c383
	bmi.s .c37f
	bra.w raster_c1e2_poll
.c37f:
	addq.w #1,(DS_23FF,a3)
.c383:
	cmp.w #$ff,d1
	bls.s raster_c395
	moveq #0,d2
	andi.w #$ff,d1
	move.b (DS_25A1,a3),d0
	subq.w #1,(DS_23FF,a3)
	bra.w raster_c27c_poll

; ---- expire: drop ended edges from the active list ---------------------

raster_c395:
	move.w ES_4060(a1),d0
	movea.w #$4062,a4
	movea.w a4,a5
	move.w d0,(DS_252D,a3)
	move.w d0,d1
raster_c3a4_poll:
	rt_hle_rasterize_poll_11_local raster_c3a4_pending
raster_c3a4:
	move.w #$7fff,d7
raster_c3a4_1:
	sub.w a5,d7
	move.w -1(a1,d7.w),d3
	move.w #$7fff,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d0
	beq.s .c3c7
	subq.w #1,d0
	beq.s .c3c7
	move.w d0,-1(a1,d7.w)
	move.w a4,d7
	cmp.w a5,d7
	beq.s .c3be
	move.w #$7fff,d7
	sub.w a5,d7
	move.w -1(a1,d7.w),d0
	move.w #$7fff,d7
	sub.w a4,d7
	move.w d0,-1(a1,d7.w)
.c3be:
	addq.w #2,a4
	addq.w #2,a5
	subq.w #1,d1
	bne.s raster_c3a4_poll
	bra.s .c3cf
.c3c7:
	addq.w #2,a5
	subq.w #1,(DS_252D,a3)
	subq.w #1,d1
	bne.s raster_c3a4_poll
.c3cf:
	move.w (DS_252D,a3),d0
	movea.w #$4060,a4
	move.w d0,ES_4060(a1)
	bne.s raster_c3df_poll
	bra.w raster_c000_poll
raster_c3a4_pending:
	rt_hle_rasterize_poll_11_tail

; ---- advance: step each active edge one row -----------------------------

raster_c3df_poll:
	rt_hle_rasterize_poll_12
raster_c3df:
	RASTER_PEEK_C3DF raster_c3df_bail
raster_c3df_take:
	addq.w #2,a4
	movea.w d6,a5
	move.w #$7fff,d6
	sub.w a5,d6		; DI record: byte k at -k(a1,d6.w)
	tst.b -5(a1,d6.w)
	bpl.s .c3eb
	or.b #$40,-5(a1,d6.w)
	move.w -13(a1,d6.w),d0
	move.w -11(a1,d6.w),d2
	cmp.w #1,-1(a1,d6.w)
	bne.s .c40a
	cmp.w #1,d2
	bls.s .c40a
	lsr.w #1,d2
	roxr.w #1,d0
.c40a:
	btst #5,-5(a1,d6.w)
	bne.s .c41b
	add.w d0,-9(a1,d6.w)
	move.w -7(a1,d6.w),d7
	addx.w d2,d7
	move.w d7,-7(a1,d6.w)
	bra.s .c423
.c41b:
	add.w d0,-9(a1,d6.w)
	move.w -7(a1,d6.w),d7
	subx.w d2,d7
	move.w d7,-7(a1,d6.w)
.c423:
	subq.w #1,(DS_252D,a3)
	bne.s raster_c3df_poll
	bra.w raster_c000_poll
.c3eb:
	moveq #RZ_C3EB,d7
	rts
raster_c3df_bail:
	moveq #RZ_C3DF,d7
	rts
