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
import profile_tree as T
import cost_meter as M
import irq_profile as I


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
        # push's, a compared segment load's and a stack run's return label
        # belong to their instruction; out-of-line stubs stay symbols.
        table = "".join(f"{a:08x} g     F .text\t00000000 {n}\n" for a, n in (
            (0x100, "R_00100"), (0x108, "R_00100_np"), (0x110, "R_00100_sr0"),
            (0x118, "R_00100_hr1"), (0x11c, "R_00100_pr0"), (0x11e, "R_00100_gr0"),
            (0x120, "R_00102"), (0x200, "R_00100_sx0"), (0x208, "R_00102_hk0"),
            (0x210, "R_00102_pf0"), (0x218, "R_00102_gx0"), (0x220, "R_00102_kr0"),
            (0x228, "R_00102_kx0")))
        with patch.object(P.subprocess, "run", return_value=SimpleNamespace(stdout=table)):
            self.assertEqual(P.symbols("objdump", "unused"),
                             [(0x100, "R_00100"), (0x120, "R_00102"), (0x200, "R_00100_sx0"),
                              (0x208, "R_00102_hk0"), (0x210, "R_00102_pf0"),
                              (0x218, "R_00102_gx0"), (0x228, "R_00102_kx0")])

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


class SemanticEntries(unittest.TestCase):
    def fixture(self, root):
        # A removed loop-tail jump shares its target, which also has direct entry.
        Path(root, "sample.s").write_text(
            "R_00010:\t; 0000:0010 mov ax, bx\n\tmove.w d3,d0\n"
            "R_00012:\t; 0000:0012 jmp 0x20\n"
            "R_00020:\t; 0000:0020 inc ax\n\taddq.w #1,d0\n"
            "R_00021_bp:\t; 0000:0021 inc bx\n\taddq.w #1,d3\n"
            "R_00030:\t; 0000:0030 jmp 0x20\n\tbra R_00020\n")
        Path(root, "sample.ir").write_text(
            "SWOTL.EXE+00010 0000:0010 89d8 mov ax, bx\n"
            "SWOTL.EXE+00012 0000:0012 eb0c jmp 0x20\n"
            "SWOTL.EXE+00020 0000:0020 40 inc ax\n"
            "SWOTL.EXE+00021 0000:0021 43 inc bx\n"
            "SWOTL.EXE+00030 0000:0030 ebee jmp 0x20\n")
        syms = [(100, "R_00010"), (102, "R_00012"), (102, "R_00020"),
                (104, "R_00021_bp"), (110, "R_00030"),
                (120, "R_00020_irq"), (130, "R_00020_walk")]
        return L.EntryMap(syms, Path(root))

    def test_alias_paths_and_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            counts = {100: 3, 102: 8, 104: 8, 110: 5, 120: 7, 130: 9}
            entries = model.count(counts, {(100, 102): 3, (110, 102): 5})
        self.assertEqual(entries, {"R_00010": 3, "R_00012": 3,
                                  "R_00020": 8, "R_00021_bp": 8, "R_00030": 5})

    def test_missing_edge_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            with self.assertRaisesRegex(ValueError, "incoming"):
                model.count({102: 8}, {(100, 102): 3})
            with self.assertRaisesRegex(ValueError, "ambiguous|unknown"):
                model.count({102: 1}, {(-1, 102): 1})

    def test_fused_conditional(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            p = Path(tmp, "sample.s")
            p.write_text(p.read_text().replace("mov ax, bx", "jne 0x30"))
            p = Path(tmp, "sample.ir")
            p.write_text(p.read_text().replace("89d8 mov ax, bx", "751e jne 0x30"))
            model = L.EntryMap(model.syms, Path(tmp))
            entries = model.count({102: 3}, {(100, 102): 3})
            self.assertEqual(entries["R_00012"], 3)
            self.assertEqual(entries["R_00020"], 3)

    def test_lowering_report_keeps_helper_costs_not_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            pcs = P.np.array([100, 102, 104, 110, 102, 120, 130])
            profile = dict(fields=[(14, 0, pcs, P.np.array([2] * 7))])
            output = io.StringIO()
            with patch.object(sys, "argv", ["lowering_cost", "unused", "unused", "--gen", tmp]), \
                    patch.object(P, "decode", return_value=profile), \
                    patch.object(P, "symbols", return_value=model.syms), \
                    patch.object(L, "mnemonics", return_value=(
                        {int(pc): ("move.w", "d0,d1") for pc in pcs},
                        {int(pc): 2 for pc in pcs})), patch("sys.stdout", output):
                L.main()
            report = output.getvalue()
            self.assertIn("14 cycles; generated code 100.00%", report)
            self.assertIn("6 guest instructions (5 distinct entry-PC hits, 1 recovered", report)
            self.assertIn("7 68k instructions", report)

    def test_indirect_dispatch_requires_observed_direct_host_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            for filename in ("sample.s", "sample.ir"):
                p = Path(tmp, filename)
                # Only the source at 0030 becomes an indirect guest jump.
                p.write_text(p.read_text().replace("0030 jmp 0x20", "0030 jmp ax")
                             .replace("ebee jmp 0x20", "ffe0 jmp ax"))
            model = L.EntryMap(model.syms, Path(tmp), {110: ("bra.w", "66 <R_00020>")})
            self.assertEqual(model.count({102: 5}, {(110, 102): 5}), {"R_00020": 5})
            model.mn[110] = ("jmp", "(a0)")
            with self.assertRaisesRegex(ValueError, "unknown indirect"):
                model.count({102: 5}, {(110, 102): 5})

    def test_fallthrough_wraps_guest_ip(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "wrap.ir").write_text(
                "SWOTL.EXE+1FFFF 1000:FFFF 89d8 mov ax, bx\n"
                "SWOTL.EXE+10001 1000:0001 40 inc ax\n")
            model = L.EntryMap([(100, "R_1FFFF"), (102, "R_10001")], Path(tmp))
            self.assertEqual(model.next["R_1FFFF"], ["R_10001"])

    def test_bp_exit_to_normal_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            syms = [(a, n + "_bp" if n == "R_00010" else n) for a, n in model.syms]
            p = Path(tmp, "sample.s")
            p.write_text(p.read_text().replace("R_00010:", "R_00010_bp:"))
            model = L.EntryMap(syms, Path(tmp))
            self.assertEqual(model.count({102: 2}, {(100, 102): 2}),
                             {"R_00012": 2, "R_00020": 2})

    def test_field_boundaries_and_unknown_start(self):
        fields = [(0, 0, P.np.array([100]), None),
                  (0, 0, P.np.array([P.IRQ_MARKER, 102, 110, P.IRQ_MARKER, 102]), None)]
        self.assertEqual(L.incoming_edges(fields, {102}), {(100, 102): 1, (110, 102): 1})
        self.assertEqual(L.incoming_edges([(0, 0, P.np.array([102]), None)], {102}),
                         {(-1, 102): 1})

    def test_host_interrupt_does_not_replace_guest_predecessor(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            model.syms.append((140, "runtime"))
            model.addrs.append(140)
            model.names.append("runtime")
            fields = [(0, 0, P.np.array([100, P.IRQ_MARKER, 0xf80010,
                                        140, P.NO_PC, 0xf80020, 102]), None)]
            self.assertEqual(L.incoming_edges(fields, {102}, model), {(100, 102): 1})
            self.assertEqual(model.count({102: 1}, L.incoming_edges(fields, {102}, model)),
                             {"R_00012": 1, "R_00020": 1})

    def test_two_semantic_paths_to_one_host_address_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            model.next["R_00010"] = ["R_00012", "R_00020"]
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                model.count({102: 1}, {(100, 102): 1})

    def test_far_jump_and_zero_code_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = self.fixture(tmp)
            p = Path(tmp, "sample.ir")
            p.write_text(p.read_text().replace("eb0c jmp 0x20", "ea20000000 jmpf 0x0:0x20"))
            model = L.EntryMap(model.syms, Path(tmp))
            entries = model.count({102: 3}, {(100, 102): 3})
            self.assertEqual(entries, {"R_00012": 3, "R_00020": 3})
            # A second no-code instruction on the path must count once too.
            model.groups[102].insert(1, "R_00017")
            model.next["R_00012"] = ["R_00017"]
            model.next["R_00017"] = ["R_00020"]
            entries = model.count({102: 3}, {(100, 102): 3})
            self.assertEqual(entries, {"R_00012": 3, "R_00017": 3, "R_00020": 3})


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

    def test_packed_far_return_check_roles(self):
        dis = """00000000 <R_00100>:
       0: cmp.l #305419896,d7
       6: bne.w 40 <rt_ret_far_mismatch>
       a: cmp.w #4660,d7
       e: bne.w 50 <rt_ret_mismatch>
      12: cmp.l #305419896,d7
      18: bne.w 60 <R_00200>
"""
        with patch.object(P.subprocess, 'run', return_value=SimpleNamespace(stdout=dis)):
            roles = P.roles('objdump', 'unused')
        for addr in (0, 6, 10, 14):
            self.assertEqual(roles[addr], 'return check')
        for addr in (18, 24):
            self.assertEqual(roles[addr], 'other')


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


def capture(path, fields, base=0):
    """Barto capture of fields of (pc, cost, a7) records (tools/profile_tree.py).
    base > 0: absolute program PCs over a first hunk at base (the native build)."""
    import numpy as np
    w = [len(fields), 1, base] + [0] * 4 + [0, 0, 0] + [28375160, 128]
    for recs in fields:
        trace = []
        for pc, cost, a7 in recs:
            regs = [0] * 17
            regs[15] = a7
            if base and pc is not None and pc < 0xF80000:
                pc += base
            trace += ([pc] if pc is not None else []) + [0xFFFFFFFF - cost] + regs
        w += [0, 0, 0, 0, 0, 0, sum(c for _, c, _ in recs), 0, len(trace)] + trace + [0, 0]
    np.array(w, dtype="<u4").tofile(path)


class ProfileTree(unittest.TestCase):
    SYMS = [(0x100, "R_00100"), (0x110, "R_00110"), (0x200, "R_00200"),
            (0x300, "R_044E2"), (0x400, "fm_field"), (0x500, "rt_irq")]
    ENTRIES = {"SWOTL.EXE": [0x100, 0x200, 0x44E2]}
    # frame; A; A body; B (called by A); guest IRQ; fm_field inside the IRQ |
    # hardware interrupt record; back in B; back in A; frame (closes A)
    FIRST = [(0x300, 1, 0x1004), (0x100, 10, 0x1000), (0x110, 5, 0x1000),
             (0x200, 7, 0xFFC), (0x500, 3, 0xFF8), (0x400, 4, 0xFF4)]
    SECOND = [(0x200, 2, 0x200100), (0x200, 6, 0xFFC), (0x110, 5, 0x1000),
              (0x300, 1, 0x1004)]

    def run_tree(self, captures, base=0):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(T.P, "symbols", return_value=self.SYMS), \
                patch.object(T.P, "routine_entries", return_value=self.ENTRIES):
            paths = []
            for k, fields in enumerate(captures):
                paths.append(Path(tmp, f"p{k}.bin"))
                capture(paths[-1], fields, base)
            return T.analyse("unused", paths, Path(tmp), "objdump", "R_044E2")

    def check(self, d):
        incl, own = dict(d["incl"]), dict(d["own"])
        self.assertEqual(d["total"], 44)
        self.assertEqual(d["frames"], 2)
        self.assertEqual(incl, {"SWOTL.EXE+00100": 33, "SWOTL.EXE+00200": 13, "fm_field": 4})
        self.assertEqual(d["edges"], [["SWOTL.EXE+00100", "SWOTL.EXE+00200", 13]])
        self.assertEqual(own["SWOTL.EXE+00100"], 20)
        self.assertEqual(own["SWOTL.EXE+00200"], 15)
        self.assertEqual(own["rt_irq"], 3)
        self.assertEqual(d["open_scopes"], [])

    def test_scopes_carry_across_consecutive_captures(self):
        self.check(self.run_tree([[self.FIRST], [self.SECOND]]))

    def test_one_capture_two_fields(self):
        self.check(self.run_tree([[self.FIRST, self.SECOND]]))

    def test_absolute_pcs_of_the_native_build(self):
        self.check(self.run_tree([[self.FIRST], [self.SECOND]], base=0x219CA8))

    def test_absolute_pc_below_the_hunk_is_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "p.bin")
            capture(path, [[(0x100, 3, 0x1000), (0xF80010, 2, 0x1000)]], base=0x219CA8)
            pcs, _, _ = next(T.records(path))
        self.assertEqual(pcs, [0x100, 0xF80010])
        rel = T.P.hunk_relative([0x219CA8 + 4, 0x2188A0, 0xF80010, T.P.IRQ_MARKER, T.P.NO_PC], 0x219CA8)
        self.assertEqual(rel.tolist(), [4, T.P.OUTSIDE, 0xF80010, T.P.IRQ_MARKER, T.P.NO_PC])
        self.assertEqual(T.P.hunk_relative([4, 0x100], 0x219CA8).tolist(), [4, 0x100])

    def test_record_without_pc(self):
        d = self.run_tree([[[(0x300, 1, 0x1004), (None, 9, 0x1004)]]])
        self.assertEqual(dict(d["own"])["<no PC>"], 9)


IRQ_DIS = "".join(f"{a:08x} <{n}>:\n" + "".join(f"    {pc:x}:\t4e71           \t{op}\n" for pc, op in body) + "\n"
                  for a, n, body in (
    (0x100, "R_00100", [(0x100, "nop"), (0x104, "tst.b 9(a6)"), (0x108, "bne.w 110 <R_00100_irq>"),
                        (0x10c, "nop"), (0x110, "jsr 500 <rt_irq>"), (0x114, "nop")]),
    (0x500, "rt_irq", [(0x500, "nop"), (0x502, "nop"), (0x504, "nop"), (0x506, "rts")]),
    (0x520, "deliver_guest", [(0x520, "nop"), (0x530, "nop")]),
    (0x600, "SPZ_007CC", [(0x600, "nop"), (0x602, "nop")]),
    (0x700, "rt_video_refresh", [(0x700, "nop"), (0x704, "nop")]),
    (0x720, "plat_service", [(0x720, "nop"), (0x722, "nop")]),
    (0x740, "present", [(0x740, "nop"), (0x742, "nop")]), (0x760, "plat_present", [(0x760, "nop")]),
    (0x780, "fm_field", [(0x780, "nop")])))


class IrqProfile(unittest.TestCase):
    """irq-plan I1: interrupt-path scopes per call, stack depth, poll share."""
    # guest; poll test and taken bne; stub; rt_irq: refresh (plat_service, a
    # hardware interrupt record, tail-called present > plat_present, a branch
    # inside present opening nothing), deliver_guest (guest handler deeper, a
    # poll in it delivering: nested rt_irq, not net), the loop back to rt_irq (no new scope), a second
    # delivery; back in the guest | a second field: a poll not taken.
    FIRST = [(0x100, 2, 0x1000), (0x104, 1, 0x1000), (0x108, 1, 0x1000), (0x110, 3, 0x1000),
             (0x500, 2, 0xFFC), (0x700, 1, 0xFF8), (0x720, 4, 0xFF4), (0x722, 2, 0xFF0),
             (0x900, 50, 0x200100), (0x704, 1, 0xFF8), (0x740, 3, 0xFF8), (0x742, 1, 0xFF8), (0x760, 5, 0xFF4),
             (0x502, 1, 0xFFC), (0x520, 2, 0xFF8), (0x600, 10, 0xFF4), (0x602, 5, 0xFE8),
             (0x500, 4, 0xFE4), (0x502, 2, 0xFE0), (0x530, 1, 0xFF8), (0x504, 1, 0xFFC), (0x500, 1, 0xFFC), (0x520, 3, 0xFF8),
             (0x504, 1, 0xFFC), (0x506, 1, 0xFFC), (0x114, 1, 0x1000)]
    SECOND = [(0x104, 1, 0x1000), (0x108, 1, 0x1000)]

    # I6: a CIA tick that runs the handler at interrupt level (rt_irq_interrupt
    # > deliver_guest > SPAZ, supervisor stack; an IRQ transition marker before
    # deliver_guest and a branch back to its start open nothing), then two that post and the next poll delivers both in user mode
    # (in order).
    ASYNC = [(0x100, 2, 0x1000), (0x800, 1, 0x200100), (0x840, 2, 0x2000FC), (P.IRQ_MARKER, 1, 0x2000F8),
             (0x520, 3, 0x2000F8),
             (0x600, 5, 0x2000F4), (0x530, 1, 0x2000F8), (0x844, 1, 0x2000FC), (0x840, 1, 0x2000FC), (0x802, 1, 0x200100),
             (0x104, 1, 0x1000), (0x108, 1, 0x1000), (0x800, 1, 0x200100), (0x10c, 1, 0x1000),
             (0x800, 1, 0x200100), (0x110, 1, 0x1000), (0x500, 2, 0xFFC), (0x520, 4, 0xFF8),
             (0x530, 1, 0xFF8), (0x504, 1, 0xFFC), (0x500, 1, 0xFFC), (0x520, 3, 0xFF8),
             (0x506, 1, 0xFFC), (0x114, 1, 0x1000)]
    DIS = IRQ_DIS + "".join(f"{a:08x} <{n}>:\n" + "".join(f"    {pc:x}:\t4e71           \tnop\n" for pc in body) + "\n"
                            for a, n, body in ((0x800, "cia_tick", (0x800, 0x802)),
                                               (0x840, "rt_irq_interrupt", (0x840, 0x844))))

    def run_profile(self, fields=None, dis=IRQ_DIS):
        p = M.Program.__new__(M.Program)
        syms = [(int(l[:8], 16), l[10:-2]) for l in dis.splitlines() if l.endswith(">:")]
        p.init(dis, syms, set())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "p.bin")
            capture(path, fields or [self.FIRST, self.SECOND])
            return I.analyse(p, [path])

    def test_interrupt_level(self):
        d = self.run_profile([self.ASYNC], self.DIS)
        s = {n: (v["calls"], v["total"], v["depth"]) for n, v in d["interrupt_scopes"].items() if v["calls"]}
        self.assertEqual(s, {"rt_irq_interrupt": (1, 13, 8), "deliver_guest": (1, 9, 4)})
        self.assertEqual(d["scopes"]["deliver_guest"]["calls"], 2)
        t = d["tick_latency"]
        self.assertEqual((t["ticks"], t["unmatched"], t["total"], t["max"]), (3, 0, 28, 13))

    def test_scopes_depth_and_polls(self):
        d = self.run_profile()
        self.assertEqual(d["total"], sum(c for _, c, _ in self.FIRST + self.SECOND))
        self.assertEqual(d["polls"], {"generated": {"cost": 4, "tests": 2}})
        keys = ("calls", "total", "max", "depth", "net_total", "net_max", "net_depth")
        s = {n: tuple(v[k] for k in keys) for n, v in d["scopes"].items()}
        self.assertEqual(s, {"rt_irq": (2, 57, 51, 28, 51, 45, 20),
                             "deliver_guest": (2, 27, 24, 24, 21, 18, 16),
                             "rt_video_refresh": (1, 17, 17, 8, 17, 17, 8),
                             "plat_service": (1, 6, 6, 4, 6, 6, 4),
                             "present": (1, 9, 9, 4, 9, 9, 4),
                             "plat_present": (1, 5, 5, 0, 5, 5, 0),
                             "fm_field": (0, 0, 0, 0, 0, 0, 0)})
        self.assertEqual(d["open_scopes"], [])
        self.assertEqual((d["scopes"]["deliver_guest"]["p50"], d["scopes"]["deliver_guest"]["p99"]), (3, 24))
        self.assertEqual([I.pct([5, 1, 4, 2, 3], q) for q in (1, 20, 50, 99, 100)], [1, 1, 3, 5, 5])


