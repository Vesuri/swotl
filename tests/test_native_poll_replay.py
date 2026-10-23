"""Host IRQ replay uses exact native aliases and the actual tail-call stack."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import host_run as H

def run(pending=True, plant=None):
 h=object.__new__(H.Host);h.services=[];h.music_skip=False;h.entry=0
 h.syms=dict(A=100,A_np=120,A_native_poll=110,A_native_np=130,A_native_irq=150,rt_irq_back=300)
 h.stack=1000;h.r=lambda _:h.stack;posted=[];h.post=posted.append;h.guest_vector=lambda _:True
 class Engine:
  def __init__(self):self.hooks={}
  def hook_range(self,kind,callback,first,last):
   assert first==last;self.hooks.setdefault(first,[]).append(callback)
  def reg_write(self,*args):pass
  def start(self,*args,**kwargs):
   visits=[]
   def at(address):
    if address in (100,110):visits.append(address)
    for callback in self.hooks.get(address,[]):callback(None,address,2,None)
    assert not h.irq_lost,h.irq_lost
   at(100);at(120) # original entry poll, then callback starts its first iteration
   h.stack=996 # only the callback return address; pending path tail-jumps
   if plant!='missing-visit':at(110)
   if pending:
    assert posted==[8]
    h.stack=984 if plant!='wrong-stack' else 988
    at(300);assert posted==[8,8] # second queued guest IRQ at the same visit
    at(300)
    h.stack=1000 # tail trampoline returned to callback caller; pending visit resumes after original poll
    if plant=='duplicate-visit':at(100)
    at(120)
   else:
    at(130) # no delivery: helper's execution continuation is counted once
   assert visits==[100,110],('duplicate/missing original poll visit',visits)
   assert h.visits=={'A':2},h.visits
   assert not h.groups,h.groups
   assert h.irq_i==(2 if pending else 0)
   return 0
 h.e=Engine()
 irqs=[(0,'A',1,8),(0,'A',1,8)] if pending else [(1,'A',0,8)]
 H.Host.run(h,dict(keys=[],snapshots=[],releases=[],irqs=irqs),1)
 # no-pending case intentionally retains one future event

run();run(False)
for plant in ('missing-visit','wrong-stack','duplicate-visit'):
 try:run(plant=plant)
 except AssertionError as e:print('caught',plant,str(e))
 else:raise AssertionError('plant escaped: '+plant)
print('native tail-poll stack and exact-once host handoff checks pass')
