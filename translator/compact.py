"""Exact native word-mask compaction within one guest instruction.

No register is known zero at entry (guest upper words are undefined,
speed-plan R4); facts come from moveq, immediate moves and masks within the
instruction. Unknown instructions, control flow and labels discard facts. A
redundant mask still defines CCR: keep that definition with TST unless a
later full CCR writer is reached before any possible reader.
"""
import re
from collections import Counter

WORD_WRITERS = frozenset({'add', 'addi', 'addq', 'sub', 'subi', 'subq', 'and',
    'or', 'eor', 'neg', 'not', 'clr', 'ext', 'lsl', 'lsr', 'asr', 'asl', 'rol',
    'ror', 'roxl', 'roxr', 'addx', 'subx', 'negx'})
FULL_CCR = frozenset({'move', 'moveq', 'cmp', 'cmpi', 'cmpa', 'tst', 'clr',
    'and', 'or', 'eor', 'add', 'addi', 'addq', 'sub', 'subi', 'subq', 'neg'})


def parts(line):
    if not line.startswith('\t') or line.startswith('\t;'):
        return None
    fields = line.strip().split(None, 1)
    op = fields[0]
    arg = fields[1] if len(fields) > 1 else ''
    src, sep, dst = arg.rpartition(',')
    return op, op.split('.')[0], arg, src, sep, dst


def small_immediate(src, limit=0xffff):
    if not src.startswith('#'):
        return False
    try:
        s = src[1:]
        n = int(s[1:], 16) if s.startswith('$') else int(s, 10)
        return 0 <= n <= limit
    except ValueError:
        return False


def ccr_dead(lines, at):
    for line in lines[at + 1:]:
        p = parts(line)
        if p is None:
            if not line.strip() or line.lstrip().startswith(';'):
                continue
            return False
        op, base, arg, src, sep, dst = p
        if re.search(r'\b(ccr|sr)\b', arg):
            return False
        address_dst = bool(re.fullmatch(r'a[0-7]', dst))
        if base in ('lea', 'movea', 'exg', 'nop') or base == 'move' and address_dst:
            continue
        return base in FULL_CCR and not address_dst
    return False


def compact(lines):
    known, out, stats = set(), [], Counter()
    for at, line in enumerate(lines):
        p = parts(line)
        if p is None:
            if line.strip() and not line.lstrip().startswith(';'):
                known.clear()
            out.append(line)
            continue
        op, base, arg, src, sep, dst = p
        # Address-register auto-update and word-sized address arithmetic affect
        # the full 32-bit address, unlike word writes to data registers.
        for reg in re.findall(r"-\((a[0-7])\)|\((a[0-7])\)\+", arg):
            known.difference_update(reg)
        if op == 'and.l' and src == '#$ffff' and dst in known:
            if ccr_dead(lines, at):
                stats['redundant upper mask removed'] += 1
            else:
                out.append(f'\ttst.l {dst}')
                stats['redundant upper mask as TST'] += 1
        else:
            out.append(line)
        if base in ('cmp', 'cmpi', 'cmpa', 'tst', 'nop', 'lea', 'movea'):
            if base in ('lea', 'movea'):
                known.discard(dst)
        elif base in ('move', 'moveq'):
            if re.fullmatch(r'a[0-7]', dst):
                known.discard(dst)
            elif re.fullmatch(r'd[0-7]', dst) and not op.endswith(('.b', '.w')):
                zero = (op == 'move.l' and src in known or
                        op in ('move.l', 'moveq') and
                        small_immediate(src, 127 if op == 'moveq' else 0xffff))
                known.discard(dst)
                if zero:
                    known.add(dst)
        elif base in WORD_WRITERS:
            if re.fullmatch(r'a[0-7]', dst):
                known.discard(dst)
            elif not op.endswith(('.b', '.w')):
                if op == 'and.l' and src == '#$ffff':
                    known.add(dst)
                else:
                    known.discard(dst if sep else arg)
        else:
            known.clear()
    return out, stats
