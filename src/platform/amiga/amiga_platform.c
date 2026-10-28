/* Platform services for the runtime on AmigaOS: the game's files through
 * dos.library (each call in an I/O window of the takeover, Swotl.cpp), the
 * PIT on a CIA-B timer (none in the frame bench, argument BENCH), the
 * diagnostic key script, the music skip (off; argument MUSIC keeps it off), and the
 * run of the translated program on its own native stack. Game files are read from the current directory (the game's
 * own data files, supplied by the user; from Workbench, the icon's drawer). */
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/cia.h>
#include <proto/icon.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include <workbench/startup.h>
#include <hardware/cia.h>
#include <hardware/intbits.h>
#include <resources/cia.h>
#include "runtime.h"
#include "platform.h"
#include "amiga_platform.h"
#include "FileDate.h"
#ifdef SWOTL_REPLAY
#include "replay_clocks.h"
#endif

struct DosLibrary *DOSBase = 0;
struct Library *IconBase = 0;

#define MAX_FILES 16
#define GUEST_STACK_BYTES 0x10000

static BPTR files[MAX_FILES];
static uint8_t file_stamped[MAX_FILES], file_modified[MAX_FILES];
static struct DateStamp file_stamps[MAX_FILES];

int32_t amiga_guest_call(void *stack_top);
static void key_script_step(void);
static uint8_t *guest_block = 0;
static uint8_t *guest_stack = 0;

void *plat_alloc(uint32_t bytes)
{
    amiga_io_begin();
    void *p = AllocVec(bytes, MEMF_ANY);
    amiga_io_end();
    return p;
}

void plat_free(void *p)
{
    amiga_io_begin();
    FreeVec(p);
    amiga_io_end();
}

static int32_t open_as(const char *path, LONG mode)
{
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (!files[k]) {
            BPTR f = Open((CONST_STRPTR)path, mode);
            if (!f) {
                return -1;
            }
            /* DOS permits another open (including an attribute query) while
             * a created file is live. MODE_NEWFILE starts exclusive on Amiga. */
            if (mode == MODE_NEWFILE && !ChangeMode(CHANGE_FH, f, SHARED_LOCK)) {
                Close(f);
                return -1;
            }
            files[k] = f;
            file_stamped[k] = 0;
            file_modified[k] = mode == MODE_NEWFILE;
            return k;
        }
    }
    return -1;
}

/* MODE_OLDFILE reads and writes an existing file. */
int32_t plat_open(const char *path, int32_t mode)
{
    (void)mode;
    amiga_io_begin();
    int32_t handle = open_as(path, MODE_OLDFILE);
    amiga_io_end();
    return handle;
}

int32_t plat_create(const char *path)
{
    amiga_io_begin();
    int32_t handle = open_as(path, MODE_NEWFILE);
    amiga_io_end();
    return handle;
}

int32_t plat_write(int32_t handle, const void *buffer, uint32_t length)
{
    amiga_io_begin();
    int32_t n = length ? Write(files[handle], (APTR)buffer, (LONG)length)
                       : SetFileSize(files[handle], 0, OFFSET_CURRENT) < 0 ? -1 : 0;
    if (n >= 0) file_modified[handle] = 1;
    amiga_io_end();
    return n;
}

int32_t plat_delete(const char *path)
{
    amiga_io_begin();
    int32_t result = DeleteFile((CONST_STRPTR)path) ? 0 : -1;
    amiga_io_end();
    return result;
}

int32_t plat_read(int32_t handle, void *buffer, uint32_t length)
{
    amiga_io_begin();
    int32_t n = Read(files[handle], buffer, (LONG)length);
    amiga_io_end();
    return n;
}

int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence)
{
    static const LONG mode[3] = {OFFSET_BEGINNING, OFFSET_CURRENT, OFFSET_END};
    int32_t position = -1;
    amiga_io_begin();
    if (whence >= 0 && whence <= 2 && Seek(files[handle], offset, mode[whence]) >= 0) {
        position = Seek(files[handle], 0, OFFSET_CURRENT);  /* Seek returns the old position */
    }
    amiga_io_end();
    return position;
}

