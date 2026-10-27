"""Scenery clear adapter and deferred vertex coverage against original x86.

Entry snapshots stay local; synthetic coverage always runs.
"""
import argparse
from functools import lru_cache
from pathlib import Path
import random
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from tools import compute_oracle as O
from translator import compute, emit, image
from translator.ir import FLAGS, FLAG_BIT, STATUS
from translator.support import equates

VERTEX = ('SWOTL.EXE', 0x10c08)
CLEAR = ('SWOTL.EXE', 0x10a2f)
# Loop heads of the vertex body where cases also enter generated code (the
# transform and projection loops); the row resumes there too (compute_resumes).
LOOP_ENTRIES = (('SWOTL.EXE', 0x10c1d), ('SWOTL.EXE', 0x10df8))


class SceneryMismatch(AssertionError):
    def __init__(self,cases,detail):
        super().__init__(detail)
        self.cases=cases


def predecessor_cases():
    program.cache_clear()
    count=0
    try:
        for mode in PREDECESSORS:
            count += run(native_clear=True,predecessor=mode)
    except SceneryMismatch as error:
        return count+error.cases,[str(error)]
    return count,[]


def reporting_controls():
    module=sys.modules[__name__]
    with patch.object(module,'run',return_value=1):
        assert predecessor_cases()==(7,[])
    with patch.object(module,'run',side_effect=SceneryMismatch(2,'wrong boundary')):
        assert predecessor_cases()==(2,['wrong boundary'])
    for error in (AssertionError('harness assertion'),RuntimeError('harness failure')):
        with patch.object(module,'run',side_effect=error):
            try: predecessor_cases()
            except type(error) as caught: assert caught is error
            else: raise AssertionError('harness failure reported as a caught mismatch')


@lru_cache(maxsize=1)
def program():
    original = image.rows
    common = dict(module='SWOTL.EXE', service='point_transform', args='', kind='compute',
                  reason='test-only scenery body', oracle=__file__, resume='continue')
    # I2: no row holds a sync access. 10CD1 and 10F0E (mov byte [9C20] before
    # the drawing calls 10CD6 and 10F13) end the body instead of those calls.
    rows = [dict(common, first='0x10C08', last='0x1112E',
                 exits='0x10CD1 0x10F0E 0x10F62 0x10F6A'),
            dict(common, first='0x10A2F', last='0x10A51')]
    existing = {int(r['first'],0) for r in original('hle.csv') if r['module']=='SWOTL.EXE'}
    rows = [r for r in rows if int(r['first'],0) not in existing]
    with patch.object(image,'rows',lambda name: original(name)+(rows if name=='hle.csv' else [])):
        p = emit.Program()
    body = p.compute_bodies[VERTEX]
    assert set(LOOP_ENTRIES) == set(body.loops), body.loops
    # 257 less the two sync accesses, plus 34 reached from the re-entries
    # 10CE4/10F21 (I10 ground_vertices row)
    assert len(body.body) == 289, len(body.body)
    assert not set(body.body) & p.loop_heads, 'vertex body loop heads left in the sync set'
    assert body.returns == tuple(('SWOTL.EXE', o) for o in (0x10cd1,0x10f0e,0x10f62,0x10f6a,0x11131))
    cache = ROOT/'tmp/scenery-differential'
    cache.mkdir(exist_ok=True)
    binary, addresses = B.program_image(p,cache)
    return p,binary,addresses


@lru_cache(maxsize=1)
def code():
    return O.code_addresses(program()[0], B.LOADSEG)


