#!/usr/bin/env python3
"""Cell-walk flag proof and caller-continuation liveness."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from translator import decode, emit, flags, smc


class WalkFlags(unittest.TestCase):
    def test_matched_forms_preserve_flags(self):
        self.assertTrue(smc.preserves_flags(list(smc.FORMS)))

    def test_flag_reader_and_writer_rejected(self):
        for form, text in (("9f", "lahf"), ("f9", "stc")):
            with self.subTest(form=form), patch.dict(smc.FORMS, {form: ([text], None)}):
                self.assertFalse(smc.preserves_flags([form]))

    def test_return_continuation_keeps_carry(self):
        # CALL through a flag-preserving walk, then ADC: carry must survive the
        # call even when the walk itself and the dispatch table read no flags.
        call, after = ("fixture", 0), ("fixture", 2)
        insns = {call: decode.decode(bytes.fromhex("ffd2"), 0),
                 after: decode.decode(bytes.fromhex("11c0"), 2)}
        p = emit.Program.__new__(emit.Program)
        p.succ = {call: [emit.SMC], after: []}
        p.call_site = {call: after}
        p.node_insn = insns.get
        p.dispatch, p.saves = set(), {}
        p.live_in, p.live_out = {}, {}
        p.walk_preserves_flags = True
        p.liveness()
        self.assertEqual(p.live_in[call], {"CF"})
        p.walk_preserves_flags = False
        p.liveness()
        self.assertEqual(p.live_in[call], set(flags.ALL))


if __name__ == "__main__":
    unittest.main()
