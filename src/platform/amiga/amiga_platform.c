/* Platform services for the runtime on AmigaOS (dos.library, an Intuition
 * screen for the frame), and the run of the translated program on its own
 * native stack. Game files are read from the current directory (the game's
 * own data files, supplied by the user). */
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/graphics.h>
#include <proto/intuition.h>
#include <proto/cia.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include <graphics/gfxbase.h>
#include <graphics/modeid.h>
#include <intuition/screens.h>
#include <hardware/cia.h>
#include <hardware/intbits.h>
#include <devices/input.h>
#include <devices/inputevent.h>
#include <resources/cia.h>
#include "runtime.h"
#include "platform.h"
#include "amiga_platform.h"

struct DosLibrary *DOSBase = 0;
struct IntuitionBase *IntuitionBase = 0;
extern struct GfxBase *GfxBase;

#define MAX_FILES 16
#define GUEST_STACK_BYTES 0x10000

static BPTR files[MAX_FILES];

/* The frame as shown (tests/host_run.py --amiga reads them back through the
 * GDB fixture): the screen's bitplanes and the LoadRGB32 table. */
#define FRAME_W 320
#define FRAME_H 200
struct Screen *amiga_screen = 0;
uint32_t amiga_colours[1 + 256 * 3 + 1];

/* Kalms c2p (c2p1x1_8_c5_bm.s): d0/d1 chunky width (a multiple of 32) and
 * height, d2/d3 screen offset (x a multiple of 8), a0 contiguous chunky
 * pixels, a1 BitMap; saves d2-d7/a2-a6. */
static void c2p(const void *chunky, int32_t w, int32_t h, int32_t x, int32_t y,
                struct BitMap *bitmap)
{
    register int32_t d0 __asm("d0") = w;
    register int32_t d1 __asm("d1") = h;
    register int32_t d2 __asm("d2") = x;
    register int32_t d3 __asm("d3") = y;
    register const void *a0 __asm("a0") = chunky;
    register struct BitMap *a1 __asm("a1") = bitmap;
    __asm volatile("jsr c2p1x1_8_c5_bm" : "+r"(d0), "+r"(d1), "+r"(a0), "+r"(a1)
                   : "r"(d2), "r"(d3) : "cc", "memory");
}

int32_t amiga_guest_call(void *stack_top);
static void key_script_step(void);

static int32_t open_as(const char *path, LONG mode)
{
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (!files[k]) {
            BPTR f = Open((CONST_STRPTR)path, mode);
            if (!f) {
                return -1;
            }
            files[k] = f;
            return k;
        }
    }
    return -1;
}

/* MODE_OLDFILE reads and writes an existing file. */
int32_t plat_open(const char *path, int32_t mode)
{
    (void)mode;
    return open_as(path, MODE_OLDFILE);
}

int32_t plat_create(const char *path)
{
    return open_as(path, MODE_NEWFILE);
}

int32_t plat_write(int32_t handle, const void *buffer, uint32_t length)
{
    if (!length) {
        return SetFileSize(files[handle], 0, OFFSET_CURRENT) < 0 ? -1 : 0;
    }
    return Write(files[handle], (APTR)buffer, (LONG)length);
}

int32_t plat_delete(const char *path)
{
    return DeleteFile((CONST_STRPTR)path) ? 0 : -1;
}

int32_t plat_read(int32_t handle, void *buffer, uint32_t length)
{
    return Read(files[handle], buffer, (LONG)length);
}

int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence)
{
    static const LONG mode[3] = {OFFSET_BEGINNING, OFFSET_CURRENT, OFFSET_END};
    if (whence < 0 || whence > 2 || Seek(files[handle], offset, mode[whence]) < 0) {
        return -1;
    }
    return Seek(files[handle], 0, OFFSET_CURRENT);  /* Seek returns the old position */
}

void plat_close(int32_t handle)
{
    Close(files[handle]);
    files[handle] = 0;
}

