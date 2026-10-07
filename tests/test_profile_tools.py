"""Tooling regressions: independent of guest semantics and timing."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
