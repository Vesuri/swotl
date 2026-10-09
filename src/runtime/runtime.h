/* SWOTL runtime: the machine the generated code runs on (DOS 5 / BIOS / EMS /
 * ports as the DOSBox-X reference presents them) and the rt_* entries of the
 * generated-code contract (docs/translator-design.md). Platform services
 * (files, log, exit) come from platform.h. */
#ifndef SWOTL_RUNTIME_H
#define SWOTL_RUNTIME_H

#include <stdint.h>

/* Guest registers in the order rt_entry.s stores them (d0-d5, a4, a5). */
struct rt_regs {
    uint16_t ax, cx, dx, bx, sp, bp, si, di;
};

extern struct rt_regs rt_r;
extern uint8_t *rt_guest;          /* a6: guest linear 0; state block below */

#define RT_GUEST_BYTES 0x110000u   /* 1 MiB + HMA (A20 on) */
#define RT_STATE_BYTES 16u
/* EMS logical pages after guest RAM (ems.c); reference: 16 KiB pages, memsize = 4 */
#define RT_EMS_PAGES 0x00a4u
#define RT_EMS_PAGE 0x4000u
#define RT_EMS_BYTES (RT_EMS_PAGES * RT_EMS_PAGE)

/* State block (translator/lower.py STATE_EQU), native big-endian. */
#define G_CCR  (rt_guest[-1])      /* C=CF V=OF Z=ZF N=SF */
#define G_PF   (rt_guest[-3])
#define G_AF   (rt_guest[-4])
#define G_DF   (rt_guest[-5])
#define G_IF   (rt_guest[-6])
#define G_TF   (rt_guest[-7])
#define G_IRQ  (rt_guest[-8])      /* poll points call rt_irq (RT_RAISE_IRQ, machine.c) */
#define G_FX   (*(uint16_t *)(rt_guest - 10))
#define G_ES   (*(uint16_t *)(rt_guest - 12))
#define G_SS   (*(uint16_t *)(rt_guest - 14))
#define G_DS   (*(uint16_t *)(rt_guest - 16))

#define CCR_C 1
#define CCR_Z 4

static inline uint32_t lin(uint16_t seg, uint16_t off) { return ((uint32_t)seg << 4) + off; }

/* Guest memory: the runtime reaches it only through these (docs/speed-plan.md
 * R1). A span is the host bytes holding guest a..a+n-1, for platform I/O and
 * opaque page copies; rt_span_order puts a span in guest order and back (the
 * same call both ways; nothing to do while host order is guest order). */
static inline uint8_t rd8(uint32_t a) { return rt_guest[a]; }
static inline void wr8(uint32_t a, uint8_t v) { rt_guest[a] = v; }
static inline uint16_t rd16(uint32_t a) { return rt_guest[a] | (uint16_t)rt_guest[a + 1] << 8; }
static inline void wr16(uint32_t a, uint16_t v) { rt_guest[a] = (uint8_t)v; rt_guest[a + 1] = (uint8_t)(v >> 8); }
static inline uint32_t rd32(uint32_t a) { return rd16(a) | (uint32_t)rd16(a + 2) << 16; }
static inline void wr32(uint32_t a, uint32_t v) { wr16(a, (uint16_t)v); wr16(a + 2, (uint16_t)(v >> 16)); }
static inline uint8_t *rt_span(uint32_t a, uint32_t n) { (void)n; return rt_guest + a; }
static inline void rt_span_order(uint8_t *span, uint32_t n) { (void)span; (void)n; }
static inline void rt_fill(uint32_t a, uint8_t v, uint32_t n)
{
    for (uint8_t *p = rt_span(a, n); n--; ) {
        *p++ = v;
    }
}

static inline void set_cf(int on) { G_CCR = on ? (G_CCR | CCR_C) : (G_CCR & ~CCR_C); }
static inline void set_zf(int on) { G_CCR = on ? (G_CCR | CCR_Z) : (G_CCR & ~CCR_Z); }
#define AL(r) ((uint8_t)(r))
#define AH(r) ((uint8_t)((r) >> 8))
#define SET_AL(r, v) ((r) = ((r) & 0xff00) | (uint8_t)(v))
#define SET_AH(r, v) ((r) = ((r) & 0x00ff) | (uint16_t)((uint8_t)(v)) << 8)

/* Generated program (build/gen/program.s). */
struct rt_dispatch_row {
    uint16_t cs, ip, overlay, pad;
    void *code;
};
extern const uint32_t dispatch_count;
extern const struct rt_dispatch_row dispatch_table[];
extern const uint32_t load_segment;
extern const uint32_t overlay_table;

