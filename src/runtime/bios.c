/* INT 10h video BIOS and INT 67h EMS 4.0 as the reference machine answers
 * them (docs/external-surface.md). */
#include "runtime.h"

void rt_int10(void)
{
    switch (AH(rt_r.ax)) {
    case 0x0f:  /* current mode, columns, page */
        rt_r.ax = (uint16_t)(rd8(0x44a) << 8 | rd8(0x449));
        SET_AH(rt_r.bx, rd8(0x462));
        break;
    default:
        rt_unsupported("video BIOS function", 0x10, 0, 0);
    }
}

#define EMS_FRAME 0xe000
#define EMS_PAGES 0x00a4        /* reference: 16 KiB pages (memsize = 4) */

static uint16_t ems_free = EMS_PAGES;
static uint16_t ems_handles = 1;  /* handle 0 is the operating system's */

void rt_int67(void)
{
    switch (AH(rt_r.ax)) {
    case 0x40:  /* status */
        break;
    case 0x41:  /* page frame segment */
        rt_r.bx = EMS_FRAME;
        break;
    case 0x42:  /* unallocated / total pages */
        rt_r.bx = ems_free;
        rt_r.dx = EMS_PAGES;
        break;
    case 0x43:  /* allocate BX pages */
        if (rt_r.bx > ems_free) {
            SET_AH(rt_r.ax, 0x88);
            return;
        }
        ems_free -= rt_r.bx;
        rt_r.dx = ems_handles++;
        break;
    default:
        rt_unsupported("EMS function", 0x67, 0, 0);
    }
    SET_AH(rt_r.ax, 0);
}
