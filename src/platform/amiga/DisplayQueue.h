#ifndef SWOTL_DISPLAY_QUEUE_H
#define SWOTL_DISPLAY_QUEUE_H

#include <stdint.h>

// Main-thread dirty state for both physical bitmaps. The ISR only changes
// shown/pending. Call begin(), queue() and flip() with interrupts excluded.
// Withdrawing pending before conversion lets updates coalesce without ever
// writing the bitmap DMA is reading, or waiting before a guest poll point.
struct DisplayQueue {
    struct Row { uint16_t lo, hi; } rows[2][200] = {};
    volatile uint16_t shown = 0;
    volatile int16_t pending = -1;

    uint16_t begin() {
        pending = -1;
        return shown ^ 1;
    }
    void mark(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {
        for (unsigned b = 0; b < 2; ++b) {
            for (unsigned y = y0; y < y1; ++y) {
                Row& r = rows[b][y];
                if (!r.hi || x0 < r.lo) r.lo = x0;
                if (x1 > r.hi) r.hi = x1;
            }
        }
    }
    void clear(uint16_t b, uint16_t y) { rows[b][y].hi = 0; }
    void queue(uint16_t b) { pending = (int16_t)b; }
    int16_t flip() {
        int16_t b = pending;
        if (b >= 0) {
            shown = (uint16_t)b;
            pending = -1;
        }
        return b;
    }
};
#endif