/* Reference: environment block; its MCB is the first one DOS gives programs. */
#define RT_ENV_SEG 0x07ca

/* Reference: INT 21h AH=1Bh returns DS:BX here, at the media descriptor byte. */
#define MEDIA_SEG 0x0410
#define MEDIA_OFF 0x0059

/* machine.c */
uint16_t rt_flags_word(void);
void rt_set_flags_word(uint16_t f);
void rt_start(uint8_t *guest);     /* machine model, EXEC of SWOTL.EXE; returns the entry */
extern uint16_t rt_entry_cs, rt_entry_ip;

/* services */
void rt_int21(uint16_t cs, uint16_t ip);
void rt_int10(void);
extern uint8_t rt_dac[768];      /* video.c: 6-bit R, G, B */
/* video.c: set to 1 by the platform (with RT_RAISE_IRQ) at each vertical blank;
 * a published frame's changed rows are presented at the next poll point
 * outside the graphics driver, or when the driver returns (D9); 2: due,
 * the platform's per-blank work done */
extern volatile uint8_t rt_present_due;
void rt_video_refresh(void);
void rt_int67(void);
void rt_dos_init(void);
uint16_t rt_psp(void);

/* hardware interrupts (machine.c): the platform appends a vector (08h tick,
 * 09h key make, 89h key break) at rt_irq_tail, then RT_RAISE_IRQ. While the
 * guest has IF = 0, rt_irq clears G_IRQ but keeps rt_irq_pending; every path
 * that sets IF copies rt_irq_pending into G_IRQ (sti, __set_flags,
 * rt_set_flags_word), so G_IRQ is never set without rt_irq_pending. */
#define RT_IRQ_RING 32
extern volatile uint8_t rt_irq_ring[RT_IRQ_RING];
extern volatile uint8_t rt_irq_tail;
extern volatile uint8_t rt_irq_pending;
#define RT_RAISE_IRQ() (rt_irq_pending = 1, *(volatile uint8_t *)&G_IRQ = 1)
void rt_bios_int08(void);

/* Frame bench (docs/speed-plan.md M2): set by the platform at startup, never
 * in release or fixture runs. PIT ticks then follow guest progress instead
 * of a timer, so every build does the same guest work:
 * - RT_BENCH_FRAME_TICKS per RT_BENCH_FRAME_SERVICES runtime services, spread
 *   over them (the flight makes 4 services per frame; the m4 reference draws
 *   a frame every 9 ticks);
 * - in a spin (RT_BENCH_SPIN or more consecutive visits with IF set to one
 *   poll point): one per RT_BENCH_POLLS such visits. Poll visits are watched
 *   from each service, PIT channel 0 reload or such tick, for at most
 *   RT_BENCH_WATCH visits outside spins and until a spin ends (SPAZ's rate
 *   calibration counts loop iterations between two ticks: the reference
 *   count; the flight demo waits for a tick after loading its replay). */
#define RT_BENCH_FRAME_TICKS 9
#define RT_BENCH_FRAME_SERVICES 4
#define RT_BENCH_POLLS 8956
#define RT_BENCH_SPIN 8
#define RT_BENCH_WATCH 64
extern uint8_t rt_bench;
void rt_bench_watch(void);

/* input.c: the platform appends keyboard events (PC set 1 scan code, bit 7
 * break, RT_KEY_E0 for E0-prefixed keys), one per 09h interrupt it posts */
#define RT_KEY_RING 16
#define RT_KEY_E0 0x100
extern volatile uint16_t rt_key_ring[RT_KEY_RING];
extern volatile uint8_t rt_key_tail;
void rt_input_init(void);
void rt_keyboard_irq(void);
int rt_key_available(void);
uint16_t rt_key_take(void);
void rt_int16(void);
void rt_int33(void);

/* ports.c */
extern uint32_t rt_pit_divisor;    /* channel 0 reload, 1..65536 */
extern uint8_t rt_opl[256];         /* AdLib registers as written */

/* stop: report and halt, never resumes */
void rt_stop(const char *what, uint32_t a, uint32_t b) __attribute__((noreturn));
void rt_unsupported(const char *what, uint16_t vector, uint16_t cs, uint16_t ip) __attribute__((noreturn));
void rt_log(const char *s);
void rt_log_hex(const char *label, uint32_t v);

#endif
