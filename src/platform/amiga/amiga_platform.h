#ifndef SWOTL_AMIGA_PLATFORM_H
#define SWOTL_AMIGA_PLATFORM_H

#ifdef __cplusplus
extern "C" {
#endif

/* Runs the translated program from its entry until it stops; returns the
 * plat_exit code (-1: no memory). Needs the OS (dos.library): call it before
 * the display takeover. */
long amiga_run_guest(void);

#ifdef __cplusplus
}
#endif

#endif
