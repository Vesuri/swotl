"""Tooling regressions: independent of guest semantics and timing."""
import os
import inspect
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import profile_report as P
import lowering_cost as L


class ProfileTools(unittest.TestCase):
    def test_entries_ignore_working_directory(self):
        old = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                entries = P.routine_entries(P.DEFAULT_GEN)
                self.assertIn(0x06A4D, entries["SWOTL.EXE"])
            finally:
                os.chdir(old)

    def test_missing_entries_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                P.routine_entries(Path(tmp))

    def test_call_sizes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "sample.s").write_text(
                "; jsr R_99999\n\tjsr R_00100\n\tbsr.w FLT_00200\n"
                "\tjsr rt_irq\n\tbsr.l R_00100\n")
            self.assertEqual(P.routine_entries(Path(tmp)),
                             {"SWOTL.EXE": [0x100], "FLIGHT.OVL": [0x200]})

    def test_labels_inside_an_instruction(self):
        # A poll's fall-through, a segment check's, a CS store hook's, a far
        # push's and a compared segment load's return label belong to their
        # instruction; out-of-line stubs stay symbols.
        table = "".join(f"{a:08x} g     F .text\t00000000 {n}\n" for a, n in (
            (0x100, "R_00100"), (0x108, "R_00100_np"), (0x110, "R_00100_sr0"),
            (0x118, "R_00100_hr1"), (0x11c, "R_00100_pr0"), (0x11e, "R_00100_gr0"),
            (0x120, "R_00102"), (0x200, "R_00100_sx0"), (0x208, "R_00102_hk0"),
            (0x210, "R_00102_pf0"), (0x218, "R_00102_gx0")))
        with patch.object(P.subprocess, "run", return_value=SimpleNamespace(stdout=table)):
            self.assertEqual(P.symbols("objdump", "unused"),
                             [(0x100, "R_00100"), (0x120, "R_00102"), (0x200, "R_00100_sx0"),
                              (0x208, "R_00102_hk0"), (0x210, "R_00102_pf0"),
                              (0x218, "R_00102_gx0")])

    def test_string_direction_continuation(self):
        table = "".join(f"{a:08x} g     F .text\t00000000 {n}\n" for a, n in (
            (0x100, "R_00100"), (0x110, "R_00100_dfend"),
            (0x200, "R_00100_dfback")))
        with patch.object(P.subprocess, "run", return_value=SimpleNamespace(stdout=table)):
            self.assertEqual(P.symbols("objdump", "unused"),
                             [(0x100, "R_00100"), (0x200, "R_00100_dfback")])

    def test_dispatch_continuation(self):
        table = "".join(f"{a:08x} g     F .text\t00000000 {n}\n" for a, n in (
            (0x100, "R_00100"), (0x110, "R_00100_dispatchend"),
            (0x200, "R_00100_dispatchcold")))
        with patch.object(P.subprocess, "run", return_value=SimpleNamespace(stdout=table)):
            self.assertEqual(P.symbols("objdump", "unused"),
                             [(0x100, "R_00100"), (0x200, "R_00100_dispatchcold")])

    def test_encoded_sizes_and_symbol_aliases(self):
        dis = """       0:\t7000           \tmoveq #0,d0
       2:\t203c 0000 0000 \tmove.l #0,d0
       8:\t60ff 0000 0008 \tbra.l 12 <R_00102>
       e:\t4e75           \trts
"""
        mn, sizes = L.parse_disassembly(dis)
        self.assertEqual(sizes, {0: 2, 2: 6, 8: 6, 14: 2})
        syms = [(0, "R_00100"), (0, "R_00101"), (8, "R_00102"),
                (14, "runtime")]
        self.assertEqual(L.static_bytes(syms, sizes),
                         {"R_00100": 8, "R_00101": 8, "R_00102": 6})
        self.assertEqual(mn[8][0], "bra.l")


class CurrentRoles(unittest.TestCase):
    def test_current_poll_state_and_return_forms(self):
        dis = """00000000 <R_00100>:
       0: tst.b 9(a6)
       4: bne.w 40 <R_00100_irq>
       8: move.w 15(a6),ccr
       c: move.b d0,16(a6)
      10: move.w 1(a6),d7
      14: move.b (0,a6),d0
      18: move.b -8(a6),d0
      1c: cmp.w #123,d7
      20: bne.s 50 <R_rm0>
      22: jsr 80 <R_00200>
      28: cmp.w d0,d1
      2a: ror.w #8,d0
00000040 <R_00100_irq>:
      40: move.l #123,d7
      46: move.l #999,d6
      4c: jsr 100 <rt_irq>
      52: bra.w 8 <R_00100_np>
00000056 <R_00102>:
      56: move.l d0,d1
"""
        with patch.object(P.subprocess, 'run', return_value=SimpleNamespace(stdout=dis)):
            roles = P.roles('objdump', 'unused')
        for addr in (0, 4, 0x40, 0x46, 0x4c, 0x52):
            self.assertEqual(roles[addr], 'poll point', hex(addr))
        for addr in (8, 12, 16):
            self.assertEqual(roles[addr], 'state block (flags, segments)', hex(addr))
        for addr in (0x14, 0x18, 0x22, 0x28, 0x56):
            self.assertEqual(roles[addr], 'other', hex(addr))
        for addr in (0x1c, 0x20):
            self.assertEqual(roles[addr], 'return check', hex(addr))
        self.assertEqual(roles[0x2a], 'byte swap')


