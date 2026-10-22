; Projection long path: user's TFH slave xproj20 (315dbd2c), adapted to
; SWOTL's constants, generated ABI and complete per-byte write histories.
; User U4 authorization 2026-10-22: B017, narrowed to B393 through B4E1.
; No live status flags at entry/resume. Control flags remain untouched.
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
	move.l d4,-(sp)
	; Optional original scratch copy, before the projection writes.
	tst.w ($5cfc,a3)
	beq.b .nocopy
	move.w ($5d1c,a3),d2
	move.w d2,($5d12,a3)
	move.w ($5d1a,a3),d2
	move.w d2,($5d10,a3)
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
	move.w d4,(\1,a3)
	move.l d4,d3
	swap d3
	move.w d3,(\1-2,a3)
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
	bpl.b .magnitude
	neg.l d4
.magnitude:
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
	bpl.b .scaled
	neg.l d2
.scaled:
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
	moveq #1,d7
	rts
.decline:
	moveq #0,d7
	rts
