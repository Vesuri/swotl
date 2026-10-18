"""Cost meter and label A/B (docs/speed-plan.md M1): static features, block
expansion, the fit and the mix adjustment, on synthetic inputs."""
from collections import Counter
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ab_labels as A  # noqa: E402
import cost_meter as M  # noqa: E402

DIS = """\
00001000 <R_00100>:
    1000:\t3c32 7800      \tmove.w (0,a2,d7.l),d6
    1004:\te05e           \tror.w #8,d6

00001006 <R_00102>:
    1006:\t5341           \tsubq.w #1,d1
    1008:\t66fc           \tbne.s 1006 <R_00102>
    100a:\t4eb9 0000 2000 \tjsr 2000 <rt_irq>
    1010:\t4e75           \trts

00002000 <rt_irq>:
    2000:\t4e75           \trts
"""


class Accesses(unittest.TestCase):
    def test_table(self):
        cases = {
            ("move.w", "(0,a2,d7.l),d6"): (1, 0, 0), ("move.w", "d6,(0,a3,a5.l)"): (0, 1, 0),
            ("ror.w", "#8,d6"): (0, 0, 0), ("addq.b", "#1,-8(a6)"): (1, 1, 0),
            ("tst.b", "-8(a6)"): (1, 0, 0), ("move.w", "152150 <rt_entry_cs>,d6"): (1, 0, 0),
            ("jsr", "1048a <path_of.constprop.0>(pc)"): (0, 1, 0),
            ("movem.l", "d0-d1/a1,-(sp)"): (0, 3, 0), ("movem.l", "(sp)+,d6-d7"): (2, 0, 0),
            ("bfins", "d1,d0,16,8"): (0, 0, 0), ("cmpm.b", "(a4)+,(a5)+"): (2, 0, 0),
            ("addx.w", "-(a4),-(a5)"): (2, 1, 0), ("clr.w", "(0,a3,d7.l)"): (0, 1, 0),
            ("sne", "-3(a6)"): (0, 1, 0), ("seq", "d0"): (0, 0, 0),
            ("bne.l", "3f00 <rt_ret_mismatch>"): (0, 0, 0), ("rts", ""): (1, 0, 0),
            ("lea", "(0,a6,d7.l),a1"): (0, 0, 0), ("mulu.w", "d1,d0"): (0, 0, 1),
            ("neg.w", "(a0)"): (1, 1, 0), ("move.w", "ccr,-2(a6)"): (0, 1, 0),
            ("move.w", "-2(a6),ccr"): (1, 0, 0), ("dbf", "d1,1234 <x>"): (0, 0, 0),
            ("add.w", "d0,(0,a3,d7.l)"): (1, 1, 0), ("cmp.w", "#5,(0,a3,d7.l)"): (1, 0, 0),
        }
        for (op, arg), want in cases.items():
            self.assertEqual(M.accesses(op, arg), want, (op, arg))


class RegisterAliases(unittest.TestCase):
    def test_movem_alias_ranges(self):
        self.assertEqual(M.accesses("movem.w", "d1/a0-a1/a3-a4/a6-sp,-(a6)"), (0, 7, 0))
        self.assertEqual(M.accesses("movem.l", "(sp)+,d0-sp"), (16, 0, 0))
        self.assertEqual(M.accesses("movem.l", "a0-fp,-(sp)"), (0, 7, 0))


