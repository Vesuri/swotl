; Polygon bounds/classify BB70, whole up to its RETF (BD67). U6 2026-10-22;
; irq-plan I10 (user 2026-10-26, go-ahead for each native), poll-free (RC5).
; SWOTL x86 is the oracle. Arguments: the vertex list (DS offset) and its
; count n at SP+4/SP+6 of the far call; vertices are x, y signed longs, 8
; bytes each; one word mask per index at 23C3h.
;   1. the largest y (first wins, ties counted at 23BDh and their masks ORed
;      at 23BFh, index at 23C1h; 237Bh = n); y < 0: AX = 0.
;   2. all n tied: C3FCh = n, C3F8h = n<<4 | 0Fh, AX = 1. Otherwise the list
;      rotates left by r passes (r = index, index+1 with ties, or 1/0 by the
;      last mask at index 0), each pass saving vertex 0 at 2389h; 24A1h = 0.
;   3. the smallest y of vertices 1..n-1 (first wins): not below the clip
;      (2338h, signed) or high word set: AX = 0; else C3FCh = n,
;      C3F8h = n<<4 | its index.
;   4. the smallest x not left of 233Ch (unsigned) or high word set: AX = 0;
;      else AX = 1 unless the largest x is negative.
; BX, CX, DX as the original leaves them; BP, SI, DI and SP as on entry
; (their pushes stay stored). Admission (R39's guard): DS = SS, the DS window
; wholly above CS's 64 KiB and below A0000h, SP C410h..FFF8h, 2 <= n <= 16 and
; the list in 23E3h..24A1h or 24A3h..C3F8h: no wrap, no code, VRAM, stack or
; scratch overlap. No status flags are live at the RETF.

	xdef rt_hle_polygon_classify
rt_hle_polygon_classify:
	move.w G_DS(a6),d7
	cmp.w G_SS(a6),d7
	bne .decline
	cmp.w #$9000,d7
	bhi .decline
	andi.l #$ffff,d7
	add.l #$1000,d6
	cmp.l d6,d7
	bcs .decline
	cmp.w #-$7ff9,d4
	blt .decline
	cmp.w #-$4411,d4
	bgt .decline
	moveq #0,d7
	move.w -7(a2,d4.w),d7		; n
	subq.w #2,d7
	cmp.w #14,d7
	bhi .decline
	addq.w #2,d7
	moveq #0,d6
	move.w -5(a2,d4.w),d6		; list
	move.l d7,a0
	add.l a0,a0
	add.l a0,a0
	add.l a0,a0
	add.l d6,a0			; end
	cmp.w #$24a3,d6
	bcc.s .high
	cmp.w #$23e3,d6
	bcs .decline
	cmpa.l #$24a1,a0
	bhi .decline
	bra.s .admit
.high:
	cmpa.l #$c3f8,a0
	bhi .decline
.admit:
	movem.l d3/d5/a1/a4/a5,-(sp)
	move.w d5,d0
	eori.w #$7fff,d0
	move.w d0,1(a2,d4.w)		; push bp
	move.w a5,3(a2,d4.w)		; push di
	move.w a4,5(a2,d4.w)		; push si
	move.w d6,($5c8b,a3)		; 2373h = list
	move.w d7,($5c85,a3)		; 2379h = n
	move.w d7,d0			; d0 = n
	move.w #$7fff,d1
	sub.w d6,d1
	lea (a3,d1.w),a0		; word at list+k: -1-k(a0)
; 1. largest y
	moveq #1,d1			; ties
	moveq #0,d3			; index
	moveq #1,d5			; masks
	move.l -7(a0),d2		; y
	lea -8(a0),a4
	lea $5c3b-2(a3),a5		; mask[1]
	moveq #1,d7
.p1:
	move.l -7(a4),d6
	cmp.l d6,d2
	bgt.s .p1next
	beq.s .p1tie
	move.l d6,d2
	moveq #1,d1
	move.w d7,d3
	move.w (a5),d5
	bra.s .p1next
.p1tie:
	addq.w #1,d1
	or.w (a5),d5
.p1next:
	subq.l #8,a4
	subq.l #2,a5
	addq.w #1,d7
	cmp.w d0,d7
	bcs.s .p1
	move.w d1,($5c41,a3)		; 23BDh
	move.w d3,($5c3d,a3)		; 23C1h
	move.w d5,($5c3f,a3)		; 23BFh
	move.w d0,($5c83,a3)		; 237Bh = n
	tst.l d2
	bpl.s .rotation
	movem.l (sp),d3			; BX unchanged
	moveq #0,d1
	swap d2
	moveq #0,d0
	bra .done
.rotation:
	cmp.w #1,d1
	beq.s .rotate			; r = index
	cmp.w d0,d1
	bne.s .ties
	move.w d0,(-$43fe,a3)		; C3FCh = n
	move.w d0,d6
	lsl.w #4,d6
	or.w #$f,d6
	move.w d6,(-$43fa,a3)		; C3F8h
	move.w d3,d1			; CX = index
	move.w d5,d3			; BX = masks
	swap d2
	moveq #1,d0
	bra .done
.ties:
	tst.w d3
	bne.s .next
	move.w d0,d6
	add.w d6,d6
	neg.w d6
	and.w ($5c3b+2,a3,d6.w),d5	; mask[n-1]
	bne.s .phase2
.next:
	addq.w #1,d3			; r = index + 1 (<= n)
.rotate:
	tst.w d3
	beq.s .phase2
	move.w #0,($5b5d,a3)		; 24A1h = 0
	move.w d3,d6
	lsl.w #3,d6
	neg.w d6
	lea 8(a0,d6.w),a4		; vertex r-1: y at -7(a4), x at -3(a4)
	move.l -3(a4),($5c73,a3)	; 238Bh:2389h = x
	move.l -7(a4),($5c6f,a3)	; 238Fh:238Dh = y
	; rotate left by r: copy the list (vertex i at 8(n-1-i) in the copy),
	; then write vertex (j+r) mod n to j
	move.w d0,d6
	lsl.w #3,d6
	movea.l a0,a1
	suba.w d6,a1
	addq.l #1,a1			; list bottom: vertex n-1
	suba.w d6,sp
	movea.l sp,a4
	move.w d0,d7
	subq.w #1,d7
.save:
	move.l (a1)+,(a4)+
	move.l (a1)+,(a4)+
	dbra d7,.save
	moveq #0,d7			; j
	move.w d3,d1			; (j + r) mod n
	cmp.w d0,d1
	bcs.s .put
	moveq #0,d1
.put:
	move.w d0,d6
	subq.w #1,d6
	sub.w d1,d6
	lsl.w #3,d6
	lea (sp,d6.w),a1
	move.w d7,d6
	lsl.w #3,d6
	neg.w d6
	lea -7(a0,d6.w),a4
	move.l (a1)+,(a4)+
	move.l (a1),(a4)
	addq.w #1,d1
	cmp.w d0,d1
	bcs.s .wrap
	moveq #0,d1
.wrap:
	addq.w #1,d7
	cmp.w d0,d7
	bcs.s .put
	move.w d0,d6
	lsl.w #3,d6
	adda.w d6,sp
; 3. smallest y of vertices 1..n-1
.phase2:
	lea -8(a0),a4
	move.l -7(a4),d2
	moveq #1,d1			; index
	moveq #2,d7
	bra.s .p2next
.p2:
	subq.l #8,a4
	move.l -7(a4),d6
	cmp.l d6,d2
	ble.s .p2skip
	move.l d6,d2
	move.w d7,d1
.p2skip:
	addq.w #1,d7
.p2next:
	cmp.w d0,d7
	bcs.s .p2
	move.w d0,d3
	lsl.w #3,d3			; BX = 8n
	tst.l d2
	bmi.s .p3
	swap d2
	tst.w d2
	bne.s .zero
	swap d2
	cmp.w ($5cc6,a3),d2		; 2338h, signed
	bge.s .zerolo
.p3:
	move.w d0,(-$43fe,a3)		; C3FCh = n
	move.w d0,d6
	lsl.w #4,d6
	or.w d1,d6
	move.w d6,(-$43fa,a3)		; C3F8h
; 4. smallest x, then largest x
	move.l -3(a0),d2
	lea -3-8(a0),a4
	move.w d0,d7
	subq.w #2,d7
.p4:
	move.l (a4),d6
	cmp.l d6,d2
	ble.s .p4skip
	move.l d6,d2
.p4skip:
	subq.l #8,a4
	dbra d7,.p4
	tst.l d2
	bmi.s .p5
	swap d2
	tst.w d2
	bne.s .zero
	swap d2
	cmp.w ($5cc2,a3),d2		; 233Ch, unsigned
	bcc.s .zerolo
.p5:
	move.l -3(a0),d2
	lea -3-8(a0),a4
	move.w d0,d7
	subq.w #2,d7
.p6:
	move.l (a4),d6
	cmp.l d6,d2
	bge.s .p6skip
	move.l d6,d2
.p6skip:
	subq.l #8,a4
	dbra d7,.p6
	moveq #0,d0
	tst.l d2
	bmi.s .p7
	moveq #1,d0
.p7:
	swap d2
	moveq #0,d1
	bra.s .done
.zerolo:
	swap d2
.zero:
	moveq #0,d0
	moveq #0,d1
.done:
	addq.l #4,sp			; entry BX
	movem.l (sp)+,d5/a1/a4/a5
	moveq #1,d7
	rts
.decline:
	moveq #0,d7
	rts
