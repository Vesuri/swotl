#!/usr/bin/env python3
"""IRQ0 in service (docs/irq-plan.md I4): the PIC holds IRQ0, and the lower
IRQ1, from delivery to the handler's EOI. SPAZ's tick handler reaches an STI
(SPAZ+05AD) before its EOI, so a tick posted meanwhile must stay pending
until rt_irq_async returns, else a nested entry overwrites rt_irq_saved."""
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import host_run as H
from test_mouse_irq import call, machine, write_guest

IF = H.TOP + 11


def pending(h):
    return h.mem(h.syms['rt_irq_pending'], 1) == b'\1'


def main():
    h = machine()
    cs = int.from_bytes(h.mem(h.syms['rt_entry_cs'], 2), 'big')
    ip = int.from_bytes(h.mem(h.syms['rt_entry_ip'], 2), 'big')
    write_guest(h, 8 * 4, struct.pack('<HH', ip, cs))
    h.post(8)
    h.post(8)
    h.post(9)
    assert call(h, 'rt_irq_c', 0x08220000, 0x100) == 1, h.log      # rt_irq_async
    call(h, 'rt_irq0_enter')
    assert h.mem(IF, 1) == b'\0'
    h.e.write(IF, b'\1')                                           # the handler's STI
    assert call(h, 'rt_irq_c', 0x1f920000, 0x5ad) == 0, 'IRQ0 nested inside its handler'
    assert pending(h) and h.mem(H.G_IRQ, 1) == b'\0' and not h.halted, h.log
    call(h, 'rt_irq0_leave')
    assert h.mem(H.G_IRQ, 1) == b'\1', 'not re-armed after the handler'
    assert call(h, 'rt_irq_c', 0x08220000, 0x100) == 1, 'second tick lost'
    print('irq in service: no IRQ0 or IRQ1 delivery inside the tick handler, re-armed after it')


if __name__ == '__main__':
    main()
