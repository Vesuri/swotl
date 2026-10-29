#ifndef SWOTL_AMIGA_PLATFORM_H
#define SWOTL_AMIGA_PLATFORM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The Workbench start message (start.c), 0 from a Shell or the slave. */
struct WBStartup;
extern struct WBStartup *amiga_wb_startup;

/* The translated program's lifetime (amiga_platform.c). open: dos.library,
 * the arguments (from Workbench the icon's tool types and drawer), guest
 * memory, the machine model and the PIT; 0 on failure; call it before the
 * takeover. run: from the program entry until it stops;
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

/* The FM re-hoster's next commands (Audio.cpp), from plat_service. */
void amiga_audio_service(void);

/* 1 for an NTSC display (60 Hz fields, NTSC clocks), from graphics'
 * DisplayFlags at Swotl's open: the mode LoadView(NULL) gives at the
 * takeover, whatever the Workbench screen's. Display, CIA timer, FM, TFH
 * and key repeat follow it. */
extern uint8_t amiga_ntsc;
/* Beam line of the display's first row (Swotl.cpp window, Pointer.cpp
 * sprites): PAL $38; NTSC $2C, the standard 200-line window $2C-$F4. */
#define AMIGA_TOP_LINE (amiga_ntsc ? 0x2c : 0x38)

extern volatile uint32_t amiga_frames;
extern volatile uint32_t amiga_io_frames;
extern volatile uint32_t amiga_mouse_reads;

#ifdef __cplusplus
}
#endif

#endif
