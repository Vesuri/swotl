#!/usr/bin/env python3
"""Exact gameport metadata, input declaration and compiled replay controls."""
import sys
import joystick_replay as J
from pathlib import Path
import tempfile
from joystick_replay import read, Run, Replay

def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('invalid input accepted')

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)/'joystick.csv'
    assert read(p) == []
    rejects(lambda: read(p, True))
    head = 'service,write,width,value,repeat\n'
    p.write_text(head)
    rejects(lambda: read(p, True))
    for line in ('0,0,1,256,1', '0,2,1,0,1', '0,0,3,0,1', '0,0,1,0,0',
                 '4294967296,0,1,0,1', '0,0,1,0,4294967296', '-1,0,1,0,1',
                 '0,0,1,0', '0,0,1,0,1,2', '0,0,1,0xFF,1'):
        p.write_text(head + line + '\n')
        rejects(lambda: read(p, True))
    p.write_text(head + '2,1,1,0,1\n1,0,1,255,1\n')
    rejects(lambda: read(p, True))
    p.write_text(head + '0,1,1,0,1\n0,0,1,255,2\n0,0,1,252,1\n1,0,1,236,1\n')
    runs = read(p, True)
    replay = Replay(runs)
    rejects(replay.complete)
    for args in ((0,1,0), (1,2,0,0), (1,1,1,0), (1,1,0,1)):
        rejects(lambda: replay.step(*args))
        assert replay.index == replay.used == 0
    assert replay.step(1,1,0,0) == 0
    assert [replay.step(0,1,0) for _ in range(3)] == [255,255,252]
    rejects(replay.complete)
    assert replay.step(0,1,1) == 236
    replay.complete()
    rejects(lambda: replay.step(0,1,1))
    # Planted lost repetition must be caught by the known original sequence.
    bad = Replay([runs[0], Run(0,0,1,255,1), *runs[2:]])
    bad.step(1,1,0,0)
    assert [bad.step(0,1,0) for _ in range(2)] != [255,255]
print('Joystick record/parser/order/completion controls pass; lost-repeat plant caught')

from pathlib import Path

for key in ('jx-1000','jx+1000','jy-1000','jy+1000','jx+0','jy-0','jb0','jb1','jb2','jb3'):
    assert J.action(key,True)
    try: J.action(key,False)
    except ValueError: pass
    else: raise AssertionError(key)
for key in ('jx','jy','jb','jx1000','jy+','jx+1001','jy-1001','jx+-1','jb-1','jb+1','jb4','jb00','jx+１２','jx+99999'):
    try: J.action(key,True)
    except ValueError: pass
    else: raise AssertionError(key)
for key in ('mx+1','my-2','mb3',None,0x1e61,'a'):
    assert not J.action(key,True)
print('Joystick actions: boundary/range/declaration controls pass')

import test_replay_events as C
p=Path(__file__).resolve().parent
source=(p/'joystick_replay.c').read_text().replace('"joystick_data.h"','"replay_data.h"')
data=J.c_header([J.Run(0,1,1,0,1),J.Run(0,0,1,255,2),J.Run(0,0,1,252,1),J.Run(1,0,1,236,1)])
harness=r'''
#define assert(x) do { if (!(x)) return 1; } while (0)
#include "amiga_replay.c"
volatile uint32_t replay_services;
uint32_t test_case;
static uint32_t in_count, out_count;
void test_stop(void) { for (;;) {} }
void rt_unsupported(const char *what,uint16_t a,uint16_t b,uint16_t c)
{ (void)what; (void)a; (void)b; (void)c; __asm__("moveq #2,%d0; jmp test_stop"); __builtin_unreachable(); }
uint32_t __real_rt_port_in(uint32_t port,uint32_t width)
{ ++in_count; return (port==0x21 && width==8) ? 0xf8 : 0; }
void __real_rt_port_out(uint32_t port,uint32_t value,uint32_t width)
{ if(port==0x43 && value==0x36 && width==8) ++out_count; }
int main(void) {
    switch(test_case) {
    case 1: __wrap_rt_port_in(0x201,8); return 3;
    case 2: __wrap_rt_port_out(0x201,1,8); return 3;
    case 3: __wrap_rt_port_out(0x201,0,16); return 3;
    case 4: replay_services=1; __wrap_rt_port_out(0x201,0,8); return 3;
    case 5: replay_joystick_complete(); return 3;
    }
    assert(__wrap_rt_port_in(0x21,8)==0xf8);
    __wrap_rt_port_out(0x43,0x36,8);
    assert(in_count==1 && out_count==1 && joystick_index==0);
    __wrap_rt_port_out(0x10201,0x100,8);
    assert(__wrap_rt_port_in(0x201,8)==255);
    if(test_case==7) { replay_joystick_complete(); return 3; }
    assert(__wrap_rt_port_in(0x201,8)==255);
    assert(__wrap_rt_port_in(0x201,8)==252);
    if(test_case==8) { __wrap_rt_port_in(0x201,8); return 3; }
    replay_services=1;
    assert(__wrap_rt_port_in(0x201,8)==236);
    replay_joystick_complete();
    if(test_case==6) { __wrap_rt_port_in(0x201,8); return 3; }
    return 0;
}
'''
expected=(0,)+(2,)*8
C.check(source,False,data,harness,range(9),expected)
for old,new in ([] if '--sabotage' not in sys.argv else [('return r->value;','return r->value ^ 1u;'),(' || r->width * 8u != width','')]):
    assert old in source
    C.check(source.replace(old,new),True,data,harness,range(9),expected)
print('68020 joystick wrapper: nine controls pass' + ('; both sabotage plants caught' if '--sabotage' in sys.argv else ''))
