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
#include "DisplayQueue.h"
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
// Restore bits: inactive, ActiView, VERTB triple, DMA, INTENA; all set = 31.
volatile uint16_t amiga_restore_status = 0;
uint32_t amiga_chip_free = 0, amiga_chip_largest = 0;
volatile uint32_t amiga_frames = 0;    // vertical blanks since the takeover (debug fixtures)
volatile uint32_t amiga_io_frames = 0; // of those, inside I/O windows (host-timed disk I/O)
}

// Heap storage: a default Shell stack is only 4 KiB. All allocations precede
// takeover; DMA reads only the two Chip bitmaps and their complete lists.
struct DisplayState {
    uint8_t* screen[2];
    uint32_t* copper[2];
    Bitmap* bitmap[2];
    CopperList* list[2];
    struct BitMap bm[2];
    DisplayQueue queue;
    uint32_t paletteIndex;
    uint32_t colours[2][1 + 256 * 3 + 1];
    uint32_t rgb[256], currentRGB[256];
    uint8_t dac[768];
    const uint8_t* frame;
    uint32_t serial;
    volatile uint32_t queuedSerial;
    // Main-thread validity belongs to each physical copper list/colour table.
    bool paletteValid[2];
};

extern "C" {
volatile uint32_t amiga_display_count = 0;
volatile uint32_t amiga_display_late = 0;
volatile uint32_t amiga_display_deferred = 0;
volatile uint16_t amiga_display_line = 0;
// Audit seams: queue snapshot before re-enabling interrupts, and actual
// handoff after updating the shown-frame metadata. Neither runs guest code.
void __attribute__((noinline)) amiga_display_queued(uint32_t serial) {
    __asm__ volatile("" : : "r"(serial) : "memory");
}
void __attribute__((noinline)) amiga_display_shown(uint32_t serial) {
    __asm__ volatile("" : : "r"(serial) : "memory");
}
}

static uint16_t beamLine() {
    return (uint16_t)((*(volatile uint32_t*)vposrPointer >> 8) & 511);
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
    display(0),
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

    display = new DisplayState{};
    if (!display) return;
    display->queue.pending = -1;
    // Largest DMA allocations first; Exec AllocMem provides 8-byte alignment.
    for (uint16_t b = 0; b < 2; ++b) {
        display->screen[b] = (uint8_t*)AllocMem(SCREEN_BYTES, MEMF_CHIP | MEMF_CLEAR);
        if (!display->screen[b]) return;
    }
    for (uint16_t b = 0; b < 2; ++b) {
        display->copper[b] = (uint32_t*)AllocMem(COPPER_LONGS * 4, MEMF_CHIP | MEMF_CLEAR);
        if (!display->copper[b]) return;
        display->bitmap[b] = new Bitmap(display->screen[b], SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_PLANES, false);
        display->list[b] = new CopperList(display->copper[b], COPPER_LONGS);
        if (!display->bitmap[b] || !display->list[b]) return;
        InitBitMap(&display->bm[b], SCREEN_PLANES, SCREEN_WIDTH, SCREEN_HEIGHT);
        for (uint16_t plane = 0; plane < SCREEN_PLANES; ++plane) {
            display->bm[b].Planes[plane] = display->screen[b] + plane * PLANE_BYTES;
        }
        uint32_t at = display->list[b]->setPlayfield(1, SCREEN_WIDTH, SCREEN_HEIGHT,
            SCREEN_PLANES, false, false, false, false, false, true, 0x9c);
        display->copper[b][at++] = copperMove(bplcon4, 0x0011);
        display->list[b]->showBitmap(at, *display->bitmap[b]);
        display->paletteIndex = at + SCREEN_PLANES * 2;
        at = buildPalette(b);
        if (at >= COPPER_LONGS) return;
        display->copper[b][at] = 0xfffffffe;
    }
    amiga_bitmap = display->bm[0];
    for (unsigned k = 0; k < 1 + 256 * 3 + 1; ++k) {
        amiga_colours[k] = display->colours[0][k];
    }

    application = this;
    // close() also unwinds a partially failed guest open.
    guestOpen = true;
    runnable = amiga_guest_open();
    amiga_chip_free = AvailMem(MEMF_CHIP);
    amiga_chip_largest = AvailMem(MEMF_CHIP | MEMF_LARGEST);
}

