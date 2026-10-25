#!/usr/bin/env python3
"""Dirty inheritance and queue races against an independent complete image.

Execute the production queue with a VBI before/during/after updates, including
repeated replacement of a pending image and palette-only publications. Then
the production runtime display path (src/runtime/video.c) with the field
task (docs/irq-plan.md I5) interrupting the main thread inside graphics
driver calls, presents and video BIOS calls: it never presents there, and a
published frame is shown by the next field task outside them.
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


VIDEO_RUNTIME = r'''
#pragma once
#include <stdint.h>
struct rt_regs { uint16_t ax, bx, cx, dx; };
extern struct rt_regs rt_r;
extern uint8_t *rt_guest;
extern uint16_t g_es;
#define G_ES g_es
#define AL(r) ((uint8_t)(r))
#define AH(r) ((uint8_t)((r) >> 8))
#define SET_AH(r, v) ((r) = ((r) & 0x00ff) | (uint16_t)((uint8_t)(v)) << 8)
static inline uint32_t lin(uint16_t seg, uint16_t off) { return ((uint32_t)seg << 4) + off; }
static inline uint8_t rd8(uint32_t a) { return *(rt_guest - a); }
static inline void wr8(uint32_t a, uint8_t v) { *(rt_guest - a) = v; }
static inline void wr16(uint32_t a, uint16_t v) { wr8(a, (uint8_t)v); wr8(a + 1, (uint8_t)(v >> 8)); }
uint8_t *rt_span(uint32_t a, uint32_t n);
void rt_stop(const char *what, uint32_t a, uint32_t b) __attribute__((noreturn));
void rt_unsupported(const char *what, uint16_t vector, uint16_t cs, uint16_t ip) __attribute__((noreturn));
extern uint8_t rt_dac[768];
extern volatile uint8_t rt_present_due;
void rt_video_refresh(void);
void rt_int10(void);
void maybe_field(void);
#define RT_FIELD_POINT() maybe_field()
'''
VIDEO_PLATFORM = r'''
#pragma once
#include <stdint.h>
struct plat_rect { uint16_t x0, y0, x1, y1; };
void plat_present(const uint8_t *frame, const struct plat_rect *rects, int32_t n);
void plat_palette(const uint8_t *dac);
void plat_service(void);
'''
VIDEO_HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "runtime.h"
#include "platform.h"
struct vram_row { uint16_t lo, hi; };
extern struct vram_row rt_vram_rows[200];
extern uint16_t rt_vram_top, rt_vram_bottom, rt_vdrv_depth;
void rt_video_publish(void);
static uint8_t memory[0x110000];
uint8_t *rt_guest = memory + 0x10ffff;
struct rt_regs rt_r;
uint16_t g_es;
static uint8_t shown[64000];
static unsigned seed = 14, fielding, driving, spanning, display;
static unsigned fields, raced, presents, owed;
static unsigned next(unsigned n) { seed = seed * 1103515245u + 12345u; return (seed >> 8) % n; }
void rt_stop(const char *what, uint32_t a, uint32_t b) { fprintf(stderr, "stop %s\n", what); abort(); }
void rt_unsupported(const char *what, uint16_t v, uint16_t cs, uint16_t ip) { rt_stop(what, v, 0); }
/* The field task: a level-1 interrupt, never nested in itself. */
static void field(void)
{
    if (fielding) return;
    fielding = 1;
    ++fields;
    raced += driving || spanning || display;
    rt_video_refresh();
    fielding = 0;
}
void maybe_field(void) { if (!next(3)) field(); }
void plat_service(void) {}
uint8_t *rt_span(uint32_t a, uint32_t n)
{
    assert(!spanning);              /* a present inside a present */
    spanning = 1;
    maybe_field();
    spanning = 0;
    return rt_guest - a - n + 1;
}
void plat_present(const uint8_t *frame, const struct plat_rect *r, int32_t n)
{
    assert(!display && !driving);   /* inside a display update or a driver call */
    display = 1;
    for (int32_t k = 0; k < n; ++k)
        for (unsigned y = r[k].y0; y < r[k].y1; ++y)
            memcpy(shown + y * 320 + r[k].x0, frame + y * 320 + r[k].x0, r[k].x1 - r[k].x0);
    ++presents;
    owed = 0;
    maybe_field();
    display = 0;
}
void plat_palette(const uint8_t *dac)
{
    assert(!display);
    display = 1;
    maybe_field();
    display = 0;
}
static void video_bios(uint16_t ax)
{
    rt_r.ax = ax;
    rt_r.bx = (uint16_t)next(200);
    rt_r.cx = (uint16_t)next(56);
    rt_r.dx = 0;
    g_es = 0x1000;
    rt_int10();
}
/* A graphics driver call (possibly nested) as rt_vram_mark and rt_vdrv_return. */
static void driver(unsigned depth)
{
    ++rt_vdrv_depth;
    ++driving;
    for (unsigned k = next(4); k--;) {
        unsigned y = next(200), x0 = next(320), x1 = x0 + 1 + next(320 - x0);
        for (unsigned x = x0; x < x1; ++x) wr8(0xa0000 + y * 320 + x, (uint8_t)next(256));
        struct vram_row *row = &rt_vram_rows[y];
        if (!row->hi || x0 < row->lo) row->lo = (uint16_t)x0;
        if (x1 > row->hi) row->hi = (uint16_t)x1;
        if (y < rt_vram_top) rt_vram_top = (uint16_t)y;
        if (y + 1 > rt_vram_bottom) rt_vram_bottom = (uint16_t)(y + 1);
        owed = 1;
        maybe_field();
        if (depth < 2 && !next(4)) driver(depth + 1);
    }
    --driving;
    maybe_field();
    if (!--rt_vdrv_depth && rt_vram_bottom) rt_video_publish();
}
int main(void)
{
    video_bios(0x0013);
    unsigned checked = 0;
    for (unsigned step = 0; step < 20000; ++step) {
        unsigned what = next(100);
        if (what < 60) driver(0);
        else if (what < 75) video_bios(0x1012);
        else if (what < 76) video_bios(0x0013);
        if (next(2)) continue;
        field();
        /* outside every display path: what was published is shown */
        if (owed) {
            fprintf(stderr, "step %u: a published frame was not shown\n", step);
            return 1;
        }
        if (presents != checked && !rt_vram_bottom) {   /* no rows left to present */
            checked = presents;
            for (unsigned k = 0; k < 64000; ++k) assert(shown[k] == rd8(0xa0000 + k));
        }
    }
    printf("fields %u, %u inside the main display path, presents %u\n", fields, raced, presents);
    assert(raced > 1000 && presents > 1000);
    return 0;
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


def run_video(source, good):
    with tempfile.TemporaryDirectory(prefix='display-field-', dir=ROOT / 'tmp') as name:
        p = Path(name)
        (p / 'runtime.h').write_text(VIDEO_RUNTIME)
        (p / 'platform.h').write_text(VIDEO_PLATFORM)
        (p / 'video.c').write_text(source)
        (p / 'test.c').write_text(VIDEO_HARNESS)
        subprocess.run(['cc', '-std=c11', '-O2', '-I', str(p), str(p / 'video.c'), str(p / 'test.c'),
                        '-o', str(p / 'test')], check=True)
        r = subprocess.run([str(p / 'test')], capture_output=True)
        assert (r.returncode == 0) == good, (r.stdout + r.stderr).decode()
        print(f'field task: {r.stdout.decode().strip()}' if good else 'field task: planted fault caught')


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
    video = (ROOT / 'src/runtime/video.c').read_text()
    run_video(video, True)
    if args.sabotage:
        # the field task presents during a publish, a video BIOS call, a driver call
        for old, new in [(' && !busy) {', ') {'),
                         ('    set_busy(1);\n    published = 1;', '    published = 1;'),
                         ('    set_busy(1);\n    switch', '    switch'),
                         ('published && !rt_vdrv_depth', 'published')]:
            assert old in video
            run_video(video.replace(old, new, 1), False)
