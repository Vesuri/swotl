/* FM re-hoster (docs/sound-plan.md, fm_paula.h). Per OPL channel the
 * envelope of both operators is followed per field from the rates and the
 * key-on edges (Nuked OPL's rate law: 24858 Hz envelope clock); the carrier
 * level sets the Paula volume. The waveform is a loop rendered with the
 * chip's own operator math (log-sine and exponent tables, feedback, phase
 * modulation) from the patch registers and the modulator level, cached in
 * the pool: one fundamental period. Feedback 6-7 with a strong modulator is
 * chaotic: two noise tables built at fm_init, played at the modulator's
 * pitch. The period plays a loop at the channel's pitch. Give each SPAZ
 * group a voice, fill spare voices from the rest, and keep continuing notes
 * on their physical voices. TFH sample-owned voices remain reserved. */
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

/* fm_init sets them for PAL or NTSC (fm_ntsc) */
#define RATE_FIELD_PAL 31869u       /* envelope clock / 4 per field, 8.8 */
#define RATE_FIELD_NTSC 26592u
#define PERIOD_NUM_PAL 149617386u   /* Paula clock * 2^21 / OPL rate */
#define PERIOD_NUM_NTSC 150994649u
#define PERIOD_MIN 124
#define ATT_SILENT 224              /* voltab ends */
#define STICKY 16                   /* 3 dB before a voice changes channel */
#define MOD_STEP 4                  /* 0.75 dB quantization; keys retain 0.1875 dB units */
#define MOD_SILENT 384               /* steps: 72 dB down, no modulation */
#define MOD_HOLD 0                  /* do not hold a stale timbre */
#define NOISE_FB 6
#define NOISE_BYTES 4096            /* per table; feedback 6 and 7 */
#define NOISE_SETTLE 512
#define NOISE_X (0x1fbu << 4)       /* odd F-number avoids short phase/feedback locking */
#define NOISE_PERIOD_PAL 18264u     /* Paula clock / OPL rate, 8.8 */
#define NOISE_PERIOD_NTSC 18432u
#define NOISE_MOD6 24               /* modulator attenuation below which feedback 6 is chaotic */
#define NOISE_MOD7 56               /* and feedback 7 (10.5 dB) */
#define CACHE 64
#define LOOP_LOG 12                  /* longest period loop, 4096 bytes */
#define RENDER_BUDGET FM_VOICES     /* every selected voice can follow its envelope */
#define NOISE_KEY 0x80000000u
#define FB_SETTLE 32                /* samples before a feedback loop's period */

enum { ATTACK, DECAY, SUSTAIN, RELEASE };

uint8_t fm_ntsc = 0;
static uint32_t rate_field, period_num, noise_period;

struct op {
    uint32_t rout;                  /* envelope attenuation, 8.8 */
    uint32_t acc;                   /* attack steps, 16.16 */
    uint8_t gen;
    uint8_t tl;                     /* total level at the last field */
    int8_t slope;                   /* its change since, within a note */
};

struct entry {
    uint16_t page, pages;
};

static struct op ops[18];
static uint8_t last_keyon[9];
static int8_t voice_ch[FM_VOICES] = {-1, -1, -1, -1};
static int8_t *pool;
static uint16_t pool_pages;
static uint8_t page_used[256];
static uint16_t first_free;         /* lowest free page, pool_pages if none */
/* cache slots: keys and field stamps apart for short scans */
static uint32_t cache_key[CACHE], cache_used[CACHE];
static struct entry cache[CACHE];
static uint32_t stamp;
static const int8_t *noise[2];
/* per voice: the last command and what it was made from */
struct memo {
    uint32_t key;                   /* the loop's (NOISE_KEY | fb: a noise table), 0 none */
    uint32_t base, x;               /* render key without loop length; fnum << block */
    uint16_t mq;                    /* its modulator step */
    uint8_t g;                      /* repeats() of a period loop */
    uint32_t stamp;
    const int8_t *loop;
    uint16_t bytes, period;
    int16_t slot;
};
static struct memo memo[FM_VOICES];
static uint8_t budget;
uint32_t fm_renders;

/* Envelope steps per field (8.8) of register rate r with key scaling ks
 * (steps[], fm_init); *hi the rate's high part (12+: attack within 2 ms). */
static uint32_t steps[64];

static uint32_t rate_step(uint8_t r, uint8_t ks, uint8_t *hi)
{
    uint8_t rate;
    if (!r) {
        *hi = 0;
        return 0;
    }
    rate = (uint8_t)((r << 2) + ks);
    if (rate > 63) {
        rate = 63;
    }
    *hi = rate >> 2;
    return steps[rate];
}

