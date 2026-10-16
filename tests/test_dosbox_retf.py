"""Exercise the live RETF oracle on both sides of the wrap, including RETF imm."""
import argparse
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dosbox_retf as D
import x86_diff as X
import uc as U


def literal_inputs():
    for registers_collide in (False, True):
        regs = dict(zip(X.REGS, (0x1234, 0x5678, 0x9012, 0x3456,
                                0xffff, 0x4567, 0x89ab, 0xcdef)))
        regs.update(es=0x4000, cs=0x2000, ss=0x7000, ds=0x5000, ip=0x100)
        if registers_collide:
            regs.update(ax=0xac, bx=0xaf, cs=0xcf, ss=0xdf, ip=0xaf)
        memory = bytearray(X.RAM)
        base = regs['ss'] * 16
        memory[base:base + 6] = bytes.fromhex('ac af cf df 34 12')
        memory[base + 0xffff:base + 0x10005] = bytes.fromhex('cf 36 d5 08 19 c4')
        read = lambda a, n: bytes(memory[a:a+n])
        for flags in (0x7002, 0x74d7):
            out, fl = D.run(regs, flags, b'\xca\xcf\x00', read)
            expected = dict(regs, ip=0x36cf, cs=0xcfaf, sp=0xd2)
            assert out == expected, (registers_collide, out, expected)
            assert fl == flags, (fl, flags)
    print('DOSBox literals: flag-name bytes, register values and RETF immediate checked')


def upper_inputs():
    # The block differential reached SS:SP DC91:FFFD. Keep those physical
    # addresses; distinct bytes distinguish word reads from SP wrapping.
    total = 0
    for ss in (0xd000, 0xdc91):
        for sp in (0xfffd, 0xfffe, 0xffff):
            for immediate in (None, 2, 0xffff):
                regs = dict(zip(X.REGS, (0xac14, 0xd180, 8, 0xe331,
                                        sp, 0x3636, 0x21d1, 0x7af6)))
                regs.update(es=0xd85a, cs=0x2762, ss=ss, ds=0x2eee, ip=0x4b5e)
                memory = bytearray(X.RAM)
                base = ss * 16
                for a in range(base, base + 0x10008):
                    memory[a] = ((a >> 8) ^ a ^ 0x5a) & 255
                read = lambda a, n: bytes(memory[a:a+n])
                code = b'\xcb' if immediate is None else b'\xca' + immediate.to_bytes(2, 'little')
                out, flags = D.run(regs, 6, code, read)
                expected = dict(regs, ip=int.from_bytes(read(base+sp, 2), 'little'),
                                cs=int.from_bytes(read(base+((sp+2)&0xffff), 2), 'little'),
                                sp=(sp+4+(immediate or 0))&0xffff)
                assert out == expected and flags == 6, (ss, sp, immediate, out, flags, expected)
                total += 1
    print(f'DOSBox upper memory: {total} exact-address wrap cases, registers/flags and full memory checks pass')


def upper_sabotage():
    if D.INSTANCE is not None:
        D.INSTANCE.close()
        D.INSTANCE = None
    original = D.Debugger.command
    def truncate(self, command):
        match = re.match(r'SM "([0-9a-f]+)":"([0-9a-f]+)" ', command)
        if match and int(match[1], 16)*16 + int(match[2], 16) >= 0xa0000:
            command = ('SM ' + D.hex_literal(int(match[1], 16)&0x7fff) + ':'
                       + D.hex_literal(int(match[2], 16)) + ' ' + command[match.end():])
        return original(self, command)
    D.Debugger.command = truncate
    try:
        try:
            upper_inputs()
        except RuntimeError as error:
            assert 'memory initialization mismatch' in str(error), error
        else:
            raise AssertionError('truncated upper-memory address escaped detection')
    finally:
        D.Debugger.command = original
        if D.INSTANCE is not None:
            D.INSTANCE.close()
            D.INSTANCE = None
    print('caught truncated upper-memory address')


def main():
    total = 0
    for sp in (0, 0xfffc, 0xfffd, 0xfffe, 0xffff):
        for immediate in (None, 2, 0xffff):
            regs = dict(zip(X.REGS, (0x1234,0xabcd,0x5678,0x9012,sp,0x4567,0x89ab,0xcdef)))
            regs.update(es=0x4000,cs=0x2000,ss=0x7000,ds=0x5000,ip=0x100)
            flags = 0x7ed7  # every defined status/control bit, TF clear
            code = b'\xcb' if immediate is None else b'\xca' + immediate.to_bytes(2, 'little')
            memory = bytearray(X.RAM)
            # Distinct bytes distinguish wrapping the word access itself
            # from wrapping SP between pops, and an unwrapped second pop.
            for a in range(0x70000,0x80008):
                memory[a] = ((a >> 8) ^ a ^ 0x5a) & 255
            read = lambda a, n: bytes(memory[a:a+n])
            out, fl = D.run(regs,flags,code,read)
            target_ip = int.from_bytes(read(0x70000+sp,2),'little')
            target_cs = int.from_bytes(read(0x70000+((sp+2)&0xffff),2),'little')
            expected = dict(regs,ip=target_ip,cs=target_cs,sp=(sp+4+(immediate or 0))&0xffff)
            assert out == expected, (sp,immediate,out,expected)
            assert fl == flags, (fl,flags)
            if sp <= 0xfffc:
                oracle = X.Oracle(bytes(memory))
                f = {name: flags >> X.FLAG_BIT[name] & 1 for name in X.FLAGS}
                case = ({r:regs[r] for r in X.REGS+X.SEGS},f,flags&0x7000,regs['ip'],[(0x20100,code)])
                err, uout, ufl, writes, ints, outs, touched = oracle.run(case,1)
                assert (err,uout,ufl,writes,ints,outs,touched)==(0,out,fl,{},[],[],set())
                U.uc.uc_close(oracle.e.h)
            total += 1
    print(f'DOSBox RETF: {total} live cases; wrapped/nonwrapped SP, immediate cleanup, registers/flags and 1 MiB memory check')
    literal_inputs()
    upper_inputs()


def sabotage():
    literal_inputs()
    original = D.hex_literal
    try:
        D.hex_literal = lambda value: f'{value:x}'
        try:
            literal_inputs()
        except RuntimeError as error:
            assert 'initialization mismatch' in str(error), error
        else:
            raise AssertionError('unquoted debugger literals escaped detection')
    finally:
        D.hex_literal = original
    print('caught unquoted debugger literals')
    upper_sabotage()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    sabotage() if args.sabotage else main()
