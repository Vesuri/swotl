// Prerendered effects (docs/sound-plan.md R2): fm_effect (fm_paula.c) against
// Nuked OPL on each captured effect (host_run.py --sfx-capture: tick,id,reg,value
// rows, the start registers in "# opl"). Nuked runs the same writes from the
// same registers, two chip samples a write (AdLib bus timing: a key-off and
// key-on in one tick retrigger), sampled every third chip sample: the
// waveform fm_effect synthesises at FM_EFFECT_RATE, its aliasing included.
// Per id, 20 ms windows at most 30 dB below the loudest, AC power (a frozen
// phase's DC is inaudible): within 3 dB (a window either side allowed) on
// >= 90%, none beyond 6 dB. Pitch where the reference is tonal (a peak >= 0.9
// after the autocorrelation falls below 0, two periods in a 40 ms window):
// within 10 cents on >= 99%, refined at the multiple nearest lag 250.
// Feedback noise and sub-audio rumble have no pitch. Writes OUT/ID-nuked.wav
// and OUT/ID-fx.wav. Build: make build/tools/fm_effect_check.
// Usage: fm_effect_check capture.csv OUTDIR [--sabotage level|pitch]
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>
extern "C" {
#include "fm_paula.h"
}
#include "nukedopl.h"

static const int WIN = FM_EFFECT_RATE / 50;

static void wav(const std::string &path, const std::vector<double> &x, double scale)
{
    FILE *f = fopen(path.c_str(), "wb");
    if (!f) return;
    auto p32 = [&](uint32_t v) { fwrite(&v, 4, 1, f); };
    auto p16 = [&](uint16_t v) { fwrite(&v, 2, 1, f); };
    fwrite("RIFF", 1, 4, f); p32(36 + 2 * (uint32_t)x.size()); fwrite("WAVEfmt ", 1, 8, f);
    p32(16); p16(1); p16(1); p32(FM_EFFECT_RATE); p32(FM_EFFECT_RATE * 2); p16(2); p16(16);
    fwrite("data", 1, 4, f); p32(2 * (uint32_t)x.size());
    for (double v : x) { double s = v * scale; p16((uint16_t)(int16_t)(s > 32767 ? 32767 : s < -32768 ? -32768 : s)); }
    fclose(f);
}

static double rms_db(const std::vector<double> &x, size_t at)
{
    double s = 0, m = 0;            // AC power: a frozen phase's DC is inaudible
    for (int k = 0; k < WIN; k++) { double v = at + k < x.size() ? x[at + k] : 0; s += v * v; m += v; }
    m /= WIN;
    return 10 * log10(s / WIN - m * m + 1e-9);
}

// normalised autocorrelation of x[at..at+LEN) at lag l, means removed (DC)
static const int LEN = 2 * WIN, MAXLAG = 2 * WIN;
static double ac(const std::vector<double> &x, size_t at, int l)
{
    double s = 0, e0 = 0, e1 = 0, m0 = 0, m1 = 0;
    for (int k = 0; k < LEN; k++) { m0 += x[at + k]; m1 += x[at + k + l]; }
    m0 /= LEN;
    m1 /= LEN;
    for (int k = 0; k < LEN; k++) {
        double u = x[at + k] - m0, v = x[at + k + l] - m1;
        s += u * v; e0 += u * u; e1 += v * v;
    }
    return s / sqrt(e0 * e1 + 1e-9);
}

// the highest autocorrelation peak in lags [lo, hi], parabolic; r in *r
static double peak(const std::vector<double> &x, size_t at, int lo, int hi, double *r)
{
    int best = 0;
    *r = -1;
    if (lo < 2) lo = 2;
    for (int l = lo; l <= hi && l < MAXLAG; l++) {
        double v = ac(x, at, l);
        if (v > *r && v >= ac(x, at, l - 1) && v >= ac(x, at, l + 1)) { *r = v; best = l; }
    }
    if (!best) return 0;
    double a = ac(x, at, best - 1), b = *r, c = ac(x, at, best + 1), d = a - 2 * b + c;
    return best + (d ? 0.5 * (a - c) / d : 0);
}

// The reference's period at `at` (its first autocorrelation peak >= 0.9
// after a fall below 0),
// then both refined at the multiple of it nearest lag 250: *ref and *ours in
// samples; 0 if the reference is not tonal, *ours 0 if ours has no peak
// >= 0.8 there.
static void periods(const std::vector<double> &a, const std::vector<double> &b, size_t at, double *ref, double *ours)
{
    *ref = *ours = 0;
    if (at + LEN + MAXLAG + 1 > a.size()) return;
    double e = 0;
    for (int k = 0; k < LEN; k++) e += a[at + k] * a[at + k];
    if (e < 1e-3) return;
    double r, p = 0;
    bool fell = false;              // a period, not sub-audio drift: the correlation falls first
    for (int l = 9; l < MAXLAG - 1 && !p; l++) {
        double v = ac(a, at, l);
        fell |= v < 0;
        if (fell && v >= 0.9 && v >= ac(a, at, l - 1) && v >= ac(a, at, l + 1)) p = l;
    }
    if (!p) return;
    int m = p < 250 ? (int)(250 / p) : 1;
    double pr = peak(a, at, (int)(m * p) - 2, (int)(m * p) + 2, &r) / m;
    if (r < 0.9 || pr > LEN / 2) return;   // two periods in the window at least
    *ref = pr;
    int w = 2 + (int)(m * pr * 0.03);
    double po = peak(b, at, (int)(m * pr) - w, (int)(m * pr) + w, &r) / m;
    *ours = r >= 0.8 ? po : 0;
}