static void build_steps(void)
{
    uint8_t rate, h, lo;
    for (rate = 0; rate < 64; ++rate) {
        h = rate >> 2;
        lo = rate & 3;
        if (h >= 15) {
            lo = 0;
        }
        steps[rate] = h >= 12 ? ((4u + lo) * rate_field) << (h - 12) : ((4u + lo) * rate_field) >> (12 - h);
    }
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

/* The envelope half a field on, the state unchanged: a decay, sustain or
 * release step at its rate; an attack as it stands. */
static uint32_t eg_mid(const struct op *o, const uint8_t *opl, uint8_t off, uint8_t ks)
{
    uint8_t sr = opl[0x80 + off], hi;
    uint32_t r = o->rout, sl = (uint32_t)(sr >> 4 == 15 ? 31 : sr >> 4) << 12;
    switch (o->gen) {
    case ATTACK:
        return r;
    case DECAY:
        r += rate_step(opl[0x60 + off] & 15, ks, &hi) >> 1;
        return r < sl ? r : sl;
    case SUSTAIN:
        if (opl[0x20 + off] & 0x20) {
            return r;
        }
        /* falls through - a percussive sustain releases */
    default:
        r += rate_step(sr & 15, ks, &hi) >> 1;
        return r < 0x1f8u << 8 ? r : 0x1ffu << 8;
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

/* Log-sine of waveforms 0-3 over the 10-bit phase, bit 15 the sign
 * (Nuked's logsin_wf; fm_init). */
static uint16_t wave[4][1024];
/* R34: exact OPL exponential results and unattenuated carrier samples.
 * These ordinary-memory tables replace work inside every rendered sample. */
static uint16_t linear_exp[8192];
static int16_t carrier_wave[4][1024];

static void build_wave(void)
{
    uint16_t p, c2, wf;
    for (p = 0; p < 8192; ++p) {
        linear_exp[p] = (uint16_t)(exptab[p & 255] >> (p >> 8));
    }
    for (p = 0; p < 1024; ++p) {
        c2 = (p & 0x100) ? logsin[(p & 0xff) ^ 0xff] : logsin[p & 0xff];
        wave[0][p] = (uint16_t)((p & 0x200 ? 0x8000 : 0) | c2);
        wave[1][p] = (p & 0x200) ? 0x1000 : c2;
        wave[2][p] = c2;
        wave[3][p] = (p & 0x100) ? 0x1000 : logsin[p & 0xff];
        for (wf = 0; wf < 4; ++wf) {
            uint16_t w = wave[wf][p], l = linear_exp[w & 0x7fff];
            carrier_wave[wf][p] = (int16_t)((w & 0x8000) ? ~l : l);
        }
    }
}

/* One operator sample: Nuked's OPL3_SlotGenerate. */
static int16_t op_out(uint8_t wf, uint16_t p, uint16_t att)
{
    if (!att) {
        return carrier_wave[wf][p & 0x3ff];
    }
    uint16_t w = wave[wf][p & 0x3ff], l;
    uint32_t level = (w & 0x7fffu) + ((uint32_t)att << 3);
    if (level > 0x1fff) {
        level = 0x1fff;
    }
    l = linear_exp[level];
    return (int16_t)((w & 0x8000) ? ~l : l);
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

/* One sample of render: op_out of the modulator through `lm` (linear_exp
 * from its attenuation on: the level stays below 0x1fff, 0x1000 + 511 * 8, so
 * the clamp never applies) and of the carrier at full level. */
#define RENDER_SAMPLE(fb, cnt) do { \
        if (fb) { \
            fbmod = (int16_t)((prev1 + prev2) >> (9 - (fb))); \
        } \
        w = wm[(uint16_t)((pm >> 6) + fbmod) & 0x3ff]; \
        m = (int16_t)(lm[w & 0x7fff] ^ (uint16_t)((int16_t)w >> 15)); \
        prev2 = prev1; \
        prev1 = m; \
        c = cw[(uint16_t)((pc >> 6) + ((cnt) ? 0 : m)) & 0x3ff]; \
        if (cnt) { \
            c = (int16_t)((c + m) >> 1); \
        } \
        pc += ic; \
        pm += im; \
    } while (0)

/* render's samples for feedback `fb` and connection `cnt` (constants where
 * inlined): `settle` discarded, then `bytes` stored. */
static inline __attribute__((always_inline)) void render_run(int8_t *dst, uint16_t settle, uint16_t bytes,
    const uint16_t *wm, const uint16_t *lm, const int16_t *cw, uint32_t ic, uint32_t im, uint8_t fb, uint8_t cnt)
{
    uint32_t pc = 0, pm = 0;
    int16_t prev1 = 0, prev2 = 0, fbmod = 0, m, c;
    uint16_t i, w;
    for (i = 0; i < settle; ++i) {
        RENDER_SAMPLE(fb, cnt);
    }
    for (i = 0; i < bytes; ++i) {
        RENDER_SAMPLE(fb, cnt);
        *dst++ = (int8_t)(c >> 5);
    }
}

/* Render key fields: wf_c 0-1, wf_m 2-3, mult_c 4-7, mult_m 8-11, fb 12-14,
 * cnt 15, modulator level 16-24 (0.1875 dB units), log2 samples per period 25-28.
 * The phase steps by the loop's fraction of a period. */
static __attribute__((noinline)) void render(int8_t *dst, uint32_t key, uint16_t bytes)
{
    uint8_t wfc = key & 3, wfm = (key >> 2) & 3, fb = (key >> 12) & 7, cnt = (key >> 15) & 1;
    uint8_t mc = (key >> 4) & 15, mm = (key >> 8) & 15;
    uint16_t mq = (key >> 16) & 511;
    uint8_t g = repeats(wfc, wfm, mc, mm, mq >= MOD_SILENT);
    uint16_t matt = mq, spp = (uint16_t)(1u << ((key >> 25) & 15));
    /* phase in cycles, 16.16; >> 6 the chip's 10 bits */
    uint32_t ic = ((uint32_t)mt[mc] << 16) / g / spp, im = ((uint32_t)mt[mm] << 16) / g / spp;
    const uint16_t *wm = wave[wfm], *lm = linear_exp + ((uint32_t)matt << 3);
    const int16_t *cw = carrier_wave[wfc];
    /* Keep synthesis phase across timbre changes; do not rotate each loop. */
    ++fm_renders;
    if (cnt) {
        if (fb) {
            render_run(dst, FB_SETTLE, bytes, wm, lm, cw, ic, im, fb, 1);
        } else {
            render_run(dst, 0, bytes, wm, lm, cw, ic, im, 0, 1);
        }
    } else if (fb) {
        render_run(dst, FB_SETTLE, bytes, wm, lm, cw, ic, im, fb, 0);
    } else {
        render_run(dst, 0, bytes, wm, lm, cw, ic, im, 0, 0);
    }
}

/* Feedback noise table (fm_init): the chip at its own rate and step, sine
 * operators 1:1, modulator at full level, pitch NOISE_X, a two-sample moving average at the chip rate. */
static void render_noise(int8_t *dst, uint8_t fb)
{
    uint32_t inc = (NOISE_X >> 1) * mt[1] >> 1, pc = 0, pm = 0;
    int16_t prev1 = 0, prev2 = 0, m, c, sum = 0;
    uint16_t i;
    for (i = 0; i < NOISE_SETTLE + NOISE_BYTES; ++i) {
        m = op_out(0, (uint16_t)((pm >> 9) + ((prev1 + prev2) >> (9 - fb))), 0);
        prev2 = prev1;
        prev1 = m;
        c = op_out(0, (uint16_t)((pc >> 9) + m), 0);
        pc += inc;
        pm += inc;
        if (i >= NOISE_SETTLE) dst[i - NOISE_SETTLE] = (int8_t)((sum + c) >> 6);
        sum = c;
    }
}

void fm_init(int8_t *p, uint32_t bytes)
{
    uint16_t i;
    rate_field = fm_ntsc ? RATE_FIELD_NTSC : RATE_FIELD_PAL;
    period_num = fm_ntsc ? PERIOD_NUM_NTSC : PERIOD_NUM_PAL;
    noise_period = fm_ntsc ? NOISE_PERIOD_NTSC : NOISE_PERIOD_PAL;
    build_steps();
    build_wave();
    pool = p;
    pool_pages = (uint16_t)(bytes / FM_POOL_PAGE);
    if (pool_pages > 256) {
        pool_pages = 256;
    }
    for (i = 0; i < 256; ++i) {
        page_used[i] = 0;
    }
    /* the noise tables take the first pages for good */
    for (i = 0; i < 2; ++i) {
        render_noise(pool + i * NOISE_BYTES, (uint8_t)(NOISE_FB + i));
        noise[i] = pool + i * NOISE_BYTES;
    }
    for (i = 0; i < 2 * NOISE_BYTES / FM_POOL_PAGE; ++i) {
        page_used[i] = 1;
    }
    for (first_free = 0; first_free < pool_pages && page_used[first_free]; ++first_free) {
    }
    for (i = 0; i < 9; ++i) last_keyon[i] = 0;
    fm_renders = 0;
    for (i = 0; i < 18; ++i) {
        ops[i].rout = 0x1ffu << 8;
        ops[i].acc = 0;
        ops[i].gen = RELEASE;
    }
    for (i = 0; i < FM_VOICES; ++i) {
        voice_ch[i] = -1;
        memo[i].key = 0;
    }
    for (i = 0; i < CACHE; ++i) {
        cache_key[i] = 0;
    }
    stamp = 2;
}

#define NO_FIT 0xffffu

/* First page p in from .. to - 1 on the `pages` grid (from on it) with pages
 * p .. p + pages - 1 free and inside the pool; NO_FIT when none. */
static uint16_t fit_from(uint16_t from, uint16_t to, uint16_t pages)
{
    uint16_t p, k;
    for (p = from; p < to && p + pages <= pool_pages; p = (uint16_t)(p + pages)) {
        for (k = 0; k < pages && !page_used[p + k]; ++k) {
        }
        if (k == pages) {
            return p;
        }
    }
    return NO_FIT;
}

/* Cache slot of `key` (`bytes` long), rendered on a miss when `render_ok`;
 * -1 when not, or when every page is held by the loops of this or the last
 * field. Slots stay put (a voice keeps its slot's index). The loop takes the
 * first free run on the `pages` grid; until a run and a slot are free, the
 * least recently used loop of an earlier field goes (lowest slot on a tie).
 * The first empty slot holds it, else the first evicted. */
static int16_t loop_for(uint32_t key, uint16_t bytes, int render_ok)
{
    uint16_t pages = (uint16_t)((bytes + FM_POOL_PAGE - 1) / FM_POOL_PAGE), i, p, q, k, a, n;
    uint32_t oldest;
    int16_t slot = -1;
    for (i = 0; i < CACHE; ++i) {
        if (cache_key[i] == key) {
            cache_used[i] = stamp;
            return (int16_t)i;
        }
    }
    if (!render_ok) {
        return -1;
    }
    for (i = 0; i < CACHE; ++i) {
        if (!cache_key[i]) {
            slot = (int16_t)i;
            break;
        }
    }
    /* grid runs wholly below the first free page are held */
    p = fit_from((uint16_t)(first_free - first_free % pages), pool_pages, pages);
    while (p == NO_FIT || slot < 0) {
        /* evict the least recently used loop no voice may still play */
        k = CACHE;
        oldest = stamp - 1;
        for (i = 0; i < CACHE; ++i) {
            if (cache_used[i] < oldest && cache_key[i]) {
                oldest = cache_used[i];
                k = i;
            }
        }
        if (k == CACHE) {
            return -1;
        }
        a = cache[k].page;
        n = cache[k].pages;
        for (i = 0; i < n; ++i) {
            page_used[a + i] = 0;
        }
        if (a < first_free) {
            first_free = a;
        }
        cache_key[k] = 0;
        if (slot < 0) {
            slot = (int16_t)k;
        }
        /* only grid runs meeting the freed pages, before the old fit, gain */
        q = fit_from((uint16_t)(a - a % pages), p < a + n ? p : (uint16_t)(a + n), pages);
        if (q != NO_FIT) {
            p = q;
        }
    }
    for (k = 0; k < pages; ++k) {
        page_used[p + k] = 1;
    }
    if (p == first_free) {
        for (first_free = (uint16_t)(p + pages); first_free < pool_pages && page_used[first_free]; ++first_free) {
        }
    }
    cache_key[slot] = key;
    cache_used[slot] = stamp;
    cache[slot].page = p;
    cache[slot].pages = pages;
    render(pool + p * FM_POOL_PAGE, key, bytes);
    return slot;
}

/* Voice i's command for channel ch at attenuation att. Unchanged patch,
 * modulator level and pitch: the last field's loop and period. Past the
 * field's render budget only a restart renders; a continuing note whose loop
 * differs in modulator level alone keeps its loop a field longer. */
static void voice_cmd(struct fm_voice *v, uint8_t i, const uint8_t *opl, int8_t ch, uint16_t att)
{
    uint8_t c = (uint8_t)ch, mo = op_off[c], co = (uint8_t)(mo + 3), b0 = opl[0xb0 + c], c0 = opl[0xc0 + c];
    uint16_t fnum = (uint16_t)(opl[0xa0 + c] | (b0 & 3) << 8), bytes, raw, matt; /* matt: 0.1875 dB units */
    uint8_t block = (b0 >> 2) & 7, ws = (opl[1] & 0x20) != 0, fb = (c0 >> 1) & 7, lg, g;
    uint8_t wfc = ws ? opl[0xe0 + co] & 3 : 0, wfm = ws ? opl[0xe0 + mo] & 3 : 0;
    uint32_t key, d, x = (uint32_t)fnum << block, period = 0, renders = fm_renders;
    struct memo *m = &memo[i];
    int16_t slot;
    raw = op_att(&ops[2 * c], opl, mo, fnum, block);
    matt = raw >= MOD_SILENT ? MOD_SILENT :
           (uint16_t)(((raw + MOD_STEP / 2) / MOD_STEP) * MOD_STEP);
    /* hysteresis: a level drifting about a step boundary keeps its loop */
    if (m->key && (uint16_t)(raw - m->mq + MOD_HOLD) <= 2 * MOD_HOLD) {
        matt = m->mq;
    }
    if (matt > MOD_SILENT) {
        matt = MOD_SILENT;
    }
    if (!fnum) {
        m->key = 0;
        v->loop = 0;
        v->volume = 0;
        return;
    }
    key = (uint32_t)wfc | (uint32_t)wfm << 2 |
          (uint32_t)(opl[0x20 + co] & 15) << 4 | (uint32_t)(opl[0x20 + mo] & 15) << 8 |
          (uint32_t)fb << 12 | (uint32_t)(c0 & 1) << 15 | (uint32_t)matt << 16;
    if (m->key && m->stamp + 1 == stamp && m->base == key) {
        /* the same loop; a new pitch only a new period, while the loop's
         * length stays the longest that keeps it at PERIOD_MIN or above */
        if (m->x != x) {
            if (m->key & NOISE_KEY) {
                uint32_t xm = x * mt[opl[0x20 + mo] & 15] >> 1;
                period = xm ? (NOISE_X * noise_period / 256 + xm / 2) / xm : 0xffff;
            } else {
                lg = (uint8_t)((m->key >> 25) & 15);
                d = x * m->g;
                /* Check before shifting: high pitches can overflow 32 bits. */
                if (d > (period_num / PERIOD_MIN >> lg)) {
                    period = 0;
                } else {
                    d <<= lg;
                    period = (period_num + d / 2) / d;
                }
                if (period < PERIOD_MIN || (period >= 2 * PERIOD_MIN && ((m->key >> 25) & 15) < LOOP_LOG)) {
                    period = 0;
                }
            }
            if (period) {
                m->x = x;
                m->period = (uint16_t)(period < PERIOD_MIN ? PERIOD_MIN : period > 0xffff ? 0xffff : period);
            }
        }
        if (m->x == x) {
            if (m->slot >= 0) {
                cache_used[m->slot] = stamp;
            }
            m->stamp = stamp;
            v->loop = m->loop;
            v->bytes = m->bytes;
            v->period = m->period;
            v->volume = voltab[att];
            return;
        }
    }
    m->base = key;
    m->x = x;
    m->stamp = stamp;
    m->mq = matt;
    if (fb >= NOISE_FB && raw < (fb == 7 ? NOISE_MOD7 : NOISE_MOD6)) {
        /* chaotic: the noise table at the modulator's pitch */
        uint32_t xm = x * mt[opl[0x20 + mo] & 15] >> 1;
        period = xm ? (NOISE_X * noise_period / 256 + xm / 2) / xm : 0xffff;
        if (period < PERIOD_MIN) {
            period = PERIOD_MIN;
        }
        if (period > 0xffff) {
            period = 0xffff;
        }
        m->key = NOISE_KEY | fb;
        m->slot = -1;
        m->loop = v->loop = noise[fb - NOISE_FB];
        m->bytes = v->bytes = NOISE_BYTES;
        m->period = v->period = (uint16_t)period;
        v->volume = voltab[att];
        return;
    }
    g = repeats(wfc, wfm, opl[0x20 + co] & 15, opl[0x20 + mo] & 15, matt >= MOD_SILENT);
    m->g = g;
    for (lg = LOOP_LOG; lg >= 3; --lg) {
        d = x * g;
        if (d > (period_num / PERIOD_MIN >> lg)) continue;
        d <<= lg;
        period = (period_num + d / 2) / d;
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
    key |= (uint32_t)lg << 25;
    bytes = (uint16_t)(1u << lg);
    slot = loop_for(key, bytes, v->restart || budget);
    if (slot < 0 && m->key && !(m->key & NOISE_KEY) && ((key ^ m->key) & ~(511u << 16)) == 0) {
        slot = loop_for(m->key, bytes, 0);
        if (slot >= 0) {
            key = m->key;
        }
    }
    if (slot < 0) {
        slot = loop_for(key, bytes, 1);
    }
    if (fm_renders != renders && budget) {
        --budget;
    }
    m->key = slot >= 0 ? key : 0;
    m->slot = slot;
    m->loop = v->loop = slot >= 0 ? pool + cache[slot].page * FM_POOL_PAGE : 0;
    m->bytes = v->bytes = bytes;
    m->period = v->period = (uint16_t)period;
    v->volume = v->loop ? voltab[att] : 0;
}

/* Prefer a continuing note within 3 dB, independently of its physical voice. */
static int8_t choose_channel(int16_t *score, uint8_t first, uint8_t last)
{
    int8_t best = -1;
    int16_t best_score = 0x7fff;
    uint8_t c;
    for (c = first; c <= last; ++c) {
        if (score[c] < best_score) { best = (int8_t)c; best_score = score[c]; }
    }
    if (best >= 0) score[(uint8_t)best] = 0x7fff;
    return best;
}

void fm_field(const uint8_t *opl, const uint8_t *keyon, uint16_t mute_mask, struct fm_voice *voice)
{
    uint16_t att[9];
    int16_t score[9];
    uint8_t c, i, j, newkey[9], reserved = 0;
    int8_t choice[FM_VOICES], assigned[FM_VOICES];
    uint16_t taken = mute_mask;
    uint16_t available = 0, held = 0;
    ++stamp;
    budget = RENDER_BUDGET;
    for (c = 0; c < 9; ++c) {
        uint8_t b0 = opl[0xb0 + c], block = (b0 >> 2) & 7, mo = op_off[c], k;
        uint16_t fnum = (uint16_t)(opl[0xa0 + c] | (b0 & 3) << 8);
        uint8_t ksv = (uint8_t)(block << 1 | ((fnum >> 9) & 1));
        newkey[c] = keyon[c] != last_keyon[c];
        last_keyon[c] = keyon[c];
        att[c] = 0xffff;
        if (!newkey[c] && ops[2 * c].gen == RELEASE && ops[2 * c + 1].gen == RELEASE &&
            (ops[2 * c].rout & ops[2 * c + 1].rout) == 0x1ffu << 8) {
            continue;   /* silent until its next key-on */
        }
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
        for (k = (opl[0xc0 + c] & 1) ? 0 : 1; k < 2; ++k) {
            struct op o = ops[2 * c + k];
            uint8_t off = (uint8_t)(mo + 3 * k);
            uint16_t a;
            o.rout = eg_mid(&o, opl, off, (opl[0x20 + off] & 0x10) ? ksv : ksv >> 2);
            a = op_att(&o, opl, off, fnum, block);
            a = (uint16_t)(o.slope < 0 && a < (uint16_t)(-2 * o.slope) ? 0 : a + 2 * o.slope);
            if (a < att[c]) {
                att[c] = a;
            }
        }
    }
    for (c = 0; c < 9; ++c) {
        score[c] = (taken >> c & 1) || att[c] >= ATT_SILENT ? 0x7fff : (int16_t)att[c];
        if (score[c] != 0x7fff) available |= (uint16_t)(1u << c);
    }
    for (i = 0; i < FM_VOICES; ++i) {
        int8_t ch = voice_ch[i];
        if (i < 3 && (mute_mask & (7u << (3 * i)))) reserved |= (uint8_t)(1u << i);
        assigned[i] = -1;
        if (ch >= 0 && score[(uint8_t)ch] != 0x7fff && !(reserved >> i & 1)) {
            assigned[i] = ch;
            held |= (uint16_t)(1u << ch);
        }
    }
    /* All audible channels already fit: selection cannot add or displace a
     * note. Still publish new key-ons, envelopes and changed loops below. */
    if (available == held) {
        goto publish_voices;
    }
    for (i = 0; i < FM_VOICES; ++i) {
        int8_t ch = voice_ch[i];
        if (ch >= 0 && score[(uint8_t)ch] != 0x7fff) score[(uint8_t)ch] -= STICKY;
    }
    /* Choose the set before assigning voices: an extra note must not steal
     * another group's only representative. A sample owns its physical slot. */
    for (i = 0; i < FM_VOICES; ++i) {
        choice[i] = assigned[i] = -1;
        if (i < 3) {
            if (mute_mask & (7u << (3 * i))) {
                reserved |= (uint8_t)(1u << i);
            } else {
                choice[i] = choose_channel(score, (uint8_t)(3 * i), (uint8_t)(3 * i + 2));
            }
        }
    }
    for (i = 0; i < FM_VOICES; ++i) {
        if (choice[i] < 0 && !(reserved >> i & 1)) {
            choice[i] = choose_channel(score, 0, 8);
        }
    }
    /* Keep a continuing selected note on its DMA voice, avoiding a restart
     * merely because it changed rank within its group. */
    for (i = 0; i < FM_VOICES; ++i) {
        if (voice_ch[i] >= 0 && !(reserved >> i & 1)) {
            for (j = 0; j < FM_VOICES; ++j) {
                if (choice[j] == voice_ch[i]) {
                    assigned[i] = choice[j];
                    choice[j] = -1;
                    break;
                }
            }
        }
    }
    for (i = 0; i < FM_VOICES; ++i) {
        if (assigned[i] < 0 && !(reserved >> i & 1)) {
            for (j = 0; j < FM_VOICES; ++j) {
                if (choice[j] >= 0) {
                    assigned[i] = choice[j];
                    choice[j] = -1;
                    break;
                }
            }
        }
    }
publish_voices:
    for (i = 0; i < FM_VOICES; ++i) {
        int8_t best = assigned[i], cur = voice_ch[i];
        voice[i].restart = best >= 0 && (best != cur || newkey[best]);
        voice[i].channel = best;
        voice_ch[i] = best;
        if (best < 0) {
            voice[i].loop = 0;
            voice[i].volume = 0;
            continue;
        }
        voice_cmd(&voice[i], i, opl, best, att[best]);
    }
}

/* Prerendered effects (docs/sound-plan.md R2): a captured effect synthesised
 * once, directly at FM_EFFECT_RATE (the chip rate / 3) with continuous phase:
 * the registers from `opl`, then `w[0..n)` applied at their ticks (236.7 Hz,
 * 5041/72 output samples each); a key-on edge restarts both operators'
 * phase and attack, as the chip. Envelopes advance per tick (eg_advance);
 * operators as op_out, feedback per output sample. Channels written by the
 * effect are mixed; the result is scaled to full 8 bits, *level its peak. */
#define FX_TICK_NUM 5041u           /* output samples per tick, / FX_TICK_DEN */
#define FX_TICK_DEN 72u
#define FX_TAIL_TICKS 474u          /* release tail after the last write, 2 s at most */

struct fx_channel {
    uint32_t pm, pc;
    int16_t prev1, prev2;
};

static int32_t fx_mix[FX_TICK_NUM / FX_TICK_DEN + 2];

uint32_t fm_effect(const uint8_t *opl0, const struct fm_write *w, uint32_t n, int8_t *out, uint32_t max,
                   uint32_t *level)
{
    uint8_t opl[256];
    struct op fop[18];
    struct fx_channel ch[9];
    uint16_t used = 0, c;
    uint32_t i = 0, tick = 0, frac = 0, len = 0, last = n ? w[n - 1].tick : 0, peak = 1;
    /* the envelope's ticks in 1/256 field, 16.16 */
    uint32_t dt = (uint32_t)((fm_ntsc ? 59.826 : FM_FIELD_HZ) * 65536.0 * 256.0 / 236.7), dacc = 0;
    for (i = 0; i < n; ++i) {
        uint8_t r = w[i].reg;
        if (r >= 0xa0 && r <= 0xc8 && (r & 15) < 9) {
            used |= (uint16_t)(1u << (r & 15));
        }
    }
    /* Two passes: the peak, then the samples scaled to it. A channel is
     * silent below the 8-bit floor of the scaled sample: ATT_SILENT under
     * the peak (32 units per halving), the chip's floor in the first pass. */
    for (int pass = 0; pass < 2; ++pass) {
        uint32_t k = 0, p = peak;
        int32_t scale = pass ? (int32_t)((127L << 16) / (int32_t)peak) : 0;
        uint16_t silent = pass ? ATT_SILENT : 0x1ff;
        for (; pass && p < FM_EFFECT_FULL && silent < 0x1ff; p <<= 1) silent += 32;
        for (c = 0; c < 256; ++c) opl[c] = opl0[c];
        for (c = 0; c < 18; ++c) {
            fop[c].rout = 0x1ffu << 8;
            fop[c].acc = 0;
            fop[c].gen = RELEASE;
        }
        for (c = 0; c < 9; ++c) {
            ch[c].pm = ch[c].pc = 0;
            ch[c].prev1 = ch[c].prev2 = 0;
        }
        i = 0;
        frac = 0;
        dacc = 0;
        len = 0;
        for (tick = 0; tick <= last + FX_TAIL_TICKS; ++tick) {
            uint32_t m_n, s;
            int audible = 0;
            for (; i < n && w[i].tick == tick; ++i) {
                uint8_t r = w[i].reg, v = w[i].value;
                if (r >= 0xb0 && r <= 0xb8) {
                    uint8_t cc = (uint8_t)(r - 0xb0);
                    if ((v & 0x20) && !(opl[r] & 0x20)) {
                        fop[2 * cc].gen = fop[2 * cc + 1].gen = ATTACK;
                        fop[2 * cc].acc = fop[2 * cc + 1].acc = 0;
                        ch[cc].pm = ch[cc].pc = 0;
                    } else if (!(v & 0x20) && (opl[r] & 0x20)) {
                        fop[2 * cc].gen = fop[2 * cc + 1].gen = RELEASE;
                    }
                }
                opl[r] = v;
            }
            frac += FX_TICK_NUM;
            m_n = frac / FX_TICK_DEN;
            frac %= FX_TICK_DEN;
            dacc += dt;
            uint32_t step = dacc >> 16;
            dacc &= 0xffff;
            for (s = 0; s < m_n; ++s) fx_mix[s] = 0;
            for (c = 0; c < 9; ++c) {
                if (!(used >> c & 1)) continue;
                uint8_t b0 = opl[0xb0 + c], block = (b0 >> 2) & 7, mo = op_off[c], co = (uint8_t)(mo + 3);
                uint16_t fnum = (uint16_t)(opl[0xa0 + c] | (b0 & 3) << 8);
                uint8_t ksv = (uint8_t)(block << 1 | ((fnum >> 9) & 1));
                uint8_t ws = (opl[1] & 0x20) != 0, c0 = opl[0xc0 + c], fb = (c0 >> 1) & 7, cnt = c0 & 1;
                uint8_t wfm = ws ? opl[0xe0 + mo] & 3 : 0, wfc = ws ? opl[0xe0 + co] & 3 : 0;
                uint16_t am, ac;
                for (uint8_t k2 = 0; k2 < 2; ++k2) {
                    uint8_t off = (uint8_t)(mo + 3 * k2);
                    eg_advance(&fop[2 * c + k2], opl, off, (opl[0x20 + off] & 0x10) ? ksv : ksv >> 2, step);
                }
                am = op_att(&fop[2 * c], opl, mo, fnum, block);
                ac = op_att(&fop[2 * c + 1], opl, co, fnum, block);
                if (am > 0x1ff) am = 0x1ff;
                if (ac > 0x1ff) ac = 0x1ff;
                if (ac >= silent && (!cnt || am >= silent)) continue;
                audible = 1;
                uint32_t base = (uint32_t)(fnum << block) >> 1;
                uint32_t im = 3 * (base * mt[opl[0x20 + mo] & 15] >> 1);
                uint32_t ic = 3 * (base * mt[opl[0x20 + co] & 15] >> 1);
                struct fx_channel *x = &ch[c];
                for (s = 0; s < m_n; ++s) {
                    int16_t fbm = fb ? (int16_t)((x->prev1 + x->prev2) >> (9 - fb)) : 0;
                    int16_t mv = op_out(wfm, (uint16_t)((x->pm >> 9) + fbm), am);
                    x->prev2 = x->prev1;
                    x->prev1 = mv;
                    int16_t cv = op_out(wfc, (uint16_t)((x->pc >> 9) + (cnt ? 0 : mv)), ac);
                    fx_mix[s] += cnt ? cv + mv : cv;
                    x->pm += im;
                    x->pc += ic;
                }
            }
            for (s = 0; s < m_n; ++s, ++k) {
                int32_t v = fx_mix[s];
                if (!pass) {
                    uint32_t a = (uint32_t)(v < 0 ? -v : v);
                    if (a > peak) peak = a;
                } else if (k < max) {
                    int32_t q = (v * scale) >> 16;
                    out[k] = (int8_t)(q > 127 ? 127 : q < -128 ? -128 : q);
                }
            }
            if (audible || tick <= last) {
                len = k;
            } else {
                break;
            }
        }
    }
    *level = peak;
    return len < max ? len : max;
}
