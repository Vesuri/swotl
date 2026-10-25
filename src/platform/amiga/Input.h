#ifndef _INPUT_H
#define _INPUT_H

#include "Util.h"

// Keyboard and mouse with the machine taken over (docs/amiga-lessons.md
// L72-L80): the keyboard from CIA-A's serial port and the mouse counters and
// buttons sampled at each vertical blank. Keys reach the runtime as PC set 1
// make and break codes (vector 09h), the mouse as counts plat_mouse takes.
class Input {
public:
    // Disables the keyboard interrupt (CIA-A SP) for reading at the vertical
    // blank; false if ciaa.resource is missing.
    static bool begin();
    static void end();

    // From the vertical blank: keyboard, mouse counters and buttons,
    // typematic repeat.
    static void verticalBlank();
    // From the vertical blank: a byte from the keyboard, if one arrived. Also
    // from the I/O windows' VERTB server.
    static void __attribute__((noinline)) keyboard();

    // An Amiga raw key edge, from the keyboard or a diagnostic
    // script.
    static void key(uint8_t raw, bool up);
    // Scripted mouse input (diagnostic key scripts): counts and buttons
    // added to the hardware's.
    static void moveMouse(int16_t dx, int16_t dy);
    static void setScriptButtons(uint8_t buttons);
};

#endif