class Program(unittest.TestCase):
    def prog(self):
        p = M.Program.__new__(M.Program)
        p.init(DIS, [(0x1000, "R_00100"), (0x1006, "R_00102"), (0x2000, "rt_irq")], set())
        return p

    def test_loop_and_classes(self):
        p = self.prog()
        self.assertEqual(p.feat[0x1006][1:3], [0, 2])     # in the bne.s loop: loop bytes
        self.assertEqual(p.feat[0x1000][1:3], [4, 0])
        self.assertEqual(p.cls[0x1004], "generated")
        self.assertEqual(p.cls[0x2000], "runtime")

    def test_expand(self):
        p = self.prog()
        blocks = Counter({(0x1000, 10): 1, (0x1006, 4): 2, (0x100a, 6): 1, (0x2000, 2): 1})
        taken = Counter({(0x1006, 4): 2, (0x100a, 6): 1})
        n, t = M.expand(p, blocks, taken)
        self.assertEqual(n[0x1006], 3)
        self.assertEqual(n[0x1010], 0)
        self.assertEqual(t, Counter({0x1008: 2, 0x100a: 1}))

    def test_model_taken_split(self):
        coef = {k: 0.0 for k in M.FEATURES}
        coef.update(taken=5.0, loop_taken=1.0, bytes=1.0, loop_bytes=0.5)
        p = self.prog()
        self.assertEqual(M.model_cycles(p.feat[0x1008], 3, 2, coef), 3 * 0.5 * 2 + 2 * 1.0)
        self.assertEqual(M.model_cycles(p.feat[0x100a], 1, 1, coef), 6 + 5.0)


class Fit(unittest.TestCase):
    def test_recovers_non_negative_weights(self):
        rng = np.random.default_rng(1)
        X = rng.uniform(0, 10, (200, 3))
        y = X @ np.array([1.5, 0.0, 3.0]) + rng.normal(0, 0.01, 200)
        X = np.column_stack([X, -X[:, 0]])          # a collinear column that would go negative
        w = M.fit(X, y, ["a", "b", "c", "d"])
        self.assertTrue(all(v >= 0 for v in w.values()))
        self.assertAlmostEqual(w["c"], 3.0, places=2)


class Mix(unittest.TestCase):
    def test_same_and_changed(self):
        a = (Counter(x=100.0, y=50.0), Counter(x=10, y=5))
        self.assertEqual(A.mix_delta(a, a, {"x": 7, "y": 3})[0], 0.0)
        b = (Counter(x=40.0, y=50.0), Counter(x=5, y=5))   # x: 10 -> 8 cycles per execution
        d, den, cov = A.mix_delta(a, b, {"x": 1, "y": 1})
        self.assertAlmostEqual(d, -2 / 20)
        self.assertEqual(cov, 1.0)
        self.assertAlmostEqual(A.mix_delta(a, b, {"x": 1, "y": 1}, {"x"})[0], -0.2)

    def test_normalize(self):
        self.assertEqual(A.normalize("bne.s 1006 <R_00102>"), "bne.s <R_00102>")


class ChangedLabels(unittest.TestCase):
    def test_unchanged_copy_is_not_a_changed_label(self):
        weights = {"R_00100": 10, "__set_flags": 20}
        old = {"R_00100": ("move.w",), "R_00100_bp": ("move.w",),
               "__set_flags": ("btst", "sne", "neg.b")}
        self.assertEqual(A.changed_labels(weights, old, old), set())
        new = dict(old, __set_flags=("bfextu",))
        self.assertEqual(A.changed_labels(weights, old, new), {"__set_flags"})
        new["R_00100_bp"] = ("move.l",)
        self.assertEqual(A.changed_labels(weights, old, new), set(weights))
        del new["R_00100_bp"]
        self.assertEqual(A.changed_labels(weights, old, new), set(weights))


class BitfieldOperands(unittest.TestCase):
    def test_extract_offsets_are_not_memory(self):
        for op in ("bfextu", "bfexts", "bfffo"):
            self.assertEqual(M.accesses(op, "d7,22,1,d6"), (0, 0, 0))
            self.assertEqual(M.accesses(op, "d7,d2,d3,d6"), (0, 0, 0))
            self.assertEqual(M.accesses(op, "(a0),22,1,d6"), (1, 0, 0))
            self.assertEqual(M.accesses(op, "bfe001 <port>,1,1,d0"), (1, 0, 0))
        self.assertEqual(M.accesses("bfins", "d1,d0,16,8"), (0, 0, 0))
        self.assertEqual(M.accesses("bfins", "d1,(a0),16,8"), (1, 1, 0))
        self.assertEqual(M.accesses("bftst", "(a0),16,8"), (1, 0, 0))


