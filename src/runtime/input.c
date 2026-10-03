/* Keyboard and mouse as the reference machine presents them: the BIOS
 * keyboard buffer (filled by the BIOS INT 09h handler, which the game leaves
 * in place), INT 16h and the INT 33h driver (docs/external-surface.md). */
#include "runtime.h"

/* Keys from the platform: scan code << 8 | ASCII, appended at rt_key_tail;
 * the platform's 09h make interrupt stores the next one as INT 09h. */
volatile uint16_t rt_key_ring[RT_KEY_RING];
volatile uint8_t rt_key_tail;
static uint8_t key_head;

#define BDA_SHIFT 0x417
#define BDA_HEAD 0x41a
#define BDA_TAIL 0x41c
#define BDA_START 0x480
#define BDA_END 0x482
#define BUFFER_START 0x1e
#define BUFFER_END 0x3e

void rt_input_init(void)
{
    wr8(BDA_SHIFT, 0x20);           /* reference: NumLock on */
    wr16(BDA_HEAD, BUFFER_START);
    wr16(BDA_TAIL, BUFFER_START);
    wr16(BDA_START, BUFFER_START);
    wr16(BDA_END, BUFFER_END);
}

/* BIOS INT 09h for a make code: the next key into the buffer (dropped when
 * full). */
void rt_keyboard_irq(void)
{
    if (key_head != rt_key_tail) {
        uint16_t key = rt_key_ring[key_head++ % RT_KEY_RING];
        uint16_t tail = rd16(BDA_TAIL), next = tail + 2;
        if (next == rd16(BDA_END)) {
            next = rd16(BDA_START);
        }
        if (next != rd16(BDA_HEAD)) {
            wr16(0x400 + tail, key);
            wr16(BDA_TAIL, next);
        }
    }
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

/* Mouse: reference driver, 3 buttons, centre of the 640x200 range after a
 * reset; no motion is ever reported (no mouse input on the target yet). */
static uint16_t mouse_x = 320, mouse_y = 100;

void rt_int33(void)
{
    switch (rt_r.ax) {
    case 0x0000:  /* reset */
        rt_r.ax = 0xffff;
        rt_r.bx = 3;
        mouse_x = 320;
        mouse_y = 100;
        break;
    case 0x0003:  /* position and buttons */
        rt_r.bx = 0;
        rt_r.cx = mouse_x;
        rt_r.dx = mouse_y;
        break;
    case 0x000b:  /* motion since last call */
        rt_r.cx = 0;
        rt_r.dx = 0;
        break;
    default:
        rt_unsupported("mouse function", 0x33, 0, 0);
    }
}
