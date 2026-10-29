/* Keyboard and mouse as the reference machine presents them: the BIOS
 * keyboard buffer (filled by the BIOS INT 09h handler, which the game leaves
 * in place), INT 16h and the INT 33h driver (docs/external-surface.md). */
#include "platform.h"
#include "runtime.h"

/* Keyboard events from the platform: PC set 1 scan code, bit 7 break,
 * RT_KEY_E0 for a combined E0-prefixed key. Reference replay can instead
 * supply the prefix and scan byte separately. Each event has one 09h
 * interrupt (89h for a break: the same vector). */
volatile uint16_t rt_key_ring[RT_KEY_RING];
volatile uint8_t rt_key_tail;
static uint8_t key_head;

#define BDA_MODE 0x449
#define BDA_SHIFT 0x417
#define BDA_HEAD 0x41a
#define BDA_TAIL 0x41c
#define BDA_START 0x480
#define BDA_END 0x482
#define BUFFER_START 0x1e
#define BUFFER_END 0x3e

/* BIOS keyboard flags (DOSBox-X BIOS_KEYBOARD_FLAGS1-3) */
#define BDA_FLAGS2 0x418
#define BDA_FLAGS3 0x496
#define RSHIFT 0x01
#define LSHIFT 0x02
#define CTRL 0x04
#define ALT 0x08
#define NUM 0x20
#define CAPS 0x40
#define BDA_TOKEN 0x419     /* Alt + keypad digits */

void rt_input_init(void)
{
    wr8(BDA_SHIFT, NUM);            /* reference: NumLock on */
    wr16(BDA_HEAD, BUFFER_START);
    wr16(BDA_TAIL, BUFFER_START);
    wr16(BDA_START, BUFFER_START);
    wr16(BDA_END, BUFFER_END);
}

/* The reference BIOS's INT 09h words per scan code 00h-58h: normal, shift,
 * ctrl, alt (DOSBox-X scan_to_scanascii; 0 none; low byte F0h marks an
 * enhanced combination that INT 16h AH=00h skips). */
