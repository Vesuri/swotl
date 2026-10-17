; Diagnostic hooks preserve the live native registers and CCR. Guest IRQs
; execute through the production rt_irq path, including its return checks.
	xdef rt_replay_point,rt_replay_enter,rt_replay_return,rt_replay_done
	xref replay_point,replay_next,replay_enter,replay_return
	xref replay_cs,replay_ip,rt_irq
	section .text,code
rt_replay_enter:
	move.w ccr,-(sp)
	movem.l d0-d7/a0-a6,-(sp)
	pea (sp)
	jsr replay_enter
	addq.l #4,sp
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
	rts
rt_replay_return:
	move.w ccr,-(sp)
	movem.l d0-d7/a0-a6,-(sp)
	pea (sp)
	jsr replay_return
	addq.l #4,sp
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
	rts
rt_replay_point:
	move.w ccr,-(sp)
	movem.l d0-d7/a0-a6,-(sp)
	move.l 66(sp),-(sp)
	jsr replay_point
	addq.l #4,sp
	tst.l d0
	bmi .done
	beq .return
	; Keep this invocation's group token beneath saved guest registers.
	move.l d0,66(sp)
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
.deliver:
	movem.l d6-d7,-(sp)
	move.l replay_cs,d6
	swap d6
	move.l replay_ip,d7
	jsr rt_irq
	movem.l (sp)+,d6-d7
	move.w ccr,-(sp)
	movem.l d0-d7/a0-a6,-(sp)
	move.l 66(sp),-(sp)
	jsr replay_next
	addq.l #4,sp
	tst.l d0
	beq .irq_return
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
	bra .deliver
.return:
	clr.l 66(sp) ; no IRQ: the guarded-copy continuation remains valid
	bra.s .restore
.irq_return:
	move.l #1,66(sp) ; tell generated copy hooks to take the exact continuation
.restore:
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
	rts
.done:
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
; Hold the recorded final guest state while the real VBI publishes its queued
; frame. Returning here would execute unrecorded guest code during the capture.
rt_replay_done:
	bra.s rt_replay_done

	xdef rt_replay_rep
	xref replay_rep
rt_replay_rep:
	move.w ccr,-(sp)
	movem.l d0-d7/a0-a6,-(sp)
	pea (sp)
	move.l 74(sp),-(sp)
	move.l 74(sp),-(sp)
	jsr replay_rep
	lea 12(sp),sp
	move.l d0,66(sp)
	movem.l (sp)+,d0-d7/a0-a6
	move.w (sp)+,ccr
	rts
