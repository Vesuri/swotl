#include <proto/exec.h>
#include <proto/graphics.h>
#include <exec/execbase.h>
#include <exec/interrupts.h>
#include <exec/memory.h>
#include <graphics/gfx.h>
#include <graphics/gfxbase.h>
#include <hardware/dmabits.h>
#include <hardware/intbits.h>
extern "C" {
#include "runtime.h"
#include "platform.h"
#include "amiga_platform.h"
}
#include "Swotl.h"
#include "Input.h"
#include "AmigaHardware.h"
#include "Bitmap.h"
#include "CopperList.h"
#include "Palette24Bit.h"

extern struct ExecBase* SysBase;
extern struct GfxBase* GfxBase;

#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define SCREEN_PLANES 8
#define PLANE_BYTES (SCREEN_WIDTH / 8 * SCREEN_HEIGHT)
#define SCREEN_BYTES (PLANE_BYTES * SCREEN_PLANES)
#define COPPER_LONGS 600

#define DMA_ALL (DMAF_ALL | DMAF_MASTER | DMAF_BLITHOG)

// The interrupts the takeover runs on: our VERTB vector, Exec's PORTS chain
// (keyboard through ciaa.resource, L13) and EXTER (the PIT on a CIA-B timer).
#define TAKEOVER_INTERRUPTS (INTF_INTEN | INTF_VERTB | INTF_PORTS | INTF_EXTER)

// The frame as shown (tests/host_run.py --amiga and amiga/display_audit.gdb
// read them back through the GDB fixture): the bitplanes, and the colour
// table in LoadRGB32 layout from which the copper palette is built.
extern "C" {
struct BitMap amiga_bitmap;
uint32_t amiga_colours[1 + 256 * 3 + 1];
volatile uint32_t amiga_frames = 0;    // vertical blanks since the takeover (debug fixtures)
volatile uint32_t amiga_io_frames = 0; // of those, inside I/O windows (host-timed disk I/O)
}

Swotl* Swotl::application = 0;
Swotl* Swotl::active = 0;

static struct Interrupt vbiInterrupt;

// Owns the level-3 VERTB vector, so it acknowledges INTREQ itself (L11).
static uint32_t vbiHandler()
{
    AmigaHardware::clearInterruptRequests(INTF_VERTB);
    if (Swotl::active) {
        Swotl::active->verticalBlank();
    }
    return 0;
}

Swotl::Swotl() :
    screenData(0),
    copperData(0),
    bitmap(0),
    copperList(0),
    paletteIndex(0),
    oldActiView(0),
    oldCopperList(0),
    oldEnabledDMAChannels(0),
    oldEnabledInterrupts(0),
    ioFrames(0),
    ioDepth(0),
    guestOpen(false),
    vectorTaken(false),
    runnable(false)
{
    GfxBase = (struct GfxBase*)OpenLibrary("graphics.library", 39);
    if (!GfxBase || !(GfxBase->ChipRevBits0 & GFXF_AA_LISA)) {
        return;
    }
    AmigaHardware::hasAGAChipSet = true;

    // Chip RAM is allocated at runtime: .MEMF_CHIP is a BSS hunk, so a __chip
    // static initialiser would be silently discarded.
    screenData = (uint8_t*)AllocMem(SCREEN_BYTES, MEMF_CHIP | MEMF_CLEAR);
    copperData = (uint32_t*)AllocMem(COPPER_LONGS * sizeof(uint32_t), MEMF_CHIP | MEMF_CLEAR);
    if (!screenData || !copperData) {
        return;
    }
    bitmap = new Bitmap(screenData, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_PLANES, false);
    copperList = new CopperList(copperData, COPPER_LONGS);
    if (!bitmap || !copperList) {
        return;
    }
    InitBitMap(&amiga_bitmap, SCREEN_PLANES, SCREEN_WIDTH, SCREEN_HEIGHT);
    for (uint16_t plane = 0; plane < SCREEN_PLANES; ++plane) {
        amiga_bitmap.Planes[plane] = screenData + plane * PLANE_BYTES;
    }

    // Mode 13h: a 320x200 eight-plane PAL screen, black until the game sets
    // its DAC; the palette slots are rewritten in place by setPalette.
    uint32_t at = copperList->setPlayfield(1, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_PLANES, false,
                                           false, false, false, false, true, 0x9c);
    copperData[at++] = copperMove(bplcon4, 0x0011);
    copperList->showBitmap(at, *bitmap);
    at += SCREEN_PLANES * 2;
    paletteIndex = at;
    static const uint8_t black[768] = {0};
    at = setPalette(black);
    if (at >= COPPER_LONGS) {
        return;
    }
    copperData[at] = 0xfffffffe;

    application = this;
    guestOpen = amiga_guest_open();
    runnable = guestOpen;
}

