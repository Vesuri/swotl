#ifndef _SWOTL_H
#define _SWOTL_H

#include <exec/interrupts.h>
#include "Util.h"

class Bitmap;
class CopperList;
struct View;
struct DisplayState;
struct plat_rect;

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
    // Called from the SOFTINT vector after each vertical blank (the field task).
    void field();

    // DOS calls between these get the OS's interrupts and multitasking back;
    // the display stays. Nest; no-ops outside the takeover.
    void beginIO();
    void endIO();

    void setPalette(const uint8_t* dac);
    void present(const uint8_t* frame, const struct plat_rect* rects, int32_t n);

    // The display and I/O windows (set by the constructor); the VERTB
    // handler's owner (set at the takeover).
    static Swotl* application;
    static Swotl* active;

private:
    void takeOver();
    void handBack();
    void takeVectors();
    void restoreVectors();
    uint16_t restoreStatus() const;

    uint16_t beginDisplayUpdate();
    void finishDisplayUpdate(uint16_t back);
    uint32_t buildPalette(uint16_t back);
    DisplayState* display;
    struct View* oldActiView;
    uint32_t* oldCopperList;
    struct IntVector oldVerticalBlankVector;
    struct IntVector oldSoftwareVector;
    uint16_t oldEnabledDMAChannels;
    uint16_t oldEnabledInterrupts;
    uint32_t ioFrames;
    uint16_t ioDepth;
    bool guestOpen;
    bool vectorTaken;
    bool runnable;
};

#endif
