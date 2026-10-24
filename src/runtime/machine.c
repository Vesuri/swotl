/* Machine model: the guest memory and CPU state the reference machine
 * (DOSBox-X, reference/dosbox-x.conf) presents at the SWOTL.EXE entry, the
 * EXEC of SWOTL.EXE, interrupt/fault delivery and the dispatch lookup. Values
 * marked "reference" are DOSBox-X's and are checked by tests/host_run.py
 * against the m0/m1 snapshots and the service log. */
#include "runtime.h"
#include "platform.h"

struct rt_regs rt_r;
uint8_t *rt_guest;
uint16_t rt_entry_cs, rt_entry_ip;
uint16_t rt_deliver_cs, rt_deliver_ip;
void *rt_deliver_code;      /* the handler's translated entry (rt_lookup, far) */

/* Command tail of the reference launch (tools/pc_run.py LAUNCH). */
static const char command_tail[] = " V S 5 N Y Y 64";
/* Environment of the reference shell, then the program path. */
static const char environment[] =
    "PATH=Z:\\;Z:\\SYSTEM;Z:\\BIN;Z:\\DOS;Z:\\4DOS;Z:\\DEBUG;Z:\\TEXTUTIL;Z:\\PATCHING\0"
    "COMSPEC=Z:\\COMMAND.COM\0"
    "PROMPT=$P$G\0"
    "\0\1\0C:\\SWOTL.EXE\0NT.COM";  /* reference: residue of the shell's own path */

#define ENV_PARAS 0x47
#define TOP_SEG 0x9fff          /* reference: first segment past DOS memory */
#define PARENT_PSP 0x0701       /* reference: COMMAND.COM */

/* Reference interrupt vectors the game reads (INT 21h AH=35h) or chains to. */
#define MOUSE_INT74_SEG 0xf000
#define MOUSE_INT74_OFF 0xd020

static const struct { uint8_t vector; uint16_t seg, off; } vectors[] = {
    {0x00, 0xf000, 0xca60}, {0x05, 0xf000, 0xff54}, {0x08, 0xf000, 0xfea5},
    {0x09, 0xf000, 0xe987}, {0x10, 0xc000, 0x00ee}, {0x16, 0xf000, 0xcfc0},
    {0x1c, 0xf000, 0xcc00}, {0x21, 0xf000, 0xd100}, {0x22, 0xf000, 0xdac8},
    {0x23, 0x0701, 0x0128}, {0x24, 0x0701, 0x0110}, {0x32, 0xf000, 0xca60}, {0x33, 0xc402, 0x0010},
    {0x67, 0xc401, 0x0004}, {0x74, MOUSE_INT74_SEG, MOUSE_INT74_OFF},
};

static void put_bytes(uint32_t a, const void *src, uint32_t n)
{
    const uint8_t *s = src;
    while (n--) {
        wr8(a++, *s++);
    }
}

static void mcb(uint16_t seg, char type, uint16_t owner, uint16_t paras, const char *name)
{
    uint32_t a = lin(seg, 0);
    wr8(a, (uint8_t)type);
    wr16(a + 1, owner);
    wr16(a + 3, paras);
    put_bytes(a + 8, name, 8);
}