Swotl::~Swotl()
{
    if (guestOpen) {
        amiga_guest_close();
    }
    application = 0;
    delete copperList;
    delete bitmap;
    if (copperData) {
        FreeMem(copperData, COPPER_LONGS * sizeof(uint32_t));
    }
    if (screenData) {
        FreeMem(screenData, SCREEN_BYTES);
    }
    AmigaHardware::releaseBlitterQueue();
    if (GfxBase) {
        CloseLibrary((struct Library*)GfxBase);
        GfxBase = 0;
    }
}

void Swotl::run()
{
    takeOver();
    amiga_guest_run();
    handBack();
}

// Takeover order and its mirror in handBack: docs/amiga-lessons.md L2, L4;
// the template's ProductionRunner sequence, with Exec's VERTB vector in place
// of the level-3 autovector (L10, L13: PORTS and EXTER stay on Exec).
void Swotl::takeOver()
{
    oldActiView = GfxBase->ActiView;
    oldCopperList = (uint32_t*)GfxBase->copinit;
    oldEnabledDMAChannels = AmigaHardware::enabledDMAChannels();
    oldEnabledInterrupts = AmigaHardware::enabledInterrupts();
    LoadView(0);
    WaitTOF();
    WaitTOF();

    AmigaHardware::setInterrupts(INTF_ALL, false);
    AmigaHardware::clearInterruptRequests(INTF_ALL);
    AmigaHardware::setDMAChannels(DMA_ALL, false);

    // Clear sprites
    uint32_t* spriteData = (uint32_t*)spr1dataPointer;
    for (uint16_t i = 0; i < 8; i++) {
        *spriteData++ = 0;
    }

    // Own the VERTB vector rather than joining exec's server chain (L10).
    vbiInterrupt.is_Node.ln_Type = NT_INTERRUPT;
    vbiInterrupt.is_Node.ln_Pri = 127;
    vbiInterrupt.is_Node.ln_Name = (char*)"SWOTL VBI";
    vbiInterrupt.is_Data = 0;
    vbiInterrupt.is_Code = (void (*)())vbiHandler;
    struct IntVector* vector = &SysBase->IntVects[INTB_VERTB];
    Disable();
    oldVerticalBlankVector = *vector;
    vector->iv_Data = 0;
    vector->iv_Code = (void (*)())vbiHandler;
    vector->iv_Node = &vbiInterrupt.is_Node;
    Enable();
    vectorTaken = true;
    active = this;

    AmigaHardware::setCopperList(*copperList, true);
    AmigaHardware::setDMAChannels(DMAF_MASTER | DMAF_COPPER | DMAF_RASTER, true);
    AmigaHardware::setInterrupts(TAKEOVER_INTERRUPTS, true);
    if (!Input::begin()) {
        plat_log("SWOTL no ciaa.resource");
    }
    // Nothing inside Wait()s except DOS calls, which run in I/O windows (L6, L7).
    Forbid();
}

void Swotl::handBack()
{
    Input::end();
    AmigaHardware::setInterrupts(INTF_ALL, false);
    AmigaHardware::clearInterruptRequests(INTF_ALL);
    AmigaHardware::setDMAChannels(DMAF_COPPER | DMAF_RASTER | DMAF_SPRITE, false);
    // LoadView restores neither COP1LC nor the ECS border blanking (L4).
    AmigaHardware::setCopperList(CopperList(oldCopperList), true);
    *bplcon3Pointer = 0x0c00;
    AmigaHardware::setDMAChannels(DMAF_MASTER | DMAF_COPPER, true);
    if (vectorTaken) {
        Disable();
        SysBase->IntVects[INTB_VERTB] = oldVerticalBlankVector;
        Enable();
        vectorTaken = false;
    }
    active = 0;
    AmigaHardware::setDMAChannels(DMA_ALL, false);
    AmigaHardware::setDMAChannels(oldEnabledDMAChannels & DMA_ALL, true);
    AmigaHardware::clearInterruptRequests(INTF_ALL);
    AmigaHardware::setInterrupts(INTF_ALL, false);
    AmigaHardware::setInterrupts(oldEnabledInterrupts & INTF_ALL, true);
    Permit();
    LoadView(oldActiView);
    WaitTOF();
    WaitTOF();
}

// Each vertical blank: the mouse and typematic repeat, and a published frame
// is due (D9); the runtime presents its changed rows at the next poll point.
void Swotl::verticalBlank()
{
    ++amiga_frames;
    Input::verticalBlank();
    rt_present_due = 1;
    G_IRQ = 1;
}

