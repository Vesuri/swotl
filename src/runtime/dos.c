/* INT 21h: the DOS 5 services SWOTL uses (docs/external-surface.md), with the
 * register results of the DOSBox-X reference (tests/host_run.py checks them
 * against the traced service log). Files are platform files. */
#include "runtime.h"
#include "platform.h"

#define HANDLES 20
#define FILES 16
#define FIRST_FILE_SFT 3        /* reference: SFT 0-2 are AUX, CON, PRN */

static int32_t file_of_sft[FILES];   /* platform handle per SFT entry, -1 free */
enum file_action { FILE_NONE, FILE_READ, FILE_WRITE };
static uint8_t file_action[FILES], file_stamped[FILES];
static uint16_t file_time[FILES], file_date[FILES];
static uint32_t dos_calendar; /* year:16, month:8, day:8; cached by DOS */
static uint32_t dos_centiseconds(void);

static void stamp_file(uint8_t sft)
{
    if (!file_stamped[sft]) {
        /* Original reads the cached date before reading time (which consumes
         * the BIOS midnight count), and retains this stamp across later writes. */
        uint32_t date = dos_calendar;
        uint32_t t = dos_centiseconds() / 100;
        file_date[sft] = (uint16_t)((((date >> 16) - 1980) & 127) << 9 |
                                  ((date >> 8) & 255) << 5 | (date & 255));
        file_time[sft] = (uint16_t)((t / 3600 % 24) << 11 |
                                  (t / 60 % 60) << 5 | (t % 60) / 2);
        file_stamped[sft] = 1;
    }
}

static uint16_t dta_seg, dta_off = 0x80;  /* AH=1Ah; reference: PSP:80h at start */
/* DOSBox DOS swappable data area, located by INT 21h/AH=34h in the oracle. */
#define DOS_SDA 0x0a30u
#define SDA_DTA 0x0cu
static void set_dta(uint16_t seg, uint16_t off)
{
    dta_seg = seg;
    dta_off = off;
    wr16(DOS_SDA + SDA_DTA, off);
    wr16(DOS_SDA + SDA_DTA + 2, seg);
}

/* DOSBox's search slots are independent of the DTA and its pattern. */
#define SEARCH_SLOTS 2048
struct search_name { struct search_name *next; char name[13]; };
static struct { char directory[80]; struct search_name *remaining; uint8_t active; } searches[SEARCH_SLOTS];
static uint16_t next_search;

static void search_free(uint16_t slot)
{
    struct search_name *p = searches[slot].remaining;
    while (p) {
        struct search_name *next = p->next;
        plat_free(p);
        p = next;
    }
    searches[slot].remaining = 0;
    searches[slot].active = 0;
}

void rt_dos_close(void)
{
    for (int k = 0; k < SEARCH_SLOTS; ++k) search_free(k);
}

static int name_order(const char *a, const char *b)
{
    while (*a && *a == *b) { ++a; ++b; }
    return (uint8_t)*a - (uint8_t)*b;
}

static void search_snapshot(uint16_t slot)
{
    char name[13];
    struct plat_file_info info;
    for (uint32_t i = 0; plat_dir_entry(searches[slot].directory, i, name, &info); ++i) {
        struct search_name *p = plat_alloc(sizeof *p);
        if (!p) rt_stop("directory snapshot allocation", slot, i);
        int k = 0;
        do {
            char c = name[k];
            p->name[k] = c >= 'a' && c <= 'z' ? (char)(c - 32) : c;
        } while (name[k++]);
        struct search_name **at = &searches[slot].remaining;
        while (*at && name_order((*at)->name, p->name) < 0) at = &(*at)->next;
        p->next = *at;
        *at = p;
    }
}

/* Names are snapshotted; metadata is read at FindNext, as DOSBox stats each
 * surviving name. New files cannot enter a search already in progress. */
static int search_next(uint16_t slot, char *name, struct plat_file_info *info)
{
    while (searches[slot].remaining) {
        struct search_name *p = searches[slot].remaining;
        searches[slot].remaining = p->next;
        for (int k = 0;; ++k) { name[k] = p->name[k]; if (!name[k]) break; }
        plat_free(p);
        char current[13];
        for (uint32_t i = 0; plat_dir_entry(searches[slot].directory, i, current, info); ++i) {
            for (int k = 0; current[k]; ++k)
                if (current[k] >= 'a' && current[k] <= 'z') current[k] -= 32;
            if (!name_order(name, current)) return 1;
        }
    }
    return 0;
}

uint16_t rt_psp(void)
{
    return (uint16_t)load_segment - 0x10;
}

