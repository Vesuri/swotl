#include <proto/exec.h>
#include <proto/dos.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include <hardware/dmabits.h>
extern "C" {
#include "runtime.h"
#include "fm_paula.h"
#include "tfh_paula.h"
#include "amiga_platform.h"
}
#include "Audio.h"
#include "AmigaHardware.h"

// Voice v plays on Paula channel v: the engine (0) and the rest (3) left,
// SPAZ's two effect slots (1, 2) right.
#define POOL_BYTES (FM_POOL_BYTES)
#define SILENCE_BYTES 4
#define AUDIO_DMA (DMAF_AUD0 | DMAF_AUD1 | DMAF_AUD2 | DMAF_AUD3)
#define PERIOD_FLOOR 124
// A restart's DMA-off window: Paula goes idle only at the end of a period in
// its second-byte state, up to two outgoing periods (AUDxPER does not cut a
// countdown short; Revs, Rescue on Fractalus, Vette), capped; a loop
// restarted late still plays valid samples (fm_paula.c keeps the last
// field's loops).
#define RESTART_LINES_MAX 16

// AUDxLC, LEN, PER, VOL, DAT, 16 bytes a channel
struct Channel {
    const int8_t* volatile lc;
    volatile uint16_t len, per, vol, dat;
    uint16_t pad[2];
};
#define PAULA ((volatile Channel*)aud0ptrPointer)

static int8_t* tfhChip = 0;
static uint32_t tfhBytes = 0;
static int8_t* effectChip[RT_SFX_IDS];
static uint32_t effectBytes[RT_SFX_IDS];
static uint8_t effectVolume[RT_SFX_IDS];
static volatile bool effects = false;
static int8_t* pool = 0;
static const int8_t* silence = 0;
static struct fm_voice pending[FM_VOICES];
static volatile bool fresh = false;
static volatile bool muted = false;
static bool running = false;
static const int8_t* shownLoop[FM_VOICES];
static uint16_t shownBytes[FM_VOICES], shownPeriod[FM_VOICES];

extern "C" {
volatile uint32_t amiga_audio_restarts = 0;   // channel restarts (diagnostics)
volatile uint32_t amiga_audio_effect_fields = 0;  // fields the prerender took (diagnostics)
volatile uint32_t amiga_audio_effect_save_fields = 0;  // of them, the cache write (diagnostics)
volatile uint32_t amiga_audio_effect_bytes = 0;   // its Chip bytes (diagnostics)
volatile uint8_t amiga_audio_effect_cached = 0;   // 1 loaded from the cache, 2 written to it (diagnostics)
}

static_assert(sizeof(struct rt_sfx_write) == sizeof(struct fm_write), "capture and fm_effect write layouts");

bool Audio::begin()
{
    pool = (int8_t*)AllocMem(POOL_BYTES + SILENCE_BYTES, MEMF_CHIP | MEMF_CLEAR);
    if (!pool) return false;
    silence = pool + POOL_BYTES;
    fm_init(pool, POOL_BYTES);
    return true;
}

bool Audio::loadTFH(const uint8_t *rsc, uint32_t size)
{
    if (!pool || tfhChip) return false;
    tfhBytes = tfh_chip_bytes(rsc, size);
    if (!tfhBytes) return false;
    tfhChip = (int8_t*)AllocMem(tfhBytes, MEMF_CHIP);
    if (!tfhChip) return false;
    if (tfh_init(rsc, size, tfhChip)) {
        FreeMem(tfhChip, tfhBytes);
        tfhChip = 0;
        return false;
    }
    return true;
}

extern "C" int amiga_audio_tfh(const uint8_t *rsc, uint32_t size)
{
    return Audio::loadTFH(rsc, size);
}

// The effect cache (docs/sound-plan.md R4): the rendered samples in the game
// drawer, keyed by everything they come from (fm_effect's version, PAL/NTSC,
// the wanted ids, the capture). Big-endian: "SWFX", version, key, count;
// count entries (id, volume, 2 bytes 0, bytes); the samples in that order.
#define CACHE_NAME "sfx.cache"
#define CACHE_MAGIC 0x53574658u     // "SWFX"
struct CacheEntry {
    uint8_t id, volume, pad[2];
    uint32_t bytes;
};

