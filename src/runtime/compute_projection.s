; Projection B017, whole routine with its divide B4E2: user's TFH slave
; xproj20/xdiv20 (315dbd2c), adapted to SWOTL's constants, generated ABI and
; complete per-byte write histories; the 16-bit path (no slave version) from
; the original's arithmetic. User U4 2026-10-22 (B017, B4E2); user 2026-10-24
; F3: whole geometry routines.
; Poll-free, four returns: d7 = 1 B15F, 2 B163, 3 B392, 4 B4E1. No live status
; flags at entry or at any return. Control flags remain untouched. Each near
; call's return address is stored as the original pushes it.
; Standalone object is linked after generated code to avoid moving hot runtime.
	ifnd G_DS
G_DS equ 1 ; translator/lower.py STATE_EQU
	endif
	xdef rt_hle_point_projection
rt_hle_point_projection:
	cmp.w #$f000,G_DS(a6)
	bhi .decline
	moveq #0,d7
	move.w G_DS(a6),d7
	add.l #$1000,d6
	cmp.l d6,d7
	bcs .decline
; B4E2, xdiv20 with the scale B017 stores (B4h): AX in; SI = AX, AX:DX the
; rounded magnitude (low, high; d0 the long), BX:CX the signed result (low,
; high; d3 the long). |AX| <=
; 8000h: both original word divides fit for every nonzero divisor; a zero
; divisor takes the original's non-dividing path (quotient |AX| << 16). The
; quotient's low word stays in a0 for BP (PJ_BP), live only on the 16-bit
; path: every 32-bit path rewrites BP. No stores. d6/d7 trashed.
PJ_DIVIDE macro
	move.w d0,a4
	moveq #0,d6
	move.w d0,d6
	bpl.b .dividend\@
	neg.w d6
.dividend\@:
	swap d6
	moveq #0,d7
	move.w ($5d3c,a3),d7
	beq.b .quotient\@
	divu.l d7,d6
.quotient\@:
	move.w d6,a0
	mulu.l #$b4,d7:d6
	add.l #$8000,d6
	bcc.b .carry\@
	addq.l #1,d7
.carry\@:
	swap d6
	swap d7
	move.w d6,d7
	move.l d7,d0
	move.l d7,d2
	swap d2
	move.w a4,d6
	bpl.b .sign\@
	neg.l d7
.sign\@:
	move.l d7,d3
	move.l d7,d1
	swap d1
	endm
; B4E2's BP: rounded product of the quotient's low word, high word.
PJ_BP macro
	move.l a0,d7
	mulu.w #$b4,d7
	add.l #$8000,d7
	swap d7
	move.w d7,d5
	eori.w #$7fff,d5
	endm
	move.w #$b4,($5d26,a3)
	move.w d4,d7
	addq.w #2,d7
	move.w #$6673,-1(a2,d7.w)
	move.w ($5d44,a3),d0
	PJ_DIVIDE
	move.l d3,($5d1e,a3)
	move.w d1,($5ce6,a3)
	move.l d0,($5d08,a3)
	tst.w ($5d02,a3)
	bne.b .second
	tst.w d2
	bne .reject
	cmp.w ($5a6f,a3),d0
	bcc .reject
.second:
	move.w #$b4,($5d26,a3)
	move.w d4,d7
	addq.w #2,d7
	move.w #$66a7,-1(a2,d7.w)
	move.w ($5d40,a3),d0
	PJ_DIVIDE
	move.l d3,($5d1a,a3)
	move.w d1,($5ce4,a3)
	move.l d0,($5d04,a3)
	tst.w ($5d02,a3)
	bne .long
	tst.w d2
	bne .reject
	cmp.w ($5a6f,a3),d0
	bcc .reject

; 16-bit path B082. A term: high word of (magnitude * matrix + 8000h).
PJ_TERM macro ; magnitude word, matrix, sign, matrix sign, branch that skips the negation, out
	move.w \1,\6
	mulu.w (\2,a3),\6
	add.l #$8000,\6
	swap \6
	move.w (\3,a3),d0
	move.w (\4,a3),d2
	eor.w d2,d0
	\5.b .positive\@
	neg.w \6
.positive\@:
	endm
	move.w ($5d0a,a3),d3
	move.w ($5d06,a3),d1
	PJ_TERM d3,$5d8e,$5ce6,$5d8a,bpl,d6
	move.w d6,a5
	PJ_TERM d1,$5d90,$5ce4,$5d8c,bmi,d7
	add.w d6,d7
	move.w d7,d2
	tst.w ($5cfc,a3)
	bne.b .inside
	tst.w d2
	bpl.b .absolute
	neg.w d2
.absolute:
	cmp.w ($5a6f,a3),d2
	bcc .reject