// Hand back interrupts and multitasking, not the display (L7): Exec's VERTB
// vector, the saved INTENA and DISK|BLITTER DMA; our copper list and
// LoadView(NULL) stay, and so does the keyboard interrupt (keys typed during
// the window still reach the game). The vertical blanks the OS serves are
// counted from graphics.library's own counter.
void Swotl::beginIO()
{
    if (!vectorTaken || ioDepth++) {
        return;
    }
    Disable();
    AmigaHardware::setInterrupts(INTF_ALL, false);
    SysBase->IntVects[INTB_VERTB] = oldVerticalBlankVector;
    ioFrames = GfxBase->VBCounter;
    AmigaHardware::setDMAChannels(oldEnabledDMAChannels & (DMAF_DISK | DMAF_BLITTER), true);
    AmigaHardware::setInterrupts(oldEnabledInterrupts & INTF_ALL, true);
    Enable();
    Permit();
}

void Swotl::endIO()
{
    if (!vectorTaken || --ioDepth) {
        return;
    }
    Forbid();
    Disable();
    AmigaHardware::setInterrupts(INTF_ALL, false);
    struct IntVector* vector = &SysBase->IntVects[INTB_VERTB];
    vector->iv_Data = 0;
    vector->iv_Code = (void (*)())vbiHandler;
    vector->iv_Node = &vbiInterrupt.is_Node;
    uint32_t fields = GfxBase->VBCounter - ioFrames;
    amiga_frames += fields;
    amiga_io_frames += fields;
    AmigaHardware::setDMAChannels(DMAF_DISK | DMAF_BLITTER, false);
    AmigaHardware::setInterrupts(TAKEOVER_INTERRUPTS, true);
    Enable();
}

// The DAC's 6-bit guns widened to 8 bits into the copper palette (MOVEs
// rewritten in place; a frame may show a mix, as a DAC write mid-frame does).
// Returns the list index after the palette.
uint32_t Swotl::setPalette(const uint8_t* dac)
{
    static uint32_t colours[256], currentColours[256];
    amiga_colours[0] = 256u << 16;
    for (uint16_t k = 0; k < 256 * 3; ++k) {
        amiga_colours[1 + k] = (dac[k] & 0x3f) * 0x04104104u;
    }
    amiga_colours[1 + 256 * 3] = 0;
    for (uint16_t k = 0; k < 256; ++k) {
        colours[k] = ((amiga_colours[1 + k * 3] >> 24) << 16) | ((amiga_colours[2 + k * 3] >> 24) << 8) |
                     (amiga_colours[3 + k * 3] >> 24);
    }
    Palette24Bit palette(colours, currentColours, 256);
    return copperList->setPalette24Bit(paletteIndex, palette, 0, 0, 255, true);
}

// Kalms c2p (c2p1x1_8_c5_bm.s): d0/d1 chunky width (a multiple of 32) and
// height, d2/d3 screen offset (x a multiple of 8), a0 contiguous chunky
// pixels, a1 BitMap; saves d2-d7/a2-a6.
static void c2p(const void* chunky, int32_t w, int32_t h, int32_t x, int32_t y, struct BitMap* bitmap)
{
    register int32_t d0 __asm("d0") = w;
    register int32_t d1 __asm("d1") = h;
    register int32_t d2 __asm("d2") = x;
    register int32_t d3 __asm("d3") = y;
    register const void* a0 __asm("a0") = chunky;
    register struct BitMap* a1 __asm("a1") = bitmap;
    __asm volatile("jsr c2p1x1_8_c5_bm" : "+r"(d0), "+r"(d1), "+r"(a0), "+r"(a1)
                   : "r"(d2), "r"(d3) : "cc", "memory");
}

// Each changed rectangle into the shown bitmap: a full-width band in one
// call, a narrower one row by row (the chunky rows of a rectangle are not
// contiguous).
extern "C" void plat_present(const uint8_t* frame, const struct plat_rect* rects, int32_t n)
{
    for (int32_t k = 0; k < n; ++k) {
        const struct plat_rect* r = &rects[k];
        int32_t w = r->x1 - r->x0;
        if (w == SCREEN_WIDTH) {
            c2p(frame + r->y0 * SCREEN_WIDTH, w, r->y1 - r->y0, 0, r->y0, &amiga_bitmap);
            continue;
        }
        for (int32_t y = r->y0; y < r->y1; ++y) {
            c2p(frame + y * SCREEN_WIDTH + r->x0, w, 1, r->x0, y, &amiga_bitmap);
        }
    }
}

extern "C" void plat_palette(const uint8_t* dac)
{
    if (Swotl::application) {
        Swotl::application->setPalette(dac);
    }
}

extern "C" void amiga_io_begin(void)
{
    if (Swotl::application) {
        Swotl::application->beginIO();
    }
}

extern "C" void amiga_io_end(void)
{
    if (Swotl::application) {
        Swotl::application->endIO();
    }
}
