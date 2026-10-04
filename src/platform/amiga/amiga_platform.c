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
 * height, d2/d3 screen offset, a0 chunky, a1 BitMap; saves d2-d7/a2-a6. */
static void c2p(const void *chunky, struct BitMap *bitmap)
{
    register int32_t d0 __asm("d0") = FRAME_W;
    register int32_t d1 __asm("d1") = FRAME_H;
    register int32_t d2 __asm("d2") = 0;
    register int32_t d3 __asm("d3") = 0;
    register const void *a0 __asm("a0") = chunky;
    register struct BitMap *a1 __asm("a1") = bitmap;
    __asm volatile("jsr c2p1x1_8_c5_bm" : "+r"(d0), "+r"(d1), "+r"(a0), "+r"(a1)
                   : "r"(d2), "r"(d3) : "cc", "memory");
}

int32_t amiga_guest_call(void *stack_top);

int32_t plat_open(const char *path)
{
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (!files[k]) {
            BPTR f = Open((CONST_STRPTR)path, MODE_OLDFILE);
            if (!f) {
                return -1;
            }
            files[k] = f;
            return k;
        }
    }
    return -1;
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

/* Mode 13h on a 320x200 8-plane PAL screen: Kalms' c2p converts the chunky
 * frame, the DAC's 6-bit guns are widened to 32 bits for LoadRGB32. */
void plat_present(const uint8_t *frame, const uint8_t *dac)
{
    if (!amiga_screen) {
        if (!IntuitionBase || !GfxBase) {
            return;
        }
        amiga_screen = OpenScreenTags(0, SA_Width, FRAME_W, SA_Height, FRAME_H, SA_Depth, 8,
                                      SA_DisplayID, PAL_MONITOR_ID | LORES_KEY,
                                      SA_Type, CUSTOMSCREEN, SA_Quiet, TRUE,
                                      SA_ShowTitle, FALSE, SA_Draggable, FALSE,
                                      SA_Exclusive, TRUE, TAG_DONE);
        if (!amiga_screen) {
            plat_log("SWOTL no 8-plane screen");
            return;
        }
    }
    amiga_colours[0] = 256u << 16;
    for (int k = 0; k < 256 * 3; ++k) {
        amiga_colours[1 + k] = (dac[k] & 0x3f) * 0x04104104u;
    }
    amiga_colours[1 + 256 * 3] = 0;
    c2p(frame, amiga_screen->RastPort.BitMap);
    LoadRGB32(&amiga_screen->ViewPort, (ULONG *)amiga_colours);
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

/* Periodic present (14a): every PRESENT_FRAMES vertical blanks the frame is
 * due again; the runtime shows it at the next poll point. */
#define PRESENT_FRAMES 5
static struct Interrupt vblank_interrupt;
static int vblank_added = 0;
static UWORD vblank_count = 0;
volatile ULONG amiga_frames = 0;   /* vertical blanks since start (debug fixtures) */

static ULONG vblank_tick(void)
{
    ++amiga_frames;
    if (++vblank_count >= PRESENT_FRAMES) {
        vblank_count = 0;
        rt_present_due = 1;
        G_IRQ = 1;
    }
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
        code = amiga_guest_call(stack + GUEST_STACK_BYTES);
    }
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
