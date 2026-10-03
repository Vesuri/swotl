/* Platform services the runtime needs: read-only data files, the display of
 * the mode 13h frame, a log line and exit. Implemented by src/platform/host (Unicorn harness) and
 * src/platform/amiga (dos.library). */
#ifndef SWOTL_PLATFORM_H
#define SWOTL_PLATFORM_H

#include <stdint.h>

/* path: game-relative, upper case, '/' separated ("DATA.OVL"). < 0 if missing. */
int32_t plat_open(const char *path);
int32_t plat_read(int32_t handle, void *buffer, uint32_t length);
/* whence 0 start, 1 current, 2 end; returns the new position, < 0 on error */
int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence);
void plat_close(int32_t handle);
/* Show the 320x200 chunky frame with its DAC (256 x 6-bit R, G, B). */
void plat_present(const uint8_t *frame, const uint8_t *dac);
void plat_log(const char *line);
void plat_exit(int32_t code) __attribute__((noreturn));

#endif
