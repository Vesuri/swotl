/* Effect capture for prerendering (docs/sound-plan.md R1). At SPAZ init's
 * return (HLE sfx_prerender, observe only) each effect id's OPL writes are
 * captured by running SPAZ's own play and INT 08h handler with the timer
 * stepped by hand; the state they touch (irq-plan I2 footprint) is saved
 * before and restored after, the real tick held meanwhile (game time
 * pauses). The writes go to rt_sfx_capture, not rt_opl. */
#include "platform.h"
#include "runtime.h"

/* SPAZ.OVL entries, offsets from its code segment (file offset - 240h), and
 * its data segment's distance from the code segment (docs/irq-plan.md I2:
 * code class 1770, data 188A). */
#define SPAZ_PLAY 0x0195            /* +03D5 play(id * 4) */
#define SPAZ_STOP_ALL 0x0426        /* +0666 */
#define SPAZ_DATA 0x011a
#define SPAZ_DATA_BYTES 0x05a0
#define SPAZ_GAME_DS 0x0162         /* word: the game's DGROUP */
/* DGROUP bytes SPAZ's handler, play and stop-all write (I2), and the flags
 * the capture sets: sound off 639F, pause 6316, gun delay CFA8. */
static const uint16_t game_ranges[][2] = {
    {0x6316, 1}, {0x639f, 1}, {0x6564, 0x27}, {0x813c, 2}, {0x9bca, 2},
    {0x9c20, 1}, {0x9c44, 0x66}, {0x9d32, 4}, {0xcfa8, 2},
};
#define GAME_BYTES (1 + 1 + 0x27 + 2 + 2 + 1 + 0x66 + 4 + 2)
#define BDA_TICK 0x46c              /* 6C..70, the BIOS chain's (I2) */
#define BDA_TICK_BYTES 5
#define TICKS_MAX 1894              /* 8 s at 236.7 Hz */
#define EFFECT_COUNTS 0x6564        /* DGROUP byte per id: play +1 (SPAZ+64E), end -1 (+65E) */
#define SENTINEL_CS RT_IRQ_SS
#define SENTINEL_IP RT_IRQ_SP

uint8_t rt_sfx_prerender_on;
volatile uint8_t rt_sfx_capturing;
struct rt_sfx_write rt_sfx_capture[RT_SFX_WRITES];
uint16_t rt_sfx_first[RT_SFX_IDS], rt_sfx_writes[RT_SFX_IDS], rt_sfx_ticks[RT_SFX_IDS];
uint8_t rt_sfx_opl[256];            /* the OPL registers at the capture's start */
static uint16_t capture_n, capture_tick, last_write;

uint32_t rt_guest_call(uint32_t sentinel);
void *rt_lookup(uint32_t cs, uint32_t ip, uint32_t far);

/* rt_out8 (rt_entry.s) while capturing: one OPL data write. */
void rt_sfx_write(uint32_t reg, uint32_t value)
{
    if (capture_n < RT_SFX_WRITES) {
        rt_sfx_capture[capture_n].tick = capture_tick;
        rt_sfx_capture[capture_n].reg = (uint8_t)reg;
        rt_sfx_capture[capture_n].value = (uint8_t)value;
        ++capture_n;
    }
    last_write = capture_tick;
}

static void push(uint16_t v)
{
    rt_r.sp = (uint16_t)(rt_r.sp - 2);
    wr16(lin(G_SS, rt_r.sp), v);
}

/* SPAZ at cs:ip on the private stack below the sentinel return: a far C call
 * with one argument, or (iret) the INT 08h handler's frame. */
static void spaz(uint16_t cs, uint16_t ip, int iret, uint16_t arg)
{
    G_SS = RT_IRQ_SS;
    rt_r.sp = RT_IRQ_SP;
    if (iret) {
        push(0x0202);
        G_IF = 0;
    } else {
        push(arg);
        G_IF = 1;
    }
    G_TF = 0;
    push(SENTINEL_CS);
    push(SENTINEL_IP);
    rt_deliver_cs = cs;
    rt_deliver_ip = ip;
    rt_deliver_code = rt_lookup(cs, ip, 1);
    rt_guest_call((uint32_t)SENTINEL_CS << 16 | SENTINEL_IP);
}

