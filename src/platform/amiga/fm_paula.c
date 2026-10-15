/* FM re-hoster (docs/sound-plan.md, fm_paula.h). Per OPL channel the
 * envelope of both operators is followed per field from the rates and the
 * key-on edges (Nuked OPL's rate law: 24858 Hz envelope clock); the carrier
 * level sets the Paula volume. The waveform is a loop rendered with the
 * chip's own operator math (log-sine and exponent tables, feedback, phase
 * modulation) from the patch registers and the modulator level, cached in
 * the pool: one fundamental period, or for feedback 6-7 (noise) 1 KB at the
 * chip's rate on a quarter-octave pitch grid. The period plays it at the
 * channel's pitch. Voices 0-2 take the
 * loudest channel of channel groups 0-2, 3-5, 6-8 (SPAZ's slots), voice 3
 * the loudest of the rest. */
#include "fm_paula.h"

/* OPL2 ROM tables: -log2(sin) quarter wave and 2^-x, x 1/256 steps (the
 * closed forms reproduce them exactly). Paula volume of an attenuation in
 * 0.1875 dB steps. */
static const uint16_t logsin[256] = {
    2137, 1731, 1543, 1419, 1326, 1252, 1190, 1137, 1091, 1050, 1013, 979,
    949, 920, 894, 869, 846, 825, 804, 785, 767, 749, 732, 717,
    701, 687, 672, 659, 646, 633, 621, 609, 598, 587, 576, 566,
    556, 546, 536, 527, 518, 509, 501, 492, 484, 476, 468, 461,
    453, 446, 439, 432, 425, 418, 411, 405, 399, 392, 386, 380,
    375, 369, 363, 358, 352, 347, 341, 336, 331, 326, 321, 316,
    311, 307, 302, 297, 293, 289, 284, 280, 276, 271, 267, 263,
    259, 255, 251, 248, 244, 240, 236, 233, 229, 226, 222, 219,
    215, 212, 209, 205, 202, 199, 196, 193, 190, 187, 184, 181,
    178, 175, 172, 169, 167, 164, 161, 159, 156, 153, 151, 148,
    146, 143, 141, 138, 136, 134, 131, 129, 127, 125, 122, 120,
    118, 116, 114, 112, 110, 108, 106, 104, 102, 100, 98, 96,
    94, 92, 91, 89, 87, 85, 83, 82, 80, 78, 77, 75,
    74, 72, 70, 69, 67, 66, 64, 63, 62, 60, 59, 57,
    56, 55, 53, 52, 51, 49, 48, 47, 46, 45, 43, 42,
    41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30,
    29, 28, 27, 26, 25, 24, 23, 23, 22, 21, 20, 20,
    19, 18, 17, 17, 16, 15, 15, 14, 13, 13, 12, 12,
    11, 10, 10, 9, 9, 8, 8, 7, 7, 7, 6, 6,
    5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2,
    2, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0,
    0, 0, 0, 0,
};
static const uint16_t exptab[256] = {
    4084, 4074, 4062, 4052, 4040, 4030, 4020, 4008, 3998, 3986, 3976, 3966,
    3954, 3944, 3932, 3922, 3912, 3902, 3890, 3880, 3870, 3860, 3848, 3838,
    3828, 3818, 3808, 3796, 3786, 3776, 3766, 3756, 3746, 3736, 3726, 3716,
    3706, 3696, 3686, 3676, 3666, 3656, 3646, 3636, 3626, 3616, 3606, 3596,
    3588, 3578, 3568, 3558, 3548, 3538, 3530, 3520, 3510, 3500, 3492, 3482,
    3472, 3464, 3454, 3444, 3434, 3426, 3416, 3408, 3398, 3388, 3380, 3370,
    3362, 3352, 3344, 3334, 3326, 3316, 3308, 3298, 3290, 3280, 3272, 3262,
    3254, 3246, 3236, 3228, 3218, 3210, 3202, 3192, 3184, 3176, 3168, 3158,
    3150, 3142, 3132, 3124, 3116, 3108, 3100, 3090, 3082, 3074, 3066, 3058,
    3050, 3040, 3032, 3024, 3016, 3008, 3000, 2992, 2984, 2976, 2968, 2960,
    2952, 2944, 2936, 2928, 2920, 2912, 2904, 2896, 2888, 2880, 2872, 2866,
    2858, 2850, 2842, 2834, 2826, 2818, 2812, 2804, 2796, 2788, 2782, 2774,
    2766, 2758, 2752, 2744, 2736, 2728, 2722, 2714, 2706, 2700, 2692, 2684,
    2678, 2670, 2664, 2656, 2648, 2642, 2634, 2628, 2620, 2614, 2606, 2600,
    2592, 2584, 2578, 2572, 2564, 2558, 2550, 2544, 2536, 2530, 2522, 2516,
    2510, 2502, 2496, 2488, 2482, 2476, 2468, 2462, 2456, 2448, 2442, 2436,
    2428, 2422, 2416, 2410, 2402, 2396, 2390, 2384, 2376, 2370, 2364, 2358,
    2352, 2344, 2338, 2332, 2326, 2320, 2314, 2308, 2300, 2294, 2288, 2282,
    2276, 2270, 2264, 2258, 2252, 2246, 2240, 2234, 2228, 2222, 2216, 2210,
    2204, 2198, 2192, 2186, 2180, 2174, 2168, 2162, 2156, 2150, 2144, 2138,
    2132, 2128, 2122, 2116, 2110, 2104, 2098, 2092, 2088, 2082, 2076, 2070,
    2064, 2060, 2054, 2048,
};
static const uint8_t voltab[224] = {
    64, 63, 61, 60, 59, 57, 56, 55, 54, 53, 52, 50, 49, 48, 47, 46,
    45, 44, 43, 42, 41, 41, 40, 39, 38, 37, 36, 36, 35, 34, 33, 33,
    32, 31, 31, 30, 29, 29, 28, 27, 27, 26, 26, 25, 25, 24, 24, 23,
    23, 22, 22, 21, 21, 20, 20, 19, 19, 19, 18, 18, 17, 17, 17, 16,
    16, 16, 15, 15, 15, 14, 14, 14, 13, 13, 13, 13, 12, 12, 12, 12,
    11, 11, 11, 11, 10, 10, 10, 10, 10, 9, 9, 9, 9, 9, 8, 8,
    8, 8, 8, 7, 7, 7, 7, 7, 7, 7, 6, 6, 6, 6, 6, 6,
    6, 6, 5, 5, 5, 5, 5, 5, 5, 5, 5, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
};
static const uint8_t mt[16] = {1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 20, 24, 24, 30, 30};
static const uint8_t kslrom[16] = {0, 32, 40, 45, 48, 51, 53, 55, 56, 58, 59, 60, 61, 62, 63, 64};
static const uint8_t kslshift[4] = {8, 1, 2, 0};
/* register offset of each channel's modulator; its carrier is 3 above */
static const uint8_t op_off[9] = {0, 1, 2, 8, 9, 10, 16, 17, 18};