int main(int argc, char **argv)
{
    if (argc != 3 && !(argc == 5 && !strcmp(argv[3], "--sabotage"))) {
        fprintf(stderr, "usage: %s capture.csv OUTDIR [--sabotage level|pitch]\n", argv[0]);
        return 1;
    }
    const char *sabotage = argc == 5 ? argv[4] : "";
    FILE *in = fopen(argv[1], "r");
    if (!in) { perror(argv[1]); return 1; }
    char line[1024];
    uint8_t opl0[256] = {};
    std::map<int, std::vector<fm_write>> fx;
    while (fgets(line, sizeof line, in)) {
        if (!strncmp(line, "# opl ", 6)) {
            for (int r = 0; r < 256; r++) { unsigned v; sscanf(line + 6 + 2 * r, "%2x", &v); opl0[r] = (uint8_t)v; }
            continue;
        }
        unsigned t, id, reg, v;
        if (sscanf(line, "%u,%u,0x%x,0x%x", &t, &id, &reg, &v) == 4) fx[id].push_back({(uint16_t)t, (uint8_t)reg, (uint8_t)v});
    }
    fclose(in);
    static int8_t pool[FM_POOL_BYTES];
    fm_init(pool, sizeof pool);
    int bad = 0;
    unsigned long total = 0;
    for (auto &[id, w] : fx) {
        std::vector<int8_t> out(FM_EFFECT_RATE * 10);
        uint32_t level = 0;
        uint32_t n = fm_effect(opl0, w.data(), (uint32_t)w.size(), out.data(), (uint32_t)out.size(), &level);
        total += n;
        double peak = level;
        std::vector<double> ours(n), ref;
        for (uint32_t k = 0; k < n; k++) ours[k] = out[k] * peak / 127;
        if (!strcmp(sabotage, "level")) for (uint32_t k = n / 2; k < n; k++) ours[k] *= 0.5;
        opl3_chip chip;
        OPL3_Reset(&chip, 49716);
        for (int r = 0x01; r < 0x100; r++) OPL3_WriteReg(&chip, (uint16_t)r, opl0[r]);
        size_t at = 0;
        double chip_pos = 0;
        long chip_n = 0;
        int a3 = 0;
        uint32_t last = w.back().tick;
        auto generate = [&]() {
            int16_t s[2];
            OPL3_Generate(&chip, s);
            chip_n++;
            if (++a3 == 3) { ref.push_back(s[0]); a3 = 0; }
        };
        for (uint32_t t = 0; ref.size() < n && t <= last + 2000; t++) {
            chip_pos += 5041.0 / 24;
            for (; at < w.size() && w[at].tick == t; at++) {   // AdLib bus timing: ~2 chip samples a write
                OPL3_WriteReg(&chip, w[at].reg, w[at].value);
                generate();
                generate();
            }
            while (chip_n < (long)chip_pos) generate();
        }
        ref.resize(n);
        if (!strcmp(sabotage, "pitch")) {   // ours a semitone up: resampled
            std::vector<double> up(n);
            for (uint32_t k = 0; k < n; k++) { double p = k * 1.059463; size_t q = (size_t)p; up[k] = q + 1 < n ? ours[q] + (p - q) * (ours[q + 1] - ours[q]) : 0; }
            ours = up;
        }
        wav(std::string(argv[2]) + "/" + std::to_string(id) + "-nuked.wav", ref, 4);
        wav(std::string(argv[2]) + "/" + std::to_string(id) + "-fx.wav", ours, 4);
        size_t windows = n / WIN;
        std::vector<double> dr(windows), dq(windows);
        double top = -1e9;
        for (size_t k = 0; k < windows; k++) { dr[k] = rms_db(ref, k * WIN); dq[k] = rms_db(ours, k * WIN); top = std::max(top, dr[k]); }
        int checked = 0, ok = 0, pc = 0, pok = 0;
        double worst = 0, far = 0;
        std::string misses;
        for (size_t k = 0; k < windows; k++) {
            if (dr[k] < top - 30) continue;
            checked++;
            double best = 1e9;
            for (long j = (long)k - 1; j <= (long)k + 1; j++)
                if (j >= 0 && j < (long)windows) best = std::min(best, fabs(dq[j] - dr[k]));
            ok += best <= 3;
            far = std::max(far, best);
            if (best > 3) misses += " L" + std::to_string(k) + ":" + std::to_string((int)dr[k]) + "/" + std::to_string((int)dq[k]);
            double p1, p2;
            periods(ref, ours, k * WIN, &p1, &p2);
            if (p1) {
                double cents = p2 ? 1200 * log2(p1 / p2) : 1200;
                pc++;
                pok += fabs(cents) <= 10;
                if (fabs(cents) > 10) misses += " P" + std::to_string(k) + ":" + std::to_string(p1).substr(0, 5) + "/" + std::to_string(p2).substr(0, 5);
                if (fabs(cents) > fabs(worst)) worst = cents;
            }
        }
        double lf = checked ? 100.0 * ok / checked : 100, pf = pc ? 100.0 * pok / pc : 100;
        bool pass = lf >= 90 && far <= 6 && pf >= 99;
        bad += !pass;
        printf("id %2d: %5u samples, peak %5.1f dB FS; level %d/%d (%.1f%%, worst %.1f dB); pitch %d/%d (%.1f%%, worst %.1f cents) %s\n",
               id, n, 20 * log10(level / (double)FM_EFFECT_FULL), ok, checked, lf, far, pok, pc, pf, worst, pass ? "ok" : "FAIL");
        if (!pass) printf("  misses (window:reference/ours, dB or period):%s\n", misses.c_str());
    }
    printf("prerendered: %zu effects, %lu samples (%.1f s, %lu bytes) %s\n", fx.size(), total,
           total / (double)FM_EFFECT_RATE, total, bad ? "FAIL" : "ok");
    return bad ? 1 : 0;
}
