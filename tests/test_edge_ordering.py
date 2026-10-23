"""BFD1 edge-ordering coverage; original x86 is the oracle."""
from pathlib import Path
import argparse
import random
import re
import os
from functools import lru_cache
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from tools import compute_oracle as O
from translator import emit, image
from translator.support import equates
from translator.ir import FLAGS, FLAG_BIT

SCOPES = ((0xc0c2, 0xc1c2),)


def synthetic(first):
    raw = B.relocated(image.load()['SWOTL.EXE'])
    variants = [(positions, flags, life, priority)
                for positions in ((30, 20, 10), (10, 20, 30), (20, 20, 20),
                                  (0x8000, 0x7fff, 0xffff))
                for flags in ((0, 0, 0), (1, 2, 3), (0x80, 0x40, 0),
                              (0x40, 0, 0x80))
                for life, priority in ((2, 1), (0, 0))]
    for index, (positions, flags, life, priority) in enumerate(variants):
        ram = bytearray(B.X.RAM)
        ram[B.LOADSEG*16:B.LOADSEG*16+len(raw)] = raw
        def word(segment, offset, value):
            at = segment*16+offset
            ram[at:at+2] = (value & 65535).to_bytes(2, 'little')
        pointers = (0x100, 0x200, 0x300) if index % 2 else (0xfffc, 0x7ffc, 0x100)
        for i, ptr in enumerate(pointers):
            word(0x6000, 0x4062+i*2, ptr)
            word(0x6000, ptr, life)
            word(0x6000, (ptr+2)&65535, priority)
            ram[0x60000+((ptr+4)&65535)] = i % 2
            ram[0x60000+((ptr+5)&65535)] = flags[i]
            word(0x6000, (ptr+6)&65535, positions[i])
            word(0x6000, (ptr+8)&65535, 123)
        regs = dict(ax=3, bx=0x8765, cx=0xabcd, dx=0xfffe, si=0x2445,
                    di=0xfffe, sp=0xec00, bp=0xf000, cs=B.LOADSEG+0x49b,
                    ip=first-0x49b0, ds=0x5000, ss=0x7000, es=0x6000,
                    flags=0x7202 | (index&1)*0x400)
        yield f'{first:x}-synthetic-{index}', bytes(ram), regs


def guard_cases(first):
    _, ram, regs = next(synthetic(first))
    for seg in ('ds', 'es'):
        for value in (regs['cs']+0x1000, 0x9000):
            copied = bytearray(ram)
            start = regs[seg]*16
            copied[value*16:value*16+0x10000] = ram[start:start+0x10000]
            yield f'{seg}-boundary-{value:x}', bytes(copied), dict(regs, **{seg:value})
    yield 'aliased-data-segments', ram, dict(regs, ds=regs['es'])


def captured(first):
    directories=sorted((ROOT/'tmp/pc-runs').glob(f'native-N4-ordering-{first:X}-*'))
    assert len(directories)==3, 'three original-game fixtures required'
    for directory in directories:
        assert len(list((directory/'trace').glob('snap-entry*')))==3, directory
        for path in sorted((directory/'trace').glob('snap-entry*')):
            ram, regs=O.load_entry(path)
            yield str(path), ram, regs


class OrderingMismatch(AssertionError):
    pass


