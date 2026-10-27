; Ground-object vertex loops in 109D6 (scenery objects): the transform loop
; 10C08..10DCF and the projection loop 10DDC..10F62. U6 authorized
; 2026-10-22 (multiple continuation endpoints approved for these loops);
; irq-plan I10, user 2026-10-26 (go-ahead for each native). Original SWOTL
; x86 is the oracle. Each vertex index (ES:[DI+i]) is transformed once:
; world X, Y, Z = sign-extended vertex words << 6 + the object origin
; (C380h..C38Ah), or for a midpoint vertex (word 8000h) the halved sum of two
; earlier vertices; Z < 0 counts at [BP-23h]. Then each vertex is projected
; once into the DS table at 2445h + [BP-0Ch]: a midpoint of two projected
; vertices with Z > 2 by halving (SAR high word, SHR low word), else by the
; normalise/project call. The transform call (B52D) and the projection call
; (D5A6), with the 9C20h writes around them (sync accesses), stay generated
; as continuation exits; the native re-enters after each POP ES (hle.csv
; entries; d7 = 0 at 10C08, 1 at 10CE4, 2 at 10F21). Endpoints: 10F62
; (projected), 10F6A (some vertex behind: clipped path), 11131 (all behind).
; BP is mirrored in d5 (BP ^ 7FFFh); the frame base a0 = SS base + d5 puts
; word [BP+K] at -1-K(a0), byte at -K(a0), long (low word at K) at
; -3-K(a0). DS words at X are ($7FFE-X,a3). ES, DS-table and midpoint
; index addressing use 16-bit word arithmetic as the original does.
; Admission (every hook, before any mutation): DS = SS in [CS + 1000h,
; 9000h] (no code or VRAM writes; the passing pair is cached, CS being the
; hook's constant); BP in C600h..FC00h, so [BP-2D6h] up to [BP+3FAh+3]
; neither wraps nor meets the DS words the row reads (C380h..C396h,
; 22DEh..22E4h) or a table entry below A44Dh: long moves keep the original's
; interleaved read/write results; SP >= 0Eh (the 14 bytes of pushes do
; not wrap); at the re-entries SI <= 0FFh (10CE4) and SI <= 3FCh (10F21).
; Vertex records across 64K and table offsets from 8000h take exact
; word-arithmetic paths. Flags are dead at every endpoint.

; Resume ids: endpoints ascending (compute.resume_dispatch).
RZ_10CD1	equ 1
RZ_10F0E	equ 2
RZ_10F62	equ 3
RZ_10F6A	equ 4
RZ_11131	equ 5

GV_PUSH	macro	; src
	addq.w #2,d4
	move.w \1,-1(a2,d4.w)
	endm
; d7 = SS word index of [\2 + K] for K in \1 (\2 a data register)
GV_SSX	macro	; K, reg
	move.w #($7fff-(\1))&$ffff,d7
	sub.w \2,d7
	endm
; AX:DX = SS long [C2 + K] + SS long [B3 + K]: C2 in d1, B3 in d3 (or the
; reverse with \2 = 1), each word with its own 16-bit wrap; \3: 1 for the
; transform's SAR/RCR, 0 for the projection's SAR/SHR halving
GV_MID	macro	; K, unused, rcr
	GV_SSX \1,d1
	move.w -1(a2,d7.w),d0
	GV_SSX \1+2,d1
	move.w -1(a2,d7.w),d2
	GV_SSX \1+2,d3
	move.w -1(a2,d7.w),d6
	GV_SSX \1,d3
	add.w -1(a2,d7.w),d0
	addx.w d6,d2
	asr.w #1,d2
	if \3
	roxr.w #1,d0
	else
	lsr.w #1,d0
	endif
	endm
; SS long [BP + SI + K] = AX:DX, word arithmetic (transform midpoints)
GV_PUTSI macro	; K
	move.w d5,d7
	sub.w a4,d7
	sub.w #\1,d7
	move.w d0,-1(a2,d7.w)
	subq.w #2,d7
	move.w d2,-1(a2,d7.w)
	endm

ground_decline:
	moveq #0,d7
	rts
; the full segment check once per DS:SS pair (CS is the hook's constant)
ground_segs_check:
	move.w d7,-(sp)
	move.w G_DS(a6),d7
	cmp.w G_SS(a6),d7
	bne.s .no
	cmp.w #$9000,d7
	bhi.s .no
	andi.l #$ffff,d7
	add.l #$1000,d6
	cmp.l d6,d7
	bcs.s .no
	move.l a0,ground_segs
	move.w (sp)+,d7
	bra.s ground_segs_ok
.no:
	addq.l #2,sp
	bra.s ground_decline
ground_segs:
	dc.l $ffffffff			; the last DS:SS pair that passed
ground_other_entry:
	bcs.w ground_10c08
	cmp.w #$3fc,d6
	bhi.s ground_decline
	bra.w ground_10f21

	xdef rt_hle_ground_vertices
rt_hle_ground_vertices:
	movea.l G_DS(a6),a0		; DS:SS
	cmpa.l ground_segs(pc),a0
	bne.s ground_segs_check
ground_segs_ok:
	cmp.w #$7fff-$fc00,d5
	blt.s ground_decline
	cmp.w #$7fff-$c600,d5
	bgt.s ground_decline
	cmp.w #$7fff-14,d4
	bgt.s ground_decline
	lea (a2,d5.w),a0
	move.w a4,d6
	subq.w #1,d7
	bne.s ground_other_entry
	cmp.w #$ff,d6
	bhi.s ground_decline

; 10CE4: the transform's results (C38Ch..C396h) for vertex SI
ground_10ce4:
	move.w d6,d3			; BX = v (SI = v again at the end)
	move.w d6,d7
	neg.w d7			; -v
	move.w d7,d6
	lsl.w #2,d6			; -4v
	move.l ($7ffe-$c38e,a3),($f3,a0,d6.w)
	move.l ($7ffe-$c392,a3),($16b,a0,d6.w)
	move.l ($7ffe-$c396,a3),d0
	move.l d0,($1e3,a0,d6.w)
	swap d0				; AX = Z high
	move.b #1,($60,a0,d7.w)
	tst.w d0
	bpl.s .front
	addq.b #1,$23(a0)
.front:
	addq.b #1,$24(a0)		; 10DC1 inline
	move.b $24(a0),d3
	cmp.b 6(a0),d3
	bne.w ground_10c1d
	bra.w ground_10dcf
ground_10c08:
; 10C08: the transform loop over the object's vertex indices
	clr.b d0			; SUB AL,AL
	clr.b $23(a0)			; [BP-23h] behind = 0
	addq.w #3,a5
	clr.b d3			; SUB BL,BL
	clr.b $24(a0)			; [BP-24h] i = 0
	cmp.b 6(a0),d3			; i < n (signed bytes)
	blt ground_10c1d
	bra.w ground_10dcf
ground_10c1d:
	andi.w #$ff,d3			; BX = i
	move.w #$7fff,d7
	sub.w d3,d7
	sub.w a5,d7
	moveq #0,d6
	move.b (a1,d7.w),d6		; v = ES:[BX+DI]
	move.w d6,d3
	movea.w d6,a4			; SI = v
	neg.w d6
	tst.b ($60,a0,d6.w)		; transformed?
	bne.w ground_10db2
	add.w d3,d3
	add.w a4,d3
	add.w d3,d3
	add.w 3(a0),d3			; BX = 6v + [BP-4]
	move.w #$7fff,d7
	sub.w d3,d7
	cmp.w #-$7ffc,d7		; ES:[BX] .. [BX+5] without a 16-bit wrap
	blt.w ground_10c38_wrap
	cmp.w #$8000,-1(a1,d7.w)
	beq.w ground_10d24
	; PUSH ES, DX, AX, [BP-12h], [BP-14h], [BP-0Eh], [BP-10h]: SP - 14 (the
	; entry guard: no wrap); each pair of pushes is one long, stored from
	; the register that holds it (the stack lies below the frame)
	add.w #14,d4
	move.w G_ES(a6),-13(a2,d4.w)
	move.w -1(a1,d7.w),d6		; X
	ext.l d6
	asl.l #6,d6
	add.l ($7ffe-$c382,a3),d6
	move.l d6,$d(a0)		; [BP-10h]
	move.l d6,-3(a2,d4.w)
	move.w -3(a1,d7.w),d6		; Y
	ext.l d6
	asl.l #6,d6
	add.l ($7ffe-$c386,a3),d6
	move.l d6,$11(a0)		; [BP-14h]
	move.l d6,-7(a2,d4.w)
	move.w -5(a1,d7.w),d0		; Z
	ext.l d0
	asl.l #6,d0
	add.l ($7ffe-$c38a,a3),d0
	move.l d0,$15(a0)		; [BP-18h]
	move.l d0,-11(a2,d4.w)
	move.l d0,d2
	swap d2				; DX = Z high, AX = Z low
	moveq #RZ_10CD1,d7		; B52D, then POP ES
	rts
; the same with ES:[BX] word arithmetic (a vertex record across 64K)
ground_10c38_wrap:
	cmp.w #$8000,-1(a1,d7.w)
	beq.w ground_10d24
	move.w -1(a1,d7.w),d0		; X
	ext.l d0
	asl.l #6,d0
	add.l ($7ffe-$c382,a3),d0
	move.l d0,$d(a0)		; [BP-10h]
	move.w #$7ffd,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d0		; Y
	ext.l d0
	asl.l #6,d0
	add.l ($7ffe-$c386,a3),d0
	move.l d0,$11(a0)		; [BP-14h]
	move.w #$7ffb,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d0		; Z
	ext.l d0
	asl.l #6,d0
	add.l ($7ffe-$c38a,a3),d0
	move.l d0,$15(a0)		; [BP-18h]
	move.l d0,d2
	swap d2				; DX = Z high, AX = Z low
	GV_PUSH G_ES(a6)
	GV_PUSH d2
	GV_PUSH d0
	GV_PUSH $11(a0)
	GV_PUSH $13(a0)
	GV_PUSH $d(a0)
	GV_PUSH $f(a0)
	moveq #RZ_10CD1,d7		; B52D, then POP ES
	rts

; 10CE4: the transform's results (C38Ch..C396h) for vertex SI
; 10D24: midpoint vertex (8000h): the halved sums of two earlier vertices
ground_10d24:
	move.w a4,d6
	neg.w d6
	move.b #1,($60,a0,d6.w)
	move.b #1,($42,a0,d6.w)
	move.w #$7ffd,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d1
	add.w d1,d1
	add.w d1,d1			; CX = ES:[BX+2] * 4
	move.w #$7ffb,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d3
	add.w d3,d3
	add.w d3,d3			; BX = ES:[BX+4] * 4
	move.w a4,d6
	add.w d6,d6
	add.w d6,d6
	movea.w d6,a4			; SI = 4v
	move.w d5,d6
	eori.w #$7fff,d6		; BP
	add.w d6,d1
	add.w d6,d3
	GV_MID $ff0a,0,1
	GV_PUTSI $ff0a
	GV_MID $fe92,0,1
	GV_PUTSI $fe92
	GV_MID $fe1a,0,1
	GV_PUTSI $fe1a
	move.w d5,d6
	eori.w #$7fff,d6
	sub.w d6,d1
	sub.w d6,d3
	tst.w d2
	bpl ground_10dc1
	addq.b #1,$23(a0)
	bra ground_10dc1

; 10DB2: already transformed: count it behind by its Z
ground_10db2:
	move.w a4,d6
	add.w d6,d6
	add.w d6,d6
	movea.w d6,a4			; SI = 4v
	neg.w d6
	tst.w ($1e3,a0,d6.w)		; [BP+SI-1E4h] Z high
	bpl ground_10dc1
	addq.b #1,$23(a0)
ground_10dc1:
	addq.b #1,$24(a0)
	move.b $24(a0),d3		; BL = i
	cmp.b 6(a0),d3
	bne.w ground_10c1d

ground_10dcf:
	move.w 5(a0),d0			; AX = [BP-6]
	cmp.b $23(a0),d0
	bne.s .some
	adda.w d0,a5			; every vertex behind
	moveq #RZ_11131,d7
	rts
.some:
	moveq #0,d0
	clr.w $b(a0)			; [BP-0Ch] table offset = 0
	clr.w ($7ffe-$c3fa,a3)
	tst.b $23(a0)
	beq.s .front
	moveq #RZ_10F6A,d7		; some vertex behind: clipped path
	rts
.front:
	clr.b $24(a0)
	cmp.b 6(a0),d0
	blt ground_10df8
	moveq #RZ_10F62,d7
	rts

; 10DF8: the projection loop
ground_10df8:
	andi.w #$ff,d0
	move.w d0,d3			; BX = i
	move.w #$7fff,d7
	sub.w d3,d7
	sub.w a5,d7
	move.b (a1,d7.w),d3		; BX = v
	movea.w d3,a4
	move.w d3,d6
	neg.w d6
	tst.b ($7e,a0,d6.w)		; projected?
	beq ground_10e33
	move.w a4,d6
	add.w d6,d6
	add.w d6,d6
	movea.w d6,a4			; SI = 4v
	neg.w d6
	move.w $b(a0),d3
	move.w #$7fff-$2445,d7
	sub.w d3,d7
	tst.w d3			; table offset < 8000h: no wrap, no alias
	bmi.s .slow
	move.l ($25b,a0,d6.w),-3(a3,d7.w)
	move.l ($2d3,a0,d6.w),d0
	move.l d0,-7(a3,d7.w)
	swap d0
	bra.w ground_10f50
.slow:
	move.w ($25d,a0,d6.w),-1(a3,d7.w)
	subq.w #2,d7
	move.w ($25b,a0,d6.w),-1(a3,d7.w)
	subq.w #2,d7
	move.w ($2d5,a0,d6.w),-1(a3,d7.w)
	subq.w #2,d7
	move.w ($2d3,a0,d6.w),d0
	move.w d0,-1(a3,d7.w)
	bra.w ground_10f50
ground_10e33:
	move.b #1,($7e,a0,d6.w)
	tst.b ($42,a0,d6.w)		; midpoint?
	beq.w ground_10ef1
	add.w d3,d3
	add.w a4,d3
	add.w d3,d3
	add.w 3(a0),d3			; BX = 6v + [BP-4]
	move.w d5,d6
	eori.w #$7fff,d6		; BP
	move.w #$7ffd,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d1
	add.w d6,d1			; CX = ES:[BX+2] + BP
	move.w #$7ffb,d7
	sub.w d3,d7
	move.w -1(a1,d7.w),d3
	add.w d6,d3			; BX = ES:[BX+4] + BP
	GV_SSX $ff82,d3
	tst.b (a2,d7.w)
	beq.w ground_10ef1
	exg d1,d3
	GV_SSX $ff82,d3
	tst.b (a2,d7.w)
	beq.w ground_10ef1
	sub.w d6,d3
	add.w d3,d3
	add.w d3,d3
	add.w d6,d3
	GV_SSX $fe1c,d3
	cmp.w #2,-1(a2,d7.w)
	ble.w ground_10ef1
	exg d1,d3
	sub.w d6,d3
	add.w d3,d3
	add.w d3,d3
	add.w d6,d3
	GV_SSX $fe1c,d3
	cmp.w #2,-1(a2,d7.w)
	ble.w ground_10ef1
	GV_MID $fda2,0,0		; AX:DX = SX[C2] + SX[B3], halved
	move.w a4,d6
	add.w d6,d6
	add.w d6,d6
	movea.w d6,a4			; SI = 4v
	neg.w d6
	move.w d0,($25d,a0,d6.w)
	move.w d2,($25b,a0,d6.w)
	move.w #$7fff-$2445,d7
	sub.w $b(a0),d7
	move.w d0,-1(a3,d7.w)
	subq.w #2,d7
	move.w d2,-1(a3,d7.w)
	GV_MID $fd2a,0,0		; AX:DX = SY[C2] + SY[B3], halved
	move.w a4,d6
	neg.w d6
	move.w d0,($2d5,a0,d6.w)
	move.w d2,($2d3,a0,d6.w)
	move.w d3,d1			; CX = B3
	move.w $b(a0),d3		; BX = table offset
	move.w #$7fff-$2449,d7
	sub.w d3,d7
	move.w d0,-1(a3,d7.w)
	subq.w #2,d7
	move.w d2,-1(a3,d7.w)
	bra ground_10f50

; 10EF1: project vertex SI through D5A6 (then POP ES)
ground_10ef1:
	add.w #14,d4			; the entry guard: no wrap
	move.w G_ES(a6),-13(a2,d4.w)
	move.w a4,d6
	add.w d6,d6
	add.w d6,d6
	movea.w d6,a4			; SI = 4v
	neg.w d6
	move.l ($1e3,a0,d6.w),-11(a2,d4.w)
	move.l ($16b,a0,d6.w),-7(a2,d4.w)
	move.l ($f3,a0,d6.w),-3(a2,d4.w)
	moveq #RZ_10F0E,d7
	rts

; 10F21: D5A6's results (22DEh..22E4h) to the table and vertex SI
ground_10f21:
	move.w $b(a0),d3		; BX = table offset
	move.w a4,d6
	neg.w d6
	move.w #$7fff-$2445,d7
	sub.w d3,d7
	tst.w d3			; table offset < 8000h: no wrap, no alias
	bmi.s .slow
	move.l ($7ffe-$22e0,a3),d0
	move.l d0,-3(a3,d7.w)
	move.l d0,($25b,a0,d6.w)
	move.l ($7ffe-$22e4,a3),d0
	move.l d0,-7(a3,d7.w)
	move.l d0,($2d3,a0,d6.w)
	swap d0				; AX = [22E4h]
	bra.s ground_10f50
.slow:
	move.w ($7ffe-$22de,a3),d0
	move.w d0,-1(a3,d7.w)
	move.w d0,($25d,a0,d6.w)
	move.w ($7ffe-$22e0,a3),d0
	subq.w #2,d7
	move.w d0,-1(a3,d7.w)
	move.w d0,($25b,a0,d6.w)
	move.w ($7ffe-$22e2,a3),d0
	subq.w #2,d7
	move.w d0,-1(a3,d7.w)
	move.w d0,($2d5,a0,d6.w)
	move.w ($7ffe-$22e4,a3),d0
	subq.w #2,d7
	move.w d0,-1(a3,d7.w)
	move.w d0,($2d3,a0,d6.w)
ground_10f50:
	addq.w #8,$b(a0)
	addq.b #1,$24(a0)
	move.b $24(a0),d0		; AL = i
	cmp.b 6(a0),d0
	blt.w ground_10df8
	moveq #RZ_10F62,d7
	rts