static void copy(uint32_t a, uint8_t *save, uint16_t n, int restore)
{
    for (uint16_t i = 0; i < n; ++i) {
        if (restore) {
            wr8(a + i, save[i]);
        } else {
            save[i] = rd8(a + i);
        }
    }
}

static uint8_t spaz_save[SPAZ_DATA_BYTES], game_save[GAME_BYTES], bda_save[BDA_TICK_BYTES];

static void state(uint32_t data, uint16_t game, int restore)
{
    uint16_t at = 0;
    copy(data, spaz_save, SPAZ_DATA_BYTES, restore);
    for (unsigned k = 0; k < sizeof game_ranges / sizeof game_ranges[0]; ++k) {
        copy(lin(game, game_ranges[k][0]), game_save + at, game_ranges[k][1], restore);
        at = (uint16_t)(at + game_ranges[k][1]);
    }
    copy(BDA_TICK, bda_save, BDA_TICK_BYTES, restore);
}

/* HLE sfx_prerender (rt_entry.s saves and restores the guest's registers and
 * state block around it). IVT 08h is SPAZ's handler, installed by init. */
void rt_sfx_prerender(void)
{
    if (!rt_sfx_prerender_on) {
        return;
    }
    uint16_t cs = rd16(8 * 4 + 2), handler = rd16(8 * 4);
    uint32_t data = lin((uint16_t)(cs + SPAZ_DATA), 0);
    uint16_t game = rd16(data + SPAZ_GAME_DS);
    uint8_t index = rt_opl_index, pair = rt_opl_pair, ids[3], starts[3];
    for (unsigned k = 0; k < 3; ++k) {
        ids[k] = rt_sfx_id[k];
        starts[k] = rt_sfx_starts[k];
    }
    state(data, game, 0);
    for (unsigned r = 0; r < 256; ++r) {
        rt_sfx_opl[r] = rt_opl[r];
    }
    rt_irq0_running = 1;            /* no tick delivered; the CIA's held */
    rt_sfx_capturing = 1;
    capture_n = 0;
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        rt_sfx_first[id] = capture_n;
        rt_sfx_writes[id] = rt_sfx_ticks[id] = 0;
        if (!plat_sfx_wanted(id)) {
            continue;
        }
        wr8(lin(game, 0x639f), 0);
        wr8(lin(game, 0x6316), 0);
        wr16(lin(game, 0xcfa8), 0);
        capture_tick = 0;
        spaz(cs, SPAZ_STOP_ALL, 0, 0);
        uint16_t first = capture_n;
        rt_sfx_first[id] = first;
        spaz(cs, SPAZ_PLAY, 0, (uint16_t)(id * 4));
        last_write = 0;
        /* until SPAZ ends the effect (its count back to 0) */
        for (capture_tick = 1; capture_tick <= TICKS_MAX &&
                rd8(lin(game, (uint16_t)(EFFECT_COUNTS + id))); ++capture_tick) {
            spaz(cs, handler, 1, 0);
        }
        rt_sfx_writes[id] = (uint16_t)(capture_n - first);
        rt_sfx_ticks[id] = (uint16_t)(last_write + 1);
        state(data, game, 1);
    }
    capture_tick = 0;
    spaz(cs, SPAZ_STOP_ALL, 0, 0);
    state(data, game, 1);
    rt_sfx_capturing = 0;
    rt_irq0_running = 0;
    rt_opl_index = index;
    rt_opl_pair = pair;
    for (unsigned k = 0; k < 3; ++k) {     /* HLE sfx_start's reports */
        rt_sfx_id[k] = ids[k];
        rt_sfx_starts[k] = starts[k];
    }
    plat_sfx_captured();
}
