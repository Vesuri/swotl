; Rebuilt with each normal/diagnostic generated poll contract.
	include "native_polls.i"
	section .text,code
	ifd NATIVE_rt_hle_sprite_packet
	include "compute_sprite.s"
	endif

	ifd NATIVE_rt_hle_line_right
	include "compute_line.s"
	endif

	ifd NATIVE_rt_hle_rasterize
	include "compute_raster.s"
	endif

	ifd NATIVE_rt_hle_opl_wait_index
	include "compute_opl.s"
	endif