Swotl::~Swotl()
{
    if (guestOpen) {
        amiga_guest_close();
    }
    application = 0;
    if (display) {
        for (uint16_t b = 0; b < 2; ++b) {
            delete display->list[b];
            delete display->bitmap[b];
            if (display->copper[b]) FreeMem(display->copper[b], COPPER_LONGS * 4);
            if (display->screen[b]) FreeMem(display->screen[b], SCREEN_BYTES);
        }
        delete display;
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

    AmigaHardware::setCopperList(*display->list[display->queue.shown], true);
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
    amiga_restore_status = restoreStatus();
}

// Only readable state: COP1LC and BPLCON3 are write-only. Check after the
// OS has processed the restored view, while our saved state still exists.
uint16_t Swotl::restoreStatus() const
{
    const struct IntVector* vector = &SysBase->IntVects[INTB_VERTB];
    uint16_t status = 0;
    if (!active && !vectorTaken) {
        status |= 1;
    }
    if (GfxBase->ActiView == oldActiView) {
        status |= 2;
    }
    if (vector->iv_Data == oldVerticalBlankVector.iv_Data &&
        vector->iv_Code == oldVerticalBlankVector.iv_Code &&
        vector->iv_Node == oldVerticalBlankVector.iv_Node) {
        status |= 4;
    }
    if ((AmigaHardware::enabledDMAChannels() & DMA_ALL) ==
        (oldEnabledDMAChannels & DMA_ALL)) {
        status |= 8;
    }
    if ((AmigaHardware::enabledInterrupts() & INTF_ALL) ==
        (oldEnabledInterrupts & INTF_ALL)) {
        status |= 16;
    }
    return status;
}

// Each vertical blank: the mouse and typematic repeat, and a published frame
// is due (D9); the runtime presents its changed rows at the next poll point.
void Swotl::verticalBlank()
{
    // Publish first. A delayed VBI must leave the completed buffer queued,
    // never restart the copper in the visible window. Exclude higher-level
    // IRQs across the beam check and the pointer/strobe pair only.
    Disable();
    int16_t next = display->queue.pending;
    if (next >= 0 && beamLine() < 8) {
        display->queue.flip();
        AmigaHardware::setCopperList(*display->list[next], true);
        amiga_display_line = beamLine();
        if (amiga_display_line >= 16) ++amiga_display_late;
        Enable();
        amiga_bitmap = display->bm[next];
        for (unsigned k = 0; k < 1 + 256 * 3 + 1; ++k) {
            amiga_colours[k] = display->colours[next][k];
        }
        ++amiga_display_count;
        amiga_display_shown(display->queuedSerial);
    } else {
        if (next >= 0) ++amiga_display_deferred;
        Enable();
    }
    ++amiga_frames;
    Input::verticalBlank();
    rt_present_due = 1;
    RT_RAISE_IRQ();
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

// A complete palette is built only in the withdrawn back list. Palette-only
// updates also bring that bitmap up to date before queuing its handoff.
uint32_t Swotl::buildPalette(uint16_t back)
{
    uint32_t* table = display->colours[back];
    table[0] = 256u << 16;
    for (uint16_t k = 0; k < 256 * 3; ++k) {
        table[1 + k] = (display->dac[k] & 0x3f) * 0x04104104u;
    }
    table[1 + 256 * 3] = 0;
    for (uint16_t k = 0; k < 256; ++k) {
        display->rgb[k] = ((table[1 + k * 3] >> 24) << 16) |
                         ((table[2 + k * 3] >> 24) << 8) | (table[3 + k * 3] >> 24);
    }
    Palette24Bit palette(display->rgb, display->currentRGB, 256);
    uint32_t end = display->list[back]->setPalette24Bit(display->paletteIndex, palette, 0, 0, 255, true);
    display->paletteValid[back] = true;
    return end;
}

uint16_t Swotl::beginDisplayUpdate()
{
    Disable();
    uint16_t back = display->queue.begin();
    Enable();
    return back;
}

void Swotl::setPalette(const uint8_t* dac)
{
    uint16_t back = beginDisplayUpdate();
    for (unsigned k = 0; k < 768; ++k) display->dac[k] = dac[k];
    display->paletteValid[0] = false;
    display->paletteValid[1] = false;
    finishDisplayUpdate(back);
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

void Swotl::finishDisplayUpdate(uint16_t back)
{
    // Each bitmap remembers changes since its own last conversion, including
    // updates that were replaced before a VBI. Bounds originate in guest
    // painter stores; no framebuffer comparison discovers dirty pixels.
    for (uint16_t y = 0; y < SCREEN_HEIGHT;) {
        DisplayQueue::Row r = display->queue.rows[back][y];
        if (!r.hi) { ++y; continue; }
        uint16_t end = y + 1;
        if (r.lo == 0 && r.hi == SCREEN_WIDTH) {
            while (end < SCREEN_HEIGHT && display->queue.rows[back][end].lo == 0 &&
                   display->queue.rows[back][end].hi == SCREEN_WIDTH) ++end;
        }
        c2p(display->frame + y * SCREEN_WIDTH + r.lo, r.hi - r.lo,
            end - y, r.lo, y, &display->bm[back]);
        for (; y < end; ++y) display->queue.clear(back, y);
    }
    if (!display->paletteValid[back]) buildPalette(back);
    Disable();
    display->queuedSerial = ++display->serial;
    display->queue.queue(back);
    amiga_display_queued(display->queuedSerial);
    Enable();
}

void Swotl::present(const uint8_t* frame, const struct plat_rect* rects, int32_t n)
{
    uint16_t back = beginDisplayUpdate();
    display->frame = frame;
    for (int32_t k = 0; k < n; ++k) {
        const struct plat_rect* r = &rects[k];
        display->queue.mark(r->x0, r->y0, r->x1, r->y1);
    }
    finishDisplayUpdate(back);
}

extern "C" void plat_present(const uint8_t* frame, const struct plat_rect* rects, int32_t n)
{
    if (Swotl::application) Swotl::application->present(frame, rects, n);
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