int32_t plat_dir_entry(const char *dir, uint32_t index, char *name, uint32_t *size)
{
    int32_t found = 0;
    BPTR lock = Lock((CONST_STRPTR)dir, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib)) {
        while (ExNext(lock, fib)) {
            int k = 0;
            while (fib->fib_FileName[k] && k <= 12) {
                ++k;
            }
            if (fib->fib_DirEntryType < 0 && k <= 12 && index-- == 0) {  /* longer: not 8.3 */
                for (k = 0; fib->fib_FileName[k]; ++k) {
                    name[k] = fib->fib_FileName[k];
                }
                name[k] = 0;
                *size = (uint32_t)fib->fib_Size;
                found = 1;
                break;
            }
        }
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    return found;
}

static void close_screen(void)
{
    if (amiga_screen) {
        CloseScreen(amiga_screen);
        amiga_screen = 0;
    }
}

/* Mode 13h on a 320x200 8-plane PAL screen, opened at the first present
 * or DAC change. */
static int screen(void)
{
    if (!amiga_screen && IntuitionBase && GfxBase) {
        amiga_screen = OpenScreenTags(0, SA_Width, FRAME_W, SA_Height, FRAME_H, SA_Depth, 8,
                                      SA_DisplayID, PAL_MONITOR_ID | LORES_KEY,
                                      SA_Type, CUSTOMSCREEN, SA_Quiet, TRUE,
                                      SA_ShowTitle, FALSE, SA_Draggable, FALSE,
                                      SA_Exclusive, TRUE, TAG_DONE);
        if (!amiga_screen) {
            plat_log("SWOTL no 8-plane screen");
        }
    }
    return amiga_screen != 0;
}

/* Kalms' c2p converts each changed rectangle into the shown bitmap: a
 * full-width band in one call, a narrower one row by row (the chunky rows
 * of a rectangle are not contiguous). */
void plat_present(const uint8_t *frame, const struct plat_rect *rects, int32_t n)
{
    if (!screen()) {
        return;
    }
    struct BitMap *bitmap = amiga_screen->RastPort.BitMap;
    for (int32_t k = 0; k < n; ++k) {
        const struct plat_rect *r = &rects[k];
        int32_t w = r->x1 - r->x0;
        if (w == FRAME_W) {
            c2p(frame + r->y0 * FRAME_W, w, r->y1 - r->y0, 0, r->y0, bitmap);
            continue;
        }
        for (int32_t y = r->y0; y < r->y1; ++y) {
            c2p(frame + y * FRAME_W + r->x0, w, 1, r->x0, y, bitmap);
        }
    }
}

/* The DAC's 6-bit guns widened to 32 bits for LoadRGB32. */
void plat_palette(const uint8_t *dac)
{
    if (!screen()) {
        return;
    }
    amiga_colours[0] = 256u << 16;
    for (int k = 0; k < 256 * 3; ++k) {
        amiga_colours[1 + k] = (dac[k] & 0x3f) * 0x04104104u;
    }
    amiga_colours[1 + 256 * 3] = 0;
    LoadRGB32(&amiga_screen->ViewPort, (ULONG *)amiga_colours);
}

void plat_service(void)
{
    key_script_step();
}

/* PIT channel 0 on a CIA-B timer (D8): one CIA period per PIT period, the
 * latch scaled from the PIT clock (1193182 Hz) to the PAL E-clock (709379 Hz,
 * 35469/59659 within 1e-5); the interrupt only posts vector 08h, the guest
 * handler runs at the next poll point. */
#define CIAB ((volatile struct CIA *)0xbfd000)
static struct Library *cia_base = 0;
static struct Interrupt cia_interrupt;
static WORD cia_bit = -1;

static ULONG cia_tick(void)
{
    rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = 8;
    ++rt_irq_tail;
    G_IRQ = 1;
    return 0;
}