uint32_t plat_calendar_date(void)
{
#ifdef SWOTL_REPLAY
    if (REPLAY_CALENDAR_DATE) return REPLAY_CALENDAR_DATE;
#endif
    struct DateStamp stamp;
    uint16_t time, date;
    amiga_io_begin();
    DateStamp(&stamp);
    amiga_io_end();
    amiga_file_date(stamp.ds_Days, stamp.ds_Minute, stamp.ds_Tick, &time, &date);
    return (uint32_t)(1980 + (date >> 9)) << 16 |
           (uint32_t)((date >> 5) & 15) << 8 | (date & 31);
}

void plat_file_stamp(int32_t handle, uint32_t time, uint32_t date)
{
    amiga_date_stamp((uint16_t)time, (uint16_t)date,
                     &file_stamps[handle].ds_Days, &file_stamps[handle].ds_Minute,
                     &file_stamps[handle].ds_Tick);
    file_stamped[handle] = 1;
}

void plat_close(int32_t handle)
{
#ifdef SWOTL_REPLAY
    if (REPLAY_FILE_DATE && file_modified[handle] && !file_stamped[handle])
        plat_file_stamp(handle, REPLAY_FILE_TIME, REPLAY_FILE_DATE);
#endif
    char path[512];
    amiga_io_begin();
    /* Resolve before closing; apply after Close so its filesystem stamp cannot
     * overwrite the DOS timestamp. NameFromFH also survives a changed cwd. */
    int named = !file_stamped[handle] || NameFromFH(files[handle], (STRPTR)path, sizeof path);
    int closed = Close(files[handle]);
    int stamped = !file_stamped[handle] ||
                  (named && closed && SetFileDate((CONST_STRPTR)path, &file_stamps[handle]));
    amiga_io_end();
    files[handle] = 0;
    if (!stamped) rt_stop("cannot set file timestamp", handle, 0);
}

int32_t plat_dir_names(const char *dir, char *buffer, uint32_t size)
{
    int32_t bytes = 0;
    amiga_io_begin();
    BPTR lock = Lock((CONST_STRPTR)dir, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib)) {
        while (ExNext(lock, fib)) {
            int k = 0;
            while (fib->fib_FileName[k] && k <= 12) {
                ++k;
            }
            if (fib->fib_DirEntryType >= 0 || k > 12) {  /* longer: not 8.3 */
                continue;
            }
            if ((uint32_t)bytes + k + 1 <= size) {
                for (int c = 0; c <= k; ++c) {
                    buffer[bytes + c] = fib->fib_FileName[c];
                }
            }
            bytes += k + 1;
        }
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    amiga_io_end();
    return bytes;
}

int32_t plat_file_info(const char *path, struct plat_file_info *info)
{
    int32_t found = -1;
    amiga_io_begin();
    BPTR lock = Lock((CONST_STRPTR)path, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib) && fib->fib_DirEntryType < 0) {
        info->size = (uint32_t)fib->fib_Size;
        amiga_file_date(fib->fib_Date.ds_Days, fib->fib_Date.ds_Minute,
                        fib->fib_Date.ds_Tick, &info->dos_time, &info->dos_date);
        found = 0;
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    amiga_io_end();
    return found;
}

/* PIT channel 0 on a CIA-B timer (D8): one CIA period per PIT period, the
 * latch scaled from the PIT clock (1193182 Hz) to the PAL E-clock (709379 Hz,
 * 35469/59659 within 1e-5). The interrupt runs the guest handler at once when
 * the runtime allows it (docs/irq-plan.md I6), with EXTER acknowledged and
 * the mask lowered to 2 so the vertical blank preempts a long tick (a nested
 * tick is posted); else it posts vector 08h for the next poll point. Replay
 * builds post only (deliveries at the recorded polls). */
#define CIAB ((volatile struct CIA *)0xbfd000)
static struct Library *cia_base = 0;
static struct Interrupt cia_interrupt;
static WORD cia_bit = -1;

/* CIA ticks, and of them those run at once (fixtures: amiga/display_audit.gdb). */
volatile ULONG amiga_ticks = 0, amiga_ticks_async = 0;