class RuntimeLabels(unittest.TestCase):
    def test_explicit_helper_counts_and_excludes_other_runtime(self):
        from unittest.mock import patch
        pcs = np.array([0x2000, 0x2002, 0x2000, 0x2002, 0x3000])
        cost = np.array([3, 4, 3, 4, 9])
        symbols = [(0x2000, "__set_flags"), (0x3000, "other_runtime")]
        with patch.object(A.P, "decode", return_value={"fields": [(23, 0, pcs, cost)]}):
            cycles, calls = A.label_cycles(Path("unused"), symbols, {"__set_flags"})
            self.assertEqual(cycles, Counter(__set_flags=14))
            self.assertEqual(calls, Counter(__set_flags=2))
            self.assertEqual(A.label_cycles(Path("unused"), symbols), (Counter(), Counter()))


class StringLayoutLabels(unittest.TestCase):
    def test_cold_cycles_belong_to_entry_without_extra_executions(self):
        from unittest.mock import patch
        pcs = np.array([0x100, 0x102, 0x200, 0x202, 0x100, 0x102])
        cost = np.array([2, 3, 5, 7, 2, 3])
        for suffix in ("", "_bp"):
            symbols = [(0x100, "R_00100" + suffix),
                       (0x200, "R_00100" + suffix + "_dfback")]
            with patch.object(A.P, "decode", return_value={"fields": [(22, 0, pcs, cost)]}):
                cycles, calls = A.label_cycles(Path("unused"), symbols)
                self.assertEqual(cycles, Counter(R_00100=22))
                self.assertEqual(calls, Counter(R_00100=2))


class InstructionMix(unittest.TestCase):
    def test_repeat_count_does_not_become_a_speed_change(self):
        p = Program().prog()
        counts = [("R_00102", 0, "subq.w", "#1,d1", 100),
                  ("R_00102", 2, "bne.s", "1006 <R_00102>", 100)]
        a = {0x1006: (10, 20), 0x1008: (10, 30)}
        b = {0x1006: (30, 60), 0x1008: (30, 90)}
        self.assertEqual(A.instruction_cycles(a, p, counts, {"R_00102"}),
                         Counter(R_00102=500))
        self.assertEqual(A.instruction_cycles(a, p, counts, {"R_00102"}),
                         A.instruction_cycles(b, p, counts, {"R_00102"}))
        # Real work removal and slower instructions must remain visible.
        fewer = [(lab, off, op, arg, n // 2) for lab, off, op, arg, n in counts]
        self.assertEqual(A.instruction_cycles(b, p, fewer, {"R_00102"}),
                         Counter(R_00102=250))
        b[0x1008] = (30, 120)
        self.assertEqual(A.instruction_cycles(b, p, counts, {"R_00102"}),
                         Counter(R_00102=600))

    def test_missing_samples_and_wrong_code_fail_loudly(self):
        p = Program().prog()
        row = [("R_00102", 0, "subq.w", "#1,d1", 100)]
        for samples in ({}, {0x1006: (0, 0)}):
            with self.assertRaises(ValueError):
                A.instruction_cycles(samples, p, row, {"R_00102"})
        for lab, off, op, arg in (("R_99999", 0, "subq.w", "#1,d1"),
                                  ("R_00102", 0, "addq.w", "#1,d1"),
                                  ("R_00102", 1, "subq.w", "#1,d1")):
            with self.assertRaises(ValueError):
                A.instruction_cycles({0x1006: (10, 20)}, p,
                                     [(lab, off, op, arg, 100)], {lab})

    def test_meter_exports_exact_instruction_counts(self):
        p = Program().prog()
        rows = M.instruction_counts(p, Counter({0x1000: 3, 0x1004: 3, 0x2000: 1}))
        self.assertEqual(rows, [("R_00100", 0, "move.w", "(0,a2,d7.l),d6", 3),
                                ("R_00100", 4, "ror.w", "#8,d6", 3)])


if __name__ == "__main__":
    unittest.main()
