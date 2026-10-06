#ifndef _SWOTL_H
#define _SWOTL_H

#include <exec/interrupts.h>
#include "Util.h"

class Bitmap;
class CopperList;
struct View;

// The Amiga application (docs/amiga-arch.md Lifecycle): everything that can
// fail is opened before the takeover; then the machine is taken from the OS
// (AGA copper display, the VERTB vector, the keyboard), the translated program
// runs to its exit, and the machine is handed back. Disk access inside the
// takeover goes through I/O windows (L7).
class Swotl {
public:
    Swotl();
    ~Swotl();

    bool isRunnable() const { return runnable; }
    void run();

    // Called from the VERTB vector (interrupt context, 50 Hz PAL).
    void verticalBlank();

    // DOS calls between these get the OS's interrupts and multitasking back;
    // the display stays. Nest; no-ops outside the takeover.
    void beginIO();
    void endIO();

    uint32_t setPalette(const uint8_t* dac);

    // The display and I/O windows (set by the constructor); the VERTB
    // handler's owner (set at the takeover).
    static Swotl* application;
    static Swotl* active;

private:
    void takeOver();
    void handBack();

    uint8_t* screenData;
    uint32_t* copperData;
    Bitmap* bitmap;
    CopperList* copperList;
    uint32_t paletteIndex;
    struct View* oldActiView;
    uint32_t* oldCopperList;
    struct IntVector oldVerticalBlankVector;
    uint16_t oldEnabledDMAChannels;
    uint16_t oldEnabledInterrupts;
    uint32_t ioFrames;
    uint16_t ioDepth;
    bool guestOpen;
    bool vectorTaken;
    bool runnable;
};

#endif
