"""Synthetic 68020 tail-poll ABI probe; not a guest-routine correctness test."""
import sys,random,json,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import m68k_blocks as B
from translator.support import equates
from translator.emit import native_poll_stub
from translator.ir import FLAGS
scratch=tempfile.TemporaryDirectory(prefix='native-poll-')
P=Path(scratch.name)
labels=['start','original_poll','original_np','native','native_poll','native_np','tail','done']
def run(mode,plant=None):
 source=equates()+f'\nrt_irq equ ${B.STUB_AT["rt_irq"]:x}\n\torg ${B.D.CODE:x}\n'
 source+='\n'.join('\tdc.l '+s for s in labels)+'\n'+'''
start:
original_poll:
 tst.b G_IRQ(a6)
 bne original_irq
original_np:
 jsr native
 cmp.l #1,d7
 beq done
 cmp.l #2,d7
 beq original_np
 illegal
native:
body:
 addq.w #1,d0
 subq.w #1,d1
 beq finish
native_poll:
 tst.b G_IRQ(a6)
 bne.l tail
native_np:
 bra body
finish:
 moveq #1,d7
 rts
tail:
 move.l #$12340000,d6
 move.l #$5678,d7
 jsr rt_irq
 moveq #2,d7
 rts
original_irq:
 move.l #$12340000,d6
 move.l #$5678,d7
 jsr rt_irq
 bra original_np
done:
 nop
'''
 source=source.replace('tail:\n move.l #$12340000,d6\n move.l #$5678,d7\n jsr rt_irq\n moveq #2,d7\n rts', '\n'.join(native_poll_stub('original',0x5678,'$1234',2)).replace('original_native_irq','tail'))
 if plant=='missing-poll':source=source.replace('bne.l tail','nop\n nop\n nop')
 if plant=='duplicate':source=source.replace('beq original_np','beq original_poll')
 if plant=='stack':source=source.replace('native:\nbody:','native:\n move.l d0,-(sp)\nbody:')
 binary=B.D.assemble(source,P/f'tail-{mode}-{plant}.bin');at={k:int.from_bytes(binary[4*i:4*i+4],'big') for i,k in enumerate(labels)}
 m=B.D.M68k(bytes(B.X.RAM),B.STUB_AT);m.load(binary);m.irq_calls=[];m.irq_keep=mode=='watch';seen=[];errors=[]
 @B.U.CODE_CB
 def hook(h,addr,size,user):
  if addr in (at['original_poll'],at['native_poll']):
   seen.append((m.r('d0')&65535,m.r('d1')&65535))
   expected=B.D.STACK-0x100-(4 if addr==at['native_poll'] else 0)
   if m.r('a7')!=expected:
    errors.append('unbalanced native poll stack');B.U.uc.uc_emu_stop(h);return
   if mode=='watch' or mode=='irq' and len(seen)==2:
    m.e.write(B.D.STATE+8,b'\1');m.e.write(B.D.PENDING,b'\1')
  if addr==B.STUB_AT['rt_irq'] and mode=='irq':
   m.e.reg_write(B.U.M68K['d0'],100);m.e.reg_write(B.U.M68K['d1'],2)
 m.e.hook(B.U.HOOK_CODE,hook);m.extra_stops={at['done']:'done'}
 regs=dict(ax=0,bx=23,cx=4,dx=31,si=45,di=67,sp=0xec00,bp=0xf000,ds=0x5000,es=0x6000,ss=0x7000)
 flags={k:0 for k in FLAGS};flags['IF']=1
 try:
  got,fl,fx,mem,outs,writes,info=m.run(at['start'],(regs,flags,0x7000,0,[]),random.Random(42),irq=False)
  assert not errors,errors
  assert not info['err'] and info['stop']=='done',info
  want=[(0,4),(1,3),(101,1)] if mode=='irq' else [(0,4),(1,3),(2,2),(3,1)]
  assert seen==want,('visits',seen,want)
  assert got['ax']==(102 if mode=='irq' else 4) and got['cx']==0,got
  assert all(got[k]==v for k,v in regs.items() if k not in ('ax','cx')),got
  assert len(m.irq_calls)=={'none':0,'irq':1,'watch':4}[mode],m.irq_calls
  assert m.r('a7')==B.D.STACK-0x100,'final stack'
  return dict(mode=mode,visits=seen,irq_calls=len(m.irq_calls),stack_balanced=True)
 finally:B.U.uc.uc_close(m.e.h)
results=[run(m) for m in ('none','irq','watch')]
for plant in ('missing-poll','duplicate','stack'):
 try:run('irq',plant)
 except AssertionError as e:print('caught',plant,str(e),flush=True)
 else:raise AssertionError('plant escaped '+plant)
print(results,flush=True)
scratch.cleanup()