#define RATE_FIELD 31869u           /* envelope clock / 4 per field, 8.8 */
#define PERIOD_NUM 149617386u       /* Paula clock * 2^21 / OPL rate */
#define PERIOD_MIN 124
#define ATT_SILENT 224              /* voltab ends */
#define STICKY 16                   /* 3 dB before a voice changes channel */
#define MOD_STEP 4                  /* modulator level steps in the render key, 0.75 dB */
#define MOD_SILENT 96               /* steps: 72 dB down, no modulation */
#define NOISE_FB 6
#define NOISE_BYTES 1024
#define NOISE_SETTLE 512
#define NOISE_PERIOD 36528u         /* Paula clock * 2 / OPL rate, 8.8 */
#define CACHE 64

enum { ATTACK, DECAY, SUSTAIN, RELEASE };

struct op {
    uint32_t rout;                  /* envelope attenuation, 8.8 */
    uint32_t acc;                   /* attack steps, 16.16 */
    uint8_t gen;
    uint8_t tl;                     /* total level at the last field */
    int8_t slope;                   /* its change since, within a note */
};

struct entry {
    uint32_t key;
    uint32_t used;                  /* field stamp */
    uint16_t page, pages;
};

static struct op ops[18];
static uint8_t last_keyon[9];
static int8_t voice_ch[FM_VOICES] = {-1, -1, -1, -1};
static int8_t *pool;
static uint16_t pool_pages;
static uint8_t page_used[64];
static struct entry cache[CACHE];
static uint16_t cached;
static uint32_t stamp;

