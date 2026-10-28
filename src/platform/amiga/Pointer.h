#ifndef _POINTER_H
#define _POINTER_H

#include "Util.h"

// The guest's pointer as AGA sprites (docs/pointer-plan.md): sprite 6 draws the
// shape's FEh pixels (colour 2: entry FEh), sprite 4 its other colour (colour
// 1: entry F9h, which then holds that colour), BPLCON4 bank F. Each display
// buffer has its own sprite data, written with that buffer's frame; the
// vertical blank writes the shown buffer's position (guest position + lead +
// hotspot) and visibility (rt_pointer_visible).
class Pointer {
public:
    // Chip RAM for both buffers' sprites and the empty sprite (before the
    // takeover); false if there is none.
    static bool begin();
    static void end();

    // Buffer b's eight SPRxPT moves at list[at]; returns the next index.
    static uint32_t copper(uint32_t* list, uint32_t at, uint16_t b);
    // Main thread, the back buffer b of this present: its pointer state from
    // rt_pointer, the sprite data if its shape changed.
    static void present(uint16_t b);
    // The colour entry F9h holds in buffer b's palette, -1 for none.
    static int16_t stolen(uint16_t b);
    // Vertical blank, buffer b shown; dx, dy the mouse counts INT 33h has
    // not taken.
    static void verticalBlank(uint16_t b, int32_t dx, int32_t dy);
};

#endif