static const uint16_t words[0x59][4] = {
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 00 */
    {0x011b, 0x011b, 0x011b, 0x01f0}, /* 01 */
    {0x0231, 0x0221, 0x0000, 0x7800}, /* 02 */
    {0x0332, 0x0340, 0x0300, 0x7900}, /* 03 */
    {0x0433, 0x0423, 0x0000, 0x7a00}, /* 04 */
    {0x0534, 0x0524, 0x0000, 0x7b00}, /* 05 */
    {0x0635, 0x0625, 0x0000, 0x7c00}, /* 06 */
    {0x0736, 0x075e, 0x071e, 0x7d00}, /* 07 */
    {0x0837, 0x0826, 0x0000, 0x7e00}, /* 08 */
    {0x0938, 0x092a, 0x0000, 0x7f00}, /* 09 */
    {0x0a39, 0x0a28, 0x0000, 0x8000}, /* 0a */
    {0x0b30, 0x0b29, 0x0000, 0x8100}, /* 0b */
    {0x0c2d, 0x0c5f, 0x0c1f, 0x8200}, /* 0c */
    {0x0d3d, 0x0d2b, 0x0000, 0x8300}, /* 0d */
    {0x0e08, 0x0e08, 0x0e7f, 0x0ef0}, /* 0e */
    {0x0f09, 0x0f00, 0x9400, 0x0000}, /* 0f */
    {0x1071, 0x1051, 0x1011, 0x1000}, /* 10 */
    {0x1177, 0x1157, 0x1117, 0x1100}, /* 11 */
    {0x1265, 0x1245, 0x1205, 0x1200}, /* 12 */
    {0x1372, 0x1352, 0x1312, 0x1300}, /* 13 */
    {0x1474, 0x1454, 0x1414, 0x1400}, /* 14 */
    {0x1579, 0x1559, 0x1519, 0x1500}, /* 15 */
    {0x1675, 0x1655, 0x1615, 0x1600}, /* 16 */
    {0x1769, 0x1749, 0x1709, 0x1700}, /* 17 */
    {0x186f, 0x184f, 0x180f, 0x1800}, /* 18 */
    {0x1970, 0x1950, 0x1910, 0x1900}, /* 19 */
    {0x1a5b, 0x1a7b, 0x1a1b, 0x1af0}, /* 1a */
    {0x1b5d, 0x1b7d, 0x1b1d, 0x1bf0}, /* 1b */
    {0x1c0d, 0x1c0d, 0x1c0a, 0x0000}, /* 1c */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 1d */
    {0x1e61, 0x1e41, 0x1e01, 0x1e00}, /* 1e */
    {0x1f73, 0x1f53, 0x1f13, 0x1f00}, /* 1f */
    {0x2064, 0x2044, 0x2004, 0x2000}, /* 20 */
    {0x2166, 0x2146, 0x2106, 0x2100}, /* 21 */
    {0x2267, 0x2247, 0x2207, 0x2200}, /* 22 */
    {0x2368, 0x2348, 0x2308, 0x2300}, /* 23 */
    {0x246a, 0x244a, 0x240a, 0x2400}, /* 24 */
    {0x256b, 0x254b, 0x250b, 0x2500}, /* 25 */
    {0x266c, 0x264c, 0x260c, 0x2600}, /* 26 */
    {0x273b, 0x273a, 0x0000, 0x27f0}, /* 27 */
    {0x2827, 0x2822, 0x0000, 0x28f0}, /* 28 */
    {0x2960, 0x297e, 0x0000, 0x29f0}, /* 29 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 2a */
    {0x2b5c, 0x2b7c, 0x2b1c, 0x2bf0}, /* 2b */
    {0x2c7a, 0x2c5a, 0x2c1a, 0x2c00}, /* 2c */
    {0x2d78, 0x2d58, 0x2d18, 0x2d00}, /* 2d */
    {0x2e63, 0x2e43, 0x2e03, 0x2e00}, /* 2e */
    {0x2f76, 0x2f56, 0x2f16, 0x2f00}, /* 2f */
    {0x3062, 0x3042, 0x3002, 0x3000}, /* 30 */
    {0x316e, 0x314e, 0x310e, 0x3100}, /* 31 */
    {0x326d, 0x324d, 0x320d, 0x3200}, /* 32 */
    {0x332c, 0x333c, 0x0000, 0x33f0}, /* 33 */
    {0x342e, 0x343e, 0x0000, 0x34f0}, /* 34 */
    {0x352f, 0x353f, 0x0000, 0x35f0}, /* 35 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 36 */
    {0x372a, 0x372a, 0x9600, 0x37f0}, /* 37 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 38 */
    {0x3920, 0x3920, 0x3920, 0x3920}, /* 39 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 3a */
    {0x3b00, 0x5400, 0x5e00, 0x6800}, /* 3b */
    {0x3c00, 0x5500, 0x5f00, 0x6900}, /* 3c */
    {0x3d00, 0x5600, 0x6000, 0x6a00}, /* 3d */
    {0x3e00, 0x5700, 0x6100, 0x6b00}, /* 3e */
    {0x3f00, 0x5800, 0x6200, 0x6c00}, /* 3f */
    {0x4000, 0x5900, 0x6300, 0x6d00}, /* 40 */
    {0x4100, 0x5a00, 0x6400, 0x6e00}, /* 41 */
    {0x4200, 0x5b00, 0x6500, 0x6f00}, /* 42 */
    {0x4300, 0x5c00, 0x6600, 0x7000}, /* 43 */
    {0x4400, 0x5d00, 0x6700, 0x7100}, /* 44 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 45 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 46 */
    {0x4700, 0x4737, 0x7700, 0x0007}, /* 47 */
    {0x4800, 0x4838, 0x8d00, 0x0008}, /* 48 */
    {0x4900, 0x4939, 0x8400, 0x0009}, /* 49 */
    {0x4a2d, 0x4a2d, 0x8e00, 0x4af0}, /* 4a */
    {0x4b00, 0x4b34, 0x7300, 0x0004}, /* 4b */
    {0x4cf0, 0x4c35, 0x8f00, 0x0005}, /* 4c */
    {0x4d00, 0x4d36, 0x7400, 0x0006}, /* 4d */
    {0x4e2b, 0x4e2b, 0x9000, 0x4ef0}, /* 4e */
    {0x4f00, 0x4f31, 0x7500, 0x0001}, /* 4f */
    {0x5000, 0x5032, 0x9100, 0x0002}, /* 50 */
    {0x5100, 0x5133, 0x7600, 0x0003}, /* 51 */
    {0x5200, 0x5230, 0x9200, 0x0000}, /* 52 */
    {0x5300, 0x532e, 0x9300, 0x0000}, /* 53 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 54 */
    {0x0000, 0x0000, 0x0000, 0x0000}, /* 55 */
    {0x565c, 0x567c, 0x0000, 0x0000}, /* 56 */
    {0x8500, 0x8700, 0x8900, 0x8b00}, /* 57 */
    {0x8600, 0x8800, 0x8a00, 0x8c00}, /* 58 */
};