void fm_init(int8_t *p, uint32_t bytes)
{
    uint16_t i;
    pool = p;
    pool_pages = (uint16_t)(bytes / FM_POOL_PAGE);
    if (pool_pages > 64) {
        pool_pages = 64;
    }
    for (i = 0; i < 64; ++i) {
        page_used[i] = 0;
    }
    for (i = 0; i < 18; ++i) {
        ops[i].rout = 0x1ffu << 8;
        ops[i].acc = 0;
        ops[i].gen = RELEASE;
    }
    for (i = 0; i < FM_VOICES; ++i) {
        voice_ch[i] = -1;
    }
    cached = 0;
    stamp = 2;
}

/* Envelope steps per field (8.8) of register rate r with key scaling ks;
 * *hi the rate's high part (12+: attack within 2 ms). */
static uint32_t rate_step(uint8_t r, uint8_t ks, uint8_t *hi)
{
    uint8_t rate, h, lo;
    if (!r) {
        *hi = 0;
        return 0;
    }
    rate = (uint8_t)((r << 2) + ks);
    h = rate >> 2;
    lo = rate & 3;
    if (h >= 15) {
        h = 15;
        lo = 0;
    }
    *hi = h;
    return h >= 12 ? ((4u + lo) * RATE_FIELD) << (h - 12) : ((4u + lo) * RATE_FIELD) >> (12 - h);
}

/* Advance one operator by dt/256 field. */
static void eg_advance(struct op *o, const uint8_t *opl, uint8_t off, uint8_t ks, uint32_t dt)
{
    uint8_t ad = opl[0x60 + off], sr = opl[0x80 + off], hi;
    uint32_t sl = (uint32_t)(sr >> 4 == 15 ? 31 : sr >> 4) << 12, step, r;
    switch (o->gen) {
    case ATTACK:
        step = rate_step(ad >> 4, ks, &hi);
        if (hi >= 12) {
            o->rout = 0;
        } else if (step) {
            o->acc += step * dt;
            r = o->rout >> 8;
            for (; o->acc >= 0x10000 && r; o->acc -= 0x10000) {
                r -= (r + 8) >> 3;  /* Nuked: rout += ~rout >> 3 */
            }
            o->rout = r << 8;
        }
        if (o->rout) {
            return;
        }
        o->gen = DECAY;
        o->acc = 0;
        if (hi < 12) {
            return;
        }
        /* falls through - an instant attack decays in the same field */
    case DECAY:
        o->rout += rate_step(ad & 15, ks, &hi) * dt >> 8;
        if (o->rout < sl) {
            break;
        }
        o->rout = sl;
        o->gen = SUSTAIN;
        break;
    case SUSTAIN:
        if (!(opl[0x20 + off] & 0x20)) {
            o->rout += rate_step(sr & 15, ks, &hi) * dt >> 8;
        }
        break;
    default:
        o->rout += rate_step(sr & 15, ks, &hi) * dt >> 8;
        break;
    }
    if (o->rout >= 0x1f8u << 8) {
        o->rout = 0x1ffu << 8;
    }
}

/* Attenuation (0.1875 dB) of an operator: envelope, total level, key scale. */
static uint16_t op_att(const struct op *o, const uint8_t *opl, uint8_t off, uint16_t fnum, uint8_t block)
{
    int16_t ksl = (int16_t)((kslrom[fnum >> 6] << 2) - ((8 - block) << 5));
    uint8_t lv = opl[0x40 + off];
    if (ksl < 0) {
        ksl = 0;
    }
    return (uint16_t)((o->rout >> 8) + ((lv & 0x3f) << 2) + (ksl >> kslshift[lv >> 6]));
}

/* One operator sample: Nuked's OPL3_SlotGenerate for waveforms 0-3. */
static int16_t op_out(uint8_t wf, uint16_t p, uint16_t att)
{
    uint16_t q = p & 0xff, l;
    uint32_t level;
    int neg = 0;
    p &= 0x3ff;
    l = (p & 0x100) ? logsin[q ^ 0xff] : logsin[q];
    switch (wf) {
    case 0:
        neg = (p & 0x200) != 0;
        break;
    case 1:
        if (p & 0x200) {
            l = 0x1000;
        }
        break;
    case 2:
        break;
    default:
        l = (p & 0x100) ? 0x1000 : logsin[q];
        break;
    }
    level = l + ((uint32_t)att << 3);
    if (level > 0x1fff) {
        level = 0x1fff;
    }
    l = (uint16_t)(exptab[level & 0xff] >> (level >> 8));
    return (int16_t)(neg ? ~l : l);
}

