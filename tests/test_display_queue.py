#!/usr/bin/env python3
"""Dirty inheritance and queue races against an independent complete image.

Execute the production queue with a VBI before/during/after updates, including
repeated replacement of a pending image and palette-only publications.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "DisplayQueue.h"
#include <cassert>
#include <cstring>
#include <random>
static unsigned char want[200][320], planes[2][200][320];
int main() {
    DisplayQueue q;
    std::mt19937 rng(14);
    unsigned flips = 0, replacements = 0;
    for (unsigned step = 0; step < 4000; ++step) {
        if (q.pending >= 0 && (rng() & 1)) {
            int b = q.flip();
            assert(!std::memcmp(planes[b], want, sizeof want));
            ++flips;
        }
        if (q.pending >= 0) ++replacements;
        unsigned b = q.begin();
        assert(b != q.shown);
        assert(q.flip() == -1); // ISR while conversion is under way.
        // Includes empty updates (e.g. palette changes), non-adjacent row
        // bands, alternating sparse columns, and changes on the last row.
        unsigned n = step % 7;
        for (unsigned k = 0; k < n; ++k) {
            unsigned x0 = (rng() % 10) * 32, x1 = x0 + 32;
            unsigned y0 = rng() % 200, y1 = y0 + 1 + rng() % (200 - y0);
            q.mark(x0, y0, x1, y1);
            for (unsigned y = y0; y < y1; ++y)
                for (unsigned x = x0; x < x1; ++x) want[y][x] = rng();
        }
        for (unsigned y = 0; y < 200; ++y) {
            const auto r = q.rows[b][y];
            if (r.hi) std::memcpy(&planes[b][y][r.lo], &want[y][r.lo], r.hi-r.lo);
            q.clear(b, y);
            assert(q.flip() == -1);
        }
        q.queue(b);
    }
    assert(!std::memcmp(planes[q.flip()], want, sizeof want));
    assert(flips > 100 && replacements > 100);
}
'''


def run(header, good):
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='display-queue-', dir=ROOT / 'tmp') as name:
        p = Path(name)
        (p / 'DisplayQueue.h').write_text(header)
        (p / 'test.cpp').write_text(HARNESS)
        subprocess.run(['c++', '-std=c++17', '-O2', str(p / 'test.cpp'), '-o', str(p / 'test')], check=True)
        r = subprocess.run([str(p / 'test')], capture_output=True)
        assert (r.returncode == 0) == good, r.stderr.decode()
        print('display queue: ok' if good else 'display queue: planted fault caught')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    header = (ROOT / 'src/platform/amiga/DisplayQueue.h').read_text()
    run(header, True)
    if args.sabotage:
        for old, new in [('b < 2', 'b < 1'),
                         ('pending = -1;\n        return shown ^ 1;', 'return shown ^ 1;'),
                         ('return shown ^ 1;', 'return shown;')]:
            assert old in header
            run(header.replace(old, new, 1), False)
