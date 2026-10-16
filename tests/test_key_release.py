"""Key-release eligibility at repeated triggers, independently of IRQ delivery."""
import argparse
import tempfile
from pathlib import Path
import host_run as H


def check():
    with tempfile.TemporaryDirectory(prefix='swotl-key-release-') as directory:
        trace = Path(directory)
        events = ('icount,kind,module,offset,detail\n'
                  '10,svc,SWOTL.EXE,0x044e0,33\n'
                  '14,svc_ret,SWOTL.EXE,0x044e2,33\n'
                  '17,key_up,SWOTL.EXE,0x044e9,n skip=1\n'
                  '20,irq,SWOTL.EXE,0x044e9,09 svc=2 hits=0\n')
        (trace / 'events.csv').write_text(events)
        irqs, releases = H.reference_inputs(trace, exact_releases=True)
        assert irqs == [(2, 'R_044E9', 0, 9)] and releases == [(2, 1)]
        assert H.reference_inputs(trace)[1] == [2]  # existing Amiga replay API
        for value in ('-1', 'wrong'):
            (trace / 'events.csv').write_text(events.replace('skip=1', 'skip=' + value))
            try:
                H.reference_inputs(trace, exact_releases=True)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid release count accepted')

    # Original c56: service return visits the snapshot target before key_up.
    gate = H.KeyRelease((2, 1))
    assert not gate.ready(2, True), 'early snapshot'
    assert gate.ready(10, True), 'next loop'
    # Several visits to the same address in one service interval.
    gate = H.KeyRelease((4, 2))
    assert not gate.ready(3, True)
    assert not gate.ready(4, False)
    assert not gate.ready(4, True), 'first held visit'
    assert not gate.ready(4, True), 'second held visit'
    assert gate.ready(4, True), 'first eligible visit'
    # A key trigger is eligible on the release instruction; a snapshot is not.
    assert H.KeyRelease((4, 0)).ready(4, True), 'same-instruction key'
    gate = H.KeyRelease((4, 1))
    assert not gate.ready(4, True), 'same-instruction snapshot'
    assert gate.ready(4, True)
    # Key presses start a fresh held-visit count, even in the same interval.
    for _ in range(2):
        gate = H.KeyRelease((4, 1))
        assert not gate.ready(4, True)
        assert gate.ready(4, True)
    legacy = H.KeyRelease(4)
    assert not legacy.ready(3, True)
    assert legacy.ready(4, False)
    print('key releases: parsing, repeated visits, service reset, key/snapshot order and legacy API pass')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    check()
    if args.sabotage:
        original = H.KeyRelease.ready
        for broken, expected in ((lambda self, n, target: n >= self.service, 'early snapshot'),
                                 (lambda self, n, target: n > self.service, 'first eligible visit')):
            H.KeyRelease.ready = broken
            try:
                try:
                    check()
                except AssertionError as error:
                    assert error.args == (expected,), error
                else:
                    raise AssertionError('release boundary fault escaped')
            finally:
                H.KeyRelease.ready = original
        print('sabotage: early release and delayed release caught')