def generated(entries=False, plant=False):
    original = image.rows
    with patch.object(image, 'rows', lambda name: [r for r in original(name)
                      if not (name == 'hle.csv' and r.get('service') == 'edge_ordering')]):
        p = emit.Program()
    work=ROOT / f'tmp/edge-ordering-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    binary, addresses=B.program_image(p, work)
    if plant:
        changed=bytearray(binary)
        for lo, hi in ((0xc121, 0xc124),):
            a=addresses[emit.label("SWOTL.EXE",lo)]-B.D.CODE
            z=addresses[emit.label("SWOTL.EXE",hi)]-B.D.CODE
            assert z>a and (z-a)%2==0
            changed[a:z]=b"\x4e\x71"*((z-a)//2)
        binary=bytes(changed)
    total=0
    for first, end in SCOPES:
        cases=list(synthetic(first))+list(guard_cases(first))+(list(captured(first)) if entries else [])
        for name, ram, regs in cases:
            expected=O.run(ram, regs, (regs['cs'], end-0x49b0), limit=100000)
            m=B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
            try:
                m.load(binary)
                m.extra_stops={addresses[emit.label('SWOTL.EXE', end)]:'endpoint'}
                history=O.watch_native(m)
                flags={f:regs['flags']>>FLAG_BIT[f]&1 for f in FLAGS}
                got, fl, fx, mem, outs, writes, info=m.run(addresses[emit.label('SWOTL.EXE', first)],
                    (regs,flags,regs['flags']&0xf000,regs['ip'],[]),random.Random(41),irq=False)
                if info['err'] or outs or info['irq'] or info['stop']!='endpoint':
                    raise OrderingMismatch((name,info))
                got.update(cs=expected['at'][0],ip=expected['at'][1])
                actual=dict(registers=got,flags=fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS),
                            writes=writes,history=history,ram=m.gread(0,B.X.RAM))
                errors=O.compare(expected,actual,p.live_in[('SWOTL.EXE',end)])
                if errors: raise OrderingMismatch((name,errors))
                total+=1
            finally:
                B.U.uc.uc_close(m.e.h)
    return total


POLLS = (0xc0c5, 0xc0d1, 0xc11a, 0xc129)
PREDECESSORS = ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return')


@lru_cache(maxsize=1)
def native_program():
    original = image.rows
    row = dict(module='SWOTL.EXE', first='0xC0C2', last='0xC1BF',
               service='edge_ordering', args='', kind='compute', polls='exact',
               resume='continue', reason='authorized ordering differential', oracle=__file__)
    present = any(r.get('service') == 'edge_ordering' for r in original('hle.csv'))
    with patch.object(image, 'rows', lambda name: original(name) +
                      ([row] if name == 'hle.csv' and not present else [])):
        return emit.Program()


def admitted(regs):
    return all(regs['cs'] + 0x1000 <= regs[s] <= 0x9000 for s in ('ds', 'es'))


def native_image(diagnostic=False, plant=None, predecessor='direct'):
    p = native_program()
    source = (ROOT/'src/runtime/compute_ordering.s').read_text()
    templates = {'write': ('move.w a5,-1(a1,a0.w)', 'nop'),
                 'index': ('subq.w #2,a0', 'subq.w #1,a0'),
                 'guard': ('bhi.w edge_ordering_decline', 'nop'),
                 'selector': ('cmp.l #1,d6', 'cmp.l #2,d6')}
    if plant in templates:
        old, new = templates[plant]
        assert old in source
        source = source.replace(old, new)
    if plant == 'poll':
        old = 'rt_hle_edge_ordering_poll_1_local edge_ordering_pending_compare'
        assert old in source
        lab = emit.label('SWOTL.EXE', POLLS[1])
        source = source.replace(old, f'{lab}_native_poll:\n nop\n{lab}_native_np:')
    with patch.object(p, 'diagnostic_hooks', {('SWOTL.EXE', a): i for i,a in enumerate(POLLS)} if diagnostic else {}):
        macros = p.native_poll_text()
    prefix = {'direct': [], 'jump': ['bra entry'], 'call': ['bsr entry', 'bra done'],
              'taken': ['cmp.w d0,d0', 'beq entry', 'illegal'],
              'fall': ['cmp.w d0,d0', 'bne done'], 'indirect': ['lea entry,a0', 'jmp (a0)'],
              'return': ['pea entry', 'rts']}[predecessor]
    text = [equates(), f'rt_irq equ ${B.STUB_AT["rt_irq"]:x}', macros,
            f'org ${B.SNIP:x}', 'dc.l done,0', *prefix, 'entry:',
            f'move.l ${B.SNIP+4:x},d7', f'move.l #${B.LOADSEG+0x49b:x},d6',
            'jsr rt_hle_edge_ordering', 'rts' if predecessor == 'call' else 'bra done',
            'done:', 'nop', source]
    for i, poll in enumerate(POLLS):
        text += emit.native_poll_stub(emit.label('SWOTL.EXE', poll), poll-0x49b0,
                                      f'${B.LOADSEG+0x49b:x}', i+2)
    work = ROOT/f'tmp/edge-ordering-native-{os.getpid()}'
    work.mkdir(exist_ok=True)
    text = [('\t'+line if '\n' not in line and not line.endswith(':')
             and ' equ ' not in line and not line.startswith('\t') else line) for line in text]
    return B.D.assemble('\n'.join(text), work/f'{diagnostic}-{plant}-{predecessor}.bin')