class ModuleCounts(unittest.TestCase):
    def report(self, rows, extra=()):
        # Independent synthetic trace: (host PC, symbol, visits, cycles/visit).
        # Body PCs have no symbol and must not count as instruction entries.
        pcs, costs = [], []
        for pc, _, visits, cost in rows:
            pcs.extend([pc] * visits)
            costs.extend([cost] * visits)
        profile = dict(sections=[0], clock=1, unit=1,
                       fields=[(sum(costs), 0, P.np.array(pcs), P.np.array(costs))])
        syms = [(pc, name) for pc, name, _, _ in rows if name]
        output = io.StringIO()
        with patch.object(sys, "argv", ["profile_report", "unused", "unused", *extra]), \
                patch.object(P, "decode", return_value=profile), \
                patch.object(P, "symbols", return_value=syms), \
                patch.object(P, "roles", return_value={}), \
                patch.object(P, "routine_entries", return_value={"FLIGHT.OVL": [0x100]}), \
                patch("sys.stdout", output):
            P.main()
        return output.getvalue()

    def test_normal_and_bp_entries_add_without_body_or_stub_visits(self):
        rows = [(0x100, "FLT_00100", 2, 4), (0x104, None, 5, 2),
                (0x120, "FLT_00102_bp", 3, 6), (0x124, None, 7, 2)]
        # Prefix matches such as _bp* would count guards and helper entries.
        suffixes = ("_bpg", "_bpr", "_irq", "_bp_irq", "_sx0", "_hk0",
                    "_walk", "_walk_go", "_bp_sx0")
        rows += [(0x200 + k * 16, "FLT_00102" + suffix, 1, 1)
                 for k, suffix in enumerate(suffixes)]
        rows += [(0x300, "R_00100", 4, 2)]
        report = self.report(rows, ("--count", "FLT_00102_bp"))
        self.assertRegex(report, r"FLIGHT\.OVL  5  11\.8\n")
        self.assertRegex(report, r"SWOTL\.EXE  4  2\.0\n")
        self.assertIn("67 cycle units", report)  # cycles include all helpers
        self.assertIn("FLT_00102_bp executions per field: [3]  total 3", report)

    def test_copy_only_module(self):
        report = self.report([(0x100, "FLT_00100_bp", 7, 6), (0x104, None, 7, 2)])
        self.assertRegex(report, r"FLIGHT\.OVL  7  8\.0\n")

    def test_helper_only_module_does_not_invent_guest_entries(self):
        report = self.report([(0x100, "FLT_00100_bpg", 2, 3),
                              (0x120, "FLT_00100_bp_irq", 4, 2)])
        self.assertRegex(report, r"FLIGHT\.OVL  0  14\.0\n")


if __name__ == "__main__":
    if "--sabotage" in sys.argv:
        source = inspect.getsource(P.roles)
        broken = source.replace('arg in ("9(a6)", "(9,a6)")', 'arg in ("-8(a6)", "(-8,a6)")')
        assert broken != source
        scope = dict(P.__dict__)
        exec(broken, scope)
        with patch.object(P, "roles", scope["roles"]):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(CurrentRoles))
        assert len(result.failures) == 1 and not result.errors, "stale poll-offset plant escaped"
        print("profile roles: stale poll-offset plant caught")
        source = inspect.getsource(P.main)
        for name, replacement, failures in (
                ("BP copies omitted", 'not g.group(3)', 2),
                ("helper labels counted", 'True', 2)):
            broken = source.replace('g.group(3) in ("", "_bp")', replacement)
            assert broken != source
            scope = dict(P.__dict__)
            exec(broken, scope)
            # Keep the module globals so the trace/ELF fixtures also reach
            # the planted main, rather than launching real external tools.
            mutant = type(P.main)(scope["main"].__code__, P.__dict__)
            with patch.object(P, "main", mutant):
                result = unittest.TextTestRunner(stream=io.StringIO()).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(ModuleCounts))
            assert len(result.failures) == failures and not result.errors, name + " plant escaped"
            print("profile module counts: " + name + " plant caught")
    else:
        unittest.main()
