"""Assemble alignment regressions at branch-relaxation boundaries."""
from collections import Counter
import inspect
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translator import emit, gen


class Convergence(unittest.TestCase):
    def check_layout(self, lines, wanted):
        texts = {'program.s': ['\tsection .text,code'] + lines}
        before = list(texts['program.s'])
        stats = Counter()
        gen.pad(texts, stats)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, 'program.s')
            source.write_text('\n'.join(texts['program.s']) + '\n')
            obj = Path(tmp, 'program.o')
            subprocess.run([gen.VASM, '-quiet', '-m68020', '-Felf', '-x',
                            '-o', str(obj), str(source)], check=True)
            symbols = gen.symbols(obj.read_bytes())
        for lab, residue in wanted.items():
            self.assertEqual(symbols[lab] % 4, residue, lab)
        self.assertEqual(stats['aligned label'], len(wanted))
        self.assertEqual(stats['alignment missed'], 0)
        self.assertEqual([x for x in before if '; align ' not in x],
                         [x for x in texts['program.s'] if '; align ' not in x])

    def test_forward_branch_grows_when_pad_added(self):
        # Zero/two-byte pads leave L at 128/132 respectively: both wrong.
        self.check_layout(['\tbcc L'] + ['\tnop'] * 62 +
                          ['\trts', emit.ALIGN + '2 L', 'L:', '\trts'], {'L': 2})

    def test_multiple_chunks_and_residues(self):
        self.check_layout(['\trts', emit.ALIGN + '0 A', 'A:', '\tnop', '\trts',
                           emit.ALIGN + '2 B', 'B:', '\trts',
                           emit.ALIGN + '0 C', 'C:', '\trts'], {'A': 0, 'B': 2, 'C': 0})

    def test_unverified_last_pass_fails(self):
        with patch.object(gen, 'PAD_ROUNDS', 1):
            with self.assertRaisesRegex(RuntimeError, 'alignment did not converge'):
                gen.pad({'program.s': ['\tsection .text,code', '\trts',
                                      emit.ALIGN + '0 L', 'L:', '\trts']}, Counter())


if __name__ == '__main__':
    if '--sabotage' in sys.argv:
        source = inspect.getsource(gen.pad)
        broken = source.replace('size[(f, k)] + 2', 'size[(f, k)] ^ 2')
        assert broken != source
        scope = dict(gen.__dict__)
        exec(broken, scope)
        with patch.object(gen, 'pad', scope['pad']):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(Convergence))
        assert not result.wasSuccessful(), 'oscillating pad plant escaped'
        print('alignment: oscillating pad plant caught')
    else:
        unittest.main()
