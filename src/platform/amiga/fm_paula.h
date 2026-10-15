/* FM re-hoster (docs/sound-plan.md): the AdLib register file as the game
 * wrote it (runtime.h rt_opl) -> commands for the four Paula voices, once
 * per PAL field. Plain C, no Amiga headers: tools/fm_check.cpp runs it on
 * the host against Nuked OPL. */
#ifndef SWOTL_FM_PAULA_H
#define SWOTL_FM_PAULA_H

#include <stdint.h>

#define FM_VOICES 4
#define FM_PAULA_CLOCK 3546895      /* PAL */
#define FM_FIELD_HZ 49.92           /* PAL field: 313 lines of 227 colour clocks */
#define FM_POOL_PAGE 256            /* loop pool unit, bytes */

struct fm_voice {
    const int8_t *loop;     /* 0: silent */
    uint16_t bytes;         /* loop length, even */
    uint16_t period;
    uint8_t volume;         /* 0..64 */
    uint8_t restart;        /* key-on or new channel: start from the first sample */
    int8_t channel;         /* OPL channel, -1 none */
};

/* Loop storage (Chip RAM on the Amiga): `bytes` a multiple of 4 pages. */
void fm_init(int8_t *pool, uint32_t bytes);
/* One field: `opl` the 256 register bytes, `keyon` per channel a count of
 * key-on edges (B0-B8 bit 5 rising), wrapping. Fills `voice[FM_VOICES]`. */
void fm_field(const uint8_t *opl, const uint8_t *keyon, struct fm_voice *voice);
/* Loops rendered since fm_init (cost statistics). */
extern uint32_t fm_renders;

#endif
