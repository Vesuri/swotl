// TFH mode render (docs/sound-plan.md): a host run's sound log
// (tests/host_run.py --sound-log: "tick,o,reg,value" AdLib writes and
// "tick,s,slot,id" HLE sfx_start reports, ticks of SPAZ's 236.7 Hz timer)
// played as the Amiga does: per PAL field tfh_paula.c owns the slots with a
// TFH sample, fm_paula.c the rest; Paula's four voices, 0 and 3 left, 1 and 2
// right, to a stereo 16-bit WAV for listening.
//
//     tfh_render sound.csv sfx.rsc out.wav

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

extern "C" {
#include "fm_paula.h"
#include "tfh_paula.h"
}

static const unsigned RATE = 44100;
static const double TICK_HZ = 1193182.0 / 5041;

struct Event { double tick; char kind; unsigned a, b; };
struct Voice {
    const int8_t *loop = nullptr, *next = nullptr;
    unsigned bytes = 0, next_bytes = 0, vol = 0;
    double pos = 0, step = 0;
};

static void put32(FILE *f, unsigned v) { fwrite(&v, 4, 1, f); }
static void put16(FILE *f, unsigned short v) { fwrite(&v, 2, 1, f); }

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s sound.csv sfx.rsc out.wav\n", argv[0]);
        return 2;
    }
    FILE *in = fopen(argv[1], "r");
    if (!in) { perror(argv[1]); return 1; }
    std::vector<Event> ev;
    char line[128];
    while (fgets(line, sizeof line, in)) {
        Event e;
        if (sscanf(line, "%lf,%c,%u,%u", &e.tick, &e.kind, &e.a, &e.b) == 4) ev.push_back(e);
    }
    fclose(in);
    FILE *r = fopen(argv[2], "rb");
    if (!r) { perror(argv[2]); return 1; }
    std::vector<uint8_t> rsc;
    for (int c; (c = fgetc(r)) != EOF;) rsc.push_back((uint8_t)c);
    fclose(r);
    uint32_t chip_bytes = tfh_chip_bytes(rsc.data(), (uint32_t)rsc.size());
    if (!chip_bytes) { fprintf(stderr, "%s: not TFH's sfx.rsc\n", argv[2]); return 1; }
    std::vector<int8_t> chip(chip_bytes);
    tfh_init(rsc.data(), (uint32_t)rsc.size(), chip.data());
    static int8_t pool[64 * FM_POOL_PAGE];
    fm_init(pool, sizeof pool);
    if (ev.empty()) { fprintf(stderr, "%s: no events\n", argv[1]); return 1; }

    uint8_t opl[256] = {}, keyon[9] = {}, ids[TFH_SLOTS], starts[TFH_SLOTS] = {};
    memset(ids, 0xff, sizeof ids);
    Voice voice[FM_VOICES];
    std::vector<short> out;
    double first = ev[0].tick, field_len = RATE / FM_FIELD_HZ, next_field = 0;
    size_t at = 0, end = (size_t)((ev.back().tick - first) / TICK_HZ * RATE) + RATE;
    unsigned tfh_fields = 0, fields = 0;
    for (size_t n = 0; n < end; n++) {
        if (n >= next_field) {
            while (at < ev.size() && (ev[at].tick - first) / TICK_HZ * RATE <= n) {
                const Event &e = ev[at++];
                if (e.kind == 'o') {
                    if (e.a >= 0xb0 && e.a <= 0xb8 && (e.b & 0x20) && !(opl[e.a] & 0x20)) keyon[e.a - 0xb0]++;
                    opl[e.a & 0xff] = (uint8_t)e.b;
                } else if (e.kind == 's' && e.a < TFH_SLOTS) {
                    ids[e.a] = (uint8_t)e.b;
                    starts[e.a]++;
                } else if (e.kind == 'm') {     // a song start: no slot holds an effect
                    memset(ids, 0xff, sizeof ids);
                }
            }
            next_field += field_len;
            struct fm_voice v[FM_VOICES], t[TFH_SLOTS];
            uint16_t mask = tfh_field(opl, ids, starts, t);
            fm_field(opl, keyon, mask, v);
            for (int k = 0; k < TFH_SLOTS; k++)
                if (mask >> (3 * k) & 7) v[k] = t[k];
            fields++;
            if (mask) tfh_fields++;
            for (int i = 0; i < FM_VOICES; i++) {
                Voice &p = voice[i];
                if (!v[i].loop) { p.vol = 0; continue; }
                p.step = FM_PAULA_CLOCK / (double)v[i].period / RATE;
                p.vol = v[i].volume;
                if (v[i].restart || !p.loop) {
                    p.loop = v[i].loop; p.bytes = v[i].bytes; p.pos = 0; p.next = nullptr;
                } else if (v[i].loop != p.loop || v[i].bytes != p.bytes) {
                    p.next = v[i].loop; p.next_bytes = v[i].bytes;
                }
            }
        }
        int mix[2] = {0, 0};
        for (int i = 0; i < FM_VOICES; i++) {
            Voice &p = voice[i];
            if (!p.loop) continue;
            mix[i == 1 || i == 2] += p.loop[(unsigned)p.pos] * (int)p.vol;
            p.pos += p.step;
            if (p.pos >= p.bytes) {             // the latched segment at the loop's end
                p.pos -= p.bytes * floor(p.pos / p.bytes);
                if (p.next) { p.loop = p.next; p.bytes = p.next_bytes; p.next = nullptr; p.pos = 0; }
            }
        }
        for (int c = 0; c < 2; c++) out.push_back((short)(mix[c] * 2));
    }
    FILE *f = fopen(argv[3], "wb");
    if (!f) { perror(argv[3]); return 1; }
    unsigned bytes = (unsigned)out.size() * 2;
    fwrite("RIFF", 1, 4, f); put32(f, 36 + bytes); fwrite("WAVEfmt ", 1, 8, f);
    put32(f, 16); put16(f, 1); put16(f, 2); put32(f, RATE); put32(f, RATE * 4); put16(f, 4); put16(f, 16);
    fwrite("data", 1, 4, f); put32(f, bytes);
    fwrite(out.data(), 2, out.size(), f);
    fclose(f);
    printf("%s: %.1f s, %u fields, %u with a TFH sample\n", argv[3], out.size() / 2.0 / RATE, fields,
           tfh_fields);
    return 0;
}
