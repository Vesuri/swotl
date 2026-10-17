/* Diagnostic link wrappers only; normal builds keep the original port handlers. */
#include "runtime.h"
#include "joystick_data.h"
extern volatile uint32_t replay_services;
extern uint32_t __real_rt_port_in(uint32_t port, uint32_t width);
extern void __real_rt_port_out(uint32_t port, uint32_t value, uint32_t width);
static uint32_t joystick_index, joystick_used;

static uint32_t joystick_step(uint32_t write, uint32_t width, uint32_t value)
{
    if (joystick_index >= REPLAY_JOYSTICK_RECORDS)
        rt_unsupported("joystick replay exhausted", joystick_index, write, width);
    const struct replay_joystick *r = &replay_joystick[joystick_index];
    if (r->service != replay_services || r->write != write || r->width * 8u != width)
        rt_unsupported("joystick replay access", joystick_index, write, width);
    if (write && r->value != value)
        rt_unsupported("joystick replay write", joystick_index, value, r->value);
    if (++joystick_used == r->repeat) {
        ++joystick_index;
        joystick_used = 0;
    }
    return r->value;
}

uint32_t __wrap_rt_port_in(uint32_t port, uint32_t width)
{
    if ((port & 0xffffu) != 0x201u) return __real_rt_port_in(port, width);
    return joystick_step(0, width, 0);
}
void __wrap_rt_port_out(uint32_t port, uint32_t value, uint32_t width)
{
    if ((port & 0xffffu) != 0x201u) {
        __real_rt_port_out(port, value, width);
        return;
    }
    /* The runtime's 8-bit handler truncates its argument before device output. */
    if (width == 8) value &= 0xff;
    else if (width == 16) value &= 0xffff;
    joystick_step(1, width, value);
}
void replay_joystick_complete(void)
{
    if (joystick_index != REPLAY_JOYSTICK_RECORDS || joystick_used)
        rt_unsupported("joystick replay incomplete", joystick_index, joystick_used, 0);
}