/* DOS 5 PSP as DOSBox-X builds it for EXEC from the shell. */
static void psp(uint16_t seg)
{
    static const uint8_t jft[20] = {1, 1, 1, 0, 2, 0xff, 0xff, 0xff, 0xff, 0xff,
                                    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
    uint32_t p = lin(seg, 0);
    wr16(p + 0x00, 0x20cd);                   /* INT 20h */
    wr16(p + 0x02, TOP_SEG);
    put_bytes(p + 0x05, "\x9a\xf0\xfe\x1d\xf0", 5);  /* reference CP/M far call */
    wr16(p + 0x0a, 0xdac8); wr16(p + 0x0c, 0xf000);  /* INT 22h */
    wr16(p + 0x0e, 0x0128); wr16(p + 0x10, PARENT_PSP);  /* INT 23h */
    wr16(p + 0x12, 0x0110); wr16(p + 0x14, PARENT_PSP);  /* INT 24h */
    wr16(p + 0x16, PARENT_PSP);
    put_bytes(p + 0x18, jft, sizeof jft);
    wr16(p + 0x2c, RT_ENV_SEG);
    wr16(p + 0x2e, 0x05e6); wr16(p + 0x30, 0x071b);  /* reference: shell SS:SP */
    wr16(p + 0x32, 20);
    wr16(p + 0x34, 0x18); wr16(p + 0x36, seg);
    wr16(p + 0x38, 0xffff); wr16(p + 0x3a, 0xffff);
    wr16(p + 0x40, 0x0005);                   /* DOS version 5.0 */
    put_bytes(p + 0x50, "\xcd\x21\xcb", 3);
    /* FCBs 1 and 2 from the first two arguments ("V", "S") */
    for (int f = 0; f < 2; ++f) {
        uint32_t fcb = p + 0x5c + 0x10 * f;
        for (int k = 1; k < 12; ++k) {
            wr8(fcb + k, ' ');
        }
        wr8(fcb + 1, (uint8_t)command_tail[1 + 2 * f]);
    }
    wr8(p + 0x80, sizeof command_tail - 1);
    put_bytes(p + 0x81, command_tail, sizeof command_tail - 1);
    wr8(p + 0x81 + sizeof command_tail - 1, '\r');
}

static void fail_read(int32_t got, int32_t want)
{
    if (got != want) {
        rt_stop("SWOTL.EXE short read", (uint32_t)got, (uint32_t)want);
    }
}

/* EXEC SWOTL.EXE at PSP + 10h (the reference load segment). */
static void exec_root(uint16_t psp_seg)
{
    uint8_t h[0x1c];
    uint16_t load = psp_seg + 0x10;
    int32_t f = plat_open("SWOTL.EXE", 0);
    if (f < 0) {
        rt_stop("SWOTL.EXE not found", 0, 0);
    }
    fail_read(plat_read(f, h, sizeof h), sizeof h);
#define HW(o) ((uint16_t)(h[o] | h[(o) + 1] << 8))
    if (HW(0) != 0x5a4d) {
        rt_stop("SWOTL.EXE is not MZ", HW(0), 0);
    }
    uint32_t size = HW(4) * 512u - (HW(2) ? 512u - HW(2) : 0) - HW(8) * 16u;
    plat_seek(f, HW(8) * 16, 0);
    uint8_t *image = rt_span_w(lin(load, 0), size);
    fail_read(plat_read(f, image, size), (int32_t)size);
    rt_span_order(image, size);
    plat_seek(f, HW(0x18), 0);
    for (uint16_t k = 0; k < HW(6); ++k) {
        uint8_t r[4];
        fail_read(plat_read(f, r, 4), 4);
        uint32_t a = lin(load + (r[2] | r[3] << 8), r[0] | r[1] << 8);
        wr16(a, rd16(a) + load);
    }
    plat_close(f);
    /* reference EXEC register state */
    rt_r.ax = 0; rt_r.bx = 0; rt_r.cx = 0x00ff; rt_r.dx = psp_seg;
    rt_r.si = HW(0x14); rt_r.di = HW(0x10); rt_r.bp = 0x091c; rt_r.sp = HW(0x10);
    G_SS = load + HW(0x0e);
    G_ES = G_DS = psp_seg;
    rt_entry_cs = load + HW(0x16);
    rt_entry_ip = HW(0x14);
#undef HW
}

void rt_start(uint8_t *mem)
{
    rt_guest = mem + RT_GUEST_BYTES - 1;
    for (uint32_t k = 1; k <= RT_STATE_BYTES; ++k) {
        rt_guest[k] = 0;
    }
    rt_fill(0, 0, RT_GUEST_BYTES);
    for (uint32_t k = 0; k < sizeof vectors / sizeof vectors[0]; ++k) {
        wr16(vectors[k].vector * 4, vectors[k].off);
        wr16(vectors[k].vector * 4 + 2, vectors[k].seg);
    }
    put_bytes(lin(0xc401, 0x0a), "EMMXXXX0", 8);  /* EMS driver name at INT 67h:000Ah */
    wr8(0x449, 0x03);                             /* BIOS: text mode 3, 80 columns */
    wr16(0x44a, 80);
    uint16_t psp_seg = (uint16_t)load_segment - 0x10;
    mcb(RT_ENV_SEG - 1, 'M', psp_seg, ENV_PARAS, "SWOTL\0\0\0");
    put_bytes(lin(RT_ENV_SEG, 0), environment, sizeof environment);
    mcb(psp_seg - 1, 'Z', psp_seg, TOP_SEG - psp_seg, "SWOTL\0\0\0");
    mcb(TOP_SEG, 'M', 0x0008, 0x2c00, "SC      ");  /* reference: link to upper memory */
    wr8(lin(MEDIA_SEG, MEDIA_OFF), 0xf8);          /* reference: drive C: media descriptor */
    psp(psp_seg);
    rt_dos_init();
    rt_input_init();
    exec_root(psp_seg);
    rt_set_flags_word(0x7202);
}

/* FLAGS bit 2 (PF) | bit 1 per byte value: even parity */
#define P2(n) n, n ^ 4, n ^ 4, n
#define P4(n) P2(n), P2(n ^ 4), P2(n ^ 4), P2(n)
#define P6(n) P4(n), P4(n ^ 4), P4(n ^ 4), P4(n)
static const uint8_t parity_flags[256] = {P6(6), P6(2), P6(2), P6(6)};
#undef P2
#undef P4
#undef P6

/* FLAGS CF, OF, ZF, SF per CCR image (C, V, Z, N) */
static const uint16_t ccr_flags[16] = {
    0x000, 0x001, 0x800, 0x801, 0x040, 0x041, 0x840, 0x841,
    0x080, 0x081, 0x880, 0x881, 0x0c0, 0x0c1, 0x8c0, 0x8c1,
};

uint16_t rt_flags_word(void)
{
    uint16_t f = ccr_flags[G_CCR & 15] | parity_flags[G_PF] | (G_AF & 0x10) |
                 (G_TF ? 0x100 : 0) | (G_IF ? 0x200 : 0) | (G_DF ? 0x400 : 0);
    return f | (G_FX & 0xf000);
}

void rt_set_flags_word(uint16_t f)
{
    if (f & 0x100) {
        rt_stop("trap flag set in FLAGS image", f, 0);
    }
    G_CCR = (f & 0x01 ? CCR_C : 0) | (f & 0x800 ? 2 : 0) | (f & 0x40 ? CCR_Z : 0) |
            (f & 0x80 ? 8 : 0);
    G_PF = f & 0x04 ? 0 : 1;
    G_AF = (uint8_t)(f & 0x10);
    G_TF = (f & 0x100) != 0;
    G_IF = (f & 0x200) != 0;
    G_DF = (f & 0x400) != 0;
    G_FX = f & 0xf000;
    if (G_IF && rt_irq_pending) {
        *(volatile uint8_t *)&G_IRQ = 1;
    }
}

/* The CPU's interrupt frame below SS:SP (IP, CS, FLAGS), SP unchanged for a
 * machine service; returns the frame's SP. */
static uint16_t push_frame(uint16_t cs, uint16_t ip)
{
    uint16_t sp = rt_r.sp;
    wr16(lin(G_SS, (uint16_t)(sp - 2)), rt_flags_word());
    wr16(lin(G_SS, (uint16_t)(sp - 4)), cs);
    wr16(lin(G_SS, (uint16_t)(sp - 6)), ip);
    return (uint16_t)(sp - 6);
}

/* Vector target inside the program's memory: the guest owns it. */
static int guest_vector(uint8_t vector)
{
    uint32_t t = lin(rd16(vector * 4 + 2), rd16(vector * 4));
    uint32_t lo = lin(rt_psp(), 0);
    return t >= lo && t < lin(rd16(lo + 2), 0);
}

void *rt_lookup(uint32_t cs, uint32_t ip, uint32_t far);

/* Returns 0 when serviced, else CS << 16 | IP of the frame pushed for the
 * guest handler at rt_deliver_cs:rt_deliver_ip (entry rt_deliver_code). */
static uint32_t deliver(uint8_t vector, uint16_t cs, uint16_t ip)
{
    rt_r.sp = push_frame(cs, ip);
    G_IF = 0;
    G_TF = 0;
    rt_deliver_ip = rd16(vector * 4);
    rt_deliver_cs = rd16(vector * 4 + 2);
    rt_deliver_code = rt_lookup(rt_deliver_cs, rt_deliver_ip, 1);
    return (uint32_t)cs << 16 | ip;
}

static void bench_service(void);

uint32_t rt_int_c(uint32_t d6, uint32_t ip)
{
    uint8_t vector = (uint8_t)d6;
    uint16_t cs = (uint16_t)(d6 >> 16);
    if (guest_vector(vector)) {
        return deliver(vector, cs, (uint16_t)ip);
    }
    push_frame(cs, (uint16_t)ip);
    if (rt_bench) {
        bench_service();
    }
    switch (vector) {
    case 0x10: rt_int10(); break;
    case 0x21: rt_int21(cs, (uint16_t)ip); break;
    case 0x16: rt_int16(); break;
    case 0x33: rt_int33(); break;
    case 0x67: rt_int67(); break;
    default: rt_unsupported("interrupt", vector, cs, (uint16_t)ip);
    }
    return 0;
}

/* -- timer (D8) ------------------------------------------------------------ */

/* Hardware interrupts posted by the platform (vector 08h tick, 09h key make,
 * 89h key break), taken in order at poll points while the guest has IF set. */
volatile uint8_t rt_irq_ring[RT_IRQ_RING];
volatile uint8_t rt_irq_tail;
volatile uint8_t rt_irq_pending;
static uint8_t irq_head;

/* -- frame bench (runtime.h) ------------------------------------------------ */

uint8_t rt_bench;
static uint16_t bench_share, bench_polls, bench_budget;
static uint32_t bench_point;        /* CS << 16 | IP of the watched poll point */
static uint32_t bench_due;          /* ticks not yet in the ring */
static uint8_t bench_watching;

/* Due ticks into the ring as far as it has room (rt_irq_c tops it up). */
static void bench_post(void)
{
    if (!bench_due) {
        return;
    }
    while (bench_due && (uint8_t)(rt_irq_tail - irq_head) < RT_IRQ_RING) {
        rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = 8;
        ++rt_irq_tail;
        --bench_due;
    }
    RT_RAISE_IRQ();
}

static void bench_ticks(uint32_t n)
{
    bench_due += n;
    bench_post();
}

/* Every poll point calls rt_irq_c while the spin watch runs (rt_irq_pending
 * stays set). */
void rt_bench_watch(void)
{
    bench_watching = 1;
    bench_budget = RT_BENCH_WATCH;
    bench_point = 0;
    bench_polls = 0;
    RT_RAISE_IRQ();
}

/* rt_int_c: a runtime service ran. */
static void bench_service(void)
{
    bench_share += RT_BENCH_FRAME_TICKS;
    bench_ticks(bench_share / RT_BENCH_FRAME_SERVICES);
    bench_share %= RT_BENCH_FRAME_SERVICES;
    rt_bench_watch();
}

/* A poll visit with IF set: consecutive visits to one poll point are
 * counted; a spin ticks every RT_BENCH_POLLS of them, leaving it ends the
 * watch, other visits use up its budget. */
static void bench_poll(uint32_t at)
{
    if (at != bench_point) {
        if (bench_polls >= RT_BENCH_SPIN) {
            bench_watching = 0;
            return;
        }
        bench_point = at;
        bench_polls = 0;
    }
    if (++bench_polls == RT_BENCH_POLLS) {
        bench_polls = 0;
        bench_ticks(1);
    } else if (bench_polls < RT_BENCH_SPIN && !--bench_budget) {
        bench_watching = 0;
    }
}

#define BIOS_TICKS 0x46c
#define BIOS_MIDNIGHT 0x470
#define BIOS_INT08_SEG 0xf000      /* reference vector 08h (vectors[] above) */
#define BIOS_INT08_OFF 0xfea5

/* The reference BIOS handler: tick count with midnight wrap (INT 1Ch and EOI
 * have no effect here: the vector is the BIOS IRET, the PIC is not modelled). */
static void bios_tick(void)
{
    uint32_t t = rd32(BIOS_TICKS);
    if (++t >= 0x1800b0) {
        wr8(BIOS_MIDNIGHT, rd8(BIOS_MIDNIGHT) + 1);
        t = 0;
    }
    wr32(BIOS_TICKS, t);
}

/* IRQ0's handler runs (rt_irq0_enter to rt_irq0_leave): the PIC holds IRQ0
 * and the lower IRQ1 in service until its EOI, so nothing posted is taken,
 * though SPAZ's handler sets IF before its EOI (an STI at SPAZ+05AD); the
 * single rt_irq_saved could not hold a nested entry. Held to the handler's
 * return: its EOI (SPAZ+0A80) precedes the IRET by register pops. */
static uint8_t irq0_in_service;

/* G_IRQ and rt_irq_pending from what is left: cleared before the ring is
 * read (a post in between raises both again); with IF = 0 nothing is taken,
 * so G_IRQ waits for IF (S2). */
static void irq_settle(void)
{
    volatile uint8_t *irq = &G_IRQ;
    *irq = 0;
    rt_irq_pending = 0;
    if (irq_head != rt_irq_tail || bench_watching) {
        rt_irq_pending = 1;
        *irq = G_IF && !irq0_in_service;
    }
    if (rt_present_due == 1) {      /* a vertical blank since rt_irq_c's check */
        RT_RAISE_IRQ();
    }
}

/* Posted interrupts in order until one runs a guest handler or none is
 * left. IRQ0 with a guest handler returns 1 (rt_entry.s rt_irq_async runs it
 * on the private stack, the interrupted state restored after it); another
 * returns as rt_int_c does, the flags settled with its IF = 0: the handler's
 * IRET re-arms G_IRQ when more are posted, and the glue polls again. */
uint32_t rt_irq_c(uint32_t d6, uint32_t ip)
{
    uint16_t cs = (uint16_t)(d6 >> 16);
    if (rt_present_due == 1) {
        rt_video_refresh();
    }
    if (bench_watching && G_IF) {
        bench_poll((d6 & 0xffff0000) | (uint16_t)ip);
    }
    while (G_IF && !irq0_in_service && irq_head != rt_irq_tail) {
        uint8_t irq = rt_irq_ring[irq_head++ % RT_IRQ_RING];
        if (bench_due) {
            bench_post();
        }
        uint8_t vector = irq & 0x7f;
        if (vector == 8 && guest_vector(vector)) {
            irq_settle();
            return 1;               /* rt_irq_async (I4) */
        }
        if (guest_vector(vector)) {
            uint32_t frame = deliver(vector, cs, (uint16_t)ip);
            irq_settle();
            return frame;
        }
        if (vector == 9) {
            rt_keyboard_irq();      /* BIOS INT 09h: the next keyboard event */
            continue;
        }
        /* DOSBox-X's external IRQ12 handler drains its mouse event queue.
         * The supported INT33 surface never shows the DOS driver cursor or
         * installs a callback; input state is already supplied by plat_mouse.
         * Guest-installed vectors were dispatched above. Keep the exact IVT
         * guard: an unknown external handler is still unsupported. */
        if (vector == 0x74 && rd16(0x74 * 4) == MOUSE_INT74_OFF &&
                rd16(0x74 * 4 + 2) == MOUSE_INT74_SEG) {
            continue;
        }
        if (vector != 8 || rd16(8 * 4) != BIOS_INT08_OFF || rd16(8 * 4 + 2) != BIOS_INT08_SEG) {
            rt_unsupported("hardware interrupt vector outside the program and the BIOS",
                           vector, cs, (uint16_t)ip);
        }
        bios_tick();
    }
    irq_settle();
    return 0;
}

/* IRQ0 entry (rt_irq_async, I4): G_SS:rt_r.sp is the private stack; the
 * frame with the sentinel CS:IP and the interrupted flags, IF and TF clear
 * (G_IRQ with them), the handler at rt_deliver_*. */
uint8_t rt_irq_saved[RT_STATE_BYTES + sizeof(struct rt_regs)];

void rt_irq0_enter(void)
{
    deliver(8, RT_IRQ_SS, RT_IRQ_SP);
    G_IRQ = 0;
    irq0_in_service = 1;
}

/* After the restore: re-arm from what is posted (runtime.h). */
void rt_irq0_leave(void)
{
    irq0_in_service = 0;
    *(volatile uint8_t *)&G_IRQ = G_IF && rt_irq_pending;
}

/* jmp far to the BIOS INT 08h entry: the tick, then the handler's IRET from
 * SS:SP; returns CS << 16 | IP popped. */
uint32_t rt_bios_int08_c(void)
{
    bios_tick();
    uint32_t sp = lin(G_SS, rt_r.sp);
    uint16_t ip = rd16(sp), cs = rd16(sp + 2);
    rt_set_flags_word(rd16(sp + 4));
    rt_r.sp += 6;
    return (uint32_t)cs << 16 | ip;
}

uint32_t rt_fault_c(uint32_t d6, uint32_t ip)
{
    uint8_t vector = (uint8_t)d6;
    uint16_t cs = (uint16_t)(d6 >> 16);
    if (!guest_vector(vector)) {
        rt_unsupported("fault without a guest handler", vector, cs, (uint16_t)ip);
    }
    return deliver(vector, cs, (uint16_t)ip);
}

void rt_halt_c(uint32_t ip)
{
    rt_stop("HLT", ip, 0);
}

/* The game never sets TF (open-work 26): no single-step delivery. */
void rt_trap_c(uint32_t ip)
{
    rt_stop("trap flag set by POPF/IRET at IP", ip, 0);
}

/* PLINK overlay record flags bit 15: resident (docs/plink.md). */
static int resident(uint16_t overlay)
{
    if (!overlay) {
        return 1;
    }
    return rd16(lin((uint16_t)load_segment, 0) + overlay_table + 16u * (overlay - 1u)) & 0x8000;
}

/* First table row at or above each recent CS:IP (the table is constant, so
 * nothing invalidates it; residency is still read on every lookup). */
static struct {
    uint32_t key, row1;     /* row1 = row + 1, 0 = empty */
} lookup_cache[64];

void *rt_lookup(uint32_t cs, uint32_t ip, uint32_t far)
{
    if ((cs & 0xffff) == BIOS_INT08_SEG && (ip & 0xffff) == BIOS_INT08_OFF) {
        return rt_bios_int08;
    }
    uint32_t key = (cs & 0xffff) << 16 | (ip & 0xffff);
    uint32_t lo;
    uint32_t slot = (key ^ key >> 16) & 63;
    if (lookup_cache[slot].row1 && lookup_cache[slot].key == key) {
        lo = lookup_cache[slot].row1 - 1;
    } else {
        uint32_t hi = dispatch_count;
        lo = 0;
        while (lo < hi) {
            uint32_t mid = (lo + hi) / 2;
            const struct rt_dispatch_row *r = &dispatch_table[mid];
            if (((uint32_t)r->cs << 16 | r->ip) < key) {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        lookup_cache[slot].key = key;
        lookup_cache[slot].row1 = lo + 1;
    }
    for (; lo < dispatch_count; ++lo) {
        const struct rt_dispatch_row *r = &dispatch_table[lo];
        if (((uint32_t)r->cs << 16 | r->ip) != key) {
            break;
        }
        if (resident(r->overlay)) {
            if (far && !r->far) {
                rt_stop("dispatch: far transfer to a near-only entry at CS:IP", cs & 0xffff,
                        ip & 0xffff);
            }
            return r->code;
        }
    }
    rt_stop("dispatch: no translated entry at CS:IP", cs & 0xffff, ip & 0xffff);
}

void rt_ret_mismatch_c(uint32_t ip, uint32_t cs)
{
    rt_stop("return site reached with IP/CS", ip & 0xffff, cs & 0xffff);
}

void rt_stop_unknown_c(uint32_t ip, uint32_t cs)
{
    rt_stop("transfer into untranslated code IP/CS", ip & 0xffff, cs & 0xffff);
}

/* -- log and stop ------------------------------------------------------------ */

static char *put_hex(char *p, uint32_t v, int digits)
{
    for (int k = digits - 1; k >= 0; --k) {
        *p++ = "0123456789abcdef"[(v >> (4 * k)) & 15];
    }
    return p;
}

static char *put_str(char *p, const char *s)
{
    while (*s) {
        *p++ = *s++;
    }
    return p;
}

void rt_log(const char *s)
{
    plat_log(s);
}

void rt_log_hex(const char *label, uint32_t v)
{
    char line[96], *p = put_str(line, label);
    *p++ = ' ';
    p = put_hex(p, v, 8);
    *p = 0;
    plat_log(line);
}

void rt_stop(const char *what, uint32_t a, uint32_t b)
{
    char line[160], *p = put_str(line, "SWOTL_STOP ");
    p = put_str(p, what);
    *p++ = ' ';
    p = put_hex(p, a, 4);
    *p++ = ' ';
    p = put_hex(p, b, 4);
    *p = 0;
    plat_log(line);
    plat_exit(2);
}

void rt_unsupported(const char *what, uint16_t vector, uint16_t cs, uint16_t ip)
{
    char line[160], *p = put_str(line, "SWOTL_STOP unsupported ");
    p = put_str(p, what);
    p = put_str(p, " int ");
    p = put_hex(p, vector, 2);
    p = put_str(p, " ax=");
    p = put_hex(p, rt_r.ax, 4);
    p = put_str(p, " at ");
    p = put_hex(p, cs, 4);
    *p++ = ':';
    p = put_hex(p, ip, 4);
    *p = 0;
    plat_log(line);
    plat_exit(2);
}