static void add_key(uint16_t key)
{
    if (!key) {
        return;
    }
    uint16_t tail = rd16(BDA_TAIL), next = tail + 2;
    if (next == rd16(BDA_END)) {
        next = rd16(BDA_START);
    }
    if (next != rd16(BDA_HEAD)) {   /* dropped when full */
        wr16(0x400 + tail, key);
        wr16(BDA_TAIL, next);
    }
}

/* Production (I8): every pending keyboard event (runtime.h). */
void rt_keyboard_drain(void)
{
    while (key_head != rt_key_tail) {
        rt_keyboard_irq();
    }
}

/* BIOS INT 09h for one keyboard event, as the reference's (DOSBox-X
 * IRQ1_Handler, US layout, lock keys toggling on release; Pause, Ctrl-Break
 * and Ctrl-Alt-Del are not modelled: the game does not use them). */
void rt_keyboard_irq(void)
{
    if (key_head == rt_key_tail) {
        return;
    }
    uint16_t ev = rt_key_ring[key_head++ % RT_KEY_RING];
    uint8_t scan = (uint8_t)ev;
    uint8_t f1 = rd8(BDA_SHIFT), f2 = rd8(BDA_FLAGS2), f3 = rd8(BDA_FLAGS3);
    uint8_t e0 = (ev & RT_KEY_E0) != 0 || (f3 & 0x02) != 0;
    uint16_t key;
    switch (scan) {
    case 0xe0: f3 |= 0x02; break;   /* prefix has its own IRQ, but no key */
    case 0x1d:                      /* Ctrl: left in flags 2, right in flags 3 */
        f1 |= CTRL;
        if (e0) f3 |= 0x04; else f2 |= 0x01;
        break;
    case 0x9d:
        if (e0) f3 &= ~0x04; else f2 &= ~0x01;
        if (!(f3 & 0x04) && !(f2 & 0x01)) f1 &= ~CTRL;
        break;
    case 0x2a: f1 |= LSHIFT; break;
    case 0xaa: f1 &= ~LSHIFT; break;
    case 0x36: f1 |= RSHIFT; break;
    case 0xb6: f1 &= ~RSHIFT; break;
    case 0x38:                      /* Alt */
        f1 |= ALT;
        if (e0) f3 |= 0x08; else f2 |= 0x02;
        break;
    case 0xb8:
        if (e0) f3 &= ~0x08; else f2 &= ~0x02;
        if (!(f3 & 0x08) && !(f2 & 0x02)) {
            f1 &= ~ALT;
            add_key(rd8(BDA_TOKEN));
            wr8(BDA_TOKEN, 0);
        }
        break;
    case 0x3a: f2 |= 0x40; break;   /* Caps Lock */
    case 0xba: f1 ^= CAPS; f2 &= ~0x40; break;
    case 0x45: f2 |= 0x20; break;   /* Num Lock */
    case 0xc5: f1 ^= NUM; f2 &= ~0x20; break;
    case 0x46: f2 |= 0x10; break;   /* Scroll Lock */
    case 0xc6: f1 ^= 0x10; f2 &= ~0x10; break;
    case 0xd2:                      /* Insert released */
        if (e0 || !(f1 & NUM)) {
            f1 ^= 0x80;
            f2 &= ~0x80;
        }
        break;
    case 0x47: case 0x48: case 0x49: case 0x4b: case 0x4c: case 0x4d:
    case 0x4f: case 0x50: case 0x51: case 0x52: case 0x53:
        if (e0) {                   /* grey cursor block */
            if (scan == 0x52) f2 |= 0x80;
            if (f1 & ALT) key = words[scan][0] + 0x5000;
            else if (f1 & CTRL) key = (words[scan][2] & 0xff00) | 0xe0;
            else if (f1 & (LSHIFT | RSHIFT | NUM)) key = (words[scan][1] & 0xff00) | 0xe0;
            else key = (words[scan][0] & 0xff00) | 0xe0;
            add_key(key);
        } else if (f1 & ALT) {
            wr8(BDA_TOKEN, (uint8_t)(rd8(BDA_TOKEN) * 10 + (uint8_t)words[scan][3]));
        } else if (f1 & CTRL) {
            add_key(words[scan][2]);
        } else if (((f1 & (LSHIFT | RSHIFT)) != 0) != ((f1 & NUM) != 0)) {
            add_key(words[scan][1]);
        } else {
            add_key(words[scan][0]);
        }
        break;
    case 0x37:
        if (e0) {
            rt_stop("keyboard: Print Screen", ev, 0);
        }
        /* keypad *: a normal key */
        __attribute__((fallthrough));
    default:
        if (scan & 0x80 || scan > 0x58) {
            break;
        }
        key = words[scan][f1 & ALT ? 3 : f1 & CTRL ? 2 : f1 & (LSHIFT | RSHIFT) ? 1 : 0];
        if (f1 & CAPS) {            /* Caps Lock inverts Shift on letters */
            uint8_t c = (uint8_t)key;
            if (f1 & (LSHIFT | RSHIFT) ? c > 0x40 && c < 0x5b : c > 0x60 && c < 0x7b) {
                key = words[scan][f1 & (LSHIFT | RSHIFT) ? 0 : 1];
            }
        }
        if (e0 && scan == 0x1c) {   /* keypad Enter */
            key = f1 & ALT ? 0xa600 : (key & 0xff) | 0xe000;
        } else if (e0 && scan == 0x35) {    /* keypad / */
            key = f1 & ALT ? 0xa400 : f1 & CTRL ? 0x9500 : 0xe02f;
        }
        add_key(key);
        break;
    }
    if (scan != 0xe0) {
        f3 &= ~0x02;
    }
    if ((scan & 0x80) == 0) {
        f2 &= 0xf7;
    }
    wr8(BDA_SHIFT, f1);
    wr8(BDA_FLAGS2, f2);
    wr8(BDA_FLAGS3, f3);
}