def synthetic():
    ram = bytearray(B.X.RAM)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    ram[B.LOADSEG*16:B.LOADSEG*16+len(raw)] = raw
    for role, off in (('clear',0x10a2f),('entry',0x10c08),('transform',0x10c1d),('projection',0x10df8)):
        settings = [(v,{}) for v in range(4)]
        settings += [(0,{'bp':v}) for v in (125,126,0x2dd,0x2de,0xc67f,0xc680,0xffff)]
        settings += [(0,{'sp':v}) for v in (13,14)]
        settings += [(0,{'ss':0x5100}), (0,{'es':0x5fff}), (0,{'es':0x5000})]
        settings += [(0,{'ds':v,'ss':v}) for v in (B.LOADSEG+0x109d+0xfff,
                                                   B.LOADSEG+0x109d+0x1000,0x9000,0x9001)]
        for case, (variant,changes) in enumerate(settings):
            data = bytearray(ram)
            regs = dict(ax=0x1234,bx=0x5500,cx=0x9abc,dx=0xdef0,si=0xbeef,di=0x300,
                        sp=0xec00,bp=0xf000,cs=B.LOADSEG+0x109d,ip=off-0x109d0,
                        ds=0x5000,ss=0x5000,es=0x6000,flags=0x7203 | (variant&1)*0x400)
            regs.update(changes)
            if role=='entry': regs['di']-=3
            if role=='projection': regs['ax']=0x5500
            def word(seg,off,value):
                for i in range(2): data[seg*16+((off+i)&65535)] = value>>(8*i)&255
            word(regs['ss'],regs['bp']-6,3)
            word(regs['ss'],regs['bp']-4,0x1000)
            for j,value in enumerate((3,-5,7)):
                word(regs['es'],0x1000+2*j,value)
            for j,value in enumerate((0x12345678,0xffffffff,0x7fffffff)):
                word(regs['ds'],0xc380+4*j,value)
                word(regs['ds'],0xc382+4*j,value>>16)
            if variant==2: data[regs['ss']*16+regs['bp']-96]=1  # cached vertex
            if role=='projection':
                word(regs['ss'],regs['bp']-606,-3)
                word(regs['ss'],regs['bp']-604,-1)
                word(regs['ss'],regs['bp']-726,5)
                if variant==2: data[regs['ss']*16+((regs['bp']-126)&65535)]=1
            if variant==3:
                word(regs['es'],0x1000,0x8000)  # midpoint, both source indices zero
                word(regs['es'],0x1002,0);word(regs['es'],0x1004,0)
                if role=='projection':
                    data[regs['ss']*16+((regs['bp']-66)&65535)]=1
                    word(regs['ss'],regs['bp']-484,3)
            yield f'{role}-{case}',bytes(data),regs, CLEAR if role=='clear' else VERTEX


def captured():
    for directory in sorted((ROOT/'tmp/pc-runs').glob('native-N4-scenery-*')):
        for path in sorted((directory/'trace').glob('snap-*')):
            if path.name=='snap-finish': continue
            ram, regs = O.load_entry(path)
            root = CLEAR if path.name.startswith('snap-clear') else VERTEX
            yield str(path),ram,regs,root


