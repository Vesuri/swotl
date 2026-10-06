/* Platform services the runtime needs: the game's files and their directory, the timer, the
 * mouse, the display of the mode 13h frame (changed rectangles, DAC), a log line and exit. Implemented by src/platform/host (Unicorn harness) and
 * src/platform/amiga (dos.library). */
#ifndef SWOTL_PLATFORM_H
#define SWOTL_PLATFORM_H

#include <stdint.h>

/* path: game-relative, upper case, '/' separated ("DATA.OVL"). mode 0 read,
 * 1 write, 2 read/write (existing file). < 0 if missing. */
int32_t plat_open(const char *path, int32_t mode);
/* New empty file (an existing one is truncated), open read/write; < 0 on error. */
int32_t plat_create(const char *path);
int32_t plat_read(int32_t handle, void *buffer, uint32_t length);
/* Bytes written, < 0 on error; length 0 truncates the file at the position. */
int32_t plat_write(int32_t handle, const void *buffer, uint32_t length);
/* < 0 if missing. */
int32_t plat_delete(const char *path);
/* whence 0 start, 1 current, 2 end; returns the new position, < 0 on error */
int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence);
void plat_close(int32_t handle);
/* Entry `index` (0 first) of the files in directory `dir` (game-relative as
 * above, "" the game directory): name (up to 12 chars + NUL, case as stored)
 * and size; 0 past the last. */
int32_t plat_dir_entry(const char *dir, uint32_t index, char *name, uint32_t *size);
/* PIT channel 0 now fires every `divisor` input clocks (1..65536, 1193182 Hz):
 * per period the platform posts vector 08h (runtime.h rt_irq_ring). */
void plat_timer_rate(uint32_t divisor);
/* Mouse counts since the last call (right and down positive) and the
 * buttons held (bit 0 left, 1 right, 2 middle). */
uint32_t plat_mouse(int32_t *dx, int32_t *dy);
/* Show rectangles of the 320x200 chunky frame (pixels, ends exclusive, x0
 * and x1 multiples of 32); the rest of the shown frame is unchanged. */
struct plat_rect { uint16_t x0, y0, x1, y1; };
void plat_present(const uint8_t *frame, const struct plat_rect *rects, int32_t n);
/* The DAC changed (256 x 6-bit R, G, B). */
void plat_palette(const uint8_t *dac);
/* The platform's own work from the main program at a vertical blank. */
void plat_service(void);
void plat_log(const char *line);
void plat_exit(int32_t code) __attribute__((noreturn));

#endif
