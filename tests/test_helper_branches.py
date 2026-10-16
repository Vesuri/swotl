"""Explicit helper branch sizes preserve vasm's original machine code."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translator.support import HELPERS, equates
from translator.gen import VASM


def check(sabotage=False):
    relaxed = re.sub(r'(?m)^(\tb\w+)\.s\t', r'\1\t', HELPERS)
    assert relaxed != HELPERS, 'no fixed helper branches exercised'
    fixed = HELPERS
    if sabotage:
        fixed = fixed.replace('\tbeq.s\t', '\tbne.s\t', 1)
        assert fixed != HELPERS
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        for base in (0x400000, 0x400002, 0x5a5d90, 0x7ffffe):
            for pending in (0x7ffe, 0x210800):
                outputs = []
                for name, body in [('relaxed', relaxed), ('fixed', fixed)]:
                    source = Path(tmp, name + '.s')
                    binary = source.with_suffix('.bin')
                    source.write_text(equates() + f'rt_irq_pending equ ${pending:x}\n'
                                      + f'\torg ${base:x}\n' + body)
                    subprocess.run([VASM, '-quiet', '-m68020', '-Fbin', '-o',
                                    str(binary), str(source)], check=True)
                    outputs.append(binary.read_bytes())
                assert outputs[0] == outputs[1], 'helper encoding differs'
                count += 1
    print(f'helper branch sizing: {count} full machine-code comparisons pass')


if __name__ == '__main__':
    check()
    if '--sabotage' in sys.argv:
        try:
            check(True)
        except AssertionError as exc:
            assert str(exc) == 'helper encoding differs', exc
        else:
            raise AssertionError('changed branch condition escaped')
        print('sabotage: changed helper branch condition caught')
