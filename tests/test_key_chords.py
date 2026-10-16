#!/usr/bin/env python3
"""Scripted modifiers: scan order, ring wrap and BIOS character boundaries."""
import argparse
import struct
import unittest
import host_run as H
from test_mouse_irq import machine, call

SABOTAGE = False
CASES = {
    'alt+c': (0x38, 0x2e, 0xae, 0xb8),
    'ctrl+c': (0x1d, 0x2e, 0xae, 0x9d),
    'shift+c': (0x2a, 0x2e, 0xae, 0xaa),
    'shift+alt+left': (0x2a, 0x38, 0xe0, 0x4b, 0xe0, 0xcb, 0xb8, 0xaa),
    'alt+shift+left': (0x2a, 0x38, 0xe0, 0x4b, 0xe0, 0xcb, 0xb8, 0xaa),
    'ctrl+alt+shift+f1': (0x2a, 0x1d, 0x38, 0x3b, 0xbb, 0xb8, 0x9d, 0xaa),
}


class ChordTests(unittest.TestCase):
    def test_plain_keys(self):
        for name, key in H.KEYS.items():
            self.assertEqual(H.key_code(name), key)
            scan = key >> 8
            expected = ((0xe0, scan, 0xe0, scan | 0x80) if key in H.GREY
                        else (scan, scan | 0x80))
            self.assertEqual(H.key_events(key), expected)

    def test_order_and_ring_wrap(self):
        for name, expected in CASES.items():
            key = H.key_code(name)
            self.assertEqual(H.key_events(key), expected)
            h = machine()
            h.e.write(h.syms['rt_key_tail'], bytes([254]))
            h.press(key)
            self.assertEqual(h.mem(h.syms['rt_key_tail'], 1), bytes([(254 + len(expected)) & 255]))
            for i, scan in enumerate(expected):
                self.assertEqual(h.mem(h.syms['rt_key_ring'] + 2 * ((254+i) % 16), 2),
                                 struct.pack('>H', scan))

    def test_invalid_chords(self):
        for name in ('alt+alt+c', 'wat+c', 'alt+', '+c', 'alt+mx+1'):
            with self.assertRaises(ValueError):
                H.key_code(name)
        for key in (-1, 0x80000, 1 << 31):
            with self.assertRaises(ValueError):
                H.key_events(key)

    def test_bios_boundaries(self):
        for name, word, flag in [('alt+c', 0x2e00, 8), ('ctrl+c', 0x2e03, 4),
                                 ('shift+c', 0x2e43, 2)]:
            h = machine()
            h.press(H.key_code(name))
            if SABOTAGE and name == 'alt+c':
                # Lose the modifier make while keeping its IRQ and all other bytes.
                h.e.write(h.syms['rt_key_ring'], struct.pack('>H', 0xb8))
            for i in range(4):
                call(h, 'rt_keyboard_irq')
                self.assertEqual(bool(call(h, 'rt_key_available')), i == 1)
                if i == 1:
                    self.assertEqual(call(h, 'rt_key_take') & 0xffff, word)
                self.assertEqual(bool(h.gmem(0x417, 1)[0] & flag), i < 3)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    SABOTAGE = ap.parse_args().sabotage
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(ChordTests))
    if SABOTAGE:
        assert len(result.failures) == 1 and not result.errors, result
        print('keyboard modifier sabotage caught')
    else:
        raise SystemExit(not result.wasSuccessful())
