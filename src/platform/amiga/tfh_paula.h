/* TFH sample player (docs/sound-plan.md, TFH mode): SPAZ's effect slots
 * played with Their Finest Hour's samples (the user's sfx.rsc) where an
 * effect has a counterpart; the others stay on the FM re-hoster. Plain C,
 * no Amiga headers, as fm_paula.c. */
#ifndef SWOTL_TFH_PAULA_H
#define SWOTL_TFH_PAULA_H

#include <stdint.h>
#include "fm_paula.h"

#define TFH_SLOTS 3                 /* SPAZ's slots: OPL channels 3k..3k+2, Paula voice k */

/* Chip bytes the samples of `rsc` (sfx.rsc, `size` bytes) need; 0: not a
 * TFH sfx.rsc. */
uint32_t tfh_chip_bytes(const uint8_t *rsc, uint32_t size);
/* The samples into `chip` (tfh_chip_bytes of it); 0 on success. */
int tfh_init(const uint8_t *rsc, uint32_t size, int8_t *chip);
/* One field: `id`, `starts` per slot as the HLE sfx_start reports them
 * (runtime.h rt_sfx_id, rt_sfx_starts), `opl` the register file. Fills
 * voice[k] of each slot a sample owns; returns the OPL channels those
 * slots hold (fm_field's mute mask). */
uint16_t tfh_field(const uint8_t *opl, const uint8_t *id, const uint8_t *starts,
                   struct fm_voice *voice);

#endif
