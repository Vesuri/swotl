"""D69C pixel-loop coverage; original x86 is the oracle (RC5: registers, live
flags, all RAM and code/VRAM write addresses at the endpoint; poll-free since
irq-plan I9)."""
from pathlib import Path
import argparse
import random
import sys
from functools import lru_cache
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from tools import compute_oracle as O
from translator import emit, image
from translator.support import equates
from translator.ir import FLAGS, FLAG_BIT

SCOPES = ((0xd92a, 0xd93d), (0xd95c, 0xd96f))


def synthetic(first):
    raw = B.relocated(image.load()['SWOTL.EXE'])
    for index, (count, di, bp, stride, es) in enumerate([
        (count, di, bp, stride, es)
        for count in (0, 1, 17)
        for di, bp, stride, es in ((0, 0, 1, 0x6000),
                                  (0xffff, 0xffff, 0xffff, 0x6000),
                                  (0x7fff, 0x7fff, 0x8000, 0x6000),
                                  (0x8000, 0x8000, 0x7fff, 0x6000),
                                  (0x2523, 0xffff, 1, 0x5000),
                                  (0x2583, 0xffff, 0xffff, 0x5000))]):
        ram = bytearray(B.X.RAM)
        ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
        regs = dict(ax=0x8123, bx=0xabcd, cx=count, dx=0xfffe,
                    si=0x2445, di=di, sp=0xec00, bp=bp,
                    cs=B.LOADSEG + 0x49b, ip=first-0x49b0,
                    ds=0x5000, ss=0x7000, es=es,
                    flags=0x7202 | (index & 1) * 0x400)
        for off, val in ((0x2523, stride), (0x2583, 320)):
            at=regs['ds']*16+off
            ram[at:at+2]=val.to_bytes(2, 'little')
        yield f'{first:x}-synthetic-{index}', bytes(ram), regs


def admitted(regs):
    return regs['ds'] <= 0x9000 and regs['cs'] + 0x1000 <= regs['es'] <= 0x9000


def guard_cases(first):
    name, ram, base = next(synthetic(first))
    for reg, values in (('ds', (0x9000, 0x9001)),
                        ('es', (base['cs']+0xfff, base['cs']+0x1000, 0x9000, 0x9001))):
        for value in values:
            regs=dict(base);regs[reg]=value;regs['di']=0xfffe
            yield f'{first:x}-guard-{reg}-{value:x}', ram, regs


def wide_cases(first):
    _,ram,base=list(synthetic(first))[1]
    for count in (0xfffe,0xffff):
        regs=dict(base,cx=count)
        yield f'{first:x}-wide-{count:x}',ram,regs


def captured(first):
    for directory in sorted((ROOT/'tmp/pc-runs').glob(f'native-N4-line-{first:X}-*')):
        for path in sorted((directory/'trace').glob('snap-entry*')):
            ram, regs=O.load_entry(path)
            yield str(path), ram, regs


class LineMismatch(AssertionError):
    pass


def generated(entries=False, plant=False, wide=False):
    p=emit.Program();work=ROOT/'tmp/line-pixels-generated';work.mkdir(exist_ok=True)
    binary, addresses=B.program_image(p, work)
    if plant:
        changed=bytearray(binary)
        for lo, hi in ((0xd938, 0xd93b), (0xd96a, 0xd96d)):
            a=addresses[emit.label("SWOTL.EXE",lo)]-B.D.CODE
            z=addresses[emit.label("SWOTL.EXE",hi)]-B.D.CODE
            assert z>a and (z-a)%2==0
            changed[a:z]=b"\x4e\x71"*((z-a)//2)
        binary=bytes(changed)
    total=0
    for first, end in SCOPES:
        cases=list(wide_cases(first)) if wide else list(synthetic(first))+(list(captured(first)) if entries else [])
        for name, ram, regs in cases:
            expected=O.run(ram, regs, (regs['cs'], end-0x49b0), limit=1000000 if wide else 100000)
            m=B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
            try:
                m.load(binary)
                m.extra_stops={addresses[emit.label('SWOTL.EXE', end)]:'endpoint'}
                O.watch_native(m)
                flags={f:regs['flags']>>FLAG_BIT[f]&1 for f in FLAGS}
                got, fl, fx, mem, outs, writes, info=m.run(addresses[emit.label('SWOTL.EXE', first)],
                    (regs,flags,regs['flags']&0xf000,regs['ip'],[]),random.Random(41),irq=False)
                assert not info['err'] and not outs and not info['irq'] and info['stop']=='endpoint',(name,info)
                got.update(cs=expected['at'][0],ip=expected['at'][1])
                actual=dict(registers=got,flags=fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS),
                            writes=writes,ram=m.gread(0,B.X.RAM))
                errors=O.compare(expected,actual,p.live_in[('SWOTL.EXE',end)],code(p))
                if errors: raise LineMismatch((name,errors))
                total+=1
            finally:
                B.U.uc.uc_close(m.e.h)
    return total


@lru_cache(maxsize=None)
def code(p):
    return O.code_addresses(p, B.LOADSEG)


