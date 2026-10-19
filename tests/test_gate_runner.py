"""Early sabotage completion must mean a catch, never an error or exhaustion."""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import m68k_sabotage as S
import x86_sabotage as X


def harness():
    h = object.__new__(S.PlantHarness)
    h.bad = []
    return h


class GateRunner(unittest.TestCase):
    def test_isolated_launcher_and_exit_status(self):
        root = Path(__file__).resolve().parent.parent
        runs = []
        try:
            for status in (0, 7):
                code = ('import os,json,sys; '
                        'print(json.dumps({k:os.environ[k] for k in '
                        "('FSUAE_RUN','DEBUG_PORT','FSUAE_CLAIM_STRICT','FSUAE_PORT_PINNED')})); "
                        f'sys.exit({status})')
                result = subprocess.run([sys.executable, str(root / 'tools/gate_launch.py'),
                                         sys.executable, '-c', code], capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)
                env = json.loads(result.stdout.splitlines()[-1])
                run = (root / 'amiga' / env['FSUAE_RUN']).resolve()
                runs.append(run)
                self.assertEqual(run.parent, root / 'tmp')
                self.assertEqual(env['FSUAE_CLAIM_STRICT'], '1')
                self.assertEqual(env['FSUAE_PORT_PINNED'], '1')
                self.assertTrue(0 < int(env['DEBUG_PORT']) < 65536)
            self.assertNotEqual(*runs)
        finally:
            for run in runs:
                shutil.rmtree(run)

    def test_x86_case(self):
        h = object.__new__(X.PlantHarness)
        h.bad = []
        with patch.object(X.X.Harness, 'case', lambda h: None):
            h.case()
        with patch.object(X.X.Harness, 'case', lambda h: h.bad.append('wrong CF')):
            with self.assertRaises(X.CaughtCase):
                h.case()

    def test_completed_batch_only(self):
        h = harness()
        def flush(h):
            h.bad.append('independent comparison failed')
        with patch.object(S.D.Harness, 'flush', flush):
            with self.assertRaises(S.CaughtBatch) as caught:
                S.PlantHarness.flush(h)
        self.assertIs(caught.exception.args[0], h)

    def test_clean_batch_continues(self):
        with patch.object(S.D.Harness, 'flush', lambda h: None):
            S.PlantHarness.flush(harness())

    def test_assembly_error_is_not_a_catch(self):
        with patch.object(S.D.Harness, 'flush', side_effect=RuntimeError('assembler failed')):
            with self.assertRaises(RuntimeError):
                S.PlantHarness.flush(harness())

    def test_program_batch(self):
        S.completed_program_batch(42, [])
        with self.assertRaises(S.CaughtProgram) as caught:
            S.completed_program_batch(43, ['wrong register'])
        self.assertEqual(caught.exception.args, (1, 43, 0, 0))

    def test_missing_catch_fails(self):
        plants = [('caught', lambda: None, 'boundary'), ('missed', lambda: None, 'forms')]
        for missed in (False, True):
            def plant(k):
                return (0 if missed and k == 1 else 1), 512, 0, 512
            with patch.object(S, 'SABOTAGE', plants), patch.object(S, 'plant', plant), \
                    patch.object(S, 'ProcessPoolExecutor', ThreadPoolExecutor), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(S.main(), int(missed))
            self.assertEqual('not caught: missed' in out.getvalue(), missed)


if __name__ == '__main__':
    unittest.main()