static void cia_load(uint32_t divisor)
{
    uint32_t latch = (divisor * 35469u + 29829u) / 59659u;
    volatile UBYTE *cr = cia_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb;
    volatile UBYTE *lo = cia_bit == CIAICRB_TA ? &CIAB->ciatalo : &CIAB->ciatblo;
    volatile UBYTE *hi = cia_bit == CIAICRB_TA ? &CIAB->ciatahi : &CIAB->ciatbhi;
    *cr &= cia_bit == CIAICRB_TA ? 0xc0 : 0x80;    /* stop; keep TOD/serial bits */
    *lo = (UBYTE)latch;
    *hi = (UBYTE)(latch >> 8);
    *cr |= CIACRAF_LOAD | CIACRAF_START;          /* continuous */
}

static int timer_open(void)
{
    cia_base = (struct Library *)OpenResource((CONST_STRPTR)CIABNAME);
    if (!cia_base) {
        return 0;
    }
    cia_interrupt.is_Node.ln_Type = NT_INTERRUPT;
    cia_interrupt.is_Node.ln_Name = (char *)"SWOTL PIT";
    cia_interrupt.is_Code = (void (*)(void))cia_tick;
    for (WORD bit = CIAICRB_TA; bit <= CIAICRB_TB; ++bit) {
        if (!AddICRVector(cia_base, bit, &cia_interrupt)) {
            cia_bit = bit;
            cia_load(0x10000);
            return 1;
        }
    }
    return 0;
}

static void timer_close(void)
{
    if (cia_bit >= 0) {
        *(cia_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb) &= ~CIACRAF_START;
        RemICRVector(cia_base, cia_bit, &cia_interrupt);
        cia_bit = -1;
    }
}

void plat_timer_rate(uint32_t divisor)
{
    if (cia_bit >= 0) {
        Disable();
        cia_load(divisor);
        Enable();
    }
}

/* Each vertical blank: a published frame is due (D9); the runtime presents
 * its changed rows at the next poll point. */
static struct Interrupt vblank_interrupt;
static int vblank_added = 0;
volatile ULONG amiga_frames = 0;   /* vertical blanks since start (debug fixtures) */

static ULONG vblank_tick(void)
{
    ++amiga_frames;
    rt_present_due = 1;
    G_IRQ = 1;
    return 0;
}

static void vblank_open(void)
{
    vblank_interrupt.is_Node.ln_Type = NT_INTERRUPT;
    vblank_interrupt.is_Node.ln_Name = (char *)"SWOTL present";
    vblank_interrupt.is_Code = (void (*)(void))vblank_tick;
    AddIntServer(INTB_VERTB, &vblank_interrupt);
    vblank_added = 1;
}

static void vblank_close(void)
{
    if (vblank_added) {
        RemIntServer(INTB_VERTB, &vblank_interrupt);
        vblank_added = 0;
    }
}

/* Keyboard (input.c): an input.device handler ahead of Intuition turns raw
 * keys into PC set 1 scan codes (US positions; RT_KEY_E0 for the grey keys)
 * and posts them as 09h/89h; the events are swallowed. Caps Lock reports its
 * lock state, so both edges are a PC make and break (one toggle each). */
#define E0 RT_KEY_E0
static const uint16_t raw_to_scan[0x68] = {
    /* 00 */ 0x29, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x2b, 0, 0x52,
    /* 10 */ 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0, 0x4f, 0x50, 0x51,
    /* 20 */ 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0, 0, 0x4b, 0x4c, 0x4d,
    /* 30 */ 0, 0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0, 0x53, 0x47, 0x48, 0x49,
    /* 40 */ 0x39, 0x0e, 0x0f, E0 | 0x1c, 0x1c, 0x01, E0 | 0x53, 0, 0, 0, 0x4a, 0,
             E0 | 0x48, E0 | 0x50, E0 | 0x4d, E0 | 0x4b,
    /* 50 */ 0x3b, 0x3c, 0x3d, 0x3e, 0x3f, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, E0 | 0x35, 0x37, 0x4e, 0,
    /* 60 */ 0x2a, 0x36, 0x3a, 0x1d, 0x38, E0 | 0x38, 0, 0,
};
static struct MsgPort *input_port = 0;
static struct IOStdReq *input_io = 0;
static struct Interrupt input_interrupt;
static int input_added = 0;
void amiga_input_stub(void);

