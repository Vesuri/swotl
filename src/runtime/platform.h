/* Platform services the runtime needs: the game's files and their directory, the timer, the
 * mouse, the display of the mode 13h frame (changed rectangles, DAC), a log line and exit. Implemented by src/platform/host (Unicorn harness) and
 * src/platform/amiga (dos.library). */
#ifndef SWOTL_PLATFORM_H
#define SWOTL_PLATFORM_H

#include <stdint.h>

/* Native runtime storage; allocation failure returns null. */
void *plat_alloc(uint32_t bytes);
void plat_free(void *memory);

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
/* DOS caches the local calendar at startup: year:16, month:8, day:8. */
uint32_t plat_calendar_date(void);
/* Retain this explicit DOS timestamp when the open file is closed. */
void plat_file_stamp(int32_t handle, uint32_t dos_time, uint32_t dos_date);
/* The names of the files in directory `dir` (game-relative as above, "" the
 * game directory), up to 12 chars each, case as stored, NUL-terminated and
 * packed, in one directory pass: the bytes they need (0 for none or a missing
 * directory); only names that fit completely are written to buffer[size]. */
int32_t plat_dir_names(const char *dir, char *buffer, uint32_t size);
/* Metadata of file `path` (local calendar, DOS packed time/date); < 0 if it is
 * missing or not a file. */
struct plat_file_info { uint32_t size; uint16_t dos_time, dos_date; };
int32_t plat_file_info(const char *path, struct plat_file_info *info);
/* PIT channel 0 now fires every `divisor` input clocks (1..65536, 1193182 Hz):
 * per period the platform posts vector 08h (runtime.h rt_irq_ring). */
void plat_timer_rate(uint32_t divisor);
/* Mouse counts since the last call (right and down positive) and the
 * buttons held (bit 0 left, 1 right, 2 middle). */
uint32_t plat_mouse(int32_t *dx, int32_t *dy);
/* Publish rectangles of the 320x200 chunky frame (pixels, ends exclusive, x0
 * and x1 multiples of 32); the rest of the frame is unchanged. The platform
 * may queue the completed image for its next safe display handoff. */
struct plat_rect { uint16_t x0, y0, x1, y1; };
void plat_present(const uint8_t *frame, const struct plat_rect *rects, int32_t n);
/* The DAC changed (256 x 6-bit R, G, B). */
void plat_palette(const uint8_t *dac);
/* The platform's own work from the main program at a vertical blank. */
void plat_service(void);
/* Effect capture (runtime.h rt_sfx_*): whether to capture effect id; the
 * capture is complete. */
int plat_sfx_wanted(uint8_t id);
void plat_sfx_captured(void);
void plat_log(const char *line);
void plat_exit(int32_t code) __attribute__((noreturn));

#endif
