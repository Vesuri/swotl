/* EGA model (docs/ecs-plan.md E4): mode 0Eh memory and registers as the IBM
 * EGA technical reference describes them, cross-read with DOSBox-X's
 * src/hardware/vga_memory.cpp (the reference): four 64 KiB planes behind
 * A0000h-AFFFFh (graphics misc 05h: memory map 1, no odd/even; sequencer
 * memory mode 06h), the sequencer's map mask and the graphics controller's
 * set/reset, enable set/reset, colour compare, data rotate and function,
 * read map, mode (write modes 0-2, read modes 0-1), colour don't care and bit
 * mask, and the four latches every read loads. Guest code writes only
 * sequencer 2 and graphics 4, 5 (00h-02h) and 8 (ecs-plan E2); any other
 * register or value stops.
 *
 * The generated EGA driver reaches the model through rt_entry.s rt_ega_*
 * (translator/lower.py, EGA device lowering): an operand's guest RAM bytes
 * are the bounce (a read puts the model's byte there, a write takes the byte
 * the instruction stored), string instructions run here element by element.
 * A word is two byte accesses, low first, as DOSBox-X's. Stores to page 0
 * (bytes 0-15999, the CRTC start never changes) mark the D9 rows in bytes
 * (video.c). */
#include "runtime.h"
#include "platform.h"

#define EGA_BASE 0xa0000u
#define EGA_WINDOW 0x10000u
#define EGA_PAGE_BYTES 16000u

uint8_t rt_ega;
_Alignas(4) uint8_t *rt_ega_planes;
struct rt_ega_regs rt_ega_regs;

static inline int in_window(uint32_t a)
{
    return a - EGA_BASE < EGA_WINDOW;
}

static void mark(uint32_t off)
{
    if (off >= EGA_PAGE_BYTES) {
        return;
    }
    if (!rt_vdrv_depth) {
        rt_vram_stray();
    }
    uint16_t y = (uint16_t)(off / 80), x = (uint16_t)(off % 80);
    struct vram_row *row = &rt_vram_rows[y];
    if (!row->hi) {
        row->lo = x;
        row->hi = (uint16_t)(x + 1);
    } else {
        if (x < row->lo) {
            row->lo = x;
        }
        if (x >= row->hi) {
            row->hi = (uint16_t)(x + 1);
        }
    }
    if (y < rt_vram_top) {
        rt_vram_top = y;
    }
    if (y >= rt_vram_bottom) {
        rt_vram_bottom = (uint16_t)(y + 1);
    }
}

static uint8_t ega_read(uint32_t off)
{
    struct rt_ega_regs *g = &rt_ega_regs;
    for (int p = 0; p < 4; ++p) {
        g->latch[p] = rt_ega_planes[(uint32_t)p << 16 | off];
    }
    if (!(g->mode & 8)) {
        return g->latch[g->read_map & 3];
    }
    uint8_t differ = 0;      /* read mode 1: 1 where every cared plane equals colour compare */
    for (int p = 0; p < 4; ++p) {
        if (g->color_dont_care >> p & 1) {
            differ |= (uint8_t)(g->latch[p] ^ (g->color_compare >> p & 1 ? 0xff : 0));
        }
    }
    return (uint8_t)~differ;
}

static uint8_t alu(uint8_t d, uint8_t latch, uint8_t function, uint8_t mask)
{
    switch (function) {
    case 0: return (uint8_t)((d & mask) | (latch & ~mask));
    case 1: return (uint8_t)((d | ~mask) & latch);
    case 2: return (uint8_t)((d & mask) | latch);
    default: return (uint8_t)((d & mask) ^ latch);
    }
}

static void ega_write(uint32_t off, uint8_t v)
{
    struct rt_ega_regs *g = &rt_ega_regs;
    uint8_t function = (uint8_t)(g->data_rotate >> 3 & 3), count = g->data_rotate & 7;
    uint8_t rotated = (uint8_t)(v >> count | v << (8 - count));
    for (int p = 0; p < 4; ++p) {
        if (!(g->map_mask >> p & 1)) {
            continue;
        }
        uint8_t d, latch = g->latch[p];
        switch (g->mode & 3) {
        case 0:
            d = g->enable_set_reset >> p & 1 ? (g->set_reset >> p & 1 ? 0xff : 0) : rotated;
            d = alu(d, latch, function, g->bit_mask);
            break;
        case 1:
            d = latch;
            break;
        default:
            d = alu(v >> p & 1 ? 0xff : 0, latch, function, g->bit_mask);
            break;
        }
        rt_ega_planes[(uint32_t)p << 16 | off] = d;
    }
    mark(off);
}

/* rt_ega_read8/16 (rt_entry.s): the n bytes from linear `a`; those in the
 * window hold the model's read afterwards. */
void rt_ega_read_c(uint32_t a, uint32_t n)
{
    for (; n; --n, ++a) {
        if (in_window(a)) {
            *(rt_guest - a) = ega_read(a - EGA_BASE);
        }
    }
}

/* rt_ega_write8/16: the bytes the instruction stored at `a`, through the
 * model's write logic. */
void rt_ega_write_c(uint32_t a, uint32_t n)
{
    for (; n; --n, ++a) {
        if (in_window(a)) {
            ega_write(a - EGA_BASE, *(rt_guest - a));
        }
    }
}

static uint8_t get(uint32_t a)
{
    return in_window(a) ? ega_read(a - EGA_BASE) : rd8(a);
}