static void post_key(uint16_t ev)
{
    Disable();                      /* rt_irq_ring is shared with the CIA tick */
    rt_key_ring[rt_key_tail % RT_KEY_RING] = ev;
    ++rt_key_tail;
    rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = ev & 0x80 ? 0x89 : 0x09;
    ++rt_irq_tail;
    G_IRQ = 1;
    Enable();
}

/* Mouse counts and buttons since plat_mouse last took them (input.device task). */
static int32_t mouse_dx, mouse_dy;
static uint32_t mouse_buttons;
static ULONG mouse_reads;    /* plat_mouse calls: the guest's INT 33h requests */

static void mouse_event(const struct InputEvent *e)
{
    static const UBYTE bit[3] = {1, 2, 4};  /* IECODE_LBUTTON, RBUTTON, MBUTTON */
    UWORD code = e->ie_Code & ~IECODE_UP_PREFIX;
    if (e->ie_Qualifier & IEQUALIFIER_RELATIVEMOUSE) {
        mouse_dx += e->ie_X;
        mouse_dy += e->ie_Y;
    }
    if (code >= IECODE_LBUTTON && code <= IECODE_MBUTTON) {
        if (e->ie_Code & IECODE_UP_PREFIX) {
            mouse_buttons &= ~(uint32_t)bit[code - IECODE_LBUTTON];
        } else {
            mouse_buttons |= bit[code - IECODE_LBUTTON];
        }
    }
}

uint32_t plat_mouse(int32_t *dx, int32_t *dy)
{
    Disable();
    *dx = mouse_dx;
    *dy = mouse_dy;
    mouse_dx = mouse_dy = 0;
    uint32_t buttons = mouse_buttons;
    Enable();
    ++mouse_reads;
    return buttons;
}

struct InputEvent *amiga_input(struct InputEvent *events)
{
    for (struct InputEvent *e = events; e; e = e->ie_NextEvent) {
        if (e->ie_Class == IECLASS_RAWMOUSE) {
            mouse_event(e);
            e->ie_Class = IECLASS_NULL;
            continue;
        }
        if (e->ie_Class != IECLASS_RAWKEY) {
            continue;
        }
        UWORD raw = e->ie_Code & 0x7f, up = e->ie_Code & IECODE_UP_PREFIX;
        uint16_t scan = raw < sizeof raw_to_scan / sizeof raw_to_scan[0] ? raw_to_scan[raw] : 0;
        if (scan == 0x3a) {
            post_key(scan);
            post_key(scan | 0x80);
        } else if (scan) {
            post_key(up ? scan | 0x80 : scan);
        }
        e->ie_Class = IECLASS_NULL;
    }
    return events;
}

static void input_open(void)
{
    input_port = CreateMsgPort();
    input_io = input_port ? (struct IOStdReq *)CreateIORequest(input_port, sizeof(struct IOStdReq)) : 0;
    if (!input_io || OpenDevice((CONST_STRPTR)"input.device", 0, (struct IORequest *)input_io, 0)) {
        plat_log("SWOTL no input.device");
        if (input_io) {
            DeleteIORequest((struct IORequest *)input_io);
            input_io = 0;
        }
        return;
    }
    input_interrupt.is_Node.ln_Type = NT_INTERRUPT;
    input_interrupt.is_Node.ln_Pri = 100;
    input_interrupt.is_Node.ln_Name = (char *)"SWOTL input";
    input_interrupt.is_Code = amiga_input_stub;
    input_io->io_Command = IND_ADDHANDLER;
    input_io->io_Data = &input_interrupt;
    DoIO((struct IORequest *)input_io);
    input_added = 1;
}

