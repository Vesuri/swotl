"""Ownership of the existing dead-stack mask; no expansion of its bounds.

The c28-c30 reference failures leave one runtime-written interrupt FLAGS
byte unmasked. Exercise the real compiled frame writer and generated PUSH,
with a non-frame runtime write as a control against ignoring all runtime code.
"""
import argparse
import struct
import unittest
import host_run as H
from test_mouse_irq import call

SABOTAGE = None


def watching():
    h = H.Host(H.image.M.REF)
    h.run({'keys': [], 'snapshots': [H.trigger('SWOTL.EXE+164f2')],
           'irqs': [], 'releases': []}, 30)
    assert h.stopped_at == 'R_164F2'
    h.halted = False
    if SABOTAGE == 'frame':
        h.frame_writer = (0, 0)  # Reintroduce runtime-frame mask removal.
    elif SABOTAGE == 'guest':
        h.frame_writer = h.code  # Incorrectly exempt generated writes.
    elif SABOTAGE == 'runtime':
        h.frame_writer = (0, h.code[0])  # Incorrectly exempt all runtime writes.
    return h


class FrameMaskTests(unittest.TestCase):
    def test_frame_write_preserves_existing_mask_only(self):
        h = watching()
        g = h.guest_regs(0)
        top = g['ss'] * 16 + g['sp']
        # Deliberately mask only the FLAGS word, not the rest of the frame.
        h.masked = {top - 2, top - 1}
        h.e.write(h.syms['rt_r'] + 8, struct.pack('>H', g['sp']))
        call(h, 'push_frame', 0x0822, 0x1234)
        self.assertEqual(h.gmem(top - 6, 4), b'\x34\x12\x22\x08')
        self.assertEqual(h.masked, {top - 2, top - 1})

    def test_generated_write_removes_mask(self):
        h = watching()
        g = h.guest_regs(0)
        top = g['ss'] * 16 + g['sp']
        h.masked = set(range(top - H.DEAD_STACK, top))
        # Execute the existing generated PUSH BP, stopping before MOV BP,SP.
        err = h.e.start(h.syms['R_00000'], h.syms['R_00001'], timeout_us=1_000_000)
        self.assertFalse(err)
        self.assertEqual(h.gmem(top - 2, 2), struct.pack('<H', g['bp']))
        self.assertEqual(h.masked, set(range(top - H.DEAD_STACK, top - 2)))

    def test_non_frame_runtime_write_is_checked(self):
        h = watching()
        tail = int.from_bytes(h.gmem(0x41c, 2), 'little')
        address = 0x400 + tail
        h.masked = {address, address + 1}
        h.press(H.KEYS['a'])
        call(h, 'rt_keyboard_irq')
        self.assertEqual(h.gmem(address, 2), b'a\x1e')
        self.assertEqual(h.masked, set())


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    if args.sabotage:
        for plant, case in [('frame', 'test_frame_write_preserves_existing_mask_only'),
                            ('guest', 'test_generated_write_removes_mask'),
                            ('runtime', 'test_non_frame_runtime_write_is_checked')]:
            SABOTAGE = plant
            result = unittest.TextTestRunner().run(unittest.TestSuite([FrameMaskTests(case)]))
            assert len(result.failures) == 1 and not result.errors, result
            print(f'interrupt frame ownership sabotage caught: {plant}')
    else:
        unittest.main(argv=[__file__])
