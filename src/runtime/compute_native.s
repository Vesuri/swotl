; Rebuilt with each normal/diagnostic generated poll contract.
	include "native_polls.i"
	section .text,code
	ifd NATIVE_rt_hle_sprite_packet
	include "compute_sprite.s"
	endif
