/* TFH sample player (tfh_paula.h, docs/sound-plan.md). The playback follows
 * Their Finest Hour's own driver: a start segment, then a repeat segment
 * (the loop, or a silent word for a one-shot), and its envelope once a field:
 * attack, decay, sustain for a count of fields (or until SPAZ keys the slot
 * off), release. */
#include "tfh_paula.h"

#define SOUNDS 13
#define SOUND_ID 1001               /* descriptors 1001..; their samples 1000 on */
#define FM 0xff
#define SILENCE_BYTES 4
#define FOREVER 0xffff
#define PERIOD_FLOOR 124
#define VOLUME_FULL 64

struct sound {
    const int8_t *pcm;
    uint16_t bytes, loop;           /* loop: offset of the repeat segment, 0 one-shot */
    uint16_t period;
    uint8_t rate[3], step[3], level[3];
    uint16_t sustain;               /* fields, FOREVER */
};

/* Per SWOTL effect id: the TFH sound (index from 1001) or FM, and its volume:
 * 64 at the loudest id sharing the sample, the others by their FM level
 * below it (tools/sfx_levels.py, the original SPAZ code under emulation). */
static const uint8_t sound_of[39] = {
    0, 10, 8, FM, FM, FM, FM,                       /* engines, wind; jet, rocket */
    3, 3, 3, 3, 3, 3,                               /* machine guns 7-12 */
    4, 4, 4, 4, 4, 4,                               /* cannon 13-18 */
    FM, 9, 2, FM, 2, 1, 2, 2, FM,                   /* rockets fired 19 .. 27 */
    11, 6, 5, 5, 7, FM, 12, FM, FM, 7, 7,           /* hits 28 .. 38 */
};
static const uint8_t volume_of[39] = {
    64, 64, 64, 0, 0, 0, 0,
    45, 16, 8, 64, 46, 43,
    64, 30, 13, 54, 27, 9,
    0, 64, 52, 0, 64, 64, 28, 18, 0,
    64, 64, 64, 10, 64, 0, 64, 0, 0, 9, 24,
};
/* Engines: TFH's low-speed period at SPAZ's 60 mph F-number (block 3 for
 * id 0, 2 for id 1), the period falling as the F-number rises. */
#define ENGINE_SINGLE 0
#define ENGINE_MULTI 1
#define SINGLE_REF (800u * (161u << 3))
#define MULTI_REF (400u * (280u << 2))

enum { ATTACK, DECAY, SUSTAIN, DONE };

struct play {
    const struct sound *s;
    uint8_t id, starts, phase, segment;
    uint8_t volume, target[3];
    uint16_t acc, sustain;
};

static struct sound sounds[SOUNDS];
static const int8_t *silence;
static struct play slots[TFH_SLOTS];

static uint16_t be16(const uint8_t *p)
{
    return (uint16_t)(p[0] << 8 | p[1]);
}

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)be16(p) << 16 | be16(p + 2);
}

/* The resource `id`: its payload and length, 0 if absent. */
static const uint8_t *resource(const uint8_t *rsc, uint32_t size, uint16_t id, uint16_t *bytes)
{
    uint32_t dir, k, n;
    if (size < 4 || size < 6 || (dir = be32(rsc)) > size - 6) {
        return 0;
    }
    n = be16(rsc + dir + 4);
    for (k = 0; k < n && dir + 12 + 6 * k <= size; ++k) {
        const uint8_t *e = rsc + dir + 6 + 6 * k;
        uint32_t off = be32(e + 2);
        if (be16(e) != id) {
            continue;
        }
        if (off > size - 4 || be16(rsc + off) > size - off - 4) {
            return 0;
        }
        *bytes = be16(rsc + off);
        return rsc + off + 4;
    }
    return 0;
}

uint32_t tfh_chip_bytes(const uint8_t *rsc, uint32_t size)
{
    uint32_t total = SILENCE_BYTES;
    uint16_t k, bytes;
    for (k = 0; k < SOUNDS; ++k) {
        if (!resource(rsc, size, (uint16_t)(SOUND_ID + k), &bytes) || bytes != 33 ||
            !resource(rsc, size, (uint16_t)(SOUND_ID + 1000 + k), &bytes) || bytes < 4) {
            return 0;
        }
        total += bytes & ~1u;
    }
    return total;
}

int tfh_init(const uint8_t *rsc, uint32_t size, int8_t *chip)
{
    uint16_t k, i, bytes;
    if (!tfh_chip_bytes(rsc, size)) {
        return 1;
    }
    for (k = 0; k < SOUNDS; ++k) {
        const uint8_t *d = resource(rsc, size, (uint16_t)(SOUND_ID + k), &bytes);
        const uint8_t *pcm = resource(rsc, size, (uint16_t)(SOUND_ID + 1000 + k), &bytes);
        struct sound *s = &sounds[k];
        uint32_t loop = be32(d + 12);
        bytes &= ~1u;
        for (i = 0; i < bytes; ++i) {
            chip[i] = (int8_t)pcm[i];
        }
        s->pcm = chip;
        s->bytes = bytes;
        s->loop = loop < bytes ? (uint16_t)(loop & ~1u) : 0;
        s->period = be16(d + 18);
        for (i = 0; i < 2; ++i) {     /* attack, decay; the release after the sustain */
            s->rate[i] = d[22 + 3 * i];
            s->step[i] = d[23 + 3 * i];
            s->level[i] = d[24 + 3 * i];
        }
        /* fields at 60 Hz in the file: PAL 5/6, NTSC as they are */
        s->sustain = be16(d + 28) == FOREVER || fm_ntsc ? be16(d + 28) : (uint16_t)(be16(d + 28) * 5u / 6);
        s->rate[2] = d[30];
        s->step[2] = d[31];
        s->level[2] = d[32];
        chip += bytes;
    }
    for (i = 0; i < SILENCE_BYTES; ++i) {
        chip[i] = 0;
    }
    silence = chip;
    for (k = 0; k < TFH_SLOTS; ++k) {
        slots[k].starts = 0;
        slots[k].s = 0;
        slots[k].phase = DONE;
    }
    return 0;
}

