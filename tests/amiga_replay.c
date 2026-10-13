/* Diagnostic only: replay original DOSBox events, never linked in a release. */
#include "runtime.h"
#include "platform.h"
#include "replay_data.h"

volatile uint32_t replay_services, replay_interrupts, replay_steps;
volatile uint32_t replay_cs, replay_ip;
static uint32_t service_hash = 2166136261u, step_hits, release_at;
static uint32_t visits[REPLAY_POINTS], epochs[REPLAY_POINTS];
static uint32_t pending[64], vectors[64], depth, makes;
static int32_t mouse_x, mouse_y;
static uint32_t mouse_buttons;

static void fail(const char *what, uint32_t a, uint32_t b)
{
    rt_unsupported(what, a, b, replay_services);
}

static void hash_word(uint16_t word)
{
    service_hash = (service_hash ^ (word >> 8)) * 16777619u;
    service_hash = (service_hash ^ (word & 255)) * 16777619u;
}

static void service(const uint32_t *r, uint32_t vector, unsigned returning)
{
    for (unsigned i = 0; i < 8; ++i) {
        unsigned k = i < 6 ? i : i + 6; /* d0-d5/a4-a5 */
        hash_word((uint16_t)r[k] ^ (i == 4 || i == 5 ? 0x7fff : 0));
    }
    hash_word(G_ES); hash_word(G_SS); hash_word(G_DS);
    hash_word(vector);
    hash_word((G_DF ? 0x400 : 0) | (G_IF ? 0x200 : 0));
    hash_word(returning);
    if (replay_services >= REPLAY_SERVICES ||
            service_hash != replay_service_hashes[replay_services])
        fail("replay service state", replay_services, service_hash);
    ++replay_services;
}

void replay_enter(const uint32_t *r)
{
    if (depth == 64) fail("replay service depth", depth, 0);
    pending[depth] = *(const uint32_t *)((const uint8_t *)r + 66);
    vectors[depth++] = r[6] & 255;
    service(r, r[6] & 255, 0);
}

void replay_return(const uint32_t *r)
{
    uint32_t address = *(const uint32_t *)((const uint8_t *)r + 66);
    if (depth && pending[depth - 1] == address)
        service(r, vectors[--depth], 1);
}

uint32_t replay_mouse(int32_t *dx, int32_t *dy)
{
    *dx = mouse_x; *dy = mouse_y;
    mouse_x = mouse_y = 0;
    return mouse_buttons;
}

static void post(void)
{
    const struct replay_irq *irq = &replay_irqs[replay_interrupts++];
    uint8_t vector = irq->vector;
    if (!G_IF) fail("replay interrupt with IF clear", replay_interrupts, vector);
    if (vector == 9) vector = (++makes & 1) ? 9 : 0x89;
    replay_cs = replay_points[irq->point].cs;
    replay_ip = replay_points[irq->point].ip;
    rt_irq_ring[rt_irq_tail++ % RT_IRQ_RING] = vector;
    RT_RAISE_IRQ();
}

/* Return group index+1, zero for no delivery, or -1 for the final snapshot. */
int32_t replay_point(uint32_t point)
{
    if (point >= REPLAY_POINTS) fail("replay point", point, 0);
    if (release_at && replay_services >= release_at) release_at = 0;
    if (replay_steps < REPLAY_STEPS && !release_at) {
        const struct replay_step *step = &replay_script[replay_steps];
        if (point == step->point && ++step_hits == step->hits) {
            ++replay_steps; step_hits = 0;
            switch (step->kind) {
            case 1:
                rt_key_ring[rt_key_tail++ % RT_KEY_RING] = step->value;
                rt_key_ring[rt_key_tail++ % RT_KEY_RING] = step->value | 0x80;
                release_at = step->release;
                break;
            case 2: mouse_x += step->value; break;
            case 3: mouse_y += step->value; break;
            case 4: mouse_buttons = step->value; break;
            case 0:
                if (replay_steps == REPLAY_STEPS) {
                    if (replay_services != REPLAY_SERVICES || replay_interrupts != REPLAY_IRQS || depth)
                        fail("replay incomplete", replay_interrupts, replay_steps);
                    return -1;
                }
                break;
            default: fail("replay step kind", step->kind, point);
            }
        }
    }
    if (epochs[point] != replay_services + 1) {
        epochs[point] = replay_services + 1;
        visits[point] = 0;
    }
    ++visits[point];
    if (replay_interrupts < REPLAY_IRQS) {
        const struct replay_irq *irq = &replay_irqs[replay_interrupts];
        if (replay_services > irq->service) fail("replay missed interrupt", replay_interrupts, point);
        if (replay_services == irq->service && point == irq->point && visits[point] == irq->hits + 1) {
            uint32_t group = replay_interrupts + 1;
            post();
            return group;
        }
    }
    return 0;
}

uint32_t replay_next(uint32_t group)
{
    if (replay_interrupts < REPLAY_IRQS) {
        const struct replay_irq *a = &replay_irqs[group - 1];
        const struct replay_irq *b = &replay_irqs[replay_interrupts];
        if (replay_services == a->service && a->service == b->service &&
                a->point == b->point && a->hits == b->hits) {
            post();
            return 1;
        }
    }
    return 0;
}
