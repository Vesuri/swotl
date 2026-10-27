/* Host platform entry and the C library pieces gcc may call. */
#include <stddef.h>
#include <stdint.h>
#include "runtime.h"
#include "platform.h"

void rt_run_guest(void);

/* Guest RAM, state block and EMS store of the harness memory map
 * (tests/host_run.py BLOCK). */
#define HOST_BLOCK ((uint8_t *)0x00400000)

void host_main(void)
{
    rt_pointer_sprite = 1;      /* the harness models the sprites (tests/host_run.py) */
    rt_start(HOST_BLOCK);
    rt_run_guest();
    rt_stop("guest returned from its entry", 0, 0);
}

void *memcpy(void *d, const void *s, size_t n)
{
    uint8_t *p = d;
    const uint8_t *q = s;
    while (n--) {
        *p++ = *q++;
    }
    return d;
}

void *memset(void *d, int c, size_t n)
{
    uint8_t *p = d;
    while (n--) {
        *p++ = (uint8_t)c;
    }
    return d;
}
