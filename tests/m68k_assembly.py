"""Deterministic widths for unsized branches in whole-program block tests.

vasm 1.9 can oscillate when relaxing the large flat test image. Explicit
sizes from the translator are preserved. Only the assembler's choice for
an unsized branch is made here; opcodes, operands and targets stay intact.
Production assembly and the instruction differential use their usual path.
"""
import re

BRANCH = re.compile(r'^(\s*b(?:ra|sr|hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le|hs|lo))\s+(\S+)(.*)$')
LABEL = re.compile(r'^([\w.]+):\s*(.*)$')


def branch_widths(source: str) -> str:
    """Use upper bounds on spans, rather than a self-dependent relaxation.

    32 bytes bounds an integer 68020 instruction, including both full
    extension operands. Data/reservation directives contribute their actual
    byte counts. A bound may select a wider encoding; vasm still validates
    every displacement, including every explicit size we leave untouched.
    """
    lines = source.splitlines()
    positions, widths, labels = [], [], {}
    position = 0
    for line in lines:
        text = line.partition(';')[0].strip()
        match = LABEL.match(text)
        if match:
            labels[match[1]] = (position, len(positions))
            text = match[2]
        positions.append(position)
        parts = text.split(None, 1)
        width = 0
        if parts:
            op = parts[0].lower()
            args = parts[1] if len(parts) == 2 else ''
            if args.split(None, 1)[:1] == ['equ']:
                pass
            elif op == 'org':
                if widths and any(widths):
                    raise ValueError('block-test assembly has a second origin')
                position = int(args.replace('$', '0x'), 0)
            elif op.startswith('dc.'):
                if '"' in args or "'" in args:
                    raise ValueError('string data in block-test assembly')
                width = {'b': 1, 'w': 2, 'l': 4}[op[-1]] * len(args.split(','))
            elif op.startswith('ds.'):
                width = {'b': 1, 'w': 2, 'l': 4}[op[-1]] * int(args.replace('$', '0x'), 0)
                if width < 0:
                    raise ValueError('negative reservation in block-test assembly')
            else:
                width = 32
        widths.append(width)
        position += width
    for index, line in enumerate(lines):
        match = BRANCH.match(line)
        if not match:
            continue
        target = labels.get(match[2])
        suffix = '.l'
        if target is not None:
            address, target_index = target
            bound = abs(address - positions[index]) + 2
            # Short displacement zero is the word-extension escape. A
            # backward branch to its own instruction instead has -2.
            empty_forward = target_index > index and not any(widths[index + 1:target_index])
            if bound <= 126 and not empty_forward:
                suffix = '.s'
            elif bound <= 32767:
                suffix = '.w'
        lines[index] = line[:match.end(1)] + suffix + line[match.end(1):]
    return '\n'.join(lines) + '\n'
