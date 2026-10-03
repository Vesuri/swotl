/* INT 21h: the DOS 5 services SWOTL uses (docs/external-surface.md), with the
 * register results of the DOSBox-X reference (tests/host_run.py checks them
 * against the traced service log). Files are read-only platform files. */
#include "runtime.h"
#include "platform.h"

#define HANDLES 20
#define FILES 16
#define FIRST_FILE_SFT 3        /* reference: SFT 0-2 are AUX, CON, PRN */

static int32_t file_of_sft[FILES];   /* platform handle per SFT entry, -1 free */

uint16_t rt_psp(void)
{
    return (uint16_t)load_segment - 0x10;
}

void rt_dos_init(void)
{
    for (int k = 0; k < FILES; ++k) {
        file_of_sft[k] = -1;
    }
}

static uint32_t jft(uint16_t handle)
{
    return lin(rt_psp(), 0x18) + handle;
}

static int32_t file_of(uint16_t handle)
{
    if (handle >= HANDLES) {
        return -1;
    }
    uint8_t sft = rd8(jft(handle));
    return sft < FILES && sft >= FIRST_FILE_SFT ? file_of_sft[sft] : -1;
}

static void fail(uint16_t code)
{
    rt_r.ax = code;
    set_cf(1);
}

/* "C:\DIR\NAME.EXT" -> "DIR/NAME.EXT", upper case */
static void path_of(uint32_t a, char *out, int size)
{
    int n = 0;
    if (rd8(a) && rd8(a + 1) == ':') {
        a += 2;
    }
    while (rd8(a) == '\\' || rd8(a) == '/') {
        ++a;
    }
    for (uint8_t c; (c = rd8(a)) != 0 && n < size - 1; ++a) {
        out[n++] = c == '\\' ? '/' : (c >= 'a' && c <= 'z') ? (char)(c - 32) : (char)c;
    }
    out[n] = 0;
}

static void open_file(void)
{
    char path[80];
    path_of(lin(G_DS, rt_r.dx), path, sizeof path);
    if (AL(rt_r.ax) & 7) {
        rt_unsupported("open for writing", 0x21, 0, 0);
    }
    int32_t f = plat_open(path);
    if (f < 0) {
        fail(2);
        return;
    }
    uint16_t h = 0;
    while (h < HANDLES && rd8(jft(h)) != 0xff) {
        ++h;
    }
    uint8_t sft = FIRST_FILE_SFT;
    while (sft < FILES && file_of_sft[sft] >= 0) {
        ++sft;
    }
    if (h == HANDLES || sft == FILES) {
        plat_close(f);
        fail(4);
        return;
    }
    file_of_sft[sft] = f;
    wr8(jft(h), sft);
    rt_r.ax = h;
    set_cf(0);
}

static void close_file(void)
{
    int32_t f = file_of(rt_r.bx);
    if (f < 0) {
        fail(6);
        return;
    }
    file_of_sft[rd8(jft(rt_r.bx))] = -1;
    wr8(jft(rt_r.bx), 0xff);
    plat_close(f);
    SET_AL(rt_r.ax, 1);         /* reference: AL = reference count before close */
    set_cf(0);
}

static void read_file(void)
{
    int32_t f = file_of(rt_r.bx);
    if (f < 0) {
        fail(6);
        return;
    }
    uint32_t a = lin(G_DS, rt_r.dx);
    if (a + rt_r.cx > RT_GUEST_BYTES) {
        rt_stop("read past guest memory", a, rt_r.cx);
    }
    int32_t got = plat_read(f, rt_guest + a, rt_r.cx);
    if (got < 0) {
        fail(5);
        return;
    }
    rt_r.ax = (uint16_t)got;
    set_cf(0);
}

static void seek_file(void)
{
    int32_t f = file_of(rt_r.bx);
    if (f < 0) {
        fail(6);
        return;
    }
    int32_t pos = plat_seek(f, (int32_t)((uint32_t)rt_r.cx << 16 | rt_r.dx), AL(rt_r.ax));
    if (pos < 0) {
        fail(0x19);
        return;
    }
    rt_r.ax = (uint16_t)pos;
    rt_r.dx = (uint16_t)((uint32_t)pos >> 16);
    set_cf(0);
}

static void ioctl(uint16_t cs, uint16_t ip)
{
    if (AL(rt_r.ax) != 0) {
        rt_unsupported("IOCTL subfunction", 0x21, cs, ip);
    }
    if (rt_r.bx < 5) {
        rt_r.ax = rt_r.dx = 0x80d3;   /* reference: character device, CON */
    } else if (file_of(rt_r.bx) >= 0) {
        rt_r.ax = rt_r.dx = 0x0002;   /* drive C:, not written */
    } else {
        fail(6);
        return;
    }
    set_cf(0);
}

static void attributes(uint16_t cs, uint16_t ip)
{
    char path[80];
    if (AL(rt_r.ax) != 0) {
        rt_unsupported("set file attributes", 0x21, cs, ip);
    }
    path_of(lin(G_DS, rt_r.dx), path, sizeof path);
    int32_t f = plat_open(path);
    if (f < 0) {
        fail(2);
        return;
    }
    plat_close(f);
    rt_r.ax = rt_r.cx = 0x0020;  /* reference: archive */
    set_cf(0);
}

