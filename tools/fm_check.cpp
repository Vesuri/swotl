// FM re-hoster check (docs/sound-plan.md step 1): an OPL log (trace/opl.csv
// "ms,reg,value") through src/platform/amiga/fm_paula.c, its commanded Paula
// voices played (zero-order hold, 8-bit x volume) and compared per field with
// Nuked OPL rendering each commanded channel alone:
//   level: voice RMS vs the channel's within 3 dB at the field or a neighbour;
//   pitch: the channel periodic at the commanded loop period within 10 cents
//   (autocorrelation peak >= 0.9 over three periods: periodic patches
//   without vibrato or tremolo, registers and level steady).
// Writes the Paula mix as mono 16-bit WAV at the OPL rate (pairs with
// opl_render's). --sabotage pitch|level plants a fault the check must catch.
// Build: make build/tools/fm_check. Usage: fm_check opl.csv out.wav [--sabotage X]
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "nukedopl.h"
extern "C" {
#include "fm_paula.h"
}

static const unsigned RATE = 49716;
static const double LEVEL_DB = 3.0, FLOOR_DB = -30.0, PITCH_CENTS = 10.0;
static const double LEVEL_MIN = 0.95, PITCH_MIN = 0.99;
static const int WINDOW = 8192;  // pitch: the channel's last samples (8 fields)
static const int PITCH_EVERY = 5;  // fields between a voice's pitch checks
static const uint8_t op_off[9] = {0, 1, 2, 8, 9, 10, 16, 17, 18};

struct Row { double ms; unsigned reg, value; };
struct Voice {
    const int8_t *loop = nullptr, *next = nullptr;
    unsigned bytes = 0, next_bytes = 0, vol = 0;
    double pos = 0, step = 0;
};
struct FieldVoice { int ch; double paula, freq; };

static int channel_of(unsigned reg)
{
    if (reg >= 0xa0 && reg <= 0xc8 && (reg & 0x0f) < 9) return reg & 0x0f;
    unsigned grp = reg & 0xe0;
    if (grp == 0x20 || grp == 0x40 || grp == 0x60 || grp == 0x80 || grp == 0xe0) {
        unsigned off = reg & 0x1f;
        for (int c = 0; c < 9; c++)
            if (off == op_off[c] || off == op_off[c] + 3u) return c;
    }
    return -1;
}

static double db(double rms) { return rms > 0 ? 20 * log10(rms / 2888.0) : -200; }

static void put32(FILE *f, unsigned v) { fwrite(&v, 4, 1, f); }
static void put16(FILE *f, unsigned short v) { fwrite(&v, 2, 1, f); }

// the lag (parabolic) near `tc` where the normalised autocorrelation peaks,
// 0 unless that peak reaches 0.9 inside +-3%: is the signal periodic there?
static double period_near(const std::vector<double> &x, double tc)
{
    int n = (int)x.size(), lo = (int)(0.97 * tc), hi = (int)(1.03 * tc) + 1;
    std::vector<double> r(hi + 2);
    for (int l = lo - 1; l <= hi + 1; l++) {
        double s = 0, a = 0, b = 0;
        for (int i = 0; i + l < n; i++) { s += x[i] * x[i + l]; a += x[i] * x[i]; b += x[i + l] * x[i + l]; }
        r[l] = a > 0 && b > 0 ? s / sqrt(a * b) : 0;
    }
    int best = lo;
    for (int l = lo; l <= hi; l++)
        if (r[l] > r[best]) best = l;
    if (r[best] < 0.9 || r[best] < r[best - 1] || r[best] < r[best + 1]) return 0;
    double d = r[best - 1] - 2 * r[best] + r[best + 1];
    return best + (d < 0 ? 0.5 * (r[best - 1] - r[best + 1]) / d : 0);
}

