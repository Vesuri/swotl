#include <proto/exec.h>
#include <proto/cia.h>
#include <exec/interrupts.h>
#include <hardware/cia.h>
#include <resources/cia.h>
extern "C" {
#include "runtime.h"
#include "platform.h"
#ifdef SWOTL_REPLAY
uint32_t replay_mouse(int32_t*, int32_t*);
#endif
}
#include "Input.h"
#include "AmigaHardware.h"

// Raw keys to PC set 1 scan codes (US positions; RT_KEY_E0 for the grey
// keys). Caps Lock reports its lock state, so both of its edges are a PC make
// and break (one toggle each).
#define E0 RT_KEY_E0
static const uint16_t rawToScan[0x68] = {
    /* 00 */ 0x29, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x2b, 0, 0x52,
    /* 10 */ 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0, 0x4f, 0x50, 0x51,
    /* 20 */ 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0, 0, 0x4b, 0x4c, 0x4d,
    /* 30 */ 0, 0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0, 0x53, 0x47, 0x48, 0x49,
    /* 40 */ 0x39, 0x0e, 0x0f, E0 | 0x1c, 0x1c, 0x01, E0 | 0x53, 0, 0, 0, 0x4a, 0,
             E0 | 0x48, E0 | 0x50, E0 | 0x4d, E0 | 0x4b,
    /* 50 */ 0x3b, 0x3c, 0x3d, 0x3e, 0x3f, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, E0 | 0x35, 0x37, 0x4e, 0,
    /* 60 */ 0x2a, 0x36, 0x3a, 0x1d, 0x38, E0 | 0x38, 0, 0,
};
#define CAPS_LOCK 0x62

// PC typematic defaults: the held key repeats after 500 ms at 10.9 per
// second; fields are 1/50 s.
#define REPEAT_DELAY_FIELDS 25
#define REPEAT_RATE_TENTHS 109
#define FIELD_TENTHS 500

extern "C" {
volatile uint32_t amiga_mouse_reads = 0;    // plat_mouse calls: the guest's INT 33h requests
volatile uint32_t amiga_unmapped_keys = 0;  // raw keys with no PC scan code
}

static struct Library* ciaaBase = 0;
static struct Interrupt keyboardInterrupt;
static struct Interrupt* savedKeyboardInterrupt = 0;
static uint8_t repeatKey = 0xff;
static uint16_t repeatDelay = 0;
static uint16_t repeatPhase = 0;
static uint8_t mouseCounterX = 0;
static uint8_t mouseCounterY = 0;
static int32_t mouseDX = 0;
static int32_t mouseDY = 0;
static uint8_t mouseButtons = 0;
static uint8_t scriptButtons = 0;

static void post(uint16_t scan)
{
    Disable();                      // the rings are shared with the PIT interrupt
    rt_key_ring[rt_key_tail % RT_KEY_RING] = scan;
    ++rt_key_tail;
    rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = (scan & 0x80) ? 0x89 : 0x09;
    ++rt_irq_tail;
    RT_RAISE_IRQ();
    Enable();
}

void Input::key(uint8_t raw, bool up)
{
    uint16_t scan = raw < sizeof rawToScan / sizeof rawToScan[0] ? rawToScan[raw] : 0;
    if (!scan) {
        ++amiga_unmapped_keys;
        return;
    }
    Disable();
    if (raw == CAPS_LOCK) {
        post(scan);
        post(scan | 0x80);
    } else if (up) {
        post(scan | 0x80);
        if (raw == repeatKey) {
            repeatKey = 0xff;
        }
    } else {
        post(scan);
        repeatKey = raw;
        repeatDelay = REPEAT_DELAY_FIELDS;
        repeatPhase = 0;
    }
    Enable();
}

// CIA-A serial port: code = ROR(~SDR, 1); the handshake holds SPMODE output
// for about 85 us (L72).
static uint32_t keyboardHandler()
{
    uint8_t code = (uint8_t)~*ciaasdrPointer;
    *ciaacraPointer |= CIACRAF_SPMODE;
    for (volatile uint16_t delay = 0; delay < 200; ++delay) {
    }
    *ciaacraPointer &= (uint8_t)~CIACRAF_SPMODE;
    code = (uint8_t)((code >> 1) | (code << 7));
    Input::key((uint8_t)(code & 0x7f), (code & 0x80) != 0);
    return 0;
}