int rt_key_available(void)
{
    return rd16(BDA_HEAD) != rd16(BDA_TAIL);
}

uint16_t rt_key_take(void)
{
    uint16_t head = rd16(BDA_HEAD), key = rd16(0x400 + head);
    head += 2;
    wr16(BDA_HEAD, head == rd16(BDA_END) ? rd16(BDA_START) : head);
    return key;
}

void rt_int16(void)
{
    switch (AH(rt_r.ax)) {
    case 0x02:  /* shift flags */
        SET_AL(rt_r.ax, rd8(BDA_SHIFT));
        break;
    default:
        rt_unsupported("keyboard BIOS function", 0x16, 0, 0);
    }
}

/* Mouse: DOSBox-X's INT 33h with the mouse captured. Ranges 0-639 and 0-199
 * in text mode 3 and mode 13h; a reset centres the pointer and sets 8 and 16
 * mickeys per 8 pixels, so one host count moves the pointer one unit and the
 * vertical motion counter rt_mickeys_y: two as DOSBox-X (host pixels), one as
 * a real mouse's equal counts per inch (production Amiga). Position reads mask to the mode's cell (8x8
 * in text, 2 horizontally in mode 13h). The platform's counts are taken at
 * each call, so clamping sees their sum rather than each event. */
static int16_t mouse_x = 320, mouse_y = 100;
int16_t rt_mickey_x, rt_mickey_y;     /* motion since the last AX=0Bh (the pointer lead reads it) */
uint8_t rt_mickeys_y = 2;
static uint8_t mouse_buttons;

