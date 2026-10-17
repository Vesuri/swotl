"""Execute both arms of independently assembled branch-width controls."""
import struct
import sys
import tempfile
from pathlib import Path

import m68k_diff as D
import uc as U
from m68k_assembly import branch_widths


def run_image(data, value):
    entry, done, branch, target = struct.unpack_from('>4I', data)
    at = branch - D.CODE
    opcode = int.from_bytes(data[at:at + 2], 'big')
    low = opcode & 255
    if low == 0:
        displacement, size = struct.unpack_from('>h', data, at + 2)[0], 16
    elif low == 255:
        displacement, size = struct.unpack_from('>i', data, at + 2)[0], 32
    else:
        displacement, size = low if low < 128 else low - 256, 8
    assert branch + 2 + displacement == target, 'branch target changed'
    engine = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
    try:
        engine.map(D.CODE, (len(data) + 4095) & ~4095)
        engine.write(D.CODE, data)
        engine.reg_write(U.M68K['d0'], value)
        engine.reg_write(U.M68K['sr'], 0)
        assert engine.start(entry, done, timeout_us=1_000_000) == 0
        assert engine.reg_read(U.M68K['pc']) == done, 'branch control did not complete'
        # Unicorn's SR API can omit lazy Z; the executed MOVE from CCR
        # captures the architectural flags without changing them.
        result = (engine.reg_read(U.M68K['a0']), engine.reg_read(U.M68K['d2']) & 31)
        assert result == (2 if value else 1, 8 if value & 0x80000000 else 0 if value else 4), \
            'branch result or live flags changed'
        return result, size
    finally:
        U.uc.uc_close(engine.h)


def check(sabotage=False):
    seen, cases = set(), 0
    with tempfile.TemporaryDirectory() as temporary:
        for backward in (False, True):
            for padding in (0, 70, 17000):
                gap = ['\tnop'] * padding
                if backward:
                    body = ['entry:', '\tbra check', 'target:', '\tmovea.w #2,a0', '\tbra done']
                    body += gap + ['check:', '\ttst.l d0', 'branch:', '\tbne target', '\tmovea.w #1,a0']
                else:
                    body = ['entry:', '\ttst.l d0', 'branch:', '\tbne target', '\tmovea.w #1,a0', '\tbra done']
                    body += gap + ['target:', '\tmovea.w #2,a0']
                body = [line.replace('\tbra done', '\tbra capture') for line in body]
                source = '\n'.join([f'\torg ${D.CODE:x}', '\tdc.l entry,done,branch,target']
                                   + body + ['capture:', '\tmove.w ccr,d2', 'done:', '\tnop']) + '\n'
                images = []
                for name, text in [('vasm', source), ('fixed', branch_widths(source))]:
                    if sabotage and name == 'fixed':
                        text = text.replace('\tbne.', '\tbeq.', 1)
                    images.append(D.assemble(text, Path(temporary, name + '.bin')))
                for value in (0, 1, 0xffffffff):
                    original, _ = run_image(images[0], value)
                    fixed, size = run_image(images[1], value)
                    assert original == fixed
                    seen.add(size)
                    cases += 1
        assert seen == {8, 16, 32}, seen
        explicit = f'\torg ${D.CODE:x}\n\tbne.s target\n\tds.b 400\ntarget:\n\trts\n'
        try:
            D.assemble(branch_widths(explicit), Path(temporary, 'explicit.bin'))
        except RuntimeError as error:
            assert 'out of range' in str(error), error
        else:
            raise AssertionError('invalid explicit short branch was hidden')
        empty = f'\torg ${D.CODE:x}\n\tbne target\ntarget:\n\trts\n'
        empty_image = D.assemble(branch_widths(empty), Path(temporary, 'empty.bin'))
        assert empty_image[:4] == bytes.fromhex('66000002'), 'zero short displacement not avoided'
    print(f'block assembler: {cases} branch executions agree; short/word/long covered')


if __name__ == '__main__':
    check()
    if '--sabotage' in sys.argv:
        try:
            check(True)
        except AssertionError as error:
            assert str(error) == 'branch result or live flags changed', error
        else:
            raise AssertionError('changed branch condition escaped')
        print('sabotage: changed branch condition caught')