if __name__ == "__main__":
    if "--sabotage" in sys.argv:
        for name, old, new in (
                ("guest interrupt charged to the interrupted routine",
                 "if name is None:\n                        continue", "if name is None:\n                        name = 'irq'"),
                ("scope state reset per capture", "for pcs, costs, a7s in records(cap):",
                 "for pcs, costs, a7s in (stack.clear(), records(cap))[1]:"),
                ("supervisor records charged", "or pc == P.IRQ_MARKER:", "and False:")):
            source = inspect.getsource(T.analyse)
            broken = source.replace(old, new)
            assert broken != source, name
            scope = dict(T.__dict__)
            exec(broken, scope)
            with patch.object(T, "analyse", scope["analyse"]):
                result = unittest.TextTestRunner(stream=io.StringIO()).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(ProfileTree))
            assert result.failures and not result.errors, name + " plant escaped"
            print("profile tree: " + name + " plant caught")
        with patch.object(T.P, "hunk_relative", lambda pcs, base: P.np.asarray(pcs, dtype=P.np.int64)):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(ProfileTree))
        assert result.failures or result.errors, "absolute PCs plant escaped"
        print("profile tree: absolute native PCs left unrelocated plant caught")
        for name, old, new in (
                ("scope opened without a call", "a7 == prev - 4 or (", "True or ("),
                ("tail call not opened", "name in TAIL and a7 == prev", "False"),
                ("supervisor records charged", "or pc == P.IRQ_MARKER:", "and False:"),
                ("depth not tracked", "s[3] = min(s[3], a7)", "pass"),
                ("nested delivery counted as net", "if k >= inner:", "if True:"),
                ("interrupt scope opened without a call", "a7 == iprev - 4", "True"),
                ("tick latency from the wrong tick", "posted.pop(0)", "posted.pop()"),
                ("marker taken as an interrupt record", "and pc != P.IRQ_MARKER:", ":")):
            source = inspect.getsource(I.analyse)
            broken = source.replace(old, new)
            assert broken != source, name
            scope = dict(I.__dict__)
            exec(broken, scope)
            with patch.object(I, "analyse", scope["analyse"]):
                result = unittest.TextTestRunner(stream=io.StringIO()).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(IrqProfile))
            assert result.failures and not result.errors, name + " plant escaped"
            print("irq profile: " + name + " plant caught")
        for name, fn, old, new in (
                ("lowering helpers counted", L.is_entry, 'g[3] in ("", "_bp")', 'True'),
                ("zero-code entries omitted", L.EntryMap.count,
                 'for name in paths.pop():', 'for name in paths.pop()[-1:]:'),
                ("missing edges accepted", L.EntryMap.count,
                 '!= n:', '< 0:')):
            import textwrap
            source = textwrap.dedent(inspect.getsource(fn))
            broken = source.replace(old, new)
            assert source != broken
            scope = dict(L.__dict__)
            exec(broken, scope)
            target = L if fn == L.is_entry else L.EntryMap
            with patch.object(target, fn.__name__, scope[fn.__name__]):
                result = unittest.TextTestRunner(stream=io.StringIO()).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(SemanticEntries))
            assert result.failures and not result.errors, name + " plant escaped"
            print("lowering entries: " + name + " plant caught")
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
