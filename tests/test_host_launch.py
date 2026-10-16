"""DOS shell launch inputs, checked before executing the first guest instruction."""
import argparse
from pathlib import Path
import host_run as H


def check(sabotage=False):
    root = Path(__file__).resolve().parents[1]
    for launch, name in [('', 'm0-entry'), ('swotl', 'c26-exit-usage')]:
        h = H.Host(H.image.M.REF)
        script = {'launch': launch, 'keys': [], 'snapshots': [H.trigger('SWOTL.EXE+164f2')],
                  'irqs': [], 'releases': []}
        h.run(script, 30)
        assert h.stopped_at == 'R_164F2', h.stopped_at
        psp = (h.u32(h.syms['load_segment']) - 0x10) * 16
        actual = h.gmem(psp, 256)
        expected = (root / f'tmp/pc-runs/ref-{name}/trace/snap-{name}-0/ram.bin').read_bytes()[psp:psp+256]
        if sabotage and launch:
            actual = actual[:0x80] + bytes([14]) + actual[0x81:]
        assert actual[0x5c:0x7c] == expected[0x5c:0x7c], (launch, 'FCBs')
        assert actual[0x80:] == expected[0x80:], (launch, 'command tail')
    h = H.Host(H.image.M.REF)
    try:
        h.run({'launch': 'swotl unsupported'}, 30)
    except ValueError:
        pass
    else:
        raise AssertionError('unsupported launch silently accepted')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    if args.sabotage:
        check()
        try:
            check(True)
        except AssertionError as exc:
            assert exc.args == (('swotl', 'command tail'),), exc
        else:
            raise AssertionError('wrong command-tail length escaped')
        print('sabotage: wrong command-tail length caught')
    else:
        check()
        print('host launch: default and no-argument PSP inputs match DOSBox-X')