void rt_dos_init(void)
{
    for (uint32_t i = 0; i < 28; ++i) wr8(DOS_SDA + i, 0);
    wr8(DOS_SDA + 2, 0xff);     /* no critical-error drive */
    wr16(DOS_SDA + 0x10, rt_psp());
    wr8(DOS_SDA + 0x16, 2);     /* current drive C: */
    set_dta(rt_psp(), 0x80);
    next_search = 0;
    rt_dos_close();
    dos_calendar = plat_calendar_date();
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

/* A free handle and SFT entry for platform file f (AX = handle), else error 4. */
static void install(int32_t f)
{
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
    file_action[sft] = FILE_NONE;
    file_stamped[sft] = 0;
    wr8(jft(h), sft);
    rt_r.ax = h;
    set_cf(0);
}

/* AH=3Dh: AL access 0 read, 1 write, 2 read/write (sharing bits ignored). */
static void open_file(uint16_t cs, uint16_t ip)
{
    char path[80];
    path_of(lin(G_DS, rt_r.dx), path, sizeof path);
    uint8_t access = AL(rt_r.ax) & 7;
    if (access > 2) {
        rt_unsupported("file access mode", 0x21, cs, ip);
    }
    int32_t f = plat_open(path, access);
    if (f < 0) {
        fail(2);
        return;
    }
    install(f);
}

/* AH=3Ch: CX attributes (the reference stores files as archive). */
static void create_file(void)
{
    char path[80];
    path_of(lin(G_DS, rt_r.dx), path, sizeof path);
    int32_t f = plat_create(path);
    if (f < 0) {
        fail(5);
        return;
    }
    next_search = 0;  /* DOS create empties the cache but retains live searches. */
    install(f);
}

/* AH=41h: AX unchanged on success. */
static void delete_file(void)
{
    char path[80];
    path_of(lin(G_DS, rt_r.dx), path, sizeof path);
    if (plat_delete(path) < 0) {
        fail(2);
        return;
    }
    set_cf(0);
}

/* AH=40h to a file handle; CX=0 truncates at the position. */
static void write_file(uint16_t cs, uint16_t ip)
{
    if (rt_r.bx < 5) {
        rt_unsupported("write to a device handle", 0x21, cs, ip);
    }
    int32_t f = file_of(rt_r.bx);
    if (f < 0) {
        fail(6);
        return;
    }
    uint32_t a = lin(G_DS, rt_r.dx);
    if (a + rt_r.cx > RT_GUEST_BYTES) {
        rt_stop("write past guest memory", a, rt_r.cx);
    }
    uint8_t *span = rt_span(a, rt_r.cx);
    rt_span_order(span, rt_r.cx);
    int32_t put = plat_write(f, span, rt_r.cx);
    rt_span_order(span, rt_r.cx);
    if (put < 0) {
        fail(5);
        return;
    }
    file_action[rd8(jft(rt_r.bx))] = FILE_WRITE;
    rt_r.ax = (uint16_t)put;
    set_cf(0);
}

static void close_file(void)
{
    int32_t f = file_of(rt_r.bx);
    if (f < 0) {
        fail(6);
        return;
    }
    uint8_t sft = rd8(jft(rt_r.bx));
    if (file_action[sft] == FILE_WRITE) stamp_file(sft);
    if (file_stamped[sft]) plat_file_stamp(f, file_time[sft], file_date[sft]);
    file_of_sft[sft] = -1;
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
    uint8_t sft = rd8(jft(rt_r.bx));
    if (file_action[sft] == FILE_WRITE) stamp_file(sft);
    file_action[sft] = FILE_READ;
    /* Through a buffer: a short read (end of file) must leave the rest of the
     * reversed span untouched. */
    static uint8_t buf[0x1000];
    uint32_t got = 0, want;
    int32_t n;
    do {
        want = rt_r.cx - got < sizeof buf ? rt_r.cx - got : sizeof buf;
        n = plat_read(f, buf, want);
        if (n < 0) {
            fail(5);
            return;
        }
        uint8_t *d = rt_span(a + got, 1);
        for (int32_t k = 0; k < n; ++k) {
            *d-- = buf[k];
        }
        got += (uint32_t)n;
    } while ((uint32_t)n == want && got < rt_r.cx);
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
    file_action[rd8(jft(rt_r.bx))] = FILE_NONE;
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
    int32_t f = plat_open(path, 0);
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

/* AH=2Ch: DOS time from the BIOS tick count (reference: no RTC read after
 * start-up), hundredths = ticks * 100 * 65536 / 1193182, exact. */
static uint32_t dos_centiseconds(void)
{
    uint8_t days = rd8(0x470);
    wr8(0x470, 0);
    while (days--) {
        uint32_t year = dos_calendar >> 16, month = (dos_calendar >> 8) & 255;
        uint32_t day = (dos_calendar & 255) + 1;
        static const uint8_t lengths[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
        uint32_t length = lengths[month - 1] + (month == 2 && year % 4 == 0 &&
                                               (year % 100 != 0 || year % 400 == 0));
        if (day > length) { day = 1; if (++month > 12) { month = 1; ++year; } }
        dos_calendar = year << 16 | month << 8 | day;
    }
    uint32_t ticks = rd32(0x46c);
    uint32_t a = ticks * 100, q = a / 1193182, r = a % 1193182;
    uint32_t t = q * 65536;
    r *= 256;
    t += (r / 1193182) * 256;
    r = (r % 1193182) * 256;
    t += r / 1193182;
    return t;
}

static void get_time(void)
{
    uint8_t midnight = rd8(0x470);
    uint32_t t = dos_centiseconds();
    rt_r.dx = (uint16_t)((t / 100 % 60) << 8 | t % 100);
    t /= 6000;
    rt_r.cx = (uint16_t)((t / 60 % 24) << 8 | t % 60);
    SET_AL(rt_r.ax, midnight);
}

/* AH=08h: CON input, no echo, as the reference's CON device reads INT 16h
 * AH=10h: an F0h low byte reads as 0; a 0 or E0h low byte gives 0, then the
 * scan code. */
static void read_char(uint16_t cs, uint16_t ip)
{
    static uint8_t scan_next;
    if (scan_next) {
        SET_AL(rt_r.ax, scan_next);
        scan_next = 0;
        return;
    }
    if (!rt_key_available()) {
        rt_unsupported("console read with no key buffered", 0x21, cs, ip);
    }
    uint16_t key = rt_key_take();
    uint8_t c = (uint8_t)key, scan = (uint8_t)(key >> 8);
    if (scan && (c == 0xf0 || c == 0xe0)) {
        c = 0;
    }
    SET_AL(rt_r.ax, c);
    if (!c) {
        scan_next = scan;
    }
}

/* DTA as the reference's DOSBox-X lays it out (DOS_DTA): search state, then
 * the found entry. */
#define DTA_DRIVE 0x00
#define DTA_SPNAME 0x01     /* the pattern's name part as written, 8 bytes */
#define DTA_SPEXT 0x09      /* its extension, 3 bytes */
#define DTA_SATTR 0x0c
#define DTA_SEARCH 0x0d     /* DOSBox directory-search slot */
#define DTA_ATTR 0x15
#define DTA_TIME 0x16
#define DTA_DATE 0x18
#define DTA_SIZE 0x1a
#define DTA_NAME 0x1e

/* "NAME.EXT" (or a pattern field pair) -> 11-char FCB form, '*' as '?' fill */
static int fcb_form(const char *name, int n, const char *ext, int e, char out[11])
{
    for (int k = 0, j = 0; k < 8; ++k) {
        char c = j < n ? name[j] : ' ';
        if (c == '*') {
            c = '?';
        } else {
            ++j;
        }
        out[k] = c;
    }
    for (int k = 0, j = 0; k < 3; ++k) {
        char c = j < e ? ext[j] : ' ';
        if (c == '*') {
            c = '?';
        } else {
            ++j;
        }
        out[8 + k] = c;
    }
    return n <= 8 && e <= 3;
}

static int field_len(uint32_t a, int max)
{
    int n = 0;
    while (n < max && rd8(a + n)) {
        ++n;
    }
    return n;
}

/* Search from the DTA's state: the next platform entry matching its pattern. */
static int find_next_entry(void)
{
    uint32_t dta = lin(dta_seg, dta_off);
    uint16_t slot = rd16(dta + DTA_SEARCH);
    if (slot >= SEARCH_SLOTS || !searches[slot].active) {
        fail(0x12);
        return 0;
    }
    char pat[11], fcb[11], spname[8], spext[3], name[16];
    for (int k = 0; k < 8; ++k) {
        spname[k] = (char)rd8(dta + DTA_SPNAME + k);
    }
    for (int k = 0; k < 3; ++k) {
        spext[k] = (char)rd8(dta + DTA_SPEXT + k);
    }
    fcb_form(spname, field_len(dta + DTA_SPNAME, 8), spext, field_len(dta + DTA_SPEXT, 3), pat);
    struct plat_file_info info;
    while (search_next(slot, name, &info)) {
        int n = 0;
        for (; name[n]; ++n) {
            name[n] = name[n] >= 'a' && name[n] <= 'z' ? (char)(name[n] - 32) : name[n];
        }
        const char *dot = 0;
        for (int k = 0; k < n; ++k) {
            dot = name[k] == '.' ? name + k : dot;
        }
        int base = dot ? (int)(dot - name) : n, ext = dot ? n - base - 1 : 0;
        if (!fcb_form(name, base, dot ? dot + 1 : "", ext, fcb)) {
            continue;  /* not an 8.3 name: DOS cannot see it */
        }
        int match = 1;
        for (int k = 0; k < 11; ++k) {
            match &= pat[k] == '?' || pat[k] == fcb[k];
        }
        if (!match) {
            continue;
        }
        wr8(dta + DTA_ATTR, 0x20);  /* archive, as AH=43h */
        wr16(dta + DTA_TIME, info.dos_time);
        wr16(dta + DTA_DATE, info.dos_date);
        wr32(dta + DTA_SIZE, info.size);
        for (int k = 0; k <= n; ++k) {
            wr8(dta + DTA_NAME + k, (uint8_t)name[k]);
        }
        rt_r.ax = 0;  /* reference: undocumented AX=0 */
        set_cf(0);
        return 1;
    }
    searches[slot].active = 0;
    fail(0x12);  /* no more files */
    return 0;
}

/* AH=4Eh: the reference's SetupSearch (raw pattern fields), then the search. */
static void find_first(uint16_t cs, uint16_t ip)
{
    char path[80];
    path_of(lin(G_DS, rt_r.dx), path, sizeof path);
    if (AL(rt_r.cx) & 0x08) {
        rt_unsupported("find first of a volume label", 0x21, cs, ip);
    }
    uint16_t checked = 0;
    while (checked < SEARCH_SLOTS && searches[next_search].active) {
        next_search = (next_search + 1) % SEARCH_SLOTS;
        ++checked;
    }
    if (checked == SEARCH_SLOTS) {
        rt_dos_close();
        next_search = 0;
    }
    uint16_t slot = next_search;
    next_search = (next_search + 1) % SEARCH_SLOTS;
    searches[slot].active = 1;
    searches[slot].remaining = 0;
    char *find_dir = searches[slot].directory;
    int slash = -1;
    for (int k = 0; path[k]; ++k) {
        slash = path[k] == '/' ? k : slash;
    }
    for (int k = 0; k < slash; ++k) {
        find_dir[k] = path[k];
    }
    find_dir[slash < 0 ? 0 : slash] = 0;
    search_snapshot(slot);
    const char *pattern = path + slash + 1;
    uint32_t dta = lin(dta_seg, dta_off);
    for (int k = 0; k < 11; ++k) {
        wr8(dta + DTA_SPNAME + k, 0);
    }
    wr8(dta + DTA_DRIVE, 2);  /* C: */
    wr8(dta + DTA_SATTR, AL(rt_r.cx));
    int n = 0;
    while (pattern[n] && pattern[n] != '.') {
        ++n;
    }
    for (int k = 0; k < n && k < 8; ++k) {
        wr8(dta + DTA_SPNAME + k, (uint8_t)pattern[k]);
    }
    for (int k = 0; pattern[n] && pattern[n + 1 + k] && k < 3; ++k) {
        wr8(dta + DTA_SPEXT + k, (uint8_t)pattern[n + 1 + k]);
    }
    wr16(dta + DTA_SEARCH, slot);
    find_next_entry();
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
    case 0x0d: break;  /* DOSBox disk reset preserves registers and search slots. */
    case 0x08: read_char(cs, ip); break;
    case 0x0b:  /* CON input status */
        SET_AL(rt_r.ax, rt_key_available() ? 0xff : 0x00);
        break;
    case 0x1a:
        set_dta(G_DS, rt_r.dx);
        break;
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
    case 0x2c: get_time(); break;
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
    case 0x3c: create_file(); break;
    case 0x3d: open_file(cs, ip); break;
    case 0x3e: close_file(); break;
    case 0x3f: read_file(); break;
    case 0x40: write_file(cs, ip); break;
    case 0x41: delete_file(); break;
    case 0x42: seek_file(); break;
    case 0x43: attributes(cs, ip); break;
    case 0x44: ioctl(cs, ip); break;
    case 0x48: allocate(); break;
    case 0x4a: resize(cs, ip); break;
    case 0x4e: find_first(cs, ip); break;
    case 0x4f: find_next_entry(); break;
    case 0x4c:
        rt_log_hex("SWOTL_EXIT", AL(rt_r.ax));
        plat_exit(AL(rt_r.ax));
    default:
        rt_unsupported("DOS function", 0x21, cs, ip);
    }
}
