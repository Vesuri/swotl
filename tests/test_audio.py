#!/usr/bin/env python3
"""Production Paula backend: sample ownership, zero-volume attack, Chip lifetime.
Mock MMIO and command producers; the sample/FM cores have independent gates.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'
HEADERS = {
    'Util.h': '#include <stdint.h>\n',
    'proto/exec.h': '#include <stdint.h>\nvoid *AllocMem(uint32_t, uint32_t);\nvoid FreeMem(void *, uint32_t);\nvoid Disable(); void Enable();\n',
    'exec/memory.h': '#define MEMF_CHIP 2\n#define MEMF_CLEAR 65536\n',
    'hardware/dmabits.h': '#define DMAF_AUD0 1\n#define DMAF_AUD1 2\n#define DMAF_AUD2 4\n#define DMAF_AUD3 8\n#define DMAF_SETCLR 32768\n',
    'runtime.h': '#include <stdint.h>\nextern uint8_t rt_opl[256], rt_opl_keyon[9], rt_sfx_id[3], rt_sfx_starts[3];\n',
    'amiga_platform.h': '',
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
#include <map>
#include "Audio.cpp"
alignas(8) unsigned char registers[128];
volatile uint16_t dma;
Beam beam;
static std::map<void *, uint32_t> allocations;
void *AllocMem(uint32_t n, uint32_t flags) {
    assert(flags & MEMF_CHIP);
    void *p = calloc(1, n); allocations[p] = n; return p;
}
void FreeMem(void *p, uint32_t n) {
    assert(allocations.at(p) == n); allocations.erase(p); free(p);
}
void Disable() {} void Enable() {}
static int8_t pcm[16], fmPCM[16];
static unsigned field;
extern "C" {
uint8_t rt_opl[256], rt_opl_keyon[9], rt_sfx_id[3], rt_sfx_starts[3];
uint32_t fm_renders;
void fm_init(int8_t *, uint32_t) {}
uint32_t tfh_chip_bytes(const uint8_t *, uint32_t) { return 212; }
int tfh_init(const uint8_t *, uint32_t, int8_t *) { return 0; }
uint16_t tfh_field(const uint8_t *, const uint8_t *, const uint8_t *, fm_voice *v) {
    v[0] = {pcm + (field ? 4 : 0), (uint16_t)(field ? 12 : 16), 800,
            (uint8_t)(field > 1 ? 4 : 0), (uint8_t)!field, -1};
    ++field; return 7;
}
void fm_field(const uint8_t *, const uint8_t *, uint16_t mask, fm_voice *v) {
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
    Audio::handBack();
    Audio::end();
    assert(allocations.empty());
}
'''


def run(plant=False):
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
            needle = 'if (muted || !v.loop)'
            assert needle in source
            source = source.replace(needle, 'if (muted || !v.loop || !v.volume)')
        (root / 'Audio.cpp').write_text(source)
        (root / 'test.cpp').write_text(HARNESS)
        exe = root / 'test'
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(root), str(root / 'test.cpp'), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True)
        assert bool(result.returncode) == plant, result.stderr.decode()
        print('Audio: silent-attack sabotage caught' if plant else 'Audio: sample merge, silent attack restart and Chip release: ok')


if __name__ == '__main__':
    run('--sabotage' in sys.argv)