static void start(struct play *p, uint8_t id)
{
    uint8_t i;
    p->s = &sounds[sound_of[id]];
    p->id = id;
    p->phase = ATTACK;
    p->segment = 0;
    p->volume = 0;
    p->acc = p->s->rate[0];
    p->sustain = p->s->sustain;
    for (i = 0; i < 3; ++i) {
        p->target[i] = (uint8_t)(p->s->level[i] * volume_of[id] / VOLUME_FULL);
    }
}

/* One field of TFH's envelope. */
static void envelope(struct play *p)
{
    const struct sound *s = p->s;
    uint8_t ph = p->phase == SUSTAIN ? 2 : p->phase;
    if (p->phase == SUSTAIN && p->sustain) {
        if (p->sustain != FOREVER) {
            --p->sustain;
        }
        return;
    }
    p->acc = (uint16_t)(p->acc + s->rate[ph]);
    if (p->acc <= 255) {
        return;
    }
    p->acc = (uint16_t)(p->acc - 256);
    if (p->phase == ATTACK) {
        p->volume = (uint8_t)(p->volume + s->step[0] > p->target[0] ? p->target[0] : p->volume + s->step[0]);
        if (p->volume >= p->target[0]) {
            p->phase = DECAY;
        }
    } else if (p->phase == DECAY) {
        p->volume = (uint8_t)(p->volume < p->target[1] + s->step[1] ? p->target[1] : p->volume - s->step[1]);
        if (p->volume <= p->target[1]) {
            p->phase = SUSTAIN;
        }
    } else {
        p->volume = (uint8_t)(p->volume < p->target[2] + s->step[2] ? p->target[2] : p->volume - s->step[2]);
        if (p->volume <= p->target[2]) {
            p->phase = DONE;
            p->volume = 0;
        }
    }
}

static uint16_t engine_period(const uint8_t *opl, uint8_t id, uint16_t period)
{
    uint8_t b0 = opl[0xb0];
    uint32_t f = (uint32_t)(opl[0xa0] | (b0 & 3) << 8) << ((b0 >> 2) & 7);
    if (id != ENGINE_SINGLE && id != ENGINE_MULTI) {
        return period;
    }
    if (f) {
        period = (uint16_t)(((id == ENGINE_SINGLE ? SINGLE_REF : MULTI_REF) + f / 2) / f);
    }
    return period < PERIOD_FLOOR ? PERIOD_FLOOR : period;
}

uint16_t tfh_field(const uint8_t *opl, const uint8_t *id, const uint8_t *starts,
                   struct fm_voice *voice)
{
    uint16_t mask = 0;
    uint8_t k;
    for (k = 0; k < TFH_SLOTS; ++k) {
        struct play *p = &slots[k];
        struct fm_voice *v = &voice[k];
        uint8_t keyed = (opl[0xb0 + 3 * k] | opl[0xb1 + 3 * k] | opl[0xb2 + 3 * k]) & 0x20;
        if (id[k] >= sizeof sound_of || sound_of[id[k]] == FM || !silence) {
            p->starts = starts[k];
            p->phase = DONE;
            continue;
        }
        mask = (uint16_t)(mask | 7u << (3 * k));
        if (starts[k] != p->starts) {
            p->starts = starts[k];
            start(p, id[k]);
            envelope(p);            /* the first field's step, as TFH's VBL */
        } else if (p->phase != DONE) {
            if (p->s->loop && !keyed) {
                p->sustain = 0;     /* SPAZ stopped the loop: the release ramp */
            }
            envelope(p);
        }
        v->channel = -1;
        v->restart = p->phase != DONE && p->segment == 0;
        if (p->phase == DONE) {
            v->loop = silence;
            v->bytes = SILENCE_BYTES;
            v->period = PERIOD_FLOOR;
            v->volume = 0;
            continue;
        }
        if (p->segment == 0) {
            v->loop = p->s->pcm;
            v->bytes = p->s->bytes;
            p->segment = 1;
        } else if (p->s->loop) {
            v->loop = p->s->pcm + p->s->loop;
            v->bytes = (uint16_t)(p->s->bytes - p->s->loop);
        } else {
            v->loop = silence;
            v->bytes = SILENCE_BYTES;
        }
        v->period = engine_period(opl, p->id, p->s->period);
        v->volume = p->volume;
    }
    return mask;
}
