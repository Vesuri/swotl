/* Effect sample player (docs/sound-plan.md): SPAZ's effect slots played
 * with Their Finest Hour's samples (TFH mode, the user's sfx.rsc) where an
 * effect has a counterpart, else with the effect prerendered at startup
 * (fm_effect); engines and the rest stay on the FM re-hoster. Plain C, no
 * Amiga headers, as fm_paula.c. */
#ifndef SWOTL_TFH_PAULA_H
#define SWOTL_TFH_PAULA_H

#include <stdint.h>
#include "fm_paula.h"

#define TFH_SLOTS 3                 /* SPAZ's slots: OPL channels 3k..3k+2, Paula voice k */

/* Chip bytes the samples of `rsc` (sfx.rsc, `size` bytes) need; 0: not a
 * TFH sfx.rsc. */
uint32_t tfh_chip_bytes(const uint8_t *rsc, uint32_t size);
/* The samples into `chip` (tfh_chip_bytes of it), fields for fm_ntsc; 0 on
 * success. */
int tfh_init(const uint8_t *rsc, uint32_t size, int8_t *chip);
/* One field: `id`, `starts` per slot as the HLE sfx_start reports them
 * (runtime.h rt_sfx_id, rt_sfx_starts), `opl` the register file. Fills
 * voice[k] of each slot a sample owns; returns the OPL channels those
 * slots hold (fm_field's mute mask). */
uint16_t tfh_field(const uint8_t *opl, const uint8_t *id, const uint8_t *starts,
                   struct fm_voice *voice);

/* Prerendered effects (R3), after tfh_init if TFH is used: 1 for an id to
 * render, a played non-engine effect TFH has no sample for. */
int tfh_effect_wanted(uint8_t id);
/* Effect id's sample: fm_effect's output in Chip (even length, at most
 * TFH_EFFECT_BYTES: two Paula loops), played at FM_EFFECT_RATE with Paula
 * volume `volume` as a one-shot; `silence` 4 zero Chip bytes. */
#define TFH_EFFECT_BYTES 131068
void tfh_effect(uint8_t id, const int8_t *pcm, uint32_t bytes, uint8_t volume, const int8_t *silence);
/* The Paula volume of fm_effect's peak: a full-scale voice is one channel
 * at 0 dB, louder mixes at full volume. */
uint8_t tfh_effect_volume(uint32_t level);

#endif