static uint32_t fnv(uint32_t h, const void* data, uint32_t n)
{
    const uint8_t* p = (const uint8_t*)data;
    while (n--) h = (h ^ *p++) * 16777619u;
    return h;
}

static uint32_t effectsKey()
{
    uint32_t h = 2166136261u, v = FM_EFFECT_VERSION;
    h = fnv(h, &v, sizeof v);
    h = fnv(h, &fm_ntsc, 1);
    h = fnv(h, rt_sfx_opl, 256);
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        uint8_t wanted = rt_sfx_writes[id] && tfh_effect_wanted(id);
        h = fnv(h, &wanted, 1);
        if (!wanted) continue;
        h = fnv(h, &rt_sfx_writes[id], sizeof rt_sfx_writes[id]);
        h = fnv(h, &rt_sfx_capture[rt_sfx_first[id]], rt_sfx_writes[id] * sizeof(struct rt_sfx_write));
    }
    return h;
}

static void freeEffects()
{
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        if (effectChip[id]) FreeMem(effectChip[id], effectBytes[id]);
        effectChip[id] = 0;
    }
    amiga_audio_effect_bytes = 0;
}

static void registerEffects()
{
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        if (!effectChip[id]) continue;
        amiga_audio_effect_bytes += effectBytes[id];
        tfh_effect(id, effectChip[id], effectBytes[id], effectVolume[id], silence);
        effects = true;
    }
}

// The cache's samples straight into Chip, in one I/O window; false (nothing
// kept) unless every wanted id comes back whole under this key.
static bool loadCache(uint32_t key)
{
    uint32_t head[4], wanted = 0;
    struct CacheEntry entry[RT_SFX_IDS];
    bool ok = false;
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) wanted += rt_sfx_writes[id] && tfh_effect_wanted(id);
    amiga_io_begin();
    BPTR f = Open((CONST_STRPTR)CACHE_NAME, MODE_OLDFILE);
    if (f) {
        ok = Read(f, head, sizeof head) == sizeof head && head[0] == CACHE_MAGIC &&
             head[1] == FM_EFFECT_VERSION && head[2] == key && head[3] == wanted &&
             Read(f, entry, wanted * sizeof entry[0]) == (LONG)(wanted * sizeof entry[0]);
        for (uint32_t k = 0; ok && k < wanted; ++k) {
            const struct CacheEntry& e = entry[k];
            ok = e.id < RT_SFX_IDS && !effectChip[e.id] && tfh_effect_wanted(e.id) && e.bytes >= 2 &&
                 e.bytes <= TFH_EFFECT_BYTES && !(e.bytes & 1) &&
                 (effectChip[e.id] = (int8_t*)AllocMem(e.bytes, MEMF_CHIP)) != 0;
            if (!ok) break;
            effectBytes[e.id] = e.bytes;
            effectVolume[e.id] = e.volume;
            ok = Read(f, effectChip[e.id], e.bytes) == (LONG)e.bytes;
        }
        Close(f);
    }
    if (!ok) freeEffects();
    amiga_io_end();
    return ok;
}

// The rendered samples to the cache in one I/O window and one Write (under
// WHDLoad each write is a save followed by its write delay; docs/whdload.md),
// the file made as the game's are: MODE_NEWFILE, Close, MODE_OLDFILE. Without
// Fast for the file's image nothing is written; a failed write leaves a file
// the next load refuses.
static void saveCache(uint32_t key)
{
    uint32_t head[4] = {CACHE_MAGIC, FM_EFFECT_VERSION, key, 0}, total = sizeof head;
    struct CacheEntry entry[RT_SFX_IDS];
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        if (!effectChip[id]) continue;
        struct CacheEntry& e = entry[head[3]++];
        e.id = id;
        e.volume = effectVolume[id];
        e.pad[0] = e.pad[1] = 0;
        e.bytes = effectBytes[id];
        total += sizeof e + e.bytes;
    }
    amiga_io_begin();
    uint8_t* image = (uint8_t*)AllocMem(total, MEMF_ANY);
    amiga_io_end();
    if (!image) return;
    uint8_t* p = image;
    CopyMem(head, p, sizeof head);
    p += sizeof head;
    CopyMem(entry, p, head[3] * sizeof entry[0]);
    p += head[3] * sizeof entry[0];
    for (uint32_t k = 0; k < head[3]; ++k) {
        CopyMem(effectChip[entry[k].id], p, entry[k].bytes);
        p += entry[k].bytes;
    }
    amiga_io_begin();
    BPTR f = Open((CONST_STRPTR)CACHE_NAME, MODE_NEWFILE);
    if (f) {
        Close(f);
        f = Open((CONST_STRPTR)CACHE_NAME, MODE_OLDFILE);
    }
    if (f) {
        if (Write(f, image, total) == (LONG)total) amiga_audio_effect_cached = 2;
        Close(f);
    }
    FreeMem(image, total);
    amiga_io_end();
}