/* Repeats of the output per fundamental period in half cycles of the
 * channel frequency (multipliers x 2, x 2 again for waveforms 2-3, which
 * repeat each half cycle); a silent modulator does not count. */
static uint8_t repeats(uint8_t wfc, uint8_t wfm, uint8_t mc, uint8_t mm, uint8_t silent)
{
    uint8_t a = (uint8_t)(mt[mc] << (wfc >= 2)), b = (uint8_t)(mt[mm] << (wfm >= 2));
    if (silent) {
        return a;
    }
    while (b) {
        uint8_t t = a % b;
        a = b;
        b = t;
    }
    return a;
}

/* Noise pitch grid, quarter octaves of fnum << block: the code of x and,
 * from a code, the grid point at the top of its quarter (x itself below 4). */
static uint8_t noise_code(uint32_t x)
{
    uint8_t e = 0;
    if (x < 4) {
        return (uint8_t)x;
    }
    while (x >> (e + 1)) {
        ++e;
    }
    return (uint8_t)(e << 2 | ((x >> (e - 2)) & 3));
}

static uint32_t noise_ref(uint8_t code)
{
    return code < 8 ? code : (uint32_t)(5 + (code & 3)) << ((code >> 2) - 2);
}

/* Render key fields: wf_c 0-1, wf_m 2-3, mult_c 4-7, mult_m 8-11, fb 12-14,
 * cnt 15, modulator level 16-22 (MOD_STEP), then log2 samples per period
 * 23-26, or for noise (fb 6-7) the pitch code 23-29. A period
 * loop steps the phase by its fraction of a period; a noise loop runs the
 * chip at its own rate and step (feedback chaos depends on the step) at the
 * grid pitch, two chip samples a byte. */
static void render(int8_t *dst, uint32_t key, uint16_t bytes)
{
    uint8_t wfc = key & 3, wfm = (key >> 2) & 3, fb = (key >> 12) & 7, cnt = (key >> 15) & 1;
    uint8_t mc = (key >> 4) & 15, mm = (key >> 8) & 15, mq = (key >> 16) & 127;
    uint8_t noise = fb >= NOISE_FB, g = repeats(wfc, wfm, mc, mm, mq >= MOD_SILENT);
    uint16_t matt = (uint16_t)(mq * MOD_STEP), spp = (uint16_t)(1u << ((key >> 23) & 15));
    /* phase: 16.16 cycles (>> 6 the chip's 10 bits), or the chip's own 19 bits (>> 9) */
    uint32_t ic, im, pc = 0, pm = 0, x = noise_ref((uint8_t)(key >> 23));
    uint8_t shift = noise ? 9 : 6;
    int16_t prev1 = 0, prev2 = 0, fbmod = 0, m, c, sum = 0;
    uint16_t i, settle = noise ? NOISE_SETTLE : fb ? bytes : 0, steps = noise ? 2 * bytes : bytes;
    if (noise) {
        ic = (x >> 1) * mt[mc] >> 1;
        im = (x >> 1) * mt[mm] >> 1;
    } else {
        ic = ((uint32_t)mt[mc] << 16) / g / spp;
        im = ((uint32_t)mt[mm] << 16) / g / spp;
    }
    for (i = 0; i < settle + steps; ++i) {
        if (fb) {
            fbmod = (int16_t)((prev1 + prev2) >> (9 - fb));
        }
        m = op_out(wfm, (uint16_t)((pm >> shift) + fbmod), matt);
        prev2 = prev1;
        prev1 = m;
        c = op_out(wfc, (uint16_t)((pc >> shift) + (cnt ? 0 : m)), 0);
        if (cnt) {
            c = (int16_t)((c + m) >> 1);
        }
        pc += ic;
        pm += im;
        if (i < settle) {
            continue;
        }
        if (!noise) {
            dst[i - settle] = (int8_t)(c >> 5);
        } else if ((i - settle) & 1) {
            dst[(i - settle) >> 1] = (int8_t)((sum + c) >> 6);
        } else {
            sum = c;
        }
    }
}