static void put(uint32_t a, uint8_t v)
{
    if (in_window(a)) {
        ega_write(a - EGA_BASE, v);
    } else {
        wr8(a, v);
    }
}

enum { OP_MOVS, OP_STOS, OP_LODS, OP_CMPS, OP_SCAS };

/* rt_ega_string: d = op | width << 8 | rep << 16 | source segment << 24
 * (translator/lower.py EGA_STRING; 0-3 DS, ES, SS, CS). 0: no element
 * reaches the window (the instruction then runs as lowered); else it ran,
 * the registers in rt_r. */
int rt_ega_string_c(uint32_t d)
{
    uint8_t op = (uint8_t)d, w = (uint8_t)(d >> 8), rep = (uint8_t)(d >> 16), seg = (uint8_t)(d >> 24);
    uint16_t n = rep ? rt_r.cx : 1;
    int src = op == OP_MOVS || op == OP_LODS || op == OP_CMPS, dst = op != OP_LODS;
    uint16_t sseg = seg == 0 ? G_DS : seg == 1 ? G_ES : seg == 2 ? G_SS : 0;
    int16_t step = (int16_t)(G_DF ? -w : w);
    int reaches = 0;
    for (uint16_t k = 0, si = rt_r.si, di = rt_r.di; k < n && !reaches; ++k) {
        for (uint8_t b = 0; b < w; ++b) {
            reaches |= (src && in_window(lin(sseg, (uint16_t)(si + b)))) ||
                       (dst && in_window(lin(G_ES, (uint16_t)(di + b))));
        }
        si = (uint16_t)(si + step);
        di = (uint16_t)(di + step);
    }
    if (!reaches) {
        return 0;
    }
    if (seg == 3 || op == OP_CMPS || op == OP_SCAS) {
        rt_stop("EGA string instruction outside the surface (op, descriptor)", op, d);
    }
    for (; n; --n) {
        uint8_t v[2];
        for (uint8_t b = 0; b < w; ++b) {
            v[b] = op == OP_STOS ? (uint8_t)(rt_r.ax >> (8 * b)) : get(lin(sseg, (uint16_t)(rt_r.si + b)));
        }
        if (op == OP_LODS) {
            rt_r.ax = w == 1 ? (uint16_t)((rt_r.ax & 0xff00) | v[0]) : (uint16_t)(v[1] << 8 | v[0]);
        } else {
            for (uint8_t b = 0; b < w; ++b) {
                put(lin(G_ES, (uint16_t)(rt_r.di + b)), v[b]);
            }
        }
        if (src) {
            rt_r.si = (uint16_t)(rt_r.si + step);
        }
        if (dst) {
            rt_r.di = (uint16_t)(rt_r.di + step);
        }
    }
    if (rep) {
        rt_r.cx = 0;
    }
    return 1;
}

/* Sequencer (3C4h/3C5h) and graphics controller (3CEh/3CFh) ports; 0 if
 * `port` is neither. A word out is the index, then the data. */
static void sequencer(uint8_t v)
{
    if (rt_ega_regs.seq_index != 2 || v & 0xf0) {
        rt_stop("EGA sequencer register outside the surface (index, value)", rt_ega_regs.seq_index, v);
    }
    rt_ega_regs.map_mask = v;
}

static void graphics(uint8_t v)
{
    struct rt_ega_regs *g = &rt_ega_regs;
    switch (g->gc_index) {
    case 4:
        if (v <= 3) {
            g->read_map = v;
            return;
        }
        break;
    case 5:
        if (v <= 2) {
            g->mode = v;
            return;
        }
        break;
    case 8:
        g->bit_mask = v;
        return;
    }
    rt_stop("EGA graphics register outside the surface (index, value)", g->gc_index, v);
}

int rt_ega_out(uint32_t port, uint32_t value, uint32_t width)
{
    uint8_t v = (uint8_t)value, hi = (uint8_t)(value >> 8);
    switch (port) {
    case 0x3c4:
        rt_ega_regs.seq_index = v;
        if (width == 16) {
            sequencer(hi);
        }
        return 1;
    case 0x3c5:
        if (width != 8) {
            break;
        }
        sequencer(v);
        return 1;
    case 0x3ce:
        rt_ega_regs.gc_index = v;
        if (width == 16) {
            graphics(hi);
        }
        return 1;
    case 0x3cf:
        if (width != 8) {
            break;
        }
        graphics(v);
        return 1;
    }
    return 0;
}

/* INT 10h AX=000Eh: the planes cleared, the registers as DOSBox-X's mode
 * set leaves them (the reference's snapshot after it, ega-m1-mode0eh); the
 * latches as they were. */
void rt_ega_mode(void)
{
    if (!rt_ega_planes) {
        rt_ega_planes = plat_alloc(4 * EGA_WINDOW);
        if (!rt_ega_planes) {
            rt_stop("no memory for the EGA planes", 4 * EGA_WINDOW, 0);
        }
    }
    for (uint32_t k = 0; k < 4 * EGA_WINDOW; ++k) {
        rt_ega_planes[k] = 0;
    }
    struct rt_ega_regs *g = &rt_ega_regs;
    g->map_mask = 0x0f;
    g->set_reset = g->enable_set_reset = g->color_compare = g->data_rotate = 0;
    g->read_map = g->mode = 0;
    g->misc = 0x05;
    g->color_dont_care = 0x0f;
    g->bit_mask = 0xff;
    for (int k = 0; k < 16; ++k) {
        g->attr[k] = (uint8_t)(k < 8 ? k : k + 8);
    }
    g->overscan = 0;
}