def native_run(binary, ram, regs, selector=0):
    binary = binary[:4] + selector.to_bytes(4, 'big') + binary[8:]
    m = B.D.M68k(ram, B.STUB_AT)
    m.irq_calls = []
    try:
        m.e.write(B.SNIP, binary)
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        history = O.watch_native(m)
        flags = {f:regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
            (regs, flags, regs['flags']&0xf000, regs['ip'], []), random.Random(41), irq=False)
        if info['err'] or outs or info['stop'] != 'done' or info['a7'] != B.D.STACK-0x100:
            raise OrderingMismatch(info)
        result = m.r('d7')
        return dict(registers=got, flags=fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS),
                    writes=writes, history=history, ram=m.gread(0,B.X.RAM)), result, len(m.irq_calls)
    finally:
        B.U.uc.uc_close(m.e.h)


def native(entries=False, plant=None, predecessor='direct'):
    p = native_program(); binary = native_image(plant=plant, predecessor=predecessor)
    cases = list(synthetic(SCOPES[0][0])) + list(guard_cases(SCOPES[0][0])) + (list(captured(SCOPES[0][0])) if entries else [])
    for name, ram, regs in cases:
        expected = O.run(ram, regs, (regs['cs'], SCOPES[0][1]-0x49b0), limit=100000)
        actual, result, irqs = native_run(binary, ram, regs)
        actual['registers'].update(cs=expected['at'][0], ip=expected['at'][1])
        errors = O.compare(expected, actual, p.live_in['SWOTL.EXE', SCOPES[0][1]])
        if errors or result != 1 or irqs:
            raise OrderingMismatch((name, errors, result, irqs))
    _, ram, regs = cases[0]
    for seg in ('ds', 'es'):
        for value in (0, regs['cs']+0xfff, 0x9001, 0xffff):
            changed = dict(regs, **{seg:value})
            actual, result, irqs = native_run(binary, ram, changed)
            if result or irqs or actual['writes'] or actual['history'] or actual['ram'] != ram:
                raise OrderingMismatch((seg, value, 'decline mutation'))
            if any(actual['registers'][k] != v for k,v in changed.items() if k in actual['registers']):
                raise OrderingMismatch((seg, value, 'decline registers'))
            if actual['flags'] | 2 != changed['flags']:
                raise OrderingMismatch((seg, value, 'decline flags'))
    return len(cases)+8


def generated_call_selectors(p):
    # Input selectors come from generated calls, not callback return values.
    lines, _ = p.module_text('SWOTL.EXE')
    out = {}
    for site in POLLS:
        label = emit.label('SWOTL.EXE', site) + '_np:'
        start = lines.index(label)
        call = next(i for i in range(start+1, len(lines))
                    if lines[i].strip() == 'jsr rt_hle_edge_ordering')
        values = [int(m[1]) for line in lines[start:call]
                  if (m := re.search(r'moveq #([0-9]+),d7', line))]
        assert len(values) == 1, (site, lines[start:call])
        out[site] = values[0]
    return out