static ULONG cia_tick(void)
{
    ++amiga_ticks;
#ifndef SWOTL_SYNC
    /* Production has no poll checks (docs/irq-plan.md I8): ticks posted while
     * IRQ0 could not run go first, then this one. */
    int current = rt_irq0_ready();  /* else this tick waits behind posted ones */
    if (current || rt_irq0_take()) {
        UWORD sr;
        *(volatile UWORD *)0xdff09c = INTF_EXTER;
        __asm__ volatile("move.w %%sr,%0" : "=d"(sr) : : "memory");
        __asm__ volatile("move.w %0,%%sr" : : "d"((UWORD)((sr & ~0x0700) | 0x0200)) : "memory");
        for (;;) {
            rt_irq0_running = 1;
            ++amiga_ticks_async;
            rt_irq_interrupt();
            if (rt_irq0_take()) {
                continue;
            }
            if (!current && rt_irq0_ready()) {
                current = 1;
                continue;
            }
            break;
        }
        __asm__ volatile("move.w %0,%%sr" : : "d"(sr) : "memory");
        if (current) {
            return 0;
        }
    }
#endif
    rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = 8;
    ++rt_irq_tail;
    RT_RAISE_IRQ();
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

/* Diagnostic key script (argument KEYS=when:key,...; when is a frame from
 * the start, or pN: N guest mouse reads after the previous step, which waits
 * for a screen that is polling rather than for a time the host load moves;
 * keys a-z 0-9 enter esc space or $hex raw codes, mouse buttons lmb rmb,
 * mouse motion mx+N mx-N my+N my-N counts; shot and quit call
 * amiga_script_mark for a debugger fixture; unknown names are logged at the
 * start and skipped): fed from the field task at each vertical blank into
 * the keyboard and mouse paths of Input.cpp; a key
 * is released 5 frames after it is pressed, a button once the guest has
 * also read the mouse twice (buttons are polled levels, keys reach the BIOS
 * buffer). */
#define SCRIPT_LMB 0x100
#define SCRIPT_RMB 0x101
static const char *key_script = 0;
static ULONG key_up_frame = 0;
static ULONG key_up_reads = 0;
static ULONG step_reads = 0;    /* amiga_mouse_reads at the previous step */
static int key_up = -1;         /* the held raw key or SCRIPT_LMB/RMB */

void __attribute__((noinline)) amiga_script_mark(int quit)
{
    __asm__ volatile("" : : "r"(quit) : "memory");
}

static void script_event(int code, int up)
{
    if (code == SCRIPT_LMB || code == SCRIPT_RMB) {
        amiga_mouse_script_buttons(up ? 0 : code == SCRIPT_LMB ? 1 : 2);
    } else {
        amiga_key(code, up);
    }
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
    if (named(name, n, "lmb")) return SCRIPT_LMB;
    if (named(name, n, "rmb")) return SCRIPT_RMB;
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

static int motion(const char *name, int n)
{
    return n > 3 && name[0] == 'm' && (name[1] == 'x' || name[1] == 'y') &&
           (name[2] == '+' || name[2] == '-');
}

static int known(const char *name, int n)
{
    return motion(name, n) || named(name, n, "shot") || named(name, n, "quit") ||
           raw_of(name, n) >= 0;
}

/* At the start (main program): the field task cannot log. */
static void key_script_check(void)
{
    for (const char *p = key_script; p && *p > ' ';) {
        while (*p > ' ' && *p != ',' && *p != ':') {
            ++p;
        }
        const char *name = *p == ':' ? ++p : p;
        while (*p > ' ' && *p != ',') {
            ++p;
        }
        if (!known(name, (int)(p - name))) {
            plat_log("SWOTL KEYS: unknown key");
        }
        p += *p == ',';
    }
}

static void key_script_step(void)
{
    if (key_up >= 0 && amiga_frames >= key_up_frame && amiga_mouse_reads >= key_up_reads) {
        script_event(key_up, 1);
        key_up = -1;
    }
    if (!key_script || *key_script <= ' ' || key_up >= 0) {
        return;
    }
    ULONG when = 0;
    const char *p = key_script;
    int reads = *p == 'p';
    p += reads;
    while (*p >= '0' && *p <= '9') {
        when = when * 10 + (ULONG)(*p++ - '0');
    }
    if (reads ? amiga_mouse_reads - step_reads < when : amiga_frames < when) {
        return;
    }
    step_reads = amiga_mouse_reads;
    const char *name = *p == ':' ? ++p : p;
    while (*p > ' ' && *p != ',') {
        ++p;
    }
    int n = (int)(p - name);
    key_script = *p == ',' ? p + 1 : p;
    if (motion(name, n)) {
        WORD v = 0;
        for (int k = 3; k < n; ++k) {
            v = (WORD)(v * 10 + name[k] - '0');
        }
        v = name[2] == '-' ? (WORD)-v : v;
        amiga_mouse_move(name[1] == 'x' ? v : 0, name[1] == 'y' ? v : 0);
        return;
    }
    if (named(name, n, "shot") || named(name, n, "quit")) {
        amiga_script_mark(name[0] == 'q');
        return;
    }
    int code = raw_of(name, n);
    if (code < 0) {
        return;
    }
    script_event(code, 0);
    key_up = code;
    key_up_frame = amiga_frames + 5;
    key_up_reads = amiga_mouse_reads + (code >= SCRIPT_LMB ? 2 : 0);
}

void plat_service(void)
{
    key_script_step();
    amiga_audio_service();
}

void plat_log(const char *line)
{
    LONG n = 0;
    while (line[n]) {
        ++n;
    }
    amiga_io_begin();
    BPTR out = Output();
    if (out) {
        Write(out, (APTR)line, n);
        Write(out, (APTR)"\n", 1);
    }
    amiga_io_end();
}

/* Before takeover: the optional sample file is read into temporary public
 * memory; Audio owns only the parsed Chip samples after this returns. */
extern int amiga_audio_tfh(const uint8_t *rsc, uint32_t size);
static void load_tfh(void)
{
    BPTR f = Open((CONST_STRPTR)"sfx.rsc", MODE_OLDFILE);
    int ok = 0;
    if (f) {
        LONG size;
        Seek(f, 0, OFFSET_END);
        size = Seek(f, 0, OFFSET_BEGINNING);
        if (size > 0) {
            uint8_t *rsc = AllocMem((ULONG)size, MEMF_ANY);
            if (rsc) {
                if (Read(f, rsc, size) == size) ok = amiga_audio_tfh(rsc, (uint32_t)size);
                FreeMem(rsc, (ULONG)size);
            }
        }
        Close(f);
    }
    plat_log(ok ? "SWOTL sound TFH" : "SWOTL TFH unavailable; sound FM");
}

/* Workbench start (L84): the icon's drawer becomes the current directory
 * (a Shell's is its own) and the icon's tool types are the arguments, the
 * same keywords; KEYS= is copied, the icon is freed before the run. */
static BPTR wb_old_dir = 0;
static char *wb_keys = 0;
static ULONG wb_keys_bytes = 0;

static int wb_options(int *tfh)
{
    struct WBArg *tool = amiga_wb_startup->sm_ArgList;
    wb_old_dir = CurrentDir(tool->wa_Lock);
    IconBase = OpenLibrary((CONST_STRPTR)"icon.library", 37);
    if (!IconBase) {
        return 1;
    }
    struct DiskObject *icon = GetDiskObject((STRPTR)tool->wa_Name);
    int ok = 1;
    if (icon) {
        STRPTR *types = (STRPTR *)icon->do_ToolTypes;
        *tfh = FindToolType(types, (STRPTR)"TFH") != 0;
        if (FindToolType(types, (STRPTR)"BENCH")) rt_bench = 1;
        if (FindToolType(types, (STRPTR)"MUSIC")) rt_music_skip = 0;
        const char *keys = (const char *)FindToolType(types, (STRPTR)"KEYS");
        if (keys) {
            ULONG n = 0;
            while (keys[n]) {
                ++n;
            }
            wb_keys_bytes = n + 1;
            wb_keys = (char *)AllocMem(wb_keys_bytes, MEMF_ANY);
            if (wb_keys) {
                for (ULONG k = 0; k < wb_keys_bytes; ++k) {
                    wb_keys[k] = keys[k];
                }
                key_script = wb_keys;
            } else {
                plat_log("SWOTL not enough memory");
                ok = 0;
            }
        }
        FreeDiskObject(icon);
    }
    CloseLibrary(IconBase);
    IconBase = 0;
    return ok;
}

/* Shell start: ReadArgs, so the keywords are case-insensitive, `?` prompts
 * with the template and a bad line fails with the DOS error. ReadArgs reads
 * the line from Input()'s buffer, where the Shell and the WHDLoad slave's
 * RunCommand put it. KEYS points into the RDArgs until the close. */
static struct RDArgs *shell_args = 0;

static int shell_options(int *tfh)
{
    enum { ARG_TFH, ARG_MUSIC, ARG_BENCH, ARG_KEYS, ARG_COUNT };
    LONG values[ARG_COUNT] = {0, 0, 0, 0};
    shell_args = ReadArgs((CONST_STRPTR)"TFH/S,MUSIC/S,BENCH/S,KEYS/K", values, 0);
    if (!shell_args) {
        amiga_io_begin();
        PrintFault(IoErr(), (CONST_STRPTR)"Swotl");
        amiga_io_end();
        return 0;
    }
    *tfh = values[ARG_TFH] != 0;
    if (values[ARG_MUSIC]) rt_music_skip = 0;   /* diagnostic: music records start their songs */
    if (values[ARG_BENCH]) rt_bench = 1;        /* frame bench: ticks from guest progress, no CIA timer */
    if (values[ARG_KEYS]) key_script = (const char *)values[ARG_KEYS];
    return 1;
}

int amiga_guest_open(void)
{
    DOSBase = (struct DosLibrary *)OpenLibrary((CONST_STRPTR)"dos.library", 39);
    if (!DOSBase) {
        return 0;
    }
    int tfh = 0;
    if (amiga_wb_startup && !wb_options(&tfh)) {
        return 0;
    }
    if (!amiga_wb_startup && !shell_options(&tfh)) {
        return 0;
    }
    key_script_check();
#ifndef SWOTL_SYNC
    if (rt_bench) {         /* production takes no tick at a poll point (irq-plan I8) */
        plat_log("SWOTL frame bench needs the sync image (make amiga-sync)");
        return 0;
    }
#endif
    if (tfh) load_tfh();
    else plat_log("SWOTL sound FM");
    /* Guest RAM, the state block below it and the EMS store after it; Fast RAM
     * when present (D15). */
    guest_block = (uint8_t *)AllocMem(RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES, MEMF_ANY | MEMF_CLEAR);
    guest_stack = (uint8_t *)AllocMem(GUEST_STACK_BYTES, MEMF_ANY);
    if (!guest_block || !guest_stack) {
        plat_log("SWOTL not enough memory");
        return 0;
    }
    plat_log("SWOTL guest start");
    rt_start(guest_block);
#ifdef SWOTL_REPLAY
    (void)timer_open;
    plat_log("SWOTL diagnostic reference replay");
#else
    if (rt_bench) {
        plat_log("SWOTL frame bench");
    } else if (!timer_open()) {
        plat_log("SWOTL no CIA-B timer");
    }
#endif
    return 1;
}

long amiga_guest_run(void)
{
    return amiga_guest_call(guest_stack + GUEST_STACK_BYTES);
}

void amiga_guest_close(void)
{
    timer_close();
    rt_dos_close();
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (files[k]) {
            plat_close(k);
        }
    }
    if (guest_stack) {
        FreeMem(guest_stack, GUEST_STACK_BYTES);
        guest_stack = 0;
    }
    if (guest_block) {
        FreeMem(guest_block, RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES);
        guest_block = 0;
    }
    if (wb_keys) {
        FreeMem(wb_keys, wb_keys_bytes);
        wb_keys = 0;
    }
    if (shell_args) {
        FreeArgs(shell_args);
        shell_args = 0;
    }
    if (DOSBase && amiga_wb_startup) {
        CurrentDir(wb_old_dir);
    }
    if (DOSBase) {
        CloseLibrary((struct Library *)DOSBase);
        DOSBase = 0;
    }
}
