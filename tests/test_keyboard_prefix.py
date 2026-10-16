#!/usr/bin/env python3
"""BIOS E0 prefix consumption at the recorded IRQ9 boundaries.

DOSBox-X bios_keyboard.cpp retains FLAGS3 bit 1 after E0, clears it after
its scan byte, and enqueues no character for the prefix. The c28 reference
also observes INT21/AH=0B returning 00 between the two make interrupts and
FF after the second. Combined Amiga events keep their existing semantics.
"""
import argparse
import struct
import unittest
import host_run as H
from test_mouse_irq import machine, call

SABOTAGE = False


def enqueue(h, events):
    for event in events:
        tail = h.mem(h.syms['rt_key_tail'], 1)[0]
        h.e.write(h.syms['rt_key_ring'] + 2 * (tail % 16), struct.pack('>H', event))
        h.e.write(h.syms['rt_key_tail'], bytes([(tail + 1) & 255]))


class PrefixTests(unittest.TestCase):
    def test_raw_prefix_boundaries(self):
        h = machine()
        enqueue(h, [0xe0, 0x4b, 0xe0, 0xcb])
        if SABOTAGE:
            # Deliver the complete arrow at the prefix interrupt: the original bug.
            h.e.write(h.syms['rt_key_ring'], struct.pack('>H', 0x14b))
        for prefix, available in [(True, False), (False, True), (True, False), (False, False)]:
            call(h, 'rt_keyboard_irq')
            self.assertEqual(bool(h.gmem(0x496, 1)[0] & 2), prefix)
            self.assertEqual(bool(call(h, 'rt_key_available')), available)
            if available:
                self.assertEqual(call(h, 'rt_key_take') & 0xffff, 0x4be0)

    def test_combined_amiga_events(self):
        h = machine()
        enqueue(h, [0x14b, 0x1cb])
        call(h, 'rt_keyboard_irq')
        self.assertEqual(call(h, 'rt_key_take') & 0xffff, 0x4be0)
        call(h, 'rt_keyboard_irq')
        self.assertFalse(call(h, 'rt_key_available'))
        self.assertFalse(h.gmem(0x496, 1)[0] & 2)

    def test_host_press_preserves_prefix_events(self):
        h = machine()
        h.press(H.KEYS['left'])
        self.assertEqual(h.mem(h.syms['rt_key_tail'], 1), b'\x04')
        self.assertEqual(h.mem(h.syms['rt_key_ring'], 8), struct.pack('>4H', 0xe0, 0x4b, 0xe0, 0xcb))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    SABOTAGE = args.sabotage
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(PrefixTests))
    if SABOTAGE:
        assert len(result.failures) == 1 and not result.errors, result
        print('keyboard prefix sabotage caught')
    else:
        raise SystemExit(not result.wasSuccessful())
