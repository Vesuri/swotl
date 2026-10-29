#include <proto/exec.h>
#include <exec/memory.h>
extern "C" {
#include "runtime.h"
#include "amiga_platform.h"
}
#include "Pointer.h"
#include "AmigaHardware.h"
#include "CopperList.h"

// 16-pixel sprites (FMODE SPR32/SPAGEM clear): position and control words,
// two words per row, two end words.
#define SPRITE_WORDS (2 + RT_POINTER_SIZE * 2 + 2)
#define SPRITE_OTHER 0              // sprite 4: colour 1
#define SPRITE_FILL 1               // sprite 6: colour 2
#define POINTER_TRANSPARENT 0xfd
#define POINTER_FILL 0xfe
// Beam position of pixel (0, 0): DIWSTRT $3881 PAL, $2C81 NTSC (setPlayfield,
// AMIGA_TOP_LINE), a sprite's HSTART $80 shows at the window's first pixel.
#define SPRITE_X 0x80
#define SPRITE_Y AMIGA_TOP_LINE

extern "C" {
// The shown buffer's sprites 4 and 6 and the colour in entry F9h (-1: none),
// for the display checks (tests/host_run.py --amiga, display_audit.gdb).
// rt_pointer for the display checks: gdb resolves that name to the struct type
// in C++ frames.
volatile void* amiga_pointer_state = 0;
volatile uint32_t amiga_pointer_bytes = 0;
volatile uint16_t* amiga_sprites = 0;
volatile int16_t amiga_sprite_stolen = -1;
// Control words written at or after line 25, where sprite DMA fetches them.
volatile uint32_t amiga_sprite_late = 0;
// After each vertical blank's sprite write (display checks wait on it).
void __attribute__((noinline)) amiga_sprite_placed(void) {
    __asm__ volatile("" : : : "memory");
}
}

#define SPRITE_DEADLINE 25

struct PointerBuffer {
    uint16_t* sprite[2];
    uint16_t image;                 // the shape in the sprite data (DGROUP offset), 0: none
    int8_t hotX, hotY;
    int16_t stolen;
    uint8_t shown;                  // the frame's state
};

static uint16_t* chip = 0;
static PointerBuffer buffers[2];
// The last shape shown: its sprite data stays through frames without the
// pointer, so the sprites change only with the shape.
static struct {
    uint16_t image;
    uint8_t w, h, other;
    int8_t hotX, hotY;
    uint8_t pixels[RT_POINTER_SIZE * RT_POINTER_SIZE];
} shape;
static uint8_t lastShown = 0;

#define CHIP_BYTES ((2 * 2 * SPRITE_WORDS + 2) * 2)

bool Pointer::begin()
{
    chip = (uint16_t*)AllocMem(CHIP_BYTES, MEMF_CHIP | MEMF_CLEAR);
    if (!chip) {
        return false;
    }
    for (uint16_t b = 0; b < 2; ++b) {
        buffers[b].sprite[SPRITE_OTHER] = chip + 2 + (2 * b) * SPRITE_WORDS;
        buffers[b].sprite[SPRITE_FILL] = chip + 2 + (2 * b + 1) * SPRITE_WORDS;
        buffers[b].stolen = -1;
    }
    amiga_sprites = buffers[0].sprite[SPRITE_OTHER];
    amiga_pointer_state = &rt_pointer;
    amiga_pointer_bytes = sizeof(rt_pointer);
    rt_pointer_sprite = 1;
    return true;
}

void Pointer::end()
{
    rt_pointer_sprite = 0;
    amiga_sprites = 0;
    if (chip) {
        FreeMem(chip, CHIP_BYTES);
        chip = 0;
    }
}

// Sprites 4 and 6 at buffer b's data, the others at the empty sprite (chip[0],
// chip[1]: position and control 0, L9).
uint32_t Pointer::copper(uint32_t* list, uint32_t at, uint16_t b)
{
    for (uint16_t n = 0; n < 8; ++n) {
        uint32_t data = (uint32_t)chip;
        if (chip && n == 4) data = (uint32_t)buffers[b].sprite[SPRITE_OTHER];
        if (chip && n == 6) data = (uint32_t)buffers[b].sprite[SPRITE_FILL];
        list[at++] = copperMove(spr1pth + (n << 2), (uint16_t)(data >> 16));
        list[at++] = copperMove(spr1pth + (n << 2) + 2, (uint16_t)data);
    }
    return at;
}

