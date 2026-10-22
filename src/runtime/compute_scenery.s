; Scenery frame clears, adapted from the user's TFH slave clr_scenery.
; User U6 authorization 2026-10-22; SWOTL's three overlapping 32-byte
; arrays and all per-byte write histories are retained.
; The guards admit ordinary RAM already exposed through SS, wholly above
; the code window, and no wrapped offset. Other states decline unchanged.

	ifnd G_SS
G_SS equ 3
G_ES equ 5
G_DF equ 12
	endif

	xdef rt_hle_scenery_clear
rt_hle_scenery_clear:
	tst.b G_DF(a6)
	bne .decline
	moveq #0,d7
	move.w G_SS(a6),d7
	cmp.w #$9000,d7
	bhi .decline
	add.l #$1000,d6
	cmp.l d6,d7
	bcs .decline
	move.w d5,d6
	eori.w #$7fff,d6
	cmp.w #126,d6
	bcs .decline
	; SS has already passed the generated segment exposure path. The
	; admitted window cannot touch code or the display; ES takes its base.
	move.w d7,G_ES(a6)
	move.l a2,a1
	move.w d6,a5
	suba.w #94,a5
	moveq #0,d0
	moveq #0,d1
	; Mirror BP itself (not BP-displacement): each checked clear is a
	; contiguous 32-byte range, including the two-byte overlap with the next.
	lea (0,a2,d5.w),a0
SCENERY_CLEAR macro
	move.l d0,(\1-3,a0)
	move.l d0,(\1-7,a0)
	move.l d0,(\1-11,a0)
	move.l d0,(\1-15,a0)
	move.l d0,(\1-19,a0)
	move.l d0,(\1-23,a0)
	move.l d0,(\1-27,a0)
	move.l d0,(\1-31,a0)
	endm
	SCENERY_CLEAR 66
	SCENERY_CLEAR 96
	SCENERY_CLEAR 126
	moveq #1,d7
	rts
.decline:
	moveq #0,d7
	rts
