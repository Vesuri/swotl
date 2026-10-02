#include <proto/exec.h>
#include <proto/graphics.h>
#include <exec/execbase.h>
#include <exec/interrupts.h>
#include <exec/memory.h>
#include <graphics/gfxbase.h>
#include <hardware/dmabits.h>
#include <hardware/intbits.h>
#include "Swotl.h"
#include "AmigaHardware.h"
#include "Bitmap.h"
#include "CopperList.h"
#include "Palette24Bit.h"

extern struct ExecBase* SysBase;
extern struct GfxBase* GfxBase;

#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define SCREEN_PLANES 8
#define SCREEN_BYTES (SCREEN_WIDTH / 8 * SCREEN_HEIGHT * SCREEN_PLANES)
#define COPPER_LONGS 558

#define CUSTOM_WORD(offset) (*(volatile uint16_t*)(0xdff000UL + (offset)))
#define REG_DMACON  0x096
#define REG_INTENA  0x09a
#define REG_INTREQ  0x09c
#define REG_BPLCON3 0x106

volatile uint16_t Swotl::vbiCount = 0;

static struct Interrupt vbiInterrupt;
static Swotl* vbiOwner = 0;

// Owns the level-3 VERTB vector, so it acknowledges INTREQ itself (L11).
static uint32_t vbiHandler()
{
    CUSTOM_WORD(REG_INTREQ) = INTF_VERTB;
    if (vbiOwner) {
        vbiOwner->verticalBlank();
    }
    return 0;
}

Swotl::Swotl() :
    screenData(0),
    copperData(0),
    bitmap(0),
    copperList(0),
    oldActiView(0),
    oldCopperList(0),
    oldEnabledDMAChannels(0),
    oldEnabledInterrupts(0),
    vectorTaken(false),
    active(false),
    runnable(false),
    quit(false)
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
    bitmap = new Bitmap(screenData, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_PLANES, true);
    copperList = new CopperList(copperData, COPPER_LONGS);
    if (!bitmap || !copperList) {
        return;
    }

    // Test card: row y shows colour y over a grey ramp.
    static uint32_t colours[256], currentColours[256];
    for (uint16_t colour = 0; colour < 256; ++colour) {
        colours[colour] = ((uint32_t)colour << 16) | (colour << 8) | colour;
    }
    for (uint16_t y = 0; y < SCREEN_HEIGHT; ++y) {
        uint8_t* row = screenData + y * (SCREEN_WIDTH / 8 * SCREEN_PLANES);
        for (uint16_t plane = 0; plane < SCREEN_PLANES; ++plane) {
            uint8_t fill = (y & (1 << plane)) ? 0xff : 0x00;
            for (uint16_t x = 0; x < SCREEN_WIDTH / 8; ++x) {
                row[plane * (SCREEN_WIDTH / 8) + x] = fill;
            }
        }
    }
    Palette24Bit palette(colours, currentColours, 256);
    uint32_t at = copperList->setPlayfield(1, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_PLANES, true,
                                           false, false, false, false, true, 0x9c);
    copperList->showBitmap(at, *bitmap);
    at += SCREEN_PLANES * 2;
    at = copperList->setPalette24Bit(at, palette, 0, 0, 255, true);
    if (at >= COPPER_LONGS) {
        return;
    }
    copperData[at] = 0xfffffffe;

    // Takeover order and its mirror in the destructor: docs/amiga-lessons.md L2, L4.
    oldActiView = GfxBase->ActiView;
    oldCopperList = (uint32_t*)GfxBase->copinit;
    oldEnabledDMAChannels = AmigaHardware::enabledDMAChannels();
    oldEnabledInterrupts = AmigaHardware::enabledInterrupts();
    LoadView(0);
    WaitTOF();
    WaitTOF();

    CUSTOM_WORD(REG_INTENA) = 0x7fff;
    CUSTOM_WORD(REG_INTREQ) = 0x7fff;
    CUSTOM_WORD(REG_DMACON) = DMAF_ALL | DMAF_MASTER | DMAF_BLITHOG;

    // Own the VERTB vector rather than joining exec's server chain (L10).
    vbiOwner = this;
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

    AmigaHardware::setCopperList(*copperList, true);
    CUSTOM_WORD(REG_DMACON) = DMAF_SETCLR | DMAF_MASTER | DMAF_COPPER | DMAF_RASTER;
    CUSTOM_WORD(REG_INTENA) = INTF_SETCLR | INTF_INTEN | INTF_VERTB | INTF_PORTS;
    Forbid();
    active = true;
    runnable = true;
}

Swotl::~Swotl()
{
    if (active) {
        CUSTOM_WORD(REG_INTENA) = 0x7fff;
        CUSTOM_WORD(REG_INTREQ) = 0x7fff;
        CUSTOM_WORD(REG_DMACON) = DMAF_COPPER | DMAF_RASTER | DMAF_SPRITE;
        AmigaHardware::setCopperList(CopperList(oldCopperList), true);
        CUSTOM_WORD(REG_BPLCON3) = 0x0c00;
        CUSTOM_WORD(REG_DMACON) = DMAF_SETCLR | DMAF_MASTER | DMAF_COPPER;
    }
    if (vectorTaken) {
        Disable();
        SysBase->IntVects[INTB_VERTB] = oldVerticalBlankVector;
        Enable();
        vectorTaken = false;
    }
    vbiOwner = 0;
    if (active) {
        CUSTOM_WORD(REG_DMACON) = DMAF_ALL | DMAF_MASTER | DMAF_BLITHOG;
        CUSTOM_WORD(REG_DMACON) = DMAF_SETCLR | (oldEnabledDMAChannels & (DMAF_ALL | DMAF_MASTER | DMAF_BLITHOG));
        CUSTOM_WORD(REG_INTREQ) = 0x7fff;
        CUSTOM_WORD(REG_INTENA) = 0x7fff;
        CUSTOM_WORD(REG_INTENA) = INTF_SETCLR | (oldEnabledInterrupts & 0x7fff);
        active = false;
        Permit();
        LoadView(oldActiView);
        WaitTOF();
        WaitTOF();
    }
    // Display memory is freed only after its DMA has stopped (L4).
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
    }
}

void Swotl::run()
{
    while (!quit) {
        uint16_t frame = vbiCount;
        while (frame == vbiCount);
    }
}

void Swotl::verticalBlank()
{
    vbiCount++;
    if (AmigaHardware::isLeftMouseButtonPressed()) {
        quit = true;
    }
}