void Pointer::present(uint16_t b)
{
    if (!chip) {
        return;
    }
    PointerBuffer& p = buffers[b];
    if (rt_pointer.shown) {
        shape.image = rt_pointer.image;
        shape.w = rt_pointer.w;
        shape.h = rt_pointer.h;
        shape.other = rt_pointer.other;
        shape.hotX = rt_pointer.hot_x;
        shape.hotY = rt_pointer.hot_y;
        for (uint16_t k = 0; k < RT_POINTER_SIZE * RT_POINTER_SIZE; ++k) {
            shape.pixels[k] = rt_pointer.pixels[k];
        }
    }
    // Entry F9h is never shown on a pointer screen (P2 census): taken in a frame
    // with the pointer and in the one after, which the sprite can still be
    // shown over (rt_pointer_visible holds for a field).
    p.stolen = shape.image && shape.other != POINTER_TRANSPARENT &&
               (rt_pointer.shown || lastShown) ? shape.other : -1;
    lastShown = rt_pointer.shown;
    p.shown = rt_pointer.shown;
    if (p.image == shape.image) {
        return;
    }
    for (uint16_t r = 0; r < RT_POINTER_SIZE; ++r) {
        uint16_t other = 0, fill = 0;
        for (uint16_t c = 0; r < shape.h && c < shape.w; ++c) {
            uint8_t v = shape.pixels[r * RT_POINTER_SIZE + c];
            if (v == POINTER_FILL) fill |= (uint16_t)(0x8000 >> c);
            else if (v != POINTER_TRANSPARENT) other |= (uint16_t)(0x8000 >> c);
        }
        p.sprite[SPRITE_OTHER][2 + 2 * r] = other;      // DATA: colour 1
        p.sprite[SPRITE_OTHER][3 + 2 * r] = 0;
        p.sprite[SPRITE_FILL][2 + 2 * r] = 0;
        p.sprite[SPRITE_FILL][3 + 2 * r] = fill;        // DATB: colour 2
    }
    p.image = shape.image;
    p.hotX = shape.hotX;
    p.hotY = shape.hotY;
}

int16_t Pointer::stolen(uint16_t b)
{
    return chip ? buffers[b].stolen : -1;
}

// POS: SV7-0, SH8-1; CTL: EV7-0, SV8, EV8, SH0.
static void place(uint16_t* sprite, bool on, uint16_t h, uint16_t v)
{
    uint16_t e = (uint16_t)(v + RT_POINTER_SIZE);
    sprite[0] = on ? (uint16_t)((v & 0xff) << 8 | ((h >> 1) & 0xff)) : 0;
    sprite[1] = on ? (uint16_t)((e & 0xff) << 8 | ((v >> 8) & 1) << 2 | ((e >> 8) & 1) << 1 | (h & 1)) : 0;
}

void Pointer::verticalBlank(uint16_t b, int32_t dx, int32_t dy)
{
    PointerBuffer& p = buffers[b];
    bool visible = rt_pointer_visible(p.shown) && chip && p.image;
    int16_t x = 0, y = 0;
    if (visible) {
        rt_pointer_lead(dx, dy, &x, &y);
    }
    uint16_t h = (uint16_t)(SPRITE_X + x + p.hotX), v = (uint16_t)(SPRITE_Y + y + p.hotY);
    if (chip) {
        place(p.sprite[SPRITE_FILL], visible, h, v);
        place(p.sprite[SPRITE_OTHER], visible && p.stolen >= 0, h, v);
        amiga_sprites = p.sprite[SPRITE_OTHER];
        amiga_sprite_stolen = p.stolen;
        if (((*(volatile uint32_t*)vposrPointer >> 8) & 511) >= SPRITE_DEADLINE) ++amiga_sprite_late;
    }
    amiga_sprite_placed();
}