/* Loop of `key` (`bytes` long) from the cache, rendered on a miss; 0 when
 * every page is held by the loops of this or the last field. */
static const int8_t *loop_for(uint32_t key, uint16_t bytes)
{
    uint16_t pages = (uint16_t)((bytes + FM_POOL_PAGE - 1) / FM_POOL_PAGE), i, p, k;
    for (i = 0; i < cached; ++i) {
        if (cache[i].key == key) {
            cache[i].used = stamp;
            return pool + cache[i].page * FM_POOL_PAGE;
        }
    }
    for (;;) {
        for (p = 0; p + pages <= pool_pages; p = (uint16_t)(p + pages)) {
            for (k = 0; k < pages && !page_used[p + k]; ++k) {
            }
            if (k == pages) {
                break;
            }
        }
        if (p + pages <= pool_pages && cached < CACHE) {
            break;
        }
        /* evict the least recently used loop no voice may still play */
        k = CACHE;
        for (i = 0; i < cached; ++i) {
            if (cache[i].used + 1 < stamp && (k == CACHE || cache[i].used < cache[k].used)) {
                k = i;
            }
        }
        if (k == CACHE) {
            return 0;
        }
        for (i = 0; i < cache[k].pages; ++i) {
            page_used[cache[k].page + i] = 0;
        }
        cache[k] = cache[--cached];
    }
    for (k = 0; k < pages; ++k) {
        page_used[p + k] = 1;
    }
    cache[cached].key = key;
    cache[cached].used = stamp;
    cache[cached].page = p;
    cache[cached].pages = pages;
    ++cached;
    render(pool + p * FM_POOL_PAGE, key, bytes);
    return pool + p * FM_POOL_PAGE;
}

static void voice_cmd(struct fm_voice *v, const uint8_t *opl, int8_t ch, uint16_t att)
{
    uint8_t c = (uint8_t)ch, mo = op_off[c], co = (uint8_t)(mo + 3), b0 = opl[0xb0 + c], c0 = opl[0xc0 + c];
    uint16_t fnum = (uint16_t)(opl[0xa0 + c] | (b0 & 3) << 8), bytes, matt; /* matt: MOD_STEP units */
    uint8_t block = (b0 >> 2) & 7, ws = (opl[1] & 0x20) != 0, fb = (c0 >> 1) & 7, lg, g;
    uint8_t wfc = ws ? opl[0xe0 + co] & 3 : 0, wfm = ws ? opl[0xe0 + mo] & 3 : 0;
    uint32_t key, d, period = 0;
    matt = (uint16_t)((op_att(&ops[2 * c], opl, mo, fnum, block) + MOD_STEP / 2) / MOD_STEP);
    if (matt > MOD_SILENT) {
        matt = MOD_SILENT;
    }
    if (!fnum) {
        v->loop = 0;
        v->volume = 0;
        return;
    }
    key = (uint32_t)wfc | (uint32_t)wfm << 2 |
          (uint32_t)(opl[0x20 + co] & 15) << 4 | (uint32_t)(opl[0x20 + mo] & 15) << 8 |
          (uint32_t)fb << 12 | (uint32_t)(c0 & 1) << 15 | (uint32_t)matt << 16;
    if (fb >= NOISE_FB) {
        uint32_t x = (uint32_t)fnum << block;
        uint8_t code = noise_code(x);
        /* grid point / x in [1, 1.25], 2.14 */
        period = ((noise_ref(code) << 14) / x * NOISE_PERIOD + (1u << 21)) >> 22;
        key |= (uint32_t)code << 23;
        bytes = NOISE_BYTES;
    } else {
        g = repeats(wfc, wfm, opl[0x20 + co] & 15, opl[0x20 + mo] & 15, matt >= MOD_SILENT);
        for (lg = 8; lg >= 3; --lg) {
            d = ((uint32_t)fnum << block) * g << lg;
            period = (PERIOD_NUM + d / 2) / d;
            if (period >= PERIOD_MIN) {
                break;
            }
        }
        if (lg < 3) {
            lg = 3;
            period = PERIOD_MIN;
        }
        if (period > 0xffff) {
            period = 0xffff;
        }
        key |= (uint32_t)lg << 23;
        bytes = (uint16_t)(1u << lg);
    }
    v->loop = loop_for(key, bytes);
    v->bytes = bytes;
    v->period = (uint16_t)period;
    v->volume = v->loop ? voltab[att] : 0;
}

