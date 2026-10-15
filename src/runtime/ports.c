/* I/O ports the game touches (docs/external-surface.md), as devices of the
 * reference machine: PIC, PIT, AdLib, joystick. Any other port stops. */
#include "runtime.h"
#include "platform.h"

/* PIC: the mask register (reference mask F8h: IRQ 0-2 enabled); the
 * non-specific EOI is answered in rt_out8 (rt_entry.s). */
static uint8_t pic_mask = 0xf8;

/* PIT: per channel the access mode of its control word (1 lo, 2 hi, 3 lo/hi)
 * and the lo/hi toggle; channel 0's reload (0 = 65536) sets the tick rate.
 * BIOS start state: all channels lo/hi. */
static uint8_t pit_access[3] = {3, 3, 3}, pit_high[3];
static uint16_t pit_reload[3];
uint32_t rt_pit_divisor = 0x10000;

/* AdLib: index register, the written OPL2 register file (D10) and the key-on
 * edges per channel (fm_paula.c); rt_out8 (rt_entry.s) answers its byte
 * writes. */
uint8_t rt_opl_index;
uint8_t rt_opl[256];
uint8_t rt_opl_keyon[9];
/* Music skip (annotations/hle.csv music_skip, rt_hle_music_skip): 1, a play
 * of a music record starts no song; 0 runs the guest code. Off while the
 * sound plan is developed (user 2026-10-15; docs/sound-plan.md Close). */
uint8_t rt_music_skip = 0;

static void pit_control(uint8_t v)
{
    uint8_t ch = v >> 6, access = (v >> 4) & 3;
    if (ch == 3 || access == 0) {
        rt_stop("PIT read-back or latch command", v, 0);
    }
    pit_access[ch] = access;
    pit_high[ch] = 0;
}

static void pit_data(uint8_t ch, uint8_t v)
{
    uint8_t access = pit_access[ch];
    int high = access == 2 || (access == 3 && pit_high[ch]);
    pit_reload[ch] = high ? (uint16_t)((pit_reload[ch] & 0x00ff) | v << 8)
                          : (uint16_t)((pit_reload[ch] & 0xff00) | v);
    if (access == 3) {
        pit_high[ch] ^= 1;
    }
    if (ch == 0 && (access != 3 || !pit_high[ch])) {
        rt_pit_divisor = pit_reload[0] ? pit_reload[0] : 0x10000;
        plat_timer_rate(rt_pit_divisor);
        if (rt_bench) {
            rt_bench_watch();
        }
    }
}

uint32_t rt_port_in(uint32_t port, uint32_t width)
{
    port &= 0xffff;
    if (width == 8) {
        switch (port) {
        case 0x21: return pic_mask;
        case 0x201: return 0xff;    /* reference: no joystick, axes never time out */
        }
    }
    rt_stop("unsupported port in (port, width)", port, width);
}

void rt_port_out(uint32_t port, uint32_t value, uint32_t width)
{
    port &= 0xffff;
    uint8_t v = (uint8_t)value;
    if (width == 8) {
        switch (port) {
        case 0x21: pic_mask = v; return;
        case 0x40: case 0x41: case 0x42: pit_data((uint8_t)(port - 0x40), v); return;
        case 0x43: pit_control(v); return;
        case 0x201: return;         /* joystick one-shots */
        }
    }
    rt_stop("unsupported port out (port, width)", port, width);
}
