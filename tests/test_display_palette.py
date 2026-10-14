#!/usr/bin/env python3
"""Production display methods vs independent DAC colours across queue histories.

Compile the actual methods with hardware stubs; the existing display audit and
DOSBox replays separately cover real copper encoding and shown pixels.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/platform/amiga/Swotl.cpp'


def body(source, start):
    at = source.index(start)
    opening = source.index('{', at)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[at:end]


PRELUDE = r'''
#include "DisplayQueue.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <random>
struct Bitmap {};
struct BitMap {};
struct Palette24Bit {
    uint32_t* source;
    Palette24Bit(uint32_t* rgb, uint32_t*, unsigned) : source(rgb) {}
};
struct CopperList {
    uint32_t rgb[256] = {};
    uint32_t setPalette24Bit(uint32_t at, const Palette24Bit& p, int, int, int, bool) {
        std::memcpy(rgb, p.source, sizeof rgb);
        return at + 528;
    }
};
static void Disable() {}
static void Enable() {}
static void amiga_display_queued(uint32_t) {}
static void c2p(const void*, int, int, int, int, BitMap*) { assert(false); }
static const unsigned SCREEN_HEIGHT = 200, SCREEN_WIDTH = 320;
'''
DECL = r'''
struct Swotl {
    DisplayState* display;
    uint32_t buildPalette(uint16_t);
    uint16_t beginDisplayUpdate();
    void setPalette(const uint8_t*);
    void finishDisplayUpdate(uint16_t);
};
'''
HARNESS = r'''
int main() {
    DisplayState d{};
    CopperList lists[2];
    d.list[0] = &lists[0]; d.list[1] = &lists[1];
    Swotl app{&d};
    app.buildPalette(0); app.buildPalette(1); // production constructor order
    uint8_t want[768] = {};
    std::mt19937 rng(17);
    unsigned flips = 0, replaced = 0, changed = 0, same = 0;
    auto check = [&](unsigned b) {
        assert(d.colours[b][0] == 256u << 16);
        assert(d.colours[b][769] == 0);
        for (unsigned c = 0; c < 256; ++c) {
            uint32_t rgb = 0;
            for (unsigned k = 0; k < 3; ++k) {
                unsigned v = want[c*3+k] & 63;
                // Independent six-bit-to-eight-bit replication, not the
                // production wide multiply/shift conversion.
                rgb = rgb * 256 + ((v << 2) | (v >> 4));
            }
            assert(lists[b].rgb[c] == rgb);
            for (unsigned k = 0; k < 3; ++k)
                assert((d.colours[b][1+c*3+k] >> 24) == ((rgb >> (16-k*8)) & 255));
        }
    };
    check(0); check(1);
    for (unsigned step = 0; step < 6000; ++step) {
        if (d.queue.pending >= 0 && (rng() & 1)) {
            check(d.queue.flip()); ++flips;
        }
        if (d.queue.pending >= 0) ++replaced;
        unsigned shown = d.queue.shown;
        uint32_t old[256]; std::memcpy(old, lists[shown].rgb, sizeof old);
        if (step % 7 < 3) {
            // Consecutive palette-only updates, every component and its
            // ignored upper bits, with/without a VBI between publications.
            for (auto& v : want) v = rng();
            app.setPalette(want); ++changed;
        } else {
            app.finishDisplayUpdate(app.beginDisplayUpdate()); ++same;
        }
        assert(d.queue.shown == shown);
        assert(!std::memcmp(old, lists[shown].rgb, sizeof old));
        assert(d.queue.pending == (shown ^ 1));
        check(d.queue.pending);
    }
    check(d.queue.flip());
    // Both physical buffers must inherit the latest palette, even when only
    // subsequent image publications cause the second to become visible.
    for (unsigned n = 0; n < 4; ++n) {
        app.finishDisplayUpdate(app.beginDisplayUpdate());
        check(d.queue.flip());
    }
    assert(flips > 100 && replaced > 100 && changed > 100 && same > 100);
}
'''


def run(source, good):
    state = body(source, 'struct DisplayState {') + ';'
    names = ['uint32_t Swotl::buildPalette', 'uint16_t Swotl::beginDisplayUpdate',
             'void Swotl::setPalette', 'void Swotl::finishDisplayUpdate']
    code = PRELUDE + state + DECL + '\n'.join(body(source, n) for n in names) + HARNESS
    with tempfile.TemporaryDirectory(prefix='display-palette-', dir=ROOT / 'tmp') as name:
        p = Path(name)
        (p / 'test.cpp').write_text(code)
        subprocess.run(['c++', '-std=c++17', '-O2', '-I', str(ROOT / 'src/platform/amiga'),
                        str(p / 'test.cpp'), '-o', str(p / 'test')], check=True)
        r = subprocess.run([str(p / 'test')], capture_output=True)
        assert (r.returncode == 0) == good, r.stderr.decode()
        print('display palette: ok' if good else 'display palette: planted fault caught')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    source = SOURCE.read_text()
    run(source, True)
    if args.sabotage:
        old = 'uint32_t* table = display->colours[back];'
        assert old in source
        run(source.replace(old, 'static unsigned calls = 0; if (++calls > 2) return 0;\n    ' + old), False)

        for old in ('display->paletteValid[0] = false;',
                    'display->paletteValid[1] = false;'):
            assert old in source
            run(source.replace(old, '', 1), False)
