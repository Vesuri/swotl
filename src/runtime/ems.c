/* INT 67h EMS 4.0 as the reference machine answers it
 * (docs/external-surface.md). */
#include "runtime.h"

#define EMS_FRAME 0xe000
#define EMS_HANDLES 16
#define EMS_PHYS 4

/* Store pages live after the state block (RT_EMS_BYTES); a mapped page is
 * copied into the frame and back out when its frame page is remapped, as host
 * bytes of a frame page span (runtime.h). A page mapped at two frame pages is
 * two copies (writes through one are not seen through the other): the game's
 * only map site (SWOTL+04918) slides a 4-page window, which aliases one page
 * only until the next call. Handles take store pages as DOSBox-X's
 * MEM_AllocatePages does, so after a release a handle's pages can be split
 * across free runs; a release leaves the frame mapped (tests/test_ems.py). */
#if RT_EMS_PAGES > 256
#error "store page numbers are bytes"
#endif
static uint16_t ems_free = RT_EMS_PAGES;
static uint16_t pages[EMS_HANDLES];   /* 0: free; handle 0 is the operating system's */
static uint8_t page_of[EMS_HANDLES][RT_EMS_PAGES], used[RT_EMS_PAGES];
static uint16_t mapped[EMS_PHYS];     /* store page + 1, 0: none */

static uint8_t *store(uint16_t slot)
{
    return rt_guest + 1 + RT_STATE_BYTES + (uint32_t)(slot - 1) * RT_EMS_PAGE;
}

/* DOSBox-X BestMatch(1): the first free run of one page, else the first of
 * the shortest; RT_EMS_PAGES when none. *largest: the longest run. */
static uint16_t free_run(uint16_t *largest)
{
    uint16_t at = RT_EMS_PAGES, best = 0xffff, k = 0;
    *largest = 0;
    while (k < RT_EMS_PAGES) {
        uint16_t first = k;
        while (k < RT_EMS_PAGES && !used[k]) {
            ++k;
        }
        uint16_t n = k - first;
        if (n > *largest) {
            *largest = n;
        }
        if (n && n < best) {
            best = n;
            at = first;
        }
        k += k < RT_EMS_PAGES;
    }
    return at;
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
    if (page != 0xffff && (handle == 0 || handle >= EMS_HANDLES || !pages[handle])) {
        return 0x83;
    }
    if (page != 0xffff && page >= pages[handle]) {
        return 0x8a;
    }
    uint16_t slot = page == 0xffff ? 0 : page_of[handle][page] + 1;
    uint8_t *frame = frame_page(phys);
    if (slot && mapped[phys] == slot) {
        /* Write-back then reload of the same page leaves the frame unchanged
         * (every remap writes back before the store is read), unless another
         * frame page holds an alias whose bytes the reload would bring in. */
        int alias = 0;
        for (int k = 0; k < EMS_PHYS; ++k) {
            alias |= k != phys && mapped[k] == slot;
        }
        if (!alias) {
            return 0;
        }
    }
    if (mapped[phys]) {
        copy(store(mapped[phys]), frame);
        mapped[phys] = 0;
    }
    if (!slot) {
        return 0;
    }
    for (int k = 0; k < EMS_PHYS; ++k) {
        if (mapped[k] == slot) {
            copy(store(slot), frame_page(k));
        }
    }
    rt_wrote(lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE, RT_EMS_PAGE);
    copy(frame, store(slot));
    mapped[phys] = slot;
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
    case 0x42:  /* free pages, and in DX the longest free run (DOSBox-X's "total") */
        rt_r.bx = ems_free;
        free_run(&rt_r.dx);
        break;
    case 0x43: {  /* allocate BX pages; 16 handles (DOSBox-X 200, the game opens 3) */
        uint16_t h = 1, n = rt_r.bx, largest;
        while (h < EMS_HANDLES && pages[h]) {
            ++h;
        }
        if (!n || n > ems_free || h == EMS_HANDLES) {
            SET_AH(rt_r.ax, !n ? 0x89 : n > ems_free ? 0x88 : 0x85);
            return;
        }
        for (uint16_t p = 0; p < n;) {
            for (uint16_t k = free_run(&largest); p < n && k < RT_EMS_PAGES && !used[k]; ++k) {
                used[k] = 1;
                page_of[h][p++] = (uint8_t)k;
            }
        }
        pages[h] = n;
        ems_free -= n;
        rt_r.dx = h;
        break;
    }
    case 0x44:  /* map logical page BX of handle DX at frame page AL */
        SET_AH(rt_r.ax, map(AL(rt_r.ax), rt_r.bx, rt_r.dx));
        return;
    case 0x45:  /* release handle DX; its frame pages stay mapped */
        if (rt_r.dx == 0) {     /* DOSBox-X frees the OS's pages, outside the store */
            rt_unsupported("EMS release of handle 0", 0x67, 0, 0);
            return;
        }
        if (rt_r.dx >= EMS_HANDLES || !pages[rt_r.dx]) {
            SET_AH(rt_r.ax, 0x83);
            return;
        }
        for (uint16_t p = 0; p < pages[rt_r.dx]; ++p) {
            used[page_of[rt_r.dx][p]] = 0;
        }
        ems_free += pages[rt_r.dx];
        pages[rt_r.dx] = 0;
        break;
    default:
        rt_unsupported("EMS function", 0x67, 0, 0);
    }
    SET_AH(rt_r.ax, 0);
}