@lru_cache(maxsize=1)
def native_program():
    original=image.rows
    rows=[]
    for (first,end),name,last in zip(SCOPES,('line_right','line_left'),(0xd93b,0xd96d)):
        rows.append(dict(module='SWOTL.EXE',first=hex(first),last=hex(last),
                         service=name,args='',kind='compute',
                         resume='continue',reason='authorized line differential',oracle=__file__))
    existing={int(r['first'],16) for r in original('hle.csv') if r['module']=='SWOTL.EXE'}
    with patch.object(image,'rows',lambda name:original(name)+
                      ([r for r in rows if int(r['first'],16) not in existing] if name=='hle.csv' else [])):
        return emit.Program()


PREDECESSORS = ("direct", "jump", "call", "taken", "fall", "indirect", "return")


def native(entries=False, plant=None, predecessor="direct", wide=False):
    p=native_program();work=ROOT/'tmp/line-pixels-native';work.mkdir(exist_ok=True)
    implementation=(ROOT/'src/runtime/compute_line.s').read_text()
    templates={'store':('move.b d3,0(a1,d7.w)','nop'),
               'carry':('bcc.s line_right_no_row','bra.s line_right_no_row'),
               'code-window':('bcs.s line_right_decline','nop'),
               'count':('addq.w #1,d1\n\tbra.s line_right_store','bra.s line_right_store'),
               'decline':('line_right_decline:\n\tmoveq #0,d7','line_right_decline:\n\taddq.w #1,d1\n\tmoveq #0,d7')}
    if plant:
        old,new=templates[plant]
        if old not in implementation:raise ValueError('missing plant template: '+plant)
        implementation=implementation.replace(old,new)
    total=0
    for (first,end),service in zip(SCOPES,('line_right','line_left')):
        prefix={'direct':[], 'jump':['\tbra entry'],
                'call':['\tbsr entry','\tbra done'],
                'taken':['\tcmp.w d0,d0','\tbeq entry','\tillegal'],
                'fall':['\tcmp.w d0,d0','\tbne done'],
                'indirect':['\tlea entry,a0','\tjmp (a0)'],
                'return':['\tpea entry','\trts']}[predecessor]
        source=[equates(),f'\torg ${B.SNIP:x}','\tdc.l done',*prefix,'entry:',
                f'\tmove.l #${B.LOADSEG+0x49b:x},d6',
                f'\tjsr rt_hle_{service}','\trts' if predecessor=='call' else '\tbra done','done:','\tnop',implementation]
        binary=B.D.assemble('\n'.join(source),work/f'{service}-{plant}.bin')
        cases=list(wide_cases(first)) if wide else list(synthetic(first))+list(guard_cases(first))+(list(captured(first)) if entries else [])
        for name,ram,regs in cases:
            expected=O.run(ram,regs,(regs['cs'],end-0x49b0),limit=1000000 if wide else 100000) if admitted(regs) else None
            m=B.D.M68k(ram,B.STUB_AT)
            try:
                m.e.write(B.SNIP,binary);m.extra_stops={int.from_bytes(binary[:4],'big'):'done'}
                O.watch_native(m)
                flags={f:regs['flags']>>FLAG_BIT[f]&1 for f in FLAGS}
                got,fl,fx,mem,outs,writes,info=m.run(B.SNIP+4,
                    (regs,flags,regs['flags']&0xf000,regs['ip'],[]),random.Random(41),irq=False)
                if info['err'] or outs or info['irq'] or info['stop']!='done':raise LineMismatch((name,info))
                if info['a7']!=B.D.STACK-0x100:raise LineMismatch((name,'native stack'))
                if expected is None:
                    errors=[]
                    if m.r('d7')!=0:errors.append('guard accepted')
                    if any(got[k]!=v for k,v in regs.items() if k in got):errors.append('decline registers')
                    if writes or m.gread(0,B.X.RAM)!=ram:errors.append('decline memory')
                    if 2|fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS)!=regs['flags']:errors.append('decline flags')
                else:
                    got.update(cs=expected['at'][0],ip=expected['at'][1])
                    actual=dict(registers=got,flags=fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS),
                                writes=writes,ram=m.gread(0,B.X.RAM))
                    errors=O.compare(expected,actual,p.live_in[('SWOTL.EXE',end)],code(p))
                    if m.r('d7')!=1:errors.append('unexpected decline')
                if errors:raise LineMismatch((name,errors))
                total+=1
            finally:B.U.uc.uc_close(m.e.h)
    return total


def predecessor_cases():
    native_program.cache_clear()
    count=0
    for predecessor in PREDECESSORS:
        try:count+=native(predecessor=predecessor)
        except LineMismatch as error:return count+1,[str(error)]
    return count,[]


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for arg in ('entries','sabotage','generated','predecessors'):
        ap.add_argument('--'+arg,action='store_true')
    args=ap.parse_args()
    if args.generated:
        print('line pixels:',generated(args.entries),'generated oracle cases pass',flush=True)
        print('line pixels:',generated(wide=True),'full-counter generated cases pass',flush=True)
    for predecessor in PREDECESSORS if args.predecessors else ('direct',):
        print('line pixels:',predecessor,native(args.entries,predecessor=predecessor),'native cases pass',flush=True)
    print('line pixels:',native(wide=True),'full-counter native cases pass',flush=True)
    if args.sabotage:
        for plant in ('store','carry','code-window','count','decline'):
            try:native(plant=plant)
            except LineMismatch as error:print('line pixels:',plant,'caught:',error,flush=True)
            else:raise AssertionError(plant+' escaped')
        try:generated(plant=True)
        except LineMismatch as error:print('line pixels: missing generated pixel caught:',error,flush=True)
        else:raise AssertionError('missing generated pixel escaped')
