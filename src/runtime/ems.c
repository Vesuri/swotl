/* INT 67h EMS 4.0 as the reference machine answers it
 * (docs/external-surface.md). */
#include "runtime.h"

#define EMS_FRAME 0xe000
#define EMS_HANDLES 16
#define EMS_PHYS 4

/* Logical pages live in the store after guest RAM (RT_EMS_BYTES); a mapped
 * page is copied into the frame and back out when its frame page is
 * remapped, as host bytes of a frame page span (runtime.h). A page mapped at two frame pages is two copies (writes through
 * one are not seen through the other): the game's only map site (SWOTL+04918)
 * slides a 4-page window, which aliases one page only until the next call. */
static uint16_t ems_free = RT_EMS_PAGES;
static uint16_t ems_handles = 1;  /* handle 0 is the operating system's */
static uint16_t first_page[EMS_HANDLES], pages[EMS_HANDLES];
static struct { uint16_t handle, page; } mapped[EMS_PHYS];

static uint8_t *store(uint16_t handle, uint16_t page)
{
    return rt_guest + RT_GUEST_BYTES + (uint32_t)(first_page[handle] + page) * RT_EMS_PAGE;
}

static uint8_t *frame_page(uint8_t phys)
{
    return rt_span(lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE, RT_EMS_PAGE);
}

static void copy(uint8_t *d, const uint8_t *s)
{
    for (uint32_t k = 0; k < RT_EMS_PAGE; ++k) {
        d[k] = s[k];
    }
}

static uint8_t map(uint8_t phys, uint16_t page, uint16_t handle)
{
    if (phys >= EMS_PHYS) {
        return 0x8b;
    }
    if (page != 0xffff && (handle == 0 || handle >= ems_handles)) {
        return 0x83;
    }
    if (page != 0xffff && page >= pages[handle]) {
        return 0x8a;
    }
    uint8_t *frame = frame_page(phys);
    if (mapped[phys].handle) {
        copy(store(mapped[phys].handle, mapped[phys].page), frame);
        mapped[phys].handle = 0;
    }
    if (page == 0xffff) {
        return 0;
    }
    for (int k = 0; k < EMS_PHYS; ++k) {
        if (mapped[k].handle == handle && mapped[k].page == page) {
            copy(store(handle, page), frame_page(k));
        }
    }
    copy(frame, store(handle, page));
    mapped[phys].handle = handle;
    mapped[phys].page = page;
    return 0;
}

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
        rt_r.dx = RT_EMS_PAGES;
        break;
    case 0x43:  /* allocate BX pages */
        if (rt_r.bx > ems_free || ems_handles == EMS_HANDLES) {
            SET_AH(rt_r.ax, rt_r.bx > ems_free ? 0x88 : 0x85);
            return;
        }
        first_page[ems_handles] = RT_EMS_PAGES - ems_free;
        pages[ems_handles] = rt_r.bx;
        ems_free -= rt_r.bx;
        rt_r.dx = ems_handles++;
        break;
    case 0x44:  /* map logical page BX of handle DX at frame page AL */
        SET_AH(rt_r.ax, map(AL(rt_r.ax), rt_r.bx, rt_r.dx));
        return;
    default:
        rt_unsupported("EMS function", 0x67, 0, 0);
    }
    SET_AH(rt_r.ax, 0);
}