.inside:
	move.w d7,d0
	add.w ($5a77,a3),d0
	add.w ($5cee,a3),d0
	move.w d0,d2
	ext.l d2
	move.l d2,($5d1e,a3)
	swap d2
	PJ_TERM d3,$5d90,$5ce6,$5d8c,bpl,d6
	PJ_TERM d1,$5d8e,$5ce4,$5d8a,bpl,d7
	add.w d7,d6
	move.w d6,d0
	and.w #$8000,d6
	beq.b .scale
	neg.w d0
.scale:
	mulu.w #$e9,d0
	add.l #$80,d0
	move.l d0,d2
	lsr.l #8,d2
	tst.w d6
	beq.b .unsigned
	neg.w d2
.unsigned:
	sub.w ($5cea,a3),d2
	move.w d2,d0
	bpl.b .distance
	neg.w d2
.distance:
	move.w #$e9,d3
	move.w d6,a5
	cmp.w ($5a65,a3),d2
	bcc .reject
	add.w ($5a69,a3),d0
	add.w ($5cec,a3),d0
	move.w d0,d2
	ext.l d2
	move.l d2,($5d1a,a3)
	swap d2
	PJ_BP
	moveq #0,d0
	moveq #1,d7
	rts
.reject:
	PJ_BP
	moveq #2,d0
	moveq #2,d7
	rts

; 32-bit paths B164. XP_MUL20 on a long magnitude: d0 = bits 16..47 of
; (magnitude * coefficient + 8000h); d7 trashed.
PJ_ROUND macro ; magnitude long, coefficient
	moveq #0,d7
	move.w \2,d7
	mulu.l \1,d0:d7
	add.l #$8000,d7
	bcc.b .carry\@
	addq.l #1,d0
.carry\@:
	swap d7
	swap d0
	move.w d7,d0
	endm
PJ_SIGN macro ; sign, matrix sign, branch that skips the negation; > d1 = SI
	move.w (\1,a3),d1
	move.w (\2,a3),d2
	eor.w d2,d1
	\3.b .positive\@
	neg.l d0
.positive\@:
	endm
; Both words in one long store: reversed RAM holds the little-endian long
; big-endian, so each byte keeps its address, value and write order.
PJ_STORE macro ; long register, original low-word destination (reversed RAM)
	move.l \1,(\2-2,a3)
	endm
.long:
	tst.w ($5cfe,a3)
	beq .near
	tst.w ($5d00,a3)
	bne.b .behind
	tst.w ($5cc0,a3)
	bne.b .ahead
.behind:
	move.l d3,d1
	subq.l #1,d1
	move.l d1,d3
	move.l d1,d0
	move.l d1,($5d1a,a3)
	swap d1
	move.w d1,($5ce4,a3)
	tst.l d0
	bpl.b .magnitude
	neg.l d0
.magnitude:
	PJ_STORE d0,$5d06
	bra .near
.ahead:
	move.l ($5d10,a3),d6
	sub.l ($5d1a,a3),d6
	bmi.b .far
	; ((D + 1) * W25CE + 4000h) << 1, bits 16..47
	addq.l #1,d6
	moveq #0,d7
	move.w ($5a30,a3),d7
	mulu.l d7,d0:d6
	add.l #$4000,d6
	bcc.b .round
	addq.l #1,d0
.round:
	lsr.l #8,d6
	lsr.l #7,d6
	swap d0
	lsl.l #1,d0
	or.l d0,d6
	move.l ($5d0c,a3),d7
	sub.l d6,d7
	bra.b .limit
.far:
	move.l ($5d0c,a3),d7
.limit:
	PJ_STORE d7,$5d1c
	move.l ($5d08,a3),d6
	tst.w ($5a36,a3)
	bne .rotated
	PJ_ROUND d6,($5d8e,a3)
	PJ_SIGN $5ce6,$5d8a,bpl
	move.l d0,d3
	PJ_STORE d0,$5d20
	move.l ($5d04,a3),d6
	PJ_ROUND d6,($5d90,a3)
	PJ_SIGN $5ce4,$5d8c,bmi
	btst #1,($5a2f,a3)
	bne.b .mirrored
	moveq #0,d2
	move.w ($5cee,a3),d2
	add.l d2,d0
	move.w ($5a77,a3),d2
	add.l d2,d0
	add.l d0,d3
	PJ_STORE d3,$5d20
	bra.b .plain
.mirrored:
	add.l d0,d3
	PJ_STORE d3,$5d20
	moveq #0,d0
	move.w ($5a77,a3),d0
	moveq #0,d2
	move.w ($5cee,a3),d2
	add.l d2,d0
	sub.l d3,d0
	PJ_STORE d0,$5d20
.plain:
	move.l d0,d2
	swap d2
	move.w d1,a4
	move.w ($5d0a,a3),d3
	move.w ($5d06,a3),d1
	move.w ($5d08,a3),d5
	eori.w #$7fff,d5
	move.w ($5d04,a3),a5
	moveq #1,d0
	moveq #3,d7
	rts
