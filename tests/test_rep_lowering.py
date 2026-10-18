"""Diagnostic REP slices execute the same guest instructions as the x86 oracle."""
from collections import Counter
import argparse
import struct
import m68k_diff as D
from translator.lower import Ctx, hx

HOOK = D.STUB + 0x800


def check(broken=False):
    h=D.Harness(8291)
    original=D.lower_case
    original_run=h.m.run
    resumed=set()
    calls=[0]
    def lower(insns,cs,tag,end_ip):
        def context(k):
            return Ctx(cs=hx(cs),label=f'{tag}_{k}',rep_hook=(0,f'{tag}_{k}'))
        lines=[f'{tag}:'];cold=[];stats=Counter()
        if tag=='c0':lines += [f'rt_replay_rep equ ${HOOK:x}']
        for k,lw in enumerate(D.F.plan(insns,D.F.seq_lives(insns),{0},context)):
            lines += [f'{tag}_{k}:']+lw.out
            cold += lw.cold
            stats.update(lw.stats)
        lines += [f'\tmove.l #{hx(end_ip)},d7','\tjmp T_END']
        return lines+cold,stats
    def run(*a,**kw):
        resumed.clear()
        return original_run(*a,**kw)
    @D.U.CODE_CB
    def checkpoint(engine,address,size,user):
        sp=h.m.r('a7');point,done=struct.unpack('>II',h.m.e.read(sp+4,8))
        cx=h.m.r('d1')&65535
        restart=not done and cx>0 and cx%2==0 and cx not in resumed
        if restart:
            resumed.add(cx);calls[0]+=1
            if broken: h.m.e.reg_write(D.U.M68K['a4'],h.m.r('a4')+1)
        h.m.e.write(sp+4,struct.pack('>I',int(restart)))
    h.m.e.write(HOOK,bytes.fromhex('4e75'))
    h.m.e.hook_range(D.U.HOOK_CODE,checkpoint,HOOK,HOOK)
    h.m.run=run
    D.lower_case=lower
    try:
        for prefix,op in [(0xf3,x) for x in range(0xa4,0xb0) if x not in (0xa8,0xa9)]+[(0xf2,x) for x in (0xa6,0xa7,0xae,0xaf)]:
            for df in (0,1):
                for cx in (0,1,7):
                    for offset in (64,65533):
                        h.case(bytes((prefix,op)),f'rep {prefix:02x}{op:02x} df={df} cx={cx} off={offset}',
                               overrides={'regs':{'cx':cx,'si':offset,'di':offset,'ds':0x1000,'es':0x2000},'flags':{'DF':df},
                                          'mem':[(0x10000+32,bytes(64)),(0x20000+32,bytes(64))]})
        h.flush()
        assert calls[0]>0, 'no slice restart exercised'
        assert bool(h.bad)==broken, h.bad[:10]
        print(f'diagnostic REP lowering: {h.ncases} x86 oracle cases; {calls[0]} resumptions; '
              + ('planted SI corruption caught' if broken else 'all match'))
    finally:
        D.lower_case=original
        D.Harness.tidy()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sabotage',action='store_true');args=p.parse_args()
    check()
    if args.sabotage:check(True)
