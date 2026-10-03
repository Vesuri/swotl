; Host platform for tests/host_run.py (Unicorn 68020): the harness hooks the
; first instruction of each plat_* stub, performs the call (arguments on the
; stack, 68020 C ABI), sets d0 and lets the stub return.

	xdef	_start
	xdef	plat_open
	xdef	plat_read
	xdef	plat_seek
	xdef	plat_close
	xdef	plat_log
	xdef	plat_exit
	xdef	host_stubs
	xdef	host_stubs_end
	xref	host_main

	section	.text,code

_start:
	jsr	host_main
	illegal

host_stubs:
plat_open:	nop
	rts
plat_read:	nop
	rts
plat_seek:	nop
	rts
plat_close:	nop
	rts
plat_log:	nop
	rts
plat_exit:	nop
	illegal
host_stubs_end:
