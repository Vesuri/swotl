/* FM re-hoster (docs/sound-plan.md): the AdLib register file as the game
 * wrote it (runtime.h rt_opl) -> commands for the four Paula voices, once
 * per field (PAL, or NTSC with fm_ntsc). Plain C, no Amiga headers:
 * tools/fm_check.cpp runs it on the host against Nuked OPL. */
#ifndef SWOTL_FM_PAULA_H
#define SWOTL_FM_PAULA_H

#include <stdint.h>

#define FM_VOICES 4
#define FM_PAULA_CLOCK 3546895      /* PAL */
#define FM_FIELD_HZ 49.92           /* PAL field: 313 lines of 227 colour clocks */
#define FM_POOL_BYTES 65536         /* production cache, including noise tables */
#define FM_POOL_PAGE 256            /* loop pool unit, bytes */

struct fm_voice {
    const int8_t *loop;     /* 0: silent */
    uint16_t bytes;         /* loop length, even */
    uint16_t period;
    uint8_t volume;         /* 0..64 */
    uint8_t restart;        /* key-on or new channel: start from the first sample */
    int8_t channel;         /* OPL channel, -1 none */
};

/* Set before fm_init and tfh_init: 1 for NTSC fields and Paula clock, 0 (default) PAL. */
extern uint8_t fm_ntsc;
/* Loop storage (Chip RAM on the Amiga): `bytes` a multiple of 4 pages. */
void fm_init(int8_t *pool, uint32_t bytes);
/* One field: `opl` the 256 register bytes, `keyon` per channel a count of
 * key-on edges (B0-B8 bit 5 rising), wrapping. mute_mask excludes OPL
 * channels owned by samples from every voice; envelopes still advance. Fills `voice[FM_VOICES]`. */
void fm_field(const uint8_t *opl, const uint8_t *keyon, uint16_t mute_mask, struct fm_voice *voice);
/* Prerendered effect (docs/sound-plan.md R2), after fm_init: OPL data writes
 * at SPAZ ticks (236.7 Hz; tick 0 the play call), the same layout as the
 * runtime's capture (runtime.h struct rt_sfx_write). */
#define FM_EFFECT_RATE 16572        /* the OPL rate / 3; Paula period 214 PAL */
struct fm_write { uint16_t tick; uint8_t reg, value; };
/* Renders the effect from registers `opl` into out[0..max): signed 8-bit at
 * full scale, its peak in OPL units in *level (a full-scale voice is one
 * channel at 0 dB, FM_EFFECT_FULL). Returns the samples written. */
#define FM_EFFECT_FULL 4095
uint32_t fm_effect(const uint8_t *opl, const struct fm_write *w, uint32_t n, int8_t *out, uint32_t max,
                   uint32_t *level);
/* Loops rendered since fm_init (cost statistics). */
extern uint32_t fm_renders;

#endif