static void input_close(void)
{
    if (input_added) {
        input_io->io_Command = IND_REMHANDLER;
        input_io->io_Data = &input_interrupt;
        DoIO((struct IORequest *)input_io);
        input_added = 0;
    }
    if (input_io) {
        CloseDevice((struct IORequest *)input_io);
        DeleteIORequest((struct IORequest *)input_io);
        input_io = 0;
    }
    if (input_port) {
        DeleteMsgPort(input_port);
        input_port = 0;
    }
}

/* Diagnostic key script (argument KEYS=when:key,...; when is a frame from
 * the start, or pN: N guest mouse reads after the previous step, which waits
 * for a screen that is polling rather than for a time the host load moves;
 * keys a-z 0-9 enter esc space or $hex raw codes, mouse buttons lmb rmb,
 * mouse motion mx+N mx-N my+N my-N counts; shot and quit call
 * amiga_script_mark for a debugger fixture): written into input.device
 * from the main task at each present, so it takes the handler path above;
 * a key is released 5 frames after it is pressed, a button once the guest
 * has also read the mouse twice (buttons are polled levels, keys reach the
 * BIOS buffer). */
static const char *key_script = 0;
static ULONG key_up_frame = 0;
static ULONG key_up_reads = 0;
static ULONG step_reads = 0;    /* mouse_reads at the previous step */
static UWORD key_up_code = 0;
static UBYTE key_up_class = 0;

void __attribute__((noinline)) amiga_script_mark(int quit)
{
    __asm__ volatile("" : : "r"(quit) : "memory");
}

static void write_event(UBYTE class, UWORD code, WORD x, WORD y)
{
    struct InputEvent e = {0};
    e.ie_Class = class;
    e.ie_Code = code;
    e.ie_Qualifier = class == IECLASS_RAWMOUSE ? IEQUALIFIER_RELATIVEMOUSE : 0;
    e.ie_X = x;
    e.ie_Y = y;
    input_io->io_Command = IND_WRITEEVENT;
    input_io->io_Data = &e;
    input_io->io_Length = sizeof e;
    DoIO((struct IORequest *)input_io);
}

static int named(const char *name, int n, const char *word)
{
    int k = 0;
    while (k < n && word[k] == name[k]) {
        ++k;
    }
    return k == n && !word[k];
}

static int raw_of(const char *name, int n)
{
    static const char rows[4][11] = {"1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"};
    static const UBYTE base[4] = {0x01, 0x10, 0x20, 0x31};
    if (n == 1) {
        for (int r = 0; r < 4; ++r) {
            for (int k = 0; rows[r][k]; ++k) {
                if (rows[r][k] == name[0]) {
                    return base[r] + k;
                }
            }
        }
    }
    if (named(name, n, "enter")) return 0x44;
    if (named(name, n, "esc")) return 0x45;
    if (named(name, n, "space")) return 0x40;
    if (n == 3 && name[0] == '$') {
        int v = 0;
        for (int k = 1; k < 3; ++k) {
            char c = name[k];
            v = v * 16 + (c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10);
        }
        return v;
    }
    return -1;
}