// Prerendered effects (docs/sound-plan.md R3, R4), from the runtime's capture
// at SPAZ init (plat_sfx_captured): from the cache when it holds this
// capture's samples, else each id through fm_effect in Fast, then its own Chip
// block, and the cache written. The allocations in I/O windows, the rendering
// not. Every wanted id or none: all render or none is kept.
void Audio::loadEffects()
{
    if (!pool) return;
    uint32_t start = amiga_frames, key = effectsKey();
    if (loadCache(key)) {
        amiga_audio_effect_cached = 1;
        registerEffects();
        amiga_audio_effect_fields = amiga_frames - start;
        return;
    }
    amiga_io_begin();
    int16_t* render = (int16_t*)AllocMem(TFH_EFFECT_BYTES * 2, MEMF_ANY);
    amiga_io_end();
    if (!render) return;
    bool ok = true;
    for (uint8_t id = 0; ok && id < RT_SFX_IDS; ++id) {
        if (!rt_sfx_writes[id] || !tfh_effect_wanted(id)) continue;
        uint32_t level = 0;
        uint32_t n = fm_effect(rt_sfx_opl, (const struct fm_write*)&rt_sfx_capture[rt_sfx_first[id]],
                               rt_sfx_writes[id], render, TFH_EFFECT_BYTES, &level);
        int8_t* pcm = (int8_t*)render;
        uint32_t bytes = n < 2 ? 2 : (n + 1) & ~1u;
        for (uint32_t k = n; k < bytes; ++k) pcm[k] = 0;
        amiga_io_begin();
        int8_t* chip = (int8_t*)AllocMem(bytes, MEMF_CHIP);
        amiga_io_end();
        if (!chip) {
            ok = false;
            break;
        }
        CopyMem(pcm, chip, bytes);
        effectChip[id] = chip;
        effectBytes[id] = bytes;
        effectVolume[id] = tfh_effect_volume(level);
    }
    amiga_io_begin();
    FreeMem(render, TFH_EFFECT_BYTES * 2);
    if (!ok) freeEffects();
    amiga_io_end();
    if (!ok) return;
    registerEffects();
    uint32_t save = amiga_frames;
    saveCache(key);
    amiga_audio_effect_save_fields = amiga_frames - save;
    amiga_audio_effect_fields = amiga_frames - start;
}

extern "C" int amiga_audio_effect_wanted(uint8_t id)
{
    return pool && tfh_effect_wanted(id);
}

extern "C" void amiga_audio_effects(void)
{
    Audio::loadEffects();
}

void Audio::end()
{
    effects = false;
    freeEffects();
    if (tfhChip) FreeMem(tfhChip, tfhBytes);
    tfhChip = 0;
    if (pool) FreeMem(pool, POOL_BYTES + SILENCE_BYTES);
    pool = 0;
}

void Audio::takeOver()
{
    if (!pool) return;
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        PAULA[c].vol = 0;
        PAULA[c].lc = silence;
        PAULA[c].len = SILENCE_BYTES / 2;
        PAULA[c].per = PERIOD_FLOOR;
        shownLoop[c] = silence;
        shownBytes[c] = SILENCE_BYTES;
        shownPeriod[c] = PERIOD_FLOOR;
    }
    AmigaHardware::setDMAChannels(AUDIO_DMA, true);
    running = true;
}

