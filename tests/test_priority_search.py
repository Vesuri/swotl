"""BFD1 priority-search coverage; original x86 is the oracle."""
from pathlib import Path
import argparse
import random
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from tools import compute_oracle as O
from translator import emit, image
from translator.ir import FLAGS, FLAG_BIT

SCOPES = ((0xc2f2, 0xc302), (0xc32d, 0xc33d))


def synthetic(first):
    raw = B.relocated(image.load()['SWOTL.EXE'])
    cases = [(bx, values, es) for bx in (0x41f2, 0x4200, 0, 1, 0xffff, 0x8000, 0x8001)
             for values in ((1,), (0, 0x80, 0xff, 0x7f)) for es in (0x6000, 0x9000)]
    for index, (bx, values, es) in enumerate(cases):
        ram = bytearray(B.X.RAM)
        ram[B.LOADSEG*16:B.LOADSEG*16+len(raw)] = raw
        for step, value in enumerate(values, 1):
            ram[es*16+((bx-2*step)&0xffff)] = value
        regs = dict(ax=0x8123, bx=bx, cx=0, dx=0xfffe, si=0x2445,
                    di=0xfffe, sp=0xec00, bp=0xf000, cs=B.LOADSEG+0x49b,
                    ip=first-0x49b0, ds=0x5000, ss=0x7000, es=es,
                    flags=0x7202 | (index&1)*0x400)
        yield f'{first:x}-synthetic-{index}', bytes(ram), regs


def guard_cases(first):
    name, ram, base = next(synthetic(first))
    for es in (0x9001, 0xffff):
        yield f'{first:x}-guard-{es:x}', ram, dict(base, es=es)


def captured(first):
    directories=sorted((ROOT/'tmp/pc-runs').glob(f'native-N4-raster-{first:X}-*'))
    assert len(directories)==3, 'three original-game fixtures required'
    for directory in directories:
        assert len(list((directory/'trace').glob('snap-entry*')))==3, directory
        for path in sorted((directory/'trace').glob('snap-entry*')):
            ram, regs=O.load_entry(path)
            yield str(path), ram, regs


class PriorityMismatch(AssertionError):
    pass


def generated(entries=False, plant=False):
    p=emit.Program()
    work=ROOT / f'tmp/priority-search-generated-{os.getpid()}'
    work.mkdir(exist_ok=True)
    binary, addresses=B.program_image(p, work)
    if plant:
        changed=bytearray(binary)
        for lo, hi in ((0xc2fa, 0xc2fe), (0xc335, 0xc339)):
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
                    raise PriorityMismatch((name,info))
                got.update(cs=expected['at'][0],ip=expected['at'][1])
                actual=dict(registers=got,flags=fx|sum(fl[f]<<FLAG_BIT[f] for f in FLAGS),
                            writes=writes,history=history,ram=m.gread(0,B.X.RAM))
                errors=O.compare(expected,actual,p.live_in[('SWOTL.EXE',end)])
                if errors: raise PriorityMismatch((name,errors))
                total+=1
            finally:
                B.U.uc.uc_close(m.e.h)
    return total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    for arg in ('entries', 'sabotage', 'generated'):
        ap.add_argument('--' + arg, action='store_true')
    args = ap.parse_args()
    print('priority searches:', generated(args.entries), 'generated oracle cases pass', flush=True)
    if args.sabotage:
        try:
            generated(plant=True)
        except PriorityMismatch as error:
            print('priority searches: missing generated read caught:', error, flush=True)
        else:
            raise AssertionError('missing generated read escaped')
