; Point transform B52D with B54B, whole: adapted from the user's TFH slave
; xform20 (315dbd2c). Authorization: native-plan U0/U2, 2026-10-21; user
; 2026-10-24 F3: the B52D wrapper too. Generated-code ABI.
; The wrapper's pushes (BP, DI, SI, the near call's return address) are stored
; as the original stores them; its pops restore SI, DI and BP, so those keep
; their entry values. Preserve each original store and byte history (merged
; long stores keep each byte's address, value and order); DS was established
; by the generated segment-load path (including cell-cache exposure).
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
	; Frame SP-8 .. SP+15 inside the stack segment without 16-bit wrap:
	; d4.w = 7FFFh - SP, so each slot is a fixed displacement from it.
	cmp.w #-$7ff1,d4
	blt .decline
	cmp.w #$7ff7,d4
	bgt .decline
	move.w d5,d7
	eori.w #$7fff,d7
	move.w d7,1(a2,d4.w)
	move.w a5,3(a2,d4.w)
	move.w a4,5(a2,d4.w)
	move.w #$6b97,7(a2,d4.w)
	; Arguments AX:BX, DX:CX, SI:DI as three longs at SP+4, SP+8, SP+12.
	move.l -7(a2,d4.w),d0
	move.l -11(a2,d4.w),d1
	move.l -15(a2,d4.w),d2
	movem.l d4-d5/a4-a5,-(sp)

; Original high difference word is the sign scratch, not a canonical mask.
XF_NATIVE_DIFF macro ; point, camera, sign register, scratch, magnitude
	sub.l (\2,a3),\1
	move.l \1,\3
	swap \3
	move.w \3,(\4,a3)
	bpl.b .positive\@
	neg.l \1
.positive\@:
	move.l \1,(\5-2,a3)
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
	move.l a0,(\1-2,a3)
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
	; AX:DX the last term, BX:CX the last sum; SI, DI and BP popped.
	move.l d4,d0
	move.l d4,d2
	swap d2
	move.l a0,d3
	move.l a0,d1
	swap d1
	movem.l (sp)+,d4-d5/a4-a5
	moveq #1,d7
	rts
.decline:
	moveq #0,d7
	rts
