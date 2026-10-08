"""Exercise the live RETF oracle on both sides of the wrap, including RETF imm."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dosbox_retf as D
import x86_diff as X
import uc as U


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


if __name__ == '__main__':
    main()