void Audio::handBack()
{
    running = false;
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        PAULA[c].vol = 0;
    }
    AmigaHardware::setDMAChannels(AUDIO_DMA, false);
}

void Audio::service()
{
    if (!running) return;
    // The OPL state between two ticks' writes (docs/irq-plan.md I5): the
    // field task runs at interrupt level, the tick masked for the copy.
    typedef uint32_t __attribute__((may_alias)) Long;
    static uint8_t opl[256] __attribute__((aligned(4)));
    static uint8_t keyon[9], id[TFH_SLOTS], starts[TFH_SLOTS];
    Disable();
    for (uint16_t k = 0; k < 256; k += 4) *(Long*)(opl + k) = *(const Long*)(rt_opl + k);
    for (uint16_t k = 0; k < 9; ++k) keyon[k] = rt_opl_keyon[k];
    for (uint16_t k = 0; k < TFH_SLOTS; ++k) {
        id[k] = rt_sfx_id[k];
        starts[k] = rt_sfx_starts[k];
    }
    Enable();
    struct fm_voice v[FM_VOICES];
    struct fm_voice t[TFH_SLOTS];
    uint16_t mask = tfhChip || effects ? tfh_field(opl, id, starts, t) : 0;
    fm_field(opl, keyon, mask, v);
    for (uint16_t k = 0; k < TFH_SLOTS; ++k) {
        if (mask & (7u << (3 * k))) v[k] = t[k];
    }
    Disable();
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        // a restart the vertical blank has not staged yet still happens
        if (fresh && pending[c].restart) v[c].restart = 1;
        pending[c] = v[c];
    }
    fresh = true;
    Enable();
}

static void waitLines(uint16_t lines)
{
    uint16_t line = *vhposrPointer >> 8;
    while (lines) {
        uint16_t now = *vhposrPointer >> 8;
        if (now != line) {
            line = now;
            --lines;
        }
    }
}

void Audio::verticalBlank()
{
    if (!running || !fresh) return;
    fresh = false;
    uint16_t restart = 0, outgoing = 0;
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        const struct fm_voice& v = pending[c];
        if (muted || !v.loop) {
            PAULA[c].vol = 0;   // silence: the loop plays on, unheard
            continue;
        }
        // A silent attack still starts its PCM and latches its repeat segment.
        if (v.restart) {
            restart |= DMAF_AUD0 << c;
            if (shownPeriod[c] > outgoing) outgoing = shownPeriod[c];
            PAULA[c].vol = 0;
            continue;
        }
        if (v.loop != shownLoop[c] || v.bytes != shownBytes[c]) {
            PAULA[c].lc = v.loop;   // latched at the running loop's end
            PAULA[c].len = v.bytes / 2;
        }
        PAULA[c].per = v.period;
        PAULA[c].vol = v.volume;
        shownLoop[c] = v.loop;
        shownBytes[c] = v.bytes;
        shownPeriod[c] = v.period;
    }
    if (!restart) return;
    *dmaconPointer = restart;
    uint16_t lines = (2u * outgoing + 226) / 227 + 2;
    waitLines(lines < RESTART_LINES_MAX ? lines : RESTART_LINES_MAX);
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        if (!(restart & (DMAF_AUD0 << c))) continue;
        const struct fm_voice& v = pending[c];
        PAULA[c].lc = v.loop;
        PAULA[c].len = v.bytes / 2;
        PAULA[c].per = v.period;
        PAULA[c].vol = v.volume;
        shownLoop[c] = v.loop;
        shownBytes[c] = v.bytes;
        shownPeriod[c] = v.period;
        ++amiga_audio_restarts;
    }
    *dmaconPointer = DMAF_SETCLR | restart;
}

void Audio::mute(bool on)
{
    muted = on;
    if (on) {
        for (uint16_t c = 0; c < FM_VOICES; ++c) {
            PAULA[c].vol = 0;
        }
    } else {
        fresh = true;   // the next vertical blank restores the volumes
    }
}

extern "C" void amiga_audio_service(void)
{
    Audio::service();
}
