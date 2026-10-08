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


if __name__ == "__main__":
    unittest.main()
