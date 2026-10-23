/* INT 67h EMS 4.0 as the reference machine answers it
 * (docs/external-surface.md). */
#include "runtime.h"

#define EMS_FRAME 0xe000
#define EMS_HANDLES 16
#define EMS_PHYS 4

/* Logical pages live in the store after the state block (RT_EMS_BYTES); a mapped
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
    return rt_guest + 1 + RT_STATE_BYTES + (uint32_t)(first_page[handle] + page) * RT_EMS_PAGE;
}

static uint8_t *frame_page(uint8_t phys)
{
    return rt_span(lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE, RT_EMS_PAGE);
}

/* One page. Frame pages and the store share their address mod 4 (both are
 * rt_guest + 1 mod 4), so after the head bytes both run long-aligned. */
static void copy(uint8_t *d, const uint8_t *s)
{
    uint32_t n = RT_EMS_PAGE;
    while (n && ((uintptr_t)d & 3)) {
        *d++ = *s++;
        --n;
    }
    if (n >= 32) {
        uint16_t k = n / 32 - 1;    /* dbra count, at most 511 */
        __asm__ volatile(
            "1:\tmove.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "dbra %2,1b"
            : "+a"(s), "+a"(d), "+d"(k) : : "memory");
    }
    for (n &= 31; n; --n) {
        *d++ = *s++;
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
    if (page != 0xffff && mapped[phys].handle == handle && mapped[phys].page == page) {
        /* Write-back then reload of the same page leaves the frame unchanged
         * (every remap writes back before the store is read), unless another
         * frame page holds an alias whose bytes the reload would bring in. */
        int alias = 0;
        for (int k = 0; k < EMS_PHYS; ++k) {
            alias |= k != phys && mapped[k].handle == handle && mapped[k].page == page;
        }
        if (!alias) {
            return 0;
        }
    }
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
    rt_wrote(lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE, RT_EMS_PAGE);
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
    case 0x42:  /* unallocated / "total" pages: DOSBox-X answers the largest
                 * free block, the free count while nothing is released */
        rt_r.bx = ems_free;
        rt_r.dx = ems_free;
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