static uint32_t mcb_at(uint16_t seg)
{
    uint32_t m = lin(seg, 0);
    if (rd8(m) != 'M' && rd8(m) != 'Z') {
        rt_stop("corrupt MCB chain", seg, rd8(m));
    }
    return m;
}

/* AH=48h: DOS first fit (the reference strategy 0) after merging adjacent
 * free blocks: a free block of the exact size is taken whole, a larger one
 * split with the new block named after the program. */
static void allocate(void)
{
    for (uint16_t seg = RT_ENV_SEG - 1; rd8(mcb_at(seg)) == 'M'; ) {
        uint32_t m = lin(seg, 0), next = mcb_at(seg + rd16(m + 3) + 1);
        if (rd16(m + 1) == 0 && rd16(next + 1) == 0) {
            wr8(m, rd8(next));
            wr16(m + 3, rd16(m + 3) + rd16(next + 3) + 1);
        } else {
            seg += rd16(m + 3) + 1;
        }
    }
    uint16_t want = rt_r.bx, biggest = 0;
    uint32_t name = lin(rt_psp() - 1, 8);
    for (uint16_t seg = RT_ENV_SEG - 1;; ) {
        uint32_t m = mcb_at(seg);
        uint8_t type = rd8(m);
        uint16_t size = rd16(m + 3);
        if (rd16(m + 1) == 0 && size == want) {
            wr16(m + 1, rt_psp());
            rt_r.ax = seg + 1;
            set_cf(0);
            return;
        }
        if (rd16(m + 1) == 0 && size > want) {
            uint32_t rest = lin(seg + want + 1, 0);
            wr8(rest, type);
            wr16(rest + 1, 0);
            wr16(rest + 3, size - want - 1);
            wr8(m, 'M');
            wr16(m + 1, rt_psp());
            wr16(m + 3, want);
            for (int k = 0, end = 0; k < 8; ++k) {
                uint8_t c = end ? 0 : rd8(name + k);
                end |= c == 0;
                wr8(m + 8 + k, c);
            }
            rt_r.ax = seg + 1;
            set_cf(0);
            return;
        }
        if (rd16(m + 1) == 0 && size > biggest) {
            biggest = size;
        }
        if (type == 'Z') {
            rt_r.bx = biggest;
            fail(8);
            return;
        }
        seg += size + 1;
    }
}

/* AH=4Ah: DOS 5 shrink/grow of the PSP's block with the next MCB. */
static void resize(uint16_t cs, uint16_t ip)
{
    uint16_t seg = G_ES;
    uint32_t m = lin(seg - 1, 0);
    uint16_t total = rd16(m + 3);
    if (rd8(m) != 'Z' || rt_r.bx > total) {
        rt_unsupported("resize other than shrinking the last block", 0x21, cs, ip);
    }
    if (rt_r.bx < total) {
        uint32_t next = lin(seg + rt_r.bx, 0);
        wr8(next, 'Z');
        wr16(next + 1, 0);
        wr16(next + 3, total - rt_r.bx - 1);
        wr8(m, 'M');
        wr16(m + 3, rt_r.bx);
        if (seg == rt_psp()) {
            wr16(lin(seg, 2), seg + rt_r.bx);   /* reference: PSP memory top follows */
        }
    }
    rt_r.ax = seg;
    set_cf(0);
}

void rt_int21(uint16_t cs, uint16_t ip)
{
    uint8_t ah = AH(rt_r.ax);
    /* DOS saves the caller's SS:SP (after the frame and 9 pushed words) */
    if (ah != 0x50 && ah != 0x51 && ah != 0x62 && ah != 0x64 && ah < 0x6c) {
        uint32_t p = lin(rt_psp(), 0);
        wr16(p + 0x2e, (uint16_t)(rt_r.sp - 6 - 18));
        wr16(p + 0x30, G_SS);
    }
    switch (ah) {
    case 0x1b:  /* reference: allocation info of drive C: */
        SET_AL(rt_r.ax, 0x40);
        rt_r.cx = 0x0200;
        rt_r.dx = 0xffff;
        rt_r.bx = MEDIA_OFF;
        G_DS = MEDIA_SEG;
        break;
    case 0x25:
        wr16(AL(rt_r.ax) * 4, rt_r.dx);
        wr16(AL(rt_r.ax) * 4 + 2, G_DS);
        break;
    case 0x30:
        if (AL(rt_r.ax) == 0) {
            SET_AH(rt_r.bx, 0xff);
        }
        rt_r.ax = 0x0005;
        SET_AL(rt_r.bx, 0);
        rt_r.cx = 0;
        break;
    case 0x35:
        rt_r.bx = rd16(AL(rt_r.ax) * 4);
        G_ES = rd16(AL(rt_r.ax) * 4 + 2);
        break;
    case 0x3d: open_file(); break;
    case 0x3e: close_file(); break;
    case 0x3f: read_file(); break;
    case 0x42: seek_file(); break;
    case 0x43: attributes(cs, ip); break;
    case 0x44: ioctl(cs, ip); break;
    case 0x48: allocate(); break;
    case 0x4a: resize(cs, ip); break;
    case 0x4c:
        rt_log_hex("SWOTL_EXIT", AL(rt_r.ax));
        plat_exit(AL(rt_r.ax));
    default:
        rt_unsupported("DOS function", 0x21, cs, ip);
    }
}
