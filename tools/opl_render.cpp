// OPL log (tools/pc_run.py --opl: trace/opl.csv "ms,reg,value") -> mono 16-bit
// WAV at the OPL's native 49716 Hz through Nuked OPL (the DOSBox-X tree's copy).
// Build: make build/tools/opl_render. Usage: opl_render opl.csv out.wav
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "nukedopl.h"

static const unsigned RATE = 49716;

static void put32(FILE *f, unsigned v) { fwrite(&v, 4, 1, f); }
static void put16(FILE *f, unsigned short v) { fwrite(&v, 2, 1, f); }

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: %s opl.csv out.wav\n", argv[0]);
        return 2;
    }
    FILE *in = fopen(argv[1], "r");
    if (!in) { perror(argv[1]); return 1; }
    static opl3_chip chip;
    OPL3_Reset(&chip, RATE);
    std::vector<short> out;
    char line[128];
    double first = -1;
    if (!fgets(line, sizeof line, in)) return 1;  // header
    while (fgets(line, sizeof line, in)) {
        double ms;
        unsigned reg, value;
        // a run stopped by its time limit may end mid-line
        if (sscanf(line, "%lf,0x%x,0x%x", &ms, &reg, &value) != 3 || !strchr(line, '\n'))
            break;
        if (first < 0) first = ms;
        size_t at = (size_t)((ms - first) * RATE / 1000.0);
        while (out.size() < at) {
            short s[2];
            OPL3_Generate(&chip, s);
            out.push_back(s[0]);
        }
        OPL3_WriteReg(&chip, (unsigned short)reg, (unsigned char)value);
    }
    for (unsigned k = 0; k < RATE; k++) {  // one second of release tail
        short s[2];
        OPL3_Generate(&chip, s);
        out.push_back(s[0]);
    }
    FILE *f = fopen(argv[2], "wb");
    if (!f) { perror(argv[2]); return 1; }
    unsigned bytes = (unsigned)out.size() * 2;
    fwrite("RIFF", 1, 4, f); put32(f, 36 + bytes); fwrite("WAVEfmt ", 1, 8, f);
    put32(f, 16); put16(f, 1); put16(f, 1); put32(f, RATE); put32(f, RATE * 2);
    put16(f, 2); put16(f, 16); fwrite("data", 1, 4, f); put32(f, bytes);
    fwrite(out.data(), 2, out.size(), f);
    fclose(f);
    printf("%s: %.1f s\n", argv[2], out.size() / (double)RATE);
    return 0;
}
