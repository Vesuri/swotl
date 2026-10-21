"""Compute entries that modify their executed code must fail loudly."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import compute_oracle as O


def check():
    cases = [
        ('current', '2ec606000190', True),
        ('future', '2ec60606019090', True),
        ('return', '2ec606060190c3', True),
        ('past', '902ec606000190', True),
        ('data', 'c606000190', False),
    ]
    for name, encoded, reject in cases:
        code = bytes.fromhex(encoded)
        ram = bytearray(O.X.RAM)
        ram[0x20100:0x20100+len(code)] = code
        regs = dict(ax=0, bx=0, cx=0, dx=0, si=0, di=0, sp=0x1000, bp=0,
                    cs=0x2000, ip=0x100, ds=0x3000, es=0x3000, ss=0x4000, flags=0x7202)
        try:
            result = O.run(bytes(ram), regs, (0x2000, 0x100+len(code)-(name == 'return')))
        except ValueError as error:
            assert reject and str(error) == 'oracle self-modifying code entry', (name, error)
        else:
            assert not reject, (name, 'self-modification was admitted')
            assert result['history'] == {0x30100: [0x90]}
    return len(cases)


if __name__ == '__main__':
    print('compute code-write boundary:', check(), 'controls pass', flush=True)
    if '--sabotage' in sys.argv:
        with patch.object(O, 'check_code_writes', lambda written, fetched: None):
            try:
                check()
            except AssertionError as error:
                print('removed code-write rejection caught:', error, flush=True)
            else:
                raise AssertionError('code-write rejection plant survived')
