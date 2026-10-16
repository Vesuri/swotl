#!/usr/bin/env python3
"""Replay modifiers consume one scan byte per recorded IRQ; no new IRQs."""
import argparse
from test_replay_events import ROOT, DATA, HARNESS, check

CASES = (
    (0x82e, (0x38, 0x2e, 0xae, 0xb8)),
    (0x42e, (0x1d, 0x2e, 0xae, 0x9d)),
    (0x22e, (0x2a, 0x2e, 0xae, 0xaa)),
    (0xb4b, (0x2a, 0x38, 0xe0, 0x4b, 0xe0, 0xcb, 0xb8, 0xaa)),
    (0xe3b, (0x2a, 0x1d, 0x38, 0x3b, 0xbb, 0xb8, 0x9d, 0xaa)),
)


def check_chords(source, broken=False):
    for value, scans in CASES:
        data = DATA.replace('{{2,1,0,0,0}}', '{{2,1,1,' + str(value) + ',1}}')
        assertions = '\n'.join(f'assert(rt_key_ring[{(254+i)%16}] == {scan});'
                               for i, scan in enumerate(scans))
        harness = HARNESS.replace('    G_IF = 1;', f'''
    G_IF = 1;
    if (test_case == 5) {{
        rt_key_tail = 254;
        assert(replay_point(2) == 0);
        assert(rt_key_tail == {(254+len(scans))%256});
        {assertions}
        assert(replay_interrupts == 0 && rt_irq_tail == 0);
        return 0;
    }}
''')
        check(source, broken, data, harness, (5,), (0,))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    source = (ROOT / 'tests/amiga_replay.c').read_text()
    check_chords(source)
    if args.sabotage:
        old = '= modifiers[i];'
        assert old in source
        check_chords(source.replace(old, '= 0;'), True)