/* Flight scaling (production, rt_mouse_scale): the flight takes each frame's
 * AX=0Bh motion as the stick, so deflection is mouse speed times frame time.
 * Scaled, AX=0Bh returns the motion over MOUSE_FRAME_MS instead: motion times
 * MOUSE_FRAME_MS over the game-clock time since the last AX=0Bh, remainders
 * carried. The same feel at any frame rate; tweak MOUSE_FRAME_MS for
 * sensitivity (larger: more). Not while the last present showed the guest's
 * pointer (a still menu presents nothing) or one within MOUSE_POINTER_FIELDS
 * (menus and film room move a pointer by the motion). */
#define MOUSE_FRAME_MS 300
#define MOUSE_POINTER_FIELDS 25
#define MOUSE_MOTION_MAX 2048            /* keeps the scaled product in 32 bits */
uint8_t rt_mouse_scale;
static uint32_t mouse_ticks;             /* IRQ0 deliveries at the last AX=0Bh */
static int32_t mouse_rest_x, mouse_rest_y;

static int16_t clamp(int32_t v, int16_t max)
{
    return v < 0 ? 0 : v > max ? max : (int16_t)v;
}

static int16_t scale(int16_t m, int32_t *rest, int32_t frame, int32_t elapsed)
{
    int32_t n = (m < -MOUSE_MOTION_MAX ? -MOUSE_MOTION_MAX : m > MOUSE_MOTION_MAX ? MOUSE_MOTION_MAX : m) *
                frame + *rest;
    int32_t q = n / elapsed;
    *rest = n - q * elapsed;
    return (int16_t)q;
}

/* AX=0Bh's motion, scaled in flight; both in 1/256 game-clock ticks. */
static void mouse_scale(void)
{
    uint32_t now = rt_irq0_runs + rt_irq0_bios;
    uint32_t ticks = now - mouse_ticks;
    mouse_ticks = now;
    if (!rt_mouse_scale || rt_pointer.shown || rt_fields - rt_pointer_field <= MOUSE_POINTER_FIELDS) {
        mouse_rest_x = mouse_rest_y = 0;
        return;
    }
    int32_t frame = (int32_t)(MOUSE_FRAME_MS * (1193182u * 256 / 1000) / rt_pit_divisor);
    int32_t elapsed = (int32_t)(ticks ? ticks : 1) * 256;
    rt_mickey_x = scale(rt_mickey_x, &mouse_rest_x, frame, elapsed);
    rt_mickey_y = scale(rt_mickey_y, &mouse_rest_y, frame, elapsed);
}

static void mouse_poll(void)
{
    int32_t dx, dy;
    rt_pointer_open();
    mouse_buttons = (uint8_t)plat_mouse(&dx, &dy);
    rt_mickey_x = (int16_t)(rt_mickey_x + dx);
    rt_mickey_y = (int16_t)(rt_mickey_y + rt_mickeys_y * dy);
    rt_pointer_close();
    mouse_x = clamp(mouse_x + dx, 639);
    mouse_y = clamp(mouse_y + dy, 199);
}

void rt_int33(void)
{
    mouse_poll();
    switch (rt_r.ax) {
    case 0x0000:  /* reset */
        rt_r.ax = 0xffff;
        rt_r.bx = 3;
        mouse_x = 320;
        mouse_y = 100;
        rt_pointer_open();
        rt_mickey_x = rt_mickey_y = 0;
        rt_pointer_close();
        mouse_rest_x = mouse_rest_y = 0;
        break;
    case 0x0003:  /* position and buttons */
        rt_r.bx = mouse_buttons;
        if (rd8(BDA_MODE) == 0x13) {
            rt_r.cx = (uint16_t)mouse_x & 0xfffe;
            rt_r.dx = (uint16_t)mouse_y;
        } else {
            rt_r.cx = (uint16_t)mouse_x & 0xfff8;
            rt_r.dx = (uint16_t)mouse_y & 0xfff8;
        }
        rt_video_frame();
        break;
    case 0x000b:  /* motion since last call */
        rt_pointer_open();
        mouse_scale();
        rt_r.cx = (uint16_t)rt_mickey_x;
        rt_r.dx = (uint16_t)rt_mickey_y;
        rt_pointer_read(rt_mickey_x, rt_mickey_y);
        rt_mickey_x = rt_mickey_y = 0;
        rt_pointer_close();
        break;
    default:
        rt_unsupported("mouse function", 0x33, 0, 0);
    }
}