static void key_script_step(void)
{
    if (!input_added) {
        return;
    }
    if (key_up_code && amiga_frames >= key_up_frame && mouse_reads >= key_up_reads) {
        write_event(key_up_class, key_up_code | IECODE_UP_PREFIX, 0, 0);
        key_up_code = 0;
    }
    if (!key_script || *key_script <= ' ' || key_up_code) {
        return;
    }
    ULONG when = 0;
    const char *p = key_script;
    int reads = *p == 'p';
    p += reads;
    while (*p >= '0' && *p <= '9') {
        when = when * 10 + (ULONG)(*p++ - '0');
    }
    if (reads ? mouse_reads - step_reads < when : amiga_frames < when) {
        return;
    }
    step_reads = mouse_reads;
    const char *name = *p == ':' ? ++p : p;
    while (*p > ' ' && *p != ',') {
        ++p;
    }
    int n = (int)(p - name);
    key_script = *p == ',' ? p + 1 : p;
    if (n > 3 && name[0] == 'm' && (name[1] == 'x' || name[1] == 'y') &&
        (name[2] == '+' || name[2] == '-')) {
        WORD v = 0;
        for (int k = 3; k < n; ++k) {
            v = (WORD)(v * 10 + name[k] - '0');
        }
        v = name[2] == '-' ? (WORD)-v : v;
        write_event(IECLASS_RAWMOUSE, IECODE_NOBUTTON, name[1] == 'x' ? v : 0, name[1] == 'y' ? v : 0);
        return;
    }
    if (named(name, n, "shot") || named(name, n, "quit")) {
        amiga_script_mark(name[0] == 'q');
        return;
    }
    UBYTE class = IECLASS_RAWKEY;
    int raw = raw_of(name, n);
    if (named(name, n, "lmb") || named(name, n, "rmb")) {
        class = IECLASS_RAWMOUSE;
        raw = name[0] == 'l' ? IECODE_LBUTTON : IECODE_RBUTTON;
    }
    if (raw < 0) {
        plat_log("SWOTL KEYS: unknown key");
        return;
    }
    write_event(class, (UWORD)raw, 0, 0);
    key_up_code = (UWORD)raw;
    key_up_class = class;
    key_up_frame = amiga_frames + 5;
    key_up_reads = mouse_reads + (class == IECLASS_RAWMOUSE ? 2 : 0);
}

void plat_log(const char *line)
{
    LONG n = 0;
    while (line[n]) {
        ++n;
    }
    BPTR out = Output();
    if (out) {
        Write(out, (APTR)line, n);
        Write(out, (APTR)"\n", 1);
    }
}

long amiga_run_guest(void)
{
    DOSBase = (struct DosLibrary *)OpenLibrary((CONST_STRPTR)"dos.library", 39);
    if (!DOSBase) {
        return -1;
    }
    for (const char *a = (const char *)GetArgStr(); a && *a; ++a) {
        if (a[0] == 'K' && a[1] == 'E' && a[2] == 'Y' && a[3] == 'S' && a[4] == '=') {
            key_script = a + 5;     /* ends at a space or the line end */
        }
    }
    IntuitionBase = (struct IntuitionBase *)OpenLibrary((CONST_STRPTR)"intuition.library", 40);
    GfxBase = (struct GfxBase *)OpenLibrary((CONST_STRPTR)"graphics.library", 40);
    /* Guest RAM, the state block below it and the EMS store after it; Fast RAM
     * when present (D15). */
    uint8_t *block = (uint8_t *)AllocMem(RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES, MEMF_ANY | MEMF_CLEAR);
    uint8_t *stack = (uint8_t *)AllocMem(GUEST_STACK_BYTES, MEMF_ANY);
    int32_t code = -1;
    if (block && stack) {
        plat_log("SWOTL guest start");
        rt_start(block + RT_STATE_BYTES);
        if (!timer_open()) {
            plat_log("SWOTL no CIA-B timer");
        }
        vblank_open();
        input_open();
        code = amiga_guest_call(stack + GUEST_STACK_BYTES);
    }
    input_close();
    timer_close();
    vblank_close();
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (files[k]) {
            plat_close(k);
        }
    }
    if (stack) {
        FreeMem(stack, GUEST_STACK_BYTES);
    }
    if (block) {
        FreeMem(block, RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES);
    }
    close_screen();
    if (IntuitionBase) {
        CloseLibrary((struct Library *)IntuitionBase);
    }
    if (GfxBase) {
        CloseLibrary((struct Library *)GfxBase);
        GfxBase = 0;
    }
    CloseLibrary((struct Library *)DOSBase);
    return code;
}