int main(int argc, char **argv)
{
    const char *sabotage = argc == 5 && !strcmp(argv[3], "--sabotage") ? argv[4] : "";
    if (argc != 3 && !*sabotage) {
        fprintf(stderr, "usage: %s opl.csv out.wav [--sabotage pitch|level]\n", argv[0]);
        return 2;
    }
    FILE *in = fopen(argv[1], "r");
    if (!in) { perror(argv[1]); return 1; }
    std::vector<Row> rows;
    char line[128];
    if (!fgets(line, sizeof line, in)) return 1;
    while (fgets(line, sizeof line, in)) {
        Row r;
        if (sscanf(line, "%lf,0x%x,0x%x", &r.ms, &r.reg, &r.value) != 3 || !strchr(line, '\n')) break;
        rows.push_back(r);
    }
    if (rows.empty()) { fprintf(stderr, "%s: no rows\n", argv[1]); return 1; }

    static opl3_chip chip[9];
    for (auto &c : chip) OPL3_Reset(&c, RATE);
    static int8_t pool[FM_POOL_BYTES];
    fm_init(pool, sizeof pool);
    uint8_t shadow[256] = {}, keyon[9] = {};
    bool moved[9] = {};
    unsigned steady[9] = {};  // fields without a register change or a 1 dB level step
    Voice voice[FM_VOICES];
    static short hist[9][WINDOW];
    unsigned pitch_due[FM_VOICES] = {};
    std::vector<short> out;
    std::vector<std::array<double, 9>> nuked;      // per field, channel RMS dB
    std::vector<std::array<FieldVoice, FM_VOICES>> fields;
    std::vector<std::array<uint8_t, FM_VOICES>> vols;
    double sq[9] = {}, vsq[FM_VOICES] = {};
    std::array<FieldVoice, FM_VOICES> cur{};
    for (auto &f : cur) f.ch = -1;
    double first = rows[0].ms, field_len = RATE / FM_FIELD_HZ, next_field = 0;
    size_t at = 0;
    unsigned samples = 0, field_samples = 0, pitch_checked = 0, pitch_ok = 0;
    double worst_cents = 0;
    uint32_t most_renders = 0;
    size_t end = (size_t)((rows.back().ms - first) * RATE / 1000.0) + RATE;
    for (size_t n = 0; n < end; n++) {
        while (at < rows.size() && (rows[at].ms - first) * RATE / 1000.0 <= n) {
            const Row &r = rows[at++];
            int c = channel_of(r.reg);
            if (r.reg >= 0xb0 && r.reg <= 0xb8 && (r.value & 0x20) && !(shadow[r.reg] & 0x20)) keyon[r.reg - 0xb0]++;
            // any change but a key-on/off of the channel's registers
            if (c >= 0 && ((r.value ^ shadow[r.reg]) & (r.reg >= 0xb0 && r.reg <= 0xb8 ? 0x1f : 0xff))) moved[c] = true;
            shadow[r.reg] = (uint8_t)r.value;
            for (int k = 0; k < 9; k++)
                if (c < 0 || c == k) OPL3_WriteReg(&chip[k], (unsigned short)r.reg, (unsigned char)r.value);
        }
        if (n >= next_field) {
            if (field_samples) {
                std::array<double, 9> lv;
                for (int k = 0; k < 9; k++) lv[k] = db(sqrt(sq[k] / field_samples));
                nuked.push_back(lv);
                for (int i = 0; i < FM_VOICES; i++) cur[i].paula = db(sqrt(vsq[i] / field_samples));
                fields.push_back(cur);
                // pitch: three periods of a steady periodic channel
                for (int i = 0; i < FM_VOICES; i++) {
                    int c = cur[i].ch;
                    if (c < 0 || fields.size() < pitch_due[i] || lv[c] < FLOOR_DB ||
                        ((shadow[0xc0 + c] >> 1) & 7) >= 6 ||                            // noise
                        ((shadow[0x20 + op_off[c]] | shadow[0x23 + op_off[c]]) & 0xc0))  // AM/VIB
                        continue;
                    double tc = RATE / cur[i].freq;
                    int len = (int)(3 * tc) + 64;
                    if (len > WINDOW || steady[c] * field_len < len) continue;
                    std::vector<double> x(len);
                    double mean = 0;
                    for (int j = 0; j < len; j++) mean += x[j] = hist[c][(samples - len + j) % WINDOW];
                    for (auto &e : x) e -= mean / len;  // waveforms 1-3 carry DC
                    double t = period_near(x, tc);
                    double cents = t ? 1200 * log2(tc / t) : 1200;
                    pitch_due[i] = (unsigned)fields.size() + PITCH_EVERY;
                    pitch_checked++;
                    if (fabs(cents) <= PITCH_CENTS) pitch_ok++;
                    if (fabs(cents) > fabs(worst_cents)) worst_cents = cents;
                }
                for (int k = 0; k < 9; k++) {
                    bool step = nuked.size() >= 2 && fabs(lv[k] - nuked[nuked.size() - 2][k]) > 1;
                    steady[k] = moved[k] || step ? 0 : steady[k] + 1;
                    moved[k] = false;
                }
            }
            next_field += field_len;
            field_samples = 0;
            for (auto &s : sq) s = 0;
            for (auto &s : vsq) s = 0;
            struct fm_voice v[FM_VOICES];
            uint32_t before = fm_renders;
            fm_field(shadow, keyon, 0, v);
            if (fm_renders - before > most_renders) most_renders = fm_renders - before;
            std::array<uint8_t, FM_VOICES> vol;
            for (int i = 0; i < FM_VOICES; i++) vol[i] = v[i].volume;
            vols.push_back(vol);
            for (int i = 0; i < FM_VOICES; i++) {
                Voice &p = voice[i];
                double period = v[i].period * (!strcmp(sabotage, "pitch") ? 1.06 : 1.0);
                unsigned volume = v[i].volume;
                if (!strcmp(sabotage, "level")) volume = vols.size() > 3 ? vols[vols.size() - 4][i] : 0;
                cur[i].ch = v[i].loop ? v[i].channel : -1;
                if (!v[i].loop) { p.vol = 0; continue; }
                cur[i].freq = FM_PAULA_CLOCK / (period * v[i].bytes);
                p.step = FM_PAULA_CLOCK / period / RATE;
                p.vol = volume;
                if (v[i].restart || !p.loop) {
                    p.loop = v[i].loop; p.bytes = v[i].bytes; p.pos = 0; p.next = nullptr;
                } else if (v[i].loop != p.loop || v[i].bytes != p.bytes) {
                    p.next = v[i].loop; p.next_bytes = v[i].bytes;
                }
            }
        }
        int mix = 0;
        for (int k = 0; k < 9; k++) {
            short s[2];
            OPL3_Generate(&chip[k], s);
            sq[k] += (double)s[0] * s[0];
            hist[k][samples % WINDOW] = s[0];
        }
        for (int i = 0; i < FM_VOICES; i++) {
            Voice &p = voice[i];
            if (!p.loop) continue;
            int s = p.loop[(unsigned)p.pos] * (int)p.vol;
            mix += s;
            vsq[i] += (s / 2.0) * (s / 2.0);  // Nuked units: loop = out >> 5, volume / 64
            p.pos += p.step;
            if (p.pos >= p.bytes) {
                p.pos -= p.bytes * floor(p.pos / p.bytes);
                if (p.next) { p.loop = p.next; p.bytes = p.next_bytes; p.next = nullptr; }
            }
        }
        out.push_back((short)(mix > 32767 ? 32767 : mix < -32768 ? -32768 : mix));
        samples++;
        field_samples++;
    }

    unsigned level_checked = 0, level_ok = 0, voiced = 0;
    for (size_t k = 0; k < fields.size(); k++) {
        for (int i = 0; i < FM_VOICES; i++) {
            const FieldVoice &f = fields[k][i];
            if (f.ch < 0) continue;
            voiced++;
            if (f.paula < FLOOR_DB && nuked[k][f.ch] < FLOOR_DB) continue;
            level_checked++;
            double best = 1e9;
            for (int d = -1; d <= 1; d++) {
                if (k + d >= fields.size() || (d < 0 && k == 0)) continue;
                double e = fabs(f.paula - nuked[k + d][f.ch]);
                if (e < best) best = e;
            }
            if (best <= LEVEL_DB) level_ok++;
        }
    }

    FILE *f = fopen(argv[2], "wb");
    if (!f) { perror(argv[2]); return 1; }
    unsigned bytes = (unsigned)out.size() * 2;
    fwrite("RIFF", 1, 4, f); put32(f, 36 + bytes); fwrite("WAVEfmt ", 1, 8, f);
    put32(f, 16); put16(f, 1); put16(f, 1); put32(f, RATE); put32(f, RATE * 2);
    put16(f, 2); put16(f, 16); fwrite("data", 1, 4, f); put32(f, bytes);
    fwrite(out.data(), 2, out.size(), f);
    fclose(f);

    double lf = level_checked ? (double)level_ok / level_checked : 0;
    double pf = pitch_checked ? (double)pitch_ok / pitch_checked : 0;
    bool ok = lf >= LEVEL_MIN && pf >= PITCH_MIN;
    printf("%s: %.1f s, %zu fields, %u voiced; level %u/%u (%.1f%%); pitch %u/%u (%.1f%%, worst %+.1f cents); "
           "renders %u (most %u in a field) %s\n",
           argv[2], samples / (double)RATE, fields.size(), voiced, level_ok, level_checked, 100 * lf,
           pitch_ok, pitch_checked, 100 * pf, worst_cents, (unsigned)fm_renders, (unsigned)most_renders,
           ok ? "ok" : "FAIL");
    return ok ? 0 : 1;
}
