"""R32 structural fences; complete paths are checked by m68k_blocks."""
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translator import emit

PAIRS = dict(emit.INVERT)


def check():
    count = 0
    for cc, inverse in PAIRS.items():
        for suffix in ('', '.s', '.w'):
            for gap, allowed in (([], True), (['\t; comment'], True),
                                 (['\ttst.b G_IRQ(a6)'], False),
                                 (['other:'], False), (['\tjsr rt_replay_point'], False)):
                lines = ['C:', f'\tb{cc}{suffix} S', 'J:'] + gap + ['\tbra T', 'S:', '\tnop', 'T:', '\trts']
                before = list(lines)
                got = emit.fuse_jumps(lines, {'J': ('C', 'S', 'T')}, Counter())
                assert bool(got) == allowed, (before, lines, got)
                if allowed:
                    assert lines == ['C:', f'\tb{inverse} T', 'J:'] + gap + ['S:', '\tnop', 'T:', '\trts']
                    assert got == {'C': 'J'}
                else:
                    assert lines == before
                count += 1
    for before in (["C:", '\tbne S', 'J:', '\tbra T', '\tnop', 'S:'],
                   ["C:", '\tbne S', 'J:', '\tbra U', 'S:'],
                   ["C:", '\tbne S', 'J:', '\tbra T', 'X:']):
        lines = list(before)
        assert not emit.fuse_jumps(lines, {'J': ('C', 'S', 'T')}, Counter())
        assert lines == before
        count += 1
    lines = ['C:', '\tbne S', 'J:', '\tbra T', 'S:']
    before = list(lines)
    assert not emit.fuse_jumps(lines, {}, Counter())
    assert lines == before       # independent entry: not a proved candidate
    return count + 1


def check_aliases(relocate):
    for target_before in (False, True):
        prefix = ['T:', '\trts'] if target_before else []
        suffix = [] if target_before else ['T:', '\trts']
        lines = prefix + ['C:', '\tbeq T', 'J:', 'S:', '\tnop'] + suffix
        instructions = [x for x in lines if x.startswith('\t')]
        relocate(lines, {'C': 'J'}, {'J': ('C', 'S', 'T')})
        assert lines[lines.index('T:') - 1] == 'J:'
        assert [x for x in lines if x.startswith('\t')] == instructions
        assert lines.count('J:') == 1
    lines = ['C:', '\tbeq T', 'J:', 'S:', 'D:', '\tbne T', 'K:', 'U:', 'T:', '\trts']
    relocate(lines, {'C': 'J', 'D': 'K'}, {'J': ('C', 'S', 'T'), 'K': ('D', 'U', 'T')})
    assert set(lines[lines.index('T:') - 2:lines.index('T:')]) == {'J:', 'K:'}
    return 3


def main():
    print('jump fusion:', check(), 'controls pass')
    print('jump aliases:', check_aliases(emit.retarget_jump_aliases), 'controls pass')
    if '--sabotage' in sys.argv:
        try:
            check_aliases(lambda *args: None)
        except AssertionError:
            print('jump aliases: old fall-through alias fault caught')
        else:
            raise AssertionError('alias fault escaped')
        emit.INVERT = {cc: cc for cc in emit.INVERT}
        try:
            check()
        except AssertionError:
            print('jump fusion: unchanged-condition plant caught')
        else:
            raise AssertionError('plant escaped')


if __name__ == '__main__':
    main()
