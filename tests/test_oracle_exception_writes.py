"""Write ownership survives the x86 oracle's exception reset."""
import argparse
import unittest
from unittest.mock import patch

import x86_diff as X


class ExceptionWrites(unittest.TestCase):
    def setUp(self):
        self.background = bytes([0x36]) * X.RAM
        self.oracle = X.Oracle(self.background)
        self.regs = dict(ax=0x125a, bx=0x200, cx=0, dx=0, sp=0x100,
                         bp=0, si=0, di=0, cs=0x2000, ds=0x3000,
                         es=0x4000, ss=0x5000)

    def tearDown(self):
        X.U.uc.uc_close(self.oracle.e.h)

    def run_code(self, code, count, **regs):
        initial = dict(self.regs, **regs)
        return self.oracle.run((initial, {f: 0 for f in X.FLAGS}, 0, 0x100,
                                [(0x20100, bytes.fromhex(code))]), count)

    def test_ordinary_write(self):
        err, out, flags, mem, ints, ports, writes = self.run_code('8807', 1)
        self.assertEqual((err, ints, ports), (0, [], []))
        self.assertEqual(out, dict(self.regs, ip=0x102))
        self.assertEqual(flags, 2)
        self.assertEqual(mem, {0x30200: 0x5a})
        self.assertEqual(writes, {0x30200})
        expected = bytearray(self.background)
        expected[0x20100:0x20102] = bytes.fromhex('8807')
        expected[0x30200] = 0x5a
        self.assertEqual(self.oracle.e.read(0, X.RAM), expected)

    def check_fault(self, code, count, expected, fault_ip=0x102, **regs):
        err, out, flags, mem, ints, ports, writes = self.run_code(code, count, **regs)
        self.assertEqual((err, ints, ports), (0, [0], []))
        self.assertEqual(out, dict(self.regs, **regs, ip=fault_ip))
        self.assertEqual(flags, 2)
        self.assertEqual(mem, expected)
        # Both outputs describe the completed run, even though the engine
        # has been reopened to prevent Unicorn's stale exception state.
        self.assertEqual(writes, set(expected), 'exception discarded write ownership')
        self.assertEqual(self.oracle.e.read(0, X.RAM), self.background)

    def test_write_before_divide_fault(self):
        self.check_fault('8807f6f1', 2, {0x30200: 0x5a})

    def test_same_value_write_before_fault(self):
        self.check_fault('8807f6f1', 2, {0x30200: 0x36}, ax=0x1236)

    def test_code_write_before_fault(self):
        # Store into a later code byte, then divide by zero. The target is
        # inside the patch, but is not the next instruction or its operand.
        self.check_fault('c606080190f6f19036', 2, {0x20108: 0x90}, fault_ip=0x105, ds=0x2000)

    def test_fault_without_write(self):
        self.check_fault('f6f1', 1, {}, fault_ip=0x100)

    def test_reset_does_not_leak_into_next_case(self):
        self.check_fault('f6f1', 1, {}, fault_ip=0x100)
        self.test_ordinary_write()


def run_suite():
    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExceptionWrites))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    result = run_suite()
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.sabotage:
        original = X.Oracle.run

        def lose_writes(self, *a, **kw):
            result = original(self, *a, **kw)
            return result[:-1] + (set(),) if result[4] else result

        with patch.object(X.Oracle, 'run', lose_writes):
            broken = run_suite()
        assert not broken.errors
        assert len(broken.failures) == 3
        assert all('exception discarded write ownership' in message
                   for _, message in broken.failures)
        print('sabotage: exception write-record loss caught by all three write controls')