void fm_field(const uint8_t *opl, const uint8_t *keyon, struct fm_voice *voice)
{
    uint16_t att[9];
    uint8_t c, i, newkey[9];
    uint16_t taken = 0;
    ++stamp;
    for (c = 0; c < 9; ++c) {
        uint8_t b0 = opl[0xb0 + c], block = (b0 >> 2) & 7, mo = op_off[c], k;
        uint16_t fnum = (uint16_t)(opl[0xa0 + c] | (b0 & 3) << 8);
        uint8_t ksv = (uint8_t)(block << 1 | ((fnum >> 9) & 1));
        newkey[c] = keyon[c] != last_keyon[c];
        last_keyon[c] = keyon[c];
        for (k = 0; k < 2; ++k) {
            struct op *o = &ops[2 * c + k];
            uint8_t off = (uint8_t)(mo + 3 * k);
            uint8_t ks = (opl[0x20 + off] & 0x10) ? ksv : ksv >> 2;
            uint8_t tl = opl[0x40 + off] & 0x3f;
            o->slope = newkey[c] ? 0 : (int8_t)(tl - o->tl);
            o->tl = tl;
            /* a key change seen now happened, on average, mid-field; a note
             * that began and ended within it gets a third each */
            if (newkey[c]) {
                eg_advance(o, opl, off, ks, (b0 & 0x20) ? 128 : 85);
                o->gen = ATTACK;
                o->acc = 0;
                eg_advance(o, opl, off, ks, (b0 & 0x20) ? 128 : 85);
                if (!(b0 & 0x20)) {
                    o->gen = RELEASE;
                    eg_advance(o, opl, off, ks, 86);
                }
            } else if (!(b0 & 0x20) && o->gen != RELEASE) {
                eg_advance(o, opl, off, ks, 128);
                o->gen = RELEASE;
                eg_advance(o, opl, off, ks, 128);
            } else {
                eg_advance(o, opl, off, ks, 256);
            }
        }
        /* the level the coming field holds: its middle's, the game's own
         * total level ramps (SPAZ ticks at 236.7 Hz) carried on */
        att[c] = 0xffff;
        for (k = (opl[0xc0 + c] & 1) ? 0 : 1; k < 2; ++k) {
            struct op o = ops[2 * c + k];
            uint8_t off = (uint8_t)(mo + 3 * k);
            uint16_t a;
            eg_advance(&o, opl, off, (opl[0x20 + off] & 0x10) ? ksv : ksv >> 2, 128);
            a = op_att(&o, opl, off, fnum, block);
            a = (uint16_t)(o.slope < 0 && a < (uint16_t)(-2 * o.slope) ? 0 : a + 2 * o.slope);
            if (a < att[c]) {
                att[c] = a;
            }
        }
    }
    for (i = 0; i < FM_VOICES; ++i) {
        int8_t best = -1, cur = voice_ch[i];
        uint8_t first = i < 3 ? (uint8_t)(3 * i) : 0, last = i < 3 ? (uint8_t)(3 * i + 2) : 8;
        for (c = first; c <= last; ++c) {
            if (!(taken >> c & 1) && att[c] < ATT_SILENT && (best < 0 || att[c] < att[best])) {
                best = (int8_t)c;
            }
        }
        if (cur >= 0 && best >= 0 && cur != best && !(taken >> cur & 1) && cur >= first && cur <= last &&
            att[cur] < ATT_SILENT && att[cur] < att[best] + STICKY) {
            best = cur;
        }
        voice[i].restart = best >= 0 && (best != cur || newkey[best]);
        voice[i].channel = best;
        voice_ch[i] = best;
        if (best < 0) {
            voice[i].loop = 0;
            voice[i].volume = 0;
            continue;
        }
        taken = (uint16_t)(taken | 1 << best);
        voice_cmd(&voice[i], opl, best, att[best]);
    }
}
