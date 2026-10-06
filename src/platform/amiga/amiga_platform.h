#ifndef SWOTL_AMIGA_PLATFORM_H
#define SWOTL_AMIGA_PLATFORM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The translated program's lifetime (amiga_platform.c). open: dos.library,
 * the arguments, guest memory, the machine model and the PIT; 0 on failure;
 * call it before the takeover. run: from the program entry until it stops;
 * returns the plat_exit code. close: after the hand-back. */
int amiga_guest_open(void);
long amiga_guest_run(void);
void amiga_guest_close(void);

/* An I/O window around DOS calls (Swotl.cpp); nests, no-op outside the
 * takeover. */
void amiga_io_begin(void);
void amiga_io_end(void);

/* Keyboard and mouse input from the diagnostic key script (Input.cpp): an
 * Amiga raw key edge, mouse counts, the script's held buttons (bit 0 left,
 * 1 right). */
void amiga_key(int raw, int up);
void amiga_mouse_move(int16_t dx, int16_t dy);
void amiga_mouse_script_buttons(uint32_t buttons);

extern volatile uint32_t amiga_frames;
extern volatile uint32_t amiga_mouse_reads;

#ifdef __cplusplus
}
#endif

#endif
