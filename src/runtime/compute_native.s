; Native compute rows (annotations/hle.csv kind compute), on the generated
; state-block equates.
	include "equates.i"
	section .text,code
	include "compute_sprite.s"
	include "compute_line.s"
	include "compute_raster.s"
	include "compute_edge.s"
	include "compute_opl.s"
	include "compute_classify.s"
	include "compute_ground.s"
	include "compute_terrain.s"
	include "compute_polygons.s"
