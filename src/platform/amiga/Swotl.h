#ifndef _SWOTL_H
#define _SWOTL_H

#include <exec/interrupts.h>
#include "Util.h"

class Bitmap;
class CopperList;
struct View;

// The Amiga application: takes the AGA display over from the OS, shows a
// 320x200 eight-plane screen until the left mouse button is pressed, and hands
// the display back. The translated game and its runtime services will hang off
// this class.
class Swotl {
public:
    Swotl();
    ~Swotl();

    bool isRunnable() const { return runnable; }
    void run();

    // Called from the VERTB vector (interrupt context, 50 Hz PAL).
    void verticalBlank();

    static volatile uint16_t vbiCount;

private:
    uint8_t* screenData;
    uint32_t* copperData;
    Bitmap* bitmap;
    CopperList* copperList;
    struct View* oldActiView;
    uint32_t* oldCopperList;
    struct IntVector oldVerticalBlankVector;
    uint16_t oldEnabledDMAChannels;
    uint16_t oldEnabledInterrupts;
    bool vectorTaken;
    bool active;
    bool runnable;
    volatile bool quit;
};

#endif