bool Input::begin()
{
#ifdef SWOTL_REPLAY
    return true; // Diagnostic events come from the original reference only.
#endif
    repeatKey = 0xff;
    mouseDX = mouseDY = 0;
    mouseButtons = scriptButtons = 0;
    uint16_t counters = *joy0datPointer;
    mouseCounterX = (uint8_t)counters;
    mouseCounterY = (uint8_t)(counters >> 8);
    // Pot pins as inputs, so POTINP reports the right and middle buttons (L79).
    *potgoPointer = 0;

    ciaaBase = (struct Library*)OpenResource((CONST_STRPTR)CIAANAME);
    if (!ciaaBase) {
        return false;
    }
    keyboardInterrupt.is_Node.ln_Type = NT_INTERRUPT;
    keyboardInterrupt.is_Node.ln_Pri = 0;
    keyboardInterrupt.is_Node.ln_Name = (char*)"SWOTL keyboard";
    keyboardInterrupt.is_Data = 0;
    keyboardInterrupt.is_Code = (void (*)())keyboardHandler;
    savedKeyboardInterrupt = AddICRVector(ciaaBase, CIAICRB_SP, &keyboardInterrupt);
    if (savedKeyboardInterrupt) {
        RemICRVector(ciaaBase, CIAICRB_SP, savedKeyboardInterrupt);
        AddICRVector(ciaaBase, CIAICRB_SP, &keyboardInterrupt);
    }
    return true;
}

void Input::end()
{
    if (!ciaaBase) {
        return;
    }
    RemICRVector(ciaaBase, CIAICRB_SP, &keyboardInterrupt);
    if (savedKeyboardInterrupt) {
        AddICRVector(ciaaBase, CIAICRB_SP, savedKeyboardInterrupt);
        savedKeyboardInterrupt = 0;
    }
    ciaaBase = 0;
}

// JOY0DAT's counters are 8 bits and wrap: the delta is taken every field
// (L80). Buttons: left CIA-A PRA bit 6, right and middle POTINP bits 10 and 8.
void Input::verticalBlank()
{
#ifdef SWOTL_REPLAY
    return;
#endif
    uint16_t counters = *joy0datPointer;
    uint8_t x = (uint8_t)counters, y = (uint8_t)(counters >> 8);
    uint8_t buttons = (uint8_t)((AmigaHardware::isLeftMouseButtonPressed() ? 1 : 0) |
                                (AmigaHardware::isRightMouseButtonPressed() ? 2 : 0) |
                                (*potinpPointer & (1 << 8) ? 0 : 4));
    Disable();
    mouseDX += (int8_t)(x - mouseCounterX);
    mouseDY += (int8_t)(y - mouseCounterY);
    mouseButtons = buttons;
    Enable();
    mouseCounterX = x;
    mouseCounterY = y;

    if (repeatKey != 0xff) {
        if (repeatDelay) {
            --repeatDelay;
        } else if ((repeatPhase += REPEAT_RATE_TENTHS) >= FIELD_TENTHS) {
            repeatPhase -= FIELD_TENTHS;
            post(rawToScan[repeatKey]);
        }
    }
}

void Input::moveMouse(int16_t dx, int16_t dy)
{
    Disable();
    mouseDX += dx;
    mouseDY += dy;
    Enable();
}

void Input::setScriptButtons(uint8_t buttons)
{
    scriptButtons = buttons;
}

extern "C" uint32_t plat_mouse(int32_t* dx, int32_t* dy)
{
#ifdef SWOTL_REPLAY
    return replay_mouse(dx, dy);
#endif
    Disable();
    *dx = mouseDX;
    *dy = mouseDY;
    mouseDX = mouseDY = 0;
    uint32_t buttons = mouseButtons | scriptButtons;
    Enable();
    ++amiga_mouse_reads;
    return buttons;
}

extern "C" void amiga_key(int raw, int up)
{
    Input::key((uint8_t)raw, up != 0);
}

extern "C" void amiga_mouse_move(int16_t dx, int16_t dy)
{
    Input::moveMouse(dx, dy);
}

extern "C" void amiga_mouse_script_buttons(uint32_t buttons)
{
    Input::setScriptButtons((uint8_t)buttons);
}
