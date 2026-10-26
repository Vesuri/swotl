; Native compute rows (annotations/hle.csv kind compute), on the generated
; state-block equates.
	include "equates.i"
	section .text,code
	include "compute_sprite.s"
	include "compute_line.s"
	include "compute_raster.s"
	include "compute_opl.s"