def arithmetic_and_exits():
    """Cold paths, signed word boundaries and aliases, independent of captures."""
    bases = {name: (ram, regs) for name, ram, regs, root in synthetic()}
    for role in ('transform', 'projection'):
        for case in range(48):
            ram, original = bases[role+'-3']  # midpoint
            data, regs = bytearray(ram), dict(original)
            def word(seg, off, value):
                for i in range(2):
                    data[seg*16+((off+i)&65535)] = (value>>(8*i))&255
            def byte(off, value):
                data[regs['ss']*16+(off&65535)] = value
            bp = regs['bp']
            first, second = ((0,0),(1,2),(29,1),(1,29),(30,0),(0xffff,0))[case//8]
            word(regs['es'],0x1002,first)
            word(regs['es'],0x1004,second)
            values = (0,1,-1,0x7fffffff,0x80000000,0xffff,0x10000,0xffff0001)
            for index, value in ((first,values[case%8]),(second,values[(case+3)%8])):
                # Native guards may decline indices outside the frame arrays;
                # their original accesses and wrap still have exact coverage.
                for displacement in (-246,-366,-486,-606,-726):
                    word(regs['ss'],bp+4*index+displacement,value)
                    word(regs['ss'],bp+4*index+displacement+2,value>>16)
                byte(bp+index-126,1)
            if role=='projection':
                # Take each of the two depth tests on both sides of >2.
                for index in (first,second):
                    word(regs['ss'],bp+4*index-484,(2,3,-1,0x7fff)[case%4])
                byte(bp-126,0)
            yield f'{role}-arithmetic-{case}',bytes(data),regs,VERTEX

    # Explicitly reach every continuation and each loop transition.
    for role, behind, count, counter, depth in (
        ('transform',0,1,0,0),
        ('transform',1,1,0,0),
        ('transform',1,2,1,0),
        ('transform',0,1,0,0xffff),
        ('projection',0,1,0,0),
        ('projection',0,0x80,0x7f,0),
        ('projection',0,0x7f,0x7e,0),
    ):
        ram, original = bases[role+'-2']  # cached
        data, regs = bytearray(ram),dict(original)
        bp, ss = regs['bp'],regs['ss']*16
        for off,value in ((bp-35,behind),(bp-36,counter),(bp-6,count),
                          (bp-484,depth&255),(bp-483,depth>>8)):
            data[ss+(off&65535)] = value
        yield f'{role}-exit-{behind}-{count}-{counter}-{depth}',bytes(data),regs,VERTEX


PREDECESSORS = ('direct','jump','call','taken','fall','indirect','return')


def run(original_entries=False, plant=None, native_clear=False,
        predecessor='direct'):
    p,binary,addresses = program()
    count = 0
    cases = list(synthetic()) + list(arithmetic_and_exits()) + (list(captured()) if original_entries else [])
    reached = set()
    callback, callbacks = None, {}
    native = native_clear
    assert predecessor in PREDECESSORS
    assert native or predecessor == 'direct'
    if native:
        cases = [case for case in cases if case[3] == (CLEAR if native_clear else VERTEX)]
    def make_callback(root,start):
        body = p.compute_bodies[root]
        assert start == root, 'compute rows have one entry (RC5)'
        for resume in (*body.returns,*body.loops):
            assert not (p.live_in[resume] & set(STATUS)), (resume,p.live_in[resume])
        service = 'rt_hle_scenery_clear' if root==CLEAR else 'rt_hle_scenery_vertices'
        hook = compute.hook(service,'handled_dispatch',f'${B.LOADSEG+0x109d:x}')
        source = [equates(), f'rt_stop_unknown equ ${B.STUB_AT["rt_stop_unknown"]:x}',
                  f'T_END equ ${B.D.STUB_AT["T_END"]:x}',
                  f'\torg ${B.SNIP:x}', '\tdc.l before_call,after_call']
        source += {'direct': [], 'jump':['\tbra entry'],
                   'call':['\tbsr entry','\tjmp T_END'],
                   'taken':['\tcmp.w d0,d0','\tbeq entry','\tillegal'],
                   'fall':['\tcmp.w d0,d0','\tbne T_END'],
                   'indirect':['\tlea entry,a0','\tjmp (a0)'],
                   'return':['\tpea entry','\trts']}[predecessor] + ['entry:']
        source += hook[:1]+['before_call:',hook[1],'after_call:']+hook[2:]
        source += [f'\tjmp ${addresses[emit.label(*start)]:x}']
        source += compute.resume_dispatch('handled_dispatch',
                    [f'${addresses[emit.label(*resume)]:x}' for resume in (*body.returns,*body.loops)],
                    f'${p.units[root[0]].ip_of(start[1]):x}')
        implementation = (ROOT/'src/runtime/compute_scenery.s').read_text()
        if plant == 'clear-store':
            implementation = implementation.replace('move.l d0,(\\1-3,a0)','nop')
        elif plant == 'clear-df':
            implementation = implementation.replace('tst.b G_DF(a6)\n\tbne .decline','nop')
        elif plant == 'clear-wrap':
            implementation = implementation.replace('cmp.w #126,d6\n\tbcs .decline','nop')
        source += [implementation]
        return B.D.assemble('\n'.join(source),ROOT/f'tmp/scenery-differential/native-{start[1]:x}.bin')
    for name,ram,regs,root in cases:
        row = p.compute_bodies[root]
        unit = p.units[root[0]]
        ends = {(regs['cs'],unit.ip_of(n[1])):n for n in row.returns}
        expected = O.run(ram,regs,next(iter(ends)),limit=10**6,returns=ends)
        destination = ends[expected['at']]
        start = next(n for n in (root,*LOOP_ENTRIES) if unit.ip_of(n[1])==regs['ip'])
        if native:
            if start not in callbacks: callbacks[start] = make_callback(root,start)
            callback = callbacks[start]
            before_at = int.from_bytes(callback[:4],'big')
            after_at = int.from_bytes(callback[4:8],'big')
        start_address = addresses[emit.label(*start)]
        def aliases(node):
            labels = (emit.label(*node),) if plant == 'missing-copy' else (emit.label(*node),emit.copy_label(*node))
            return {addresses[label] for label in labels
                    if label in addresses}
        service = p.hle[root][1]
        stubs = {n:a for n,a in B.STUB_AT.items() if plant != 'empty-native' or n != service}
        hles = {p.hle[n][1] for n in p.compute_rows}
        m = B.D.M68k(ram,stubs,hles - ({service} if plant == 'empty-native' else set()))
        before, outcomes = [], []
        @B.U.CODE_CB
        def native_result(h,address,size,user):
            saved = tuple(m.r(r) for r in ('d0','d1','d2','d3','d4','d5','a1','a2','a3','a4','a5','a6','a7'))
            state = (saved,m.e.read(B.D.STATE,16),m.gread(0,B.X.RAM))
            if address == before_at:
                before.append(state)
            elif address == after_at:
                handled = m.r('d7') != 0
                outcomes.append(handled)
                if not before or saved[-2:] != before[0][0][-2:]:
                    outcomes.append('native stack or RAM base changed')
                if not handled and before and state != before[0]:
                    outcomes.append('decline changed state')
        try:
            m.load(binary)
            if callback:
                m.e.write(B.SNIP,callback)
                m.e.hook_range(B.U.HOOK_CODE,native_result,before_at,after_at)
            if plant == 'empty-native': m.e.write(B.STUB_AT[service],bytes.fromhex('7e014e75'))
            O.watch_native(m)
            m.extra_stops = {address:str(n) for n in row.returns for address in aliases(n)}
            flags = {f:regs['flags']>>FLAG_BIT[f]&1 for f in FLAGS}
            got,fl,fx,mem,outs,writes,info = m.run(B.SNIP+8 if callback else start_address,
                (regs,flags,regs['flags']&0xf000,regs['ip'],[]),random.Random(40),irq=False)
            if info['err'] or outs or info['irq']:
                raise SceneryMismatch(count+1,(name,info,outs))
            if info['stop']!=str(destination):
                raise SceneryMismatch(count+1,(name,'wrong boundary',info['stop'],destination))
            got.update(cs=expected['at'][0],ip=expected['at'][1])
            actual = dict(registers=got,flags=fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS),
                          writes=writes,ram=m.gread(0,B.X.RAM))
            errors = O.compare(expected,actual,p.live_in[destination],code())
            if errors: raise SceneryMismatch(count+1,(name,errors))
            if callback:
                admitted = (not (regs['flags']&0x400) and regs['cs']+0x1000 <= regs['ss'] <= 0x9000 and regs['bp'] >= 126)
                if outcomes != [admitted]:
                    raise SceneryMismatch(count+1,(name,'guard outcome',outcomes,admitted))
            count += 1
            reached.add(destination)
            print('scenery native:' if callback else 'scenery generated:',name,predecessor,'->',hex(destination[1]),
                  'pass',flush=True)
        finally:
            B.U.uc.uc_close(m.e.h)
    required = set(p.compute_bodies[VERTEX].returns) | set(p.compute_bodies[CLEAR].returns)
    if native_clear: required = set(p.compute_bodies[CLEAR].returns)
    assert required <= reached, ('uncovered scenery boundaries',required-reached)
    return count


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original-entries',action='store_true')
    ap.add_argument('--sabotage',action='store_true')
    ap.add_argument('--native-clear',action='store_true')
    ap.add_argument('--predecessor',choices=PREDECESSORS,default='direct')
    ap.add_argument('--predecessors',action='store_true')
    args=ap.parse_args()
    reporting_controls()
    print('scenery cases:',run(args.original_entries,native_clear=args.native_clear,
                              predecessor=args.predecessor),'pass',flush=True)
    if args.predecessors:
        count,errors=predecessor_cases()
        assert not errors,errors
        print('scenery clear predecessors:',count,'pass',flush=True)
    if args.sabotage:
        plants = ('clear-store','clear-df','clear-wrap') if args.native_clear else ('missing-copy','empty-native')
        for plant in plants:
            try: run(plant=plant,native_clear=args.native_clear)
            except SceneryMismatch as error:
                if plant=='missing-copy': assert 'wrong boundary' in str(error), error
                else: assert any(x in str(error) for x in ('register','RAM','live flags','write addresses','guard outcome')), error
                print('scenery:',plant,'caught',error,flush=True)
            else: raise AssertionError(plant+' escaped')