.rotated:
	PJ_ROUND d6,($5d90,a3)
	PJ_SIGN $5ce6,$5d8c,bpl
	move.l d0,d3
	PJ_STORE d0,$5d20
	move.l ($5d04,a3),d6
	PJ_ROUND d6,($5d8e,a3)
	PJ_SIGN $5ce4,$5d8a,bpl
	add.l d0,d3
	PJ_STORE d3,$5d20
	; SI keeps the sum's high word, DI the magnitude's; BP the rounded low half.
	move.l d3,d6
	swap d3
	move.w d3,a4
	tst.l d6
	bpl.b .positive
	neg.l d6
.positive:
	move.l d6,d7
	swap d7
	move.w d7,a5
	moveq #0,d7
	move.w d6,d7
	mulu.w #$e8ba,d7
	add.l #$8000,d7
	swap d7
	move.w d7,d5
	eori.w #$7fff,d5
	PJ_ROUND d6,#$e8ba
	move.w a4,d7
	bpl.b .scaled
	neg.l d0
.scaled:
	btst #0,($5a2f,a3)
	bne.b .flipped
	moveq #0,d7
	move.w ($5a69,a3),d7
	add.l d7,d0
	move.w ($5cec,a3),d7
	add.l d7,d0
	sub.l ($5ce8,a3),d0
	move.w ($5d06,a3),d1
	bra.b .screen
.flipped:
	move.w d0,d1
	move.l d0,d5
	swap d5
	eori.w #$7fff,d5
	moveq #0,d7
	move.w ($5a69,a3),d7
	sub.l d0,d7
	moveq #0,d0
	move.w ($5cec,a3),d0
	sub.l d0,d7
	add.l ($5ce8,a3),d7
	move.l d7,d0
.screen:
	PJ_STORE d0,$5d20
	move.l d0,d2
	swap d2
	move.w #$e8ba,d3
	moveq #1,d0
	moveq #3,d7
	rts

; B393 through B4DF: xproj20. Optional original scratch copy first.
.near:
	move.l d4,-(sp)
	tst.w ($5cfc,a3)
	beq.b .nocopy
	move.l ($5d1a,a3),($5d10,a3)
.nocopy:
	move.l ($5d08,a3),d0
	move.l ($5d04,a3),d1

; XP_MUL20: unsigned product rounded by 8000h, bits 16..47.
XP_NATIVE_MUL macro ; magnitude, coefficient
	moveq #0,d3
	move.w \2,d3
	mulu.l \1,d2:d3
	add.l #$8000,d3
	bcc.b .carry\@
	addq.l #1,d2
.carry\@:
	swap d3
	swap d2
	move.w d3,d2
	endm
XP_NATIVE_TERM macro ; magnitude, coefficient, sign, matrix sign, positive branch
	XP_NATIVE_MUL \1,\2
	move.w (\3,a3),d6
	move.w (\4,a3),d3
	eor.w d6,d3
	\5.b .positive\@
	neg.l d2
.positive\@:
	endm
XP_NATIVE_STORE macro ; original low-word destination (reversed RAM)
	move.l d4,(\1-2,a3)
	endm
	XP_NATIVE_TERM d0,($5d8e,a3),$5ce6,$5d8a,bpl
	move.l d2,d4
	XP_NATIVE_STORE $5d20
	XP_NATIVE_TERM d1,($5d90,a3),$5ce4,$5d8c,bmi
	add.l d2,d4
	moveq #0,d3
	move.w ($5a77,a3),d3
	add.l d3,d4
	move.w ($5cee,a3),d3
	add.l d3,d4
	XP_NATIVE_STORE $5d20
	XP_NATIVE_TERM d0,($5d90,a3),$5ce6,$5d8c,bpl
	move.l d2,d4
	XP_NATIVE_STORE $5d1c
	XP_NATIVE_TERM d1,($5d8e,a3),$5ce4,$5d8a,bpl
	add.l d2,d4
	XP_NATIVE_STORE $5d1c
	; SI retains the signed sum's high word; DI the magnitude's high word.
	move.l d4,d3
	swap d3
	move.w d3,a4
	tst.l d4
	bpl.b .absolute32
	neg.l d4
.absolute32:
	move.l d4,d3
	swap d3
	move.w d3,a5
	; Original BP is the rounded low-half product, not the full result.
	moveq #0,d7
	move.w d4,d7
	mulu.w #$e8ba,d7
	add.l #$8000,d7
	swap d7
	move.w d7,d5
	eori.w #$7fff,d5
	XP_NATIVE_MUL d4,#$e8ba
	move.l a4,d3
	tst.w d3
	bpl.b .scaled32
	neg.l d2
.scaled32:
	sub.l ($5ce8,a3),d2
	moveq #0,d3
	move.w ($5a69,a3),d3
	add.l d3,d2
	move.w ($5cec,a3),d3
	add.l d3,d2
	move.l d2,d4
	XP_NATIVE_STORE $5d1c
	swap d2
	move.w #$e8ba,d3
	moveq #0,d0
	move.l (sp)+,d4
	moveq #4,d7
	rts
.decline:
	moveq #0,d7
	rts

