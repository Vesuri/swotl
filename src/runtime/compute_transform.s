; Point transform: adapted from the user's TFH slave xform20 (315dbd2c).
; Authorization: native-plan U0/U2, 2026-10-21. Generated-code ABI.
; Preserve each original word store and byte history; DS was established by
; the generated segment-load path (including cell-cache exposure).
; No polls, flags inputs, services or internal guest calls in this body.

	xdef rt_hle_point_transform
rt_hle_point_transform:
	cmp.w #$f000,G_DS(a6)
	bhi .decline
	; Admit only a data window wholly above the original 64 KiB CS window.
	; CS is zero-extended in d6; the long add cannot wrap at FFFFh.
	moveq #0,d7
	move.w G_DS(a6),d7
	add.l #$1000,d6
	cmp.l d6,d7
	bcs .decline
	movem.l d4-d5,-(sp)
	; AX:BX, DX:CX, SI:DI -> d0,d1,d2; discard undefined upper words.
	swap d0
	move.w d3,d0
	move.l d2,d7
	swap d7
	move.w d1,d7
	move.l a4,d2
	swap d2
	move.w a5,d2
	move.l d7,d1

; Original high difference word is the sign scratch, not a canonical mask.
XF_NATIVE_DIFF macro ; point, camera, sign register, scratch, magnitude
	sub.l (\2,a3),\1
	move.l \1,\3
	swap \3
	move.w \3,(\4,a3)
	bpl.b .positive\@
	neg.l \1
.positive\@:
	move.w \1,(\5,a3)
	move.l \1,d3
	swap d3
	move.w d3,(\5-2,a3)
	endm
	XF_NATIVE_DIFF d0,$5d86,d5,$5d2c,$5d38
	XF_NATIVE_DIFF d1,$5d82,d6,$5d2a,$5d34
	XF_NATIVE_DIFF d2,$5d7e,d7,$5d28,$5d30

; xform20 unsigned 64-bit product, bits 16..47, then original bit-15
; sign test. Do not replace this with signed multiplication or equality.
XF_NATIVE_TERM macro ; magnitude, matrix, sign, matrix sign, branch, sum
	moveq #0,d3
	move.w (\2,a3),d3
	mulu.l \1,d4:d3
	swap d3
	swap d4
	move.w d3,d4
	move.w (\4,a3),d3
	eor.w \3,d3
	\5.b .positive\@
	neg.l d4
.positive\@:
	\6 d4,a0
	endm
XF_NATIVE_STORE macro ; output low word
	move.l a0,d3
	move.w d3,(\1,a3)
	swap d3
	move.w d3,(\1-2,a3)
	endm
	XF_NATIVE_TERM d0,$5da8,d5,$5d98,bpl,movea.l
	XF_NATIVE_TERM d1,$5da2,d6,$5d92,bpl,adda.l
	XF_NATIVE_TERM d2,$5daa,d7,$5d9a,bpl,adda.l
	XF_NATIVE_STORE -$4396
	XF_NATIVE_TERM d0,$5db0,d5,$5da0,bpl,movea.l
	XF_NATIVE_TERM d1,$5dae,d6,$5d9e,bmi,adda.l
	XF_NATIVE_STORE -$438e
	XF_NATIVE_TERM d0,$5da6,d5,$5d96,bmi,movea.l
	XF_NATIVE_TERM d1,$5da4,d6,$5d94,bmi,adda.l
	XF_NATIVE_TERM d2,$5dac,d7,$5d9c,bpl,adda.l
	XF_NATIVE_STORE -$4392
	; Preserve every original register result, including scratch SI/DI.
	move.w d2,a5
	move.w ($5d9c,a3),d3
	eor.w d7,d3
	move.w d3,a4
	move.l d4,d0
	move.l d4,d2
	swap d2
	move.l a0,d3
	move.l a0,d1
	swap d1
	movem.l (sp)+,d4-d5
	moveq #1,d7
	rts
.decline:
	moveq #0,d7
	rts