def poll_prefixes(plant=None):
    p = native_program(); binary = native_image(diagnostic=True, plant=plant)
    input_selectors = generated_call_selectors(p)
    count = 0; seen = set(); resume_states = {}
    cases = [(False, case) for case in synthetic(SCOPES[0][0])]
    name, ram, regs = next(synthetic(SCOPES[0][0]))
    cases += [(True, (f'count-{n}', ram, dict(regs, ax=n))) for n in (0, 1)]
    for bounded, (name, ram, regs) in cases:
        selector = 0
        for step in range(12 if bounded else 32):
            expected = O.run(ram, regs, (regs['cs'], SCOPES[0][1]-0x49b0),
                             stops=tuple((regs['cs'], a-0x49b0) for a in POLLS))
            actual, result, irqs = native_run(binary, ram, regs, selector)
            endpoint = expected['at'][1] + 0x49b0
            wanted = POLLS.index(endpoint)+2 if endpoint in POLLS else 1
            actual['registers'].update(cs=expected['at'][0], ip=expected['at'][1])
            errors = O.compare(expected, actual, p.live_in['SWOTL.EXE', endpoint])
            if errors or result != wanted or irqs != int(wanted != 1):
                raise OrderingMismatch((name, step, errors, result, wanted, irqs))
            count += 1
            if wanted == 1: break
            seen.add(endpoint)
            resume_states.setdefault(endpoint, (expected['ram'], dict(expected['registers'],
                cs=expected['at'][0], ip=expected['at'][1], flags=expected['flags']), input_selectors[endpoint]))
            selector = input_selectors[endpoint]
            ram = expected['ram']
            regs = dict(expected['registers'], cs=expected['at'][0], ip=expected['at'][1], flags=expected['flags'])
        else:
            if not bounded: raise OrderingMismatch((name, 'prefix step limit'))
    if seen != set(POLLS): raise OrderingMismatch(('poll coverage', seen))
    for site, (ram, regs, selector) in resume_states.items():
        for mode in ('bx', 'es'):
            changed = dict(regs, flags=regs['flags'] ^ 0x400)
            if mode == 'bx':
                changed['bx'] = (regs['bx'] + 2) & 65535
                memory = ram
            else:
                changed['es'] = 0x9000
                memory = bytearray(ram)
                memory[0x90000:0xa0000] = ram[regs['es']*16:regs['es']*16+0x10000]
                memory = bytes(memory)
            expected = O.run(memory, changed, (regs['cs'], SCOPES[0][1]-0x49b0),
                             stops=tuple((regs['cs'], a-0x49b0) for a in POLLS))
            actual, result, irqs = native_run(binary, memory, changed, selector)
            endpoint = expected['at'][1] + 0x49b0
            wanted = POLLS.index(endpoint)+2 if endpoint in POLLS else 1
            actual['registers'].update(cs=expected['at'][0], ip=expected['at'][1])
            errors = O.compare(expected, actual, p.live_in['SWOTL.EXE', endpoint])
            if errors or result != wanted or irqs != int(wanted != 1):
                raise OrderingMismatch(('handler state', site, mode, errors, result, wanted, irqs))
            count += 1
    return count


def predecessor_cases():
    native_program.cache_clear()
    total = 0
    for predecessor in PREDECESSORS:
        try: total += native(predecessor=predecessor)
        except OrderingMismatch as error: return total+1, [str(error)]
    return total, []


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('entries', 'sabotage', 'generated', 'native', 'predecessors', 'polls'):
        ap.add_argument('--'+arg, action='store_true')
    args = ap.parse_args()
    if args.generated or not (args.native or args.predecessors or args.polls):
        print('edge ordering:', generated(args.entries), 'generated oracle cases pass', flush=True)
    if args.native or args.predecessors:
        for predecessor in PREDECESSORS if args.predecessors else ('direct',):
            print('edge ordering:', predecessor, native(args.entries, predecessor=predecessor), 'native cases pass', flush=True)
    if args.polls:
        print('edge ordering:', poll_prefixes(), 'original poll prefixes pass', flush=True)
    if args.sabotage:
        for plant in ('write', 'index', 'guard') if args.native else ():
            try: native(plant=plant)
            except OrderingMismatch as error: print('caught', plant, error, flush=True)
            else: raise AssertionError(plant+' escaped')
        if args.polls:
            for plant in ('poll', 'selector'):
                try: poll_prefixes(plant=plant)
                except OrderingMismatch as error: print('caught', plant, error, flush=True)
                else: raise AssertionError(plant+' escaped')
        try: generated(plant=True)
        except OrderingMismatch as error: print('caught missing swap write', error, flush=True)
        else: raise AssertionError('missing swap write escaped')
