/* Hardware-sprite pointer (docs/pointer-plan.md): while the guest's software
 * pointer is complete in VGA memory at a present, its opaque pixels are
 * replaced in the presented frame by the save buffer's (what the guest's hide
 * restores) and rt_pointer describes it for the platform's sprites; otherwise
 * the frame is VGA memory as it is. Only for a platform that shows the sprites
 * (rt_pointer_sprite). Guest addresses: annotations/pointer.csv, the DGROUP
 * offsets in pointer_guest (gen), DGROUP from the tracker's exit (HLE
 * pointer_tracked).
 *
 * Lead: the motion the guest has read (AX=0Bh) but not applied, and the motion
 * not read yet, each applied to the position at the tracker's last exit by the
 * guest's own rule (SWOTL.EXE 0320:05B6 poll, 0320:0D1A tracker): clamped to
 * +-BFh (x) and +-7Fh (y), halved toward zero unless that gives 0, added, held
 * in [min, end). A second read before the tracker's exit discards the first
 * read's motion: no lead until the next exit. A shown pointer elsewhere than
 * the last exit's position is adopted with no read pending. Writers: the main
 * thread (INT 33h: the platform's motion taken into rt_mickey_x/y,
 * rt_pointer_read and the mickeys cleared, each between rt_pointer_open and
 * rt_pointer_close; rt_pointer_tracked at the exit; rt_pointer_mask at a
 * present); rt_pointer_lead runs at the vertical blank and keeps its last
 * result while a write is open (`serial` odd). */
#include "runtime.h"

/* pointer_guest order (translator/emit.py POINTER_NAMES) */
enum { POINTER_X, POINTER_Y, POINTER_WIDTH, POINTER_HEIGHT, POINTER_HOT_X, POINTER_HOT_Y,
       POINTER_IMAGE, POINTER_X_MIN, POINTER_X_END, POINTER_Y_MIN, POINTER_Y_END, POINTER_BUFFER };
extern const uint16_t pointer_guest[];

#define POINTER_TRANSPARENT 0xfd
#define POINTER_FILL 0xfe          /* sprite 6's colour: entry FEh as it is */
#define POINTER_X_LIMIT 0xbf       /* the poll's motion clamps (0320:060B, 062A) */
#define POINTER_Y_LIMIT 0x7f

uint16_t rt_pointer_ds;
uint8_t rt_pointer_sprite;
struct rt_pointer rt_pointer;
int16_t rt_pointer_predicted[3];

static volatile struct {
    uint16_t serial;
    int16_t x, y;               /* position at the tracker's last exit */
    int16_t read_x, read_y;     /* the last AX=0Bh motion */
    uint8_t reads;              /* AX=0Bh calls since that exit */
    uint8_t tracked;            /* an exit has been seen */
} lead;
static int16_t lead_x, lead_y;  /* rt_pointer_lead's last result */

static uint16_t word(uint16_t name)
{
    return rd16(lin(rt_pointer_ds, pointer_guest[name]));
}

static int on_screen(int16_t x, int16_t y)
{
    return x >= 0 && x < 320 && y >= 0 && y < 200;
}

static void adopt(int16_t x, int16_t y);

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
    rt_pointer.hot_x = (int8_t)word(POINTER_HOT_X);
    rt_pointer.hot_y = (int8_t)word(POINTER_HOT_Y);
    rt_pointer.shown = 1;
    adopt((int16_t)word(POINTER_X), (int16_t)word(POINTER_Y));
}

static int16_t advance(int16_t p, int16_t m, int16_t limit, uint16_t min, uint16_t end)
{
    m = m <= -limit - 1 ? (int16_t)-limit : m >= limit + 1 ? limit : m;
    if (m / 2) {
        m = (int16_t)(m / 2);
    }
    int16_t v = (int16_t)(p + m), lo = (int16_t)word(min), hi = (int16_t)word(end);
    return v >= hi ? (int16_t)(hi - 1) : v < lo ? lo : v;
}

void rt_pointer_open(void)
{
    ++lead.serial;
}

void rt_pointer_close(void)
{
    ++lead.serial;
}

void rt_pointer_read(int16_t mx, int16_t my)
{
    lead.read_x = mx;
    lead.read_y = my;
    lead.reads = (uint8_t)(lead.reads < 2 ? lead.reads + 1 : 2);
}

/* The guest has applied the pending read: (x, y) is the lead's new start, and
 * what the lead predicted for it (one read since the last start) goes to
 * rt_pointer_predicted. */
static void consume(int16_t x, int16_t y)
{
    rt_pointer_predicted[0] = lead.tracked && lead.reads == 1;
    rt_pointer_predicted[1] = advance(lead.x, lead.read_x, POINTER_X_LIMIT, POINTER_X_MIN, POINTER_X_END);
    rt_pointer_predicted[2] = advance(lead.y, lead.read_y, POINTER_Y_LIMIT, POINTER_Y_MIN, POINTER_Y_END);
    ++lead.serial;
    lead.x = x;
    lead.y = y;
    lead.reads = 0;
    lead.tracked = 1;
    ++lead.serial;
}

/* A shown pointer away from the lead's start: set directly (0C64), or moved
 * by the tracker and presented after its show, before its exit. */
static uint8_t adopted;

static void adopt(int16_t x, int16_t y)
{
    if (lead.x != x || lead.y != y) {
        consume(x, y);
        adopted = 1;
    }
}

void rt_pointer_tracked(void)
{
    int16_t x = (int16_t)word(POINTER_X), y = (int16_t)word(POINTER_Y);
    /* Adopted at this move's present: the prediction was made there. */
    if (!(adopted && lead.reads == 0 && lead.x == x && lead.y == y)) {
        consume(x, y);
    }
    adopted = 0;
}

void rt_pointer_lead(int32_t dx, int32_t dy, int16_t *x, int16_t *y)
{
    uint16_t serial = lead.serial;
    if (!(serial & 1) && lead.tracked) {
        int16_t px = lead.x, py = lead.y;
        uint8_t reads = lead.reads;
        if (reads == 1) {
            px = advance(px, lead.read_x, POINTER_X_LIMIT, POINTER_X_MIN, POINTER_X_END);
            py = advance(py, lead.read_y, POINTER_Y_LIMIT, POINTER_Y_MIN, POINTER_Y_END);
        }
        if (reads < 2) {
            px = advance(px, (int16_t)(rt_mickey_x + dx), POINTER_X_LIMIT, POINTER_X_MIN, POINTER_X_END);
            py = advance(py, (int16_t)(rt_mickey_y + 2 * dy), POINTER_Y_LIMIT, POINTER_Y_MIN, POINTER_Y_END);
        }
        if (lead.serial == serial) {
            lead_x = px;
            lead_y = py;
        }
    }
    *x = lead_x;
    *y = lead_y;
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
