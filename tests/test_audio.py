#!/usr/bin/env python3
"""Production Paula backend: sample ownership, zero-volume attack, the restart's
DMA-off window (two outgoing periods), Chip lifetime,
the field's OPL snapshot (taken with interrupts disabled; a tick when they
return must not reach it), prerendered effects (a Chip block per wanted
captured id, even, the Fast render buffer released, the sample player run
without TFH; the cache written in one Write, loaded instead of rendering, refused for
another capture or a cut file). Mock MMIO and command producers; the sample/FM cores have
independent gates.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'
HEADERS = {
    'Util.h': '#include <stdint.h>\n',
    'proto/exec.h': '#include <stdint.h>\nvoid *AllocMem(uint32_t, uint32_t);\nvoid FreeMem(void *, uint32_t);\nvoid Disable(); void Enable();\nvoid CopyMem(const void *, void *, uint32_t);\n',
    'exec/memory.h': '#define MEMF_ANY 0\n#define MEMF_CHIP 2\n#define MEMF_CLEAR 65536\n',
    'hardware/dmabits.h': '#define DMAF_AUD0 1\n#define DMAF_AUD1 2\n#define DMAF_AUD2 4\n#define DMAF_AUD3 8\n#define DMAF_SETCLR 32768\n',
    'runtime.h': '''#include <stdint.h>
extern uint8_t rt_opl[256], rt_opl_keyon[9], rt_sfx_id[3], rt_sfx_starts[3];
#define RT_SFX_IDS 39
struct rt_sfx_write { uint16_t tick; uint8_t reg, value; };
extern struct rt_sfx_write rt_sfx_capture[64];
extern uint16_t rt_sfx_first[RT_SFX_IDS], rt_sfx_writes[RT_SFX_IDS];
extern uint8_t rt_sfx_opl[256];
''',
    'amiga_platform.h': '#include <stdint.h>\nextern volatile uint32_t amiga_frames;\nvoid amiga_io_begin(void);\nvoid amiga_io_end(void);\n',
    'proto/dos.h': '''#include <stdint.h>
typedef void *BPTR; typedef const unsigned char *CONST_STRPTR; typedef int32_t LONG;
BPTR Open(CONST_STRPTR, LONG); void Close(BPTR);
LONG Read(BPTR, void *, LONG); LONG Write(BPTR, const void *, LONG);
''',
    'dos/dos.h': '#define MODE_OLDFILE 1005\n#define MODE_NEWFILE 1006\n',
    'AmigaHardware.h': '''#include <stdint.h>
extern unsigned char registers[128];
extern volatile uint16_t dma;
struct Beam { unsigned n = 0; operator uint16_t() { return (++n & 255) << 8; } };
extern Beam beam;
#define aud0ptrPointer registers
#define dmaconPointer (&dma)
#define vhposrPointer (&beam)
class AmigaHardware { public: static void setDMAChannels(uint16_t, bool) {} };
''',
}
HARNESS = r'''
#include <cassert>
#include <cstdlib>
#include <algorithm>
#include <cstring>
#include <map>
#include <string>
#include "Audio.cpp"
alignas(8) unsigned char registers[128];
volatile uint16_t dma;
Beam beam;
static std::map<void *, uint32_t> allocations;
static unsigned fastBlocks, ioDepth;
static bool takenOver;          // allocations after the takeover: in I/O windows
void *AllocMem(uint32_t n, uint32_t flags) {
    assert(!takenOver || ioDepth == 1);
    if (!(flags & MEMF_CHIP)) ++fastBlocks;
    void *p = calloc(1, n); allocations[p] = n; return p;
}
void FreeMem(void *p, uint32_t n) {
    assert(allocations.at(p) == n); allocations.erase(p); free(p);
}
void CopyMem(const void *s, void *d, uint32_t n) { memcpy(d, s, n); }
// One DOS file (the cache): opened in I/O windows only, the name checked.
static std::string disk;
static bool exists;
static size_t pos;
static int opens, writes;
BPTR Open(CONST_STRPTR name, LONG mode) {
    assert(ioDepth == 1 && !strcmp((const char *)name, "sfx.cache"));
    if (mode == MODE_NEWFILE) { disk.clear(); exists = true; }
    if (!exists) return 0;
    ++opens; pos = 0; return (BPTR)&disk;
}
void Close(BPTR) { assert(ioDepth == 1); --opens; }
LONG Read(BPTR, void *b, LONG n) {
    LONG k = (LONG)std::min((size_t)n, disk.size() - pos);
    memcpy(b, disk.data() + pos, k); pos += k; return k;
}
LONG Write(BPTR, const void *b, LONG n) {
    ++writes;
    disk.replace(pos, n, (const char *)b, n); pos += n; return n;
}
volatile uint32_t amiga_frames;
void amiga_io_begin() { ++ioDepth; }
void amiga_io_end() { --ioDepth; }
static uint8_t snapshot;     // rt_opl[B0] when interrupts were last disabled
void Disable() { snapshot = rt_opl[0xb0]; }
void Enable() { rt_opl[0xb0] ^= 0x20; }     // a tick as soon as they return
static int8_t pcm[16], fmPCM[16];
static unsigned field;
extern "C" {
uint8_t rt_opl[256], rt_opl_keyon[9], rt_sfx_id[3], rt_sfx_starts[3];
struct rt_sfx_write rt_sfx_capture[64];
uint16_t rt_sfx_first[RT_SFX_IDS], rt_sfx_writes[RT_SFX_IDS];
uint8_t rt_sfx_opl[256];
uint8_t fm_ntsc;
static unsigned renders;
uint32_t fm_renders;
static bool tfhLoaded = true;
static std::map<int, std::pair<const int8_t *, uint32_t>> registered;
int tfh_effect_wanted(uint8_t id) { return id == 7 || id == 8; }
uint8_t tfh_effect_volume(uint32_t level) { return (uint8_t)(level / 64); }
void tfh_effect(uint8_t id, const int8_t *pcm, uint32_t bytes, uint8_t volume, const int8_t *zero) {
    assert(volume == 9 && zero && !zero[0] && !zero[3]);
    registered[id] = {pcm, bytes};
}
// id 7: 5 samples (odd), id 8: 100; the 8-bit result in place, 16-bit buffer
uint32_t fm_effect(const uint8_t *opl, const fm_write *w, uint32_t n, int16_t *buf, uint32_t max, uint32_t *level) {
    assert(opl == rt_sfx_opl && max == TFH_EFFECT_BYTES && n == 2);
    ++renders;
    uint32_t len = w == (const fm_write *)rt_sfx_capture ? 5 : 100;
    for (uint32_t k = 0; k < max; ++k) buf[k] = -1;
    for (uint32_t k = 0; k < len; ++k) ((int8_t *)buf)[k] = (int8_t)(k + 1);
    *level = 600;
    return len;
}
void fm_init(int8_t *, uint32_t) {}
uint32_t tfh_chip_bytes(const uint8_t *, uint32_t) { return 212; }
int tfh_init(const uint8_t *, uint32_t, int8_t *) { return 0; }
static unsigned effectFields;
static bool retrigger;      // a new start over the running period-800 sample
uint16_t tfh_field(const uint8_t *opl, const uint8_t *, const uint8_t *, fm_voice *v) {
    assert(opl != rt_opl && opl[0xb0] == snapshot);
    if (!tfhLoaded) { ++effectFields; v[0] = {pcm, 16, 214, 9, 0, -1}; return 7; }
    if (retrigger) { v[0] = {pcm, 16, 800, 4, 1, -1}; return 7; }
    v[0] = {pcm + (field ? 4 : 0), (uint16_t)(field ? 12 : 16), 800,
            (uint8_t)(field > 1 ? 4 : 0), (uint8_t)!field, -1};
    ++field; return 7;
}
void fm_field(const uint8_t *opl, const uint8_t *keyon, uint16_t mask, fm_voice *v) {
    assert(opl != rt_opl && keyon != rt_opl_keyon && opl[0xb0] == snapshot);
    assert(mask == 7);
    for (int k = 0; k < 4; ++k) v[k] = {fmPCM, 16, 200, 16, 0, (int8_t)(3+k)};
}
}
int main() {
    assert(Audio::begin());
    uint8_t dummy = 0;
    assert(Audio::loadTFH(&dummy, 1));
    assert(allocations.size() == 2);
    Audio::takeOver();
    Audio::service();
    Audio::verticalBlank();
    // Attack starts at zero volume, but its PCM must start immediately.
    assert(amiga_audio_restarts == 1);
    assert(PAULA[0].lc == pcm && PAULA[0].len == 8 && PAULA[0].vol == 0);
    for (int k = 1; k < 4; ++k) assert(PAULA[k].lc == fmPCM && PAULA[k].vol == 16);
    Audio::service();
    Audio::verticalBlank();
    assert(amiga_audio_restarts == 1);
    assert(PAULA[0].lc == pcm+4 && PAULA[0].len == 6 && PAULA[0].vol == 0);
    Audio::service();
    Audio::verticalBlank();
    assert(PAULA[0].lc == pcm+4 && PAULA[0].vol == 4);
    // A restart keeps DMA off for two outgoing periods (Paula idles only at
    // the end of its second-byte state): 1600 colour clocks, 10 lines with
    // the margin; each mock VHPOSR read is a new line.
    retrigger = true;
    Audio::service();
    unsigned reads = beam.n;
    Audio::verticalBlank();
    assert(amiga_audio_restarts == 2 && PAULA[0].lc == pcm && PAULA[0].len == 8);
    assert(beam.n - reads >= 10);
    retrigger = false;
    Audio::handBack();
    Audio::end();
    assert(allocations.empty());
    // Effects without TFH: the wanted captured ids, each its own even Chip
    // block, the render buffer gone; the field runs the sample player.
    tfhLoaded = false;
    assert(Audio::begin());
    rt_sfx_writes[5] = rt_sfx_writes[7] = rt_sfx_writes[8] = 2;
    rt_sfx_first[7] = 0; rt_sfx_first[8] = 10;
    takenOver = true;
    Audio::loadEffects();
    takenOver = false;
    // Fast: the render buffer and the cache image, both released (allocations below)
    assert(ioDepth == 0 && fastBlocks == 2 && registered.size() == 2 && !registered.count(5));
    assert(registered[7].second == 6 && registered[8].second == 100);
    const int8_t *e7 = registered[7].first;
    assert(e7[0] == 1 && e7[4] == 5 && e7[5] == 0 && allocations.at((void *)e7) == 6);
    assert(allocations.size() == 3 && amiga_audio_effect_bytes == 106);
    // the cache written in one Write (WHDLoad: one save): header, two entries, the samples
    assert(renders == 2 && amiga_audio_effect_cached == 2 && opens == 0 && writes == 1 && disk.size() == 16 + 16 + 106);
    Audio::takeOver();
    Audio::service();
    Audio::verticalBlank();
    assert(effectFields == 1 && PAULA[0].per == 214);
    Audio::handBack();
    Audio::end();
    assert(allocations.empty());
    // The next start: the same samples from the cache, nothing rendered.
    auto load = [&]() {
        registered.clear();
        amiga_audio_effect_cached = 0;
        assert(Audio::begin());
        takenOver = true;
        Audio::loadEffects();
        takenOver = false;
        assert(ioDepth == 0 && opens == 0 && registered.size() == 2);
        assert(registered[7].second == 6 && registered[8].second == 100);
        const int8_t *e = registered[7].first;
        assert(e[0] == 1 && e[4] == 5 && e[5] == 0 && registered[8].first[99] == 100);
    };
    load();
    assert(renders == 2 && amiga_audio_effect_cached == 1 && amiga_audio_effect_bytes == 106);
    Audio::end();
    assert(allocations.empty());
    // Another capture (another key) renders again and rewrites the cache.
    rt_sfx_capture[10].value ^= 1;
    load();
    assert(renders == 4 && amiga_audio_effect_cached == 2 && writes == 2);
    Audio::end();
    // A cut file: refused whole (nothing kept), rendered and rewritten.
    disk.resize(disk.size() - 1);
    load();
    assert(renders == 6 && amiga_audio_effect_cached == 2 && disk.size() == 138);
    Audio::end();
    assert(allocations.empty());
}
'''


def run(plant=None):
    with tempfile.TemporaryDirectory(prefix='swotl-audio-') as tmp:
        root = Path(tmp)
        for name, text in HEADERS.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for name in ('Audio.h', 'fm_paula.h', 'tfh_paula.h'):
            (root / name).write_text((SRC / name).read_text())
        source = (SRC / 'Audio.cpp').read_text()
        if plant:
            needle, fault = PLANTS[plant]
            assert needle in source
            source = source.replace(needle, fault)
        (root / 'Audio.cpp').write_text(source)
        (root / 'test.cpp').write_text(HARNESS)
        exe = root / 'test'
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(root), str(root / 'test.cpp'), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True)
        assert bool(result.returncode) == bool(plant), result.stderr.decode()
        print(f'Audio: {plant} sabotage caught' if plant else
              'Audio: sample merge, silent attack restart, restart window, Chip release, OPL snapshot, prerendered effects and their cache: ok')


PLANTS = {'silent-attack': ('if (muted || !v.loop)', 'if (muted || !v.loop || !v.volume)'),
          'restart-period': ('(2u * outgoing + 226) / 227 + 2', 'outgoing / 227 + 4'),
          'restart-wait': ('    waitLines(lines < RESTART_LINES_MAX', '    if (0) waitLines(lines < RESTART_LINES_MAX'),
          'live-opl': ('fm_field(opl, keyon, mask, v)', 'fm_field(rt_opl, rt_opl_keyon, mask, v)'),
          'effects-only': ('tfhChip || effects ?', 'tfhChip ?'),
          'effect-pad': ('for (uint32_t k = n; k < bytes; ++k) pcm[k] = 0;', ''),
          'effect-free': ('if (effectChip[id]) FreeMem(effectChip[id], effectBytes[id]);', ''),
          'cache-key': ('head[2] == key &&', '(head[2] == key || true) &&'),
          'cache-short': ('ok = Read(f, effectChip[e.id], e.bytes) == (LONG)e.bytes;', 'Read(f, effectChip[e.id], e.bytes);'),
          'cache-split': ('if (Write(f, image, total) == (LONG)total)', 'if (Write(f, image, 16) == 16 && Write(f, image + 16, total - 16) == (LONG)(total - 16))'),
          'cache-off': ('    if (loadCache(key)) {', '    if (false && loadCache(key)) {')}

if __name__ == '__main__':
    if '--sabotage' in sys.argv:
        for name in PLANTS:
            run(name)
    else:
        run()
