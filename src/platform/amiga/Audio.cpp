#include <proto/exec.h>
#include <exec/memory.h>
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
#define POOL_BYTES (64 * FM_POOL_PAGE)
#define SILENCE_BYTES 4
#define AUDIO_DMA (DMAF_AUD0 | DMAF_AUD1 | DMAF_AUD2 | DMAF_AUD3)
#define PERIOD_FLOOR 124
// A restart's DMA-off window: the outgoing period's countdown runs out first
// (Revs, Rescue on Fractalus: AUDxPER does not cut it short), capped; a
// loop restarted late still plays valid samples (fm_paula.c keeps the last
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
}

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

void Audio::end()
{
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
    struct fm_voice v[FM_VOICES];
    struct fm_voice t[TFH_SLOTS];
    uint16_t mask = tfhChip ? tfh_field(rt_opl, rt_sfx_id, rt_sfx_starts, t) : 0;
    fm_field(rt_opl, rt_opl_keyon, mask, v);
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
    uint16_t lines = outgoing / 227 + 4;
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
