/* Hardware-sprite pointer (docs/pointer-plan.md): while the guest's software
 * pointer is complete in VGA memory at a present, its opaque pixels are
 * replaced in the presented frame by the save buffer's (what the guest's hide
 * restores) and rt_pointer describes it for the platform's sprites; otherwise
 * the frame is VGA memory as it is. Only for a platform that shows the sprites
 * (rt_pointer_sprite). Guest addresses: annotations/pointer.csv, the DGROUP
 * offsets in pointer_guest (gen), DGROUP from the tracker's exit (HLE
 * pointer_tracked). */
#include "runtime.h"

/* pointer_guest order (translator/emit.py POINTER_NAMES) */
enum { POINTER_X, POINTER_Y, POINTER_WIDTH, POINTER_HEIGHT, POINTER_HOT_X, POINTER_HOT_Y,
       POINTER_IMAGE, POINTER_BUFFER };
extern const uint16_t pointer_guest[];

#define POINTER_TRANSPARENT 0xfd
#define POINTER_FILL 0xfe          /* sprite 6's colour: entry FEh as it is */

uint16_t rt_pointer_ds;
uint8_t rt_pointer_sprite;
struct rt_pointer rt_pointer;

static uint16_t word(uint16_t name)
{
    return rd16(lin(rt_pointer_ds, pointer_guest[name]));
}

static int on_screen(int16_t x, int16_t y)
{
    return x >= 0 && x < 320 && y >= 0 && y < 200;
}

void rt_pointer_mask(uint8_t *frame)
{
    rt_pointer.shown = 0;
    if (!rt_pointer_sprite || !rt_pointer_ds) {
        return;
    }
    int16_t w = (int16_t)word(POINTER_WIDTH), h = (int16_t)word(POINTER_HEIGHT);
    if (w <= 0 || w > RT_POINTER_SIZE || h <= 0 || h > RT_POINTER_SIZE) {
        return;
    }
    int16_t x0 = (int16_t)(word(POINTER_X) + word(POINTER_HOT_X));
    int16_t y0 = (int16_t)(word(POINTER_Y) + word(POINTER_HOT_Y));
    uint32_t image = lin(rt_pointer_ds, word(POINTER_IMAGE));
    uint32_t buffer = lin(rt_pointer_ds, pointer_guest[POINTER_BUFFER]);
    uint8_t other = POINTER_TRANSPARENT;
    int drawn = 0;
    /* Complete: every opaque pixel the draw writes (on screen) holds the shape. */
    for (int16_t r = 0; r < h; ++r) {
        for (int16_t c = 0; c < w; ++c) {
            uint8_t p = rd8(image + (uint32_t)(r * w + c));
            if (p == POINTER_TRANSPARENT || !on_screen(x0 + c, y0 + r)) {
                continue;
            }
            if (rd8(0xa0000u + (uint32_t)((y0 + r) * 320 + x0 + c)) != p) {
                return;
            }
            if (p != POINTER_FILL) {
                if (other != POINTER_TRANSPARENT && other != p) {
                    return;     /* a second colour besides FEh: no sprite colour for it */
                }
                other = p;
            }
            drawn = 1;
        }
    }
    if (!drawn) {
        return;
    }
    for (int16_t r = 0; r < h; ++r) {
        for (int16_t c = 0; c < w; ++c) {
            uint8_t p = rd8(image + (uint32_t)(r * w + c));
            rt_pointer.pixels[r * RT_POINTER_SIZE + c] = p;
            if (p != POINTER_TRANSPARENT && on_screen(x0 + c, y0 + r)) {
                frame[(y0 + r) * 320 + x0 + c] = rd8(buffer + (uint32_t)(r * w + c));
            }
        }
    }
    rt_pointer.masked_x0 = (uint16_t)(x0 < 0 ? 0 : x0);
    rt_pointer.masked_x1 = (uint16_t)(x0 + w > 320 ? 320 : x0 + w);
    rt_pointer.masked_y0 = (uint16_t)(y0 < 0 ? 0 : y0);
    rt_pointer.masked_y1 = (uint16_t)(y0 + h > 200 ? 200 : y0 + h);
    rt_pointer.x = x0;
    rt_pointer.y = y0;
    rt_pointer.w = (uint8_t)w;
    rt_pointer.h = (uint8_t)h;
    rt_pointer.other = other;
    rt_pointer.image = (uint16_t)(image - lin(rt_pointer_ds, 0));
    rt_pointer.shown = 1;
}

uint8_t rt_pointer_visible(uint8_t shown)
{
    static uint8_t visible, last, held;
    if (shown != last) {
        last = shown;
        held = 0;
    } else {
        held = 1;
    }
    if (held) {
        visible = shown;
    }
    return visible;
}
