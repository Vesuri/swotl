"""Guard edges for upper-word and CCR proofs; no guest assumptions from profiles."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translator.compact import compact


def check(text, expected):
    lines=['\t'+x if not x.endswith(':') else x for x in text.split(';')]
    actual,_=compact(lines)
    assert [x.strip() for x in actual] == expected.split(';'), (text,actual,expected)


def main():
    check('and.l #$ffff,d0;move.w d0,d1','move.w d0,d1')
    check('and.l #$ffff,d0;move.w ccr,d7','tst.l d0;move.w ccr,d7')
    check('and.l #$ffff,d0;addx.w d0,d1','tst.l d0;addx.w d0,d1')
    check('and.l #$ffff,d0;bne target','tst.l d0;bne target')
    check('and.l #$ffff,d0;target:;move.w d0,d1','tst.l d0;target:;move.w d0,d1')
    check('move.l d0,d7;and.l #$ffff,d7;move.w d7,d1','move.l d0,d7;move.w d7,d1')
    for prefix in ('move.l (a0),d0','mulu.w d1,d0','swap d0','lsl.l #1,d0',
                   'jsr helper','target:','moveq #-1,d0','moveq #$ff,d0',
                   'moveq #$80,d0','move.l #$10000,d0'):
        text=prefix+';and.l #$ffff,d0;move.w d0,d1'
        check(text,text)
    check('move #0,d6;and.l #$ffff,d6','move #0,d6;and.l #$ffff,d6')
    check('move.w (a0),d6;and.l #$ffff,d6','move.w (a0),d6;and.l #$ffff,d6')
    check('moveq #0,d6;move.w (a0),d6;and.l #$ffff,d6','moveq #0,d6;move.w (a0),d6;tst.l d6')
    for prefix in ('move.w (a4)+,d6', 'move.w -(a4),d6', 'addq.w #1,a4', 'sub.w d0,a4'):
        text=prefix+';move.l a4,d7;and.l #$ffff,d7'
        check(text,text)
    print('compact: upper-word, clobber, label, control-flow and CCR guard edges pass')


if __name__ == '__main__':
    main()
