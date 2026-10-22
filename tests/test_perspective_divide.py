"""Authorized perspective divide: original x86 vs xdiv20 adapter."""
import argparse
from functools import lru_cache
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import m68k_blocks as B
from tools import compute_oracle as O
from translator import compute, emit, image
from translator.ir import FLAGS, FLAG_BIT
from translator.support import equates


class DivideMismatch(AssertionError):
    """An executed perspective-divide case disagrees with its oracle or ABI checks."""

    def __init__(self, cases, detail):
        super().__init__(detail)
        self.cases = cases


def predecessor_cases():
    """Report only comparison failures through the block differential protocol."""
    # Sabotage workers reuse the process with different translator patches.
    program.cache_clear()
    try:
        return run(predecessors=True), []
    except DivideMismatch as error:
        return error.cases, [str(error)]


def reporting_controls():
    from unittest.mock import patch
    module = sys.modules[__name__]
    with patch.object(module, 'run', return_value=7):
        assert predecessor_cases() == (7, [])
    with patch.object(module, 'run', side_effect=DivideMismatch(3, 'wrong return')):
        assert predecessor_cases() == (3, ['wrong return'])
    for error in (AssertionError('harness assertion'), RuntimeError('harness error')):
        with patch.object(module, 'run', side_effect=error):
            try:
                predecessor_cases()
            except type(error) as caught:
                assert caught is error
            else:
                raise AssertionError('unrelated harness error reported as a mismatch')
    cache_reporting_control()


def cache_reporting_control():
    from unittest.mock import patch
    module = sys.modules[__name__]
    try:
        with patch.object(emit, 'Program') as make_program, patch.object(compute, 'validate'), \
                patch.object(B, 'program_image', return_value=(b'', {})), \
                patch.object(module, 'run', side_effect=lambda **kw: (program(), 7)[1]):
            assert predecessor_cases() == (7, [])
            with patch.object(emit, 'cold_return', lambda lab: []):
                assert predecessor_cases() == (7, [])
            assert make_program.call_count == 2, 'divide program reused across plants'
    finally:
        program.cache_clear()


def boundaries():
    ram = bytearray(B.X.RAM)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
    base = dict(ax=0, bx=0x5678, cx=0x9abc, dx=0xdef0, si=0xabcd,
                di=0x4321, sp=0xfffe, bp=0x8000, cs=B.LOADSEG+0x49b,
                ip=0x6b32, ds=0x5000, ss=0x6000, es=0xa000, flags=0x7603)
    rng = random.Random(37)
    specs = []
    for ax in (0,1,2,0x7fff,0x8000,0x8001,0xffff):
        for denominator in (0,1,2,3,0x7fff,0x8000,0xffff):
            for scale in (0,1,0x7fff,0x8000,0xffff):
                specs.append((ax,denominator,scale,0x5000))
    for ds in (0,0xcbd,0x1cbd,0xf000,0xffff):
        specs.append((0x8000,3,0xffff,ds))
    specs += [(rng.randrange(65536),rng.randrange(65536),rng.randrange(65536),0x5000) for _ in range(32)]
    for ix,(ax,denominator,scale,ds) in enumerate(specs):
        data=bytearray(ram)
        for off,value in ((0x22c2,denominator),(0x22d8,scale)):
            data[ds*16+off:ds*16+off+2]=value.to_bytes(2,'little')
        yield f'divide-{ix}-{ax:x}-{denominator:x}-{scale:x}-{ds:x}',bytes(data),dict(base,ax=ax,ds=ds)


@lru_cache(maxsize=1)
def program():
    p = emit.Program()
    node, resume = ('SWOTL.EXE', 0xb4e2), ('SWOTL.EXE', 0xb52c)
    compute.validate(p, node, resume)
    cache = ROOT/'tmp/point-divide'
    cache.mkdir(exist_ok=True)
    binary, addresses = B.program_image(p, cache)
    return p, node, resume, cache, binary, addresses


def run(entries=(), plant=None, predecessors=False, generated=False, broken=False):
    p, node, resume, cache, binary, addresses = program()
    callback = (ROOT/'src/runtime/compute_divide.s').read_text() if not generated and not broken else ''
    if broken:
        callback = 'rt_hle_perspective_divide:\n\tmoveq #1,d7\n\trts\n'
    if generated:
        callback = 'rt_hle_perspective_divide:\n\tmoveq #0,d7\n\trts\n'
    if plant == 'rounding':
        callback = callback.replace('#$8000,d3', '#$7fff,d3')
    elif plant == 'register':
        callback = callback.replace('eori.w #$7fff,d5', 'moveq #0,d5')
    elif plant == 'sign':
        callback = callback.replace('neg.l d3', 'nop')
    elif plant == 'zero':
        callback = callback.replace('beq.b .multiply', 'nop')
    cases = list(boundaries())
    for path in entries:
        ram, regs = O.load_entry(path)
        cases.append((str(path), ram, regs))
    # Every legal predecessor reaches the same compute ABI; its own guest
    # stack effects remain in the generated caller and return protocol.
    modes = ('direct','jump','call','taken','fall','indirect','return') if predecessors else ('direct',)
    count = 0
    with tempfile.TemporaryDirectory(prefix='point-divide-', dir=cache) as scratch:
        for mode in modes:
            intro = {'direct': [], 'jump':['\tbra entry'], 'call':['\tbsr entry','\tjmp T_END'],
                     'taken':['\tcmp.w d0,d0','\tbeq entry','\tillegal'],
                     'fall':['\tcmp.w d0,d0','\tbne T_END'],
                     'indirect':['\tlea entry,a0','\tjmp (a0)'], 'return':['\tpea entry','\trts']}[mode]
            hook = compute.hook('rt_hle_perspective_divide', f'${addresses[emit.label(*resume)]:x}', '$cbd')
            source = [equates(), f'T_END equ ${B.D.STUB_AT["T_END"]:x}', f'\torg ${B.SNIP:x}', '\tdc.l before_call,result']
            source += intro + ['entry:', hook[0], 'before_call:', hook[1], 'result:'] + hook[2:]
            source += [f'\tjmp ${addresses[emit.label(*node)]:x}', callback]
            code = B.D.assemble('\n'.join(source), Path(scratch)/'callback.bin')
            before_at = int.from_bytes(code[:4], 'big')
            result_at = int.from_bytes(code[4:8], 'big')
            for name, ram, regs in cases:
                end = (regs['cs'], 0x6b7c)
                expected = O.run(ram, regs, end)
                m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
                outcomes, before = [], []
                @B.U.CODE_CB
                def result(h, addr, size, user):
                    saved = tuple(m.r(r) for r in ('d0','d1','d2','d3','d4','d5','a1','a2','a3','a4','a5','a6','a7'))
                    if addr == before_at:
                        before.append((saved, m.e.read(B.D.STATE, 16), m.gread(0, B.X.RAM)))
                    elif addr == result_at:
                        handled = m.r('d7') != 0
                        outcomes.append(handled)
                        # Fail outside the ctypes callback, whose exceptions are ignored.
                        if not before or saved[-2:] != before[0][0][-2:]:
                            outcomes.append('native stack or RAM base changed')
                        if before and m.e.read(B.D.STATE, 12) != before[0][1][:12]:
                            outcomes.append('segments, control flags or IRQ state changed')
                        if not handled and before and (saved, m.e.read(B.D.STATE, 16), m.gread(0, B.X.RAM)) != before[0]:
                            outcomes.append('decline mutated state')
                try:
                    m.load(binary)
                    m.e.write(B.SNIP, code)
                    m.e.hook_range(B.U.HOOK_CODE, result, before_at, result_at)
                    history = O.watch_native(m)
                    stop_at = addresses[emit.label(*resume)]
                    m.extra_stops = {stop_at: 'compute_resume'}
                    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                    got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
                        (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(36), irq=False)
                    if info['err'] or info['stop'] != 'compute_resume' or outs or info['irq']:
                        raise DivideMismatch(count + 1, (name, mode, 'execution', info, outs))
                    if outcomes != [not generated]:
                        raise DivideMismatch(count + 1, (name, mode, 'guard outcome', outcomes))
                    got.update(cs=end[0], ip=end[1])
                    actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                                  writes=writes, history=history, ram=m.gread(0, B.X.RAM))
                    errors = O.compare(expected, actual, p.live_in[resume])
                    if errors:
                        raise DivideMismatch(count + 1, (name, mode, errors))
                    count += 1
                finally:
                    B.U.uc.uc_close(m.e.h)
    return count


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--entries', nargs='*', type=Path, default=[])
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    ap.add_argument('--generated-only', action='store_true')
    ap.add_argument('--broken', action='store_true')
    args = ap.parse_args()
    reporting_controls()
    print('generated divide:', run(args.entries, generated=True), 'cases pass', flush=True)
    if args.generated_only:
        raise SystemExit(0)
    print('perspective divide:', run(args.entries, predecessors=args.predecessors, broken=args.broken), 'cases pass', flush=True)
    if args.sabotage:
        from unittest.mock import patch
        try:
            with patch.object(program, 'cache_clear', lambda: None):
                cache_reporting_control()
        except AssertionError as error:
            print('perspective divide: stale-program cache caught:', error, flush=True)
        else:
            raise AssertionError('plant survived: stale-program cache')
        finally:
            program.cache_clear()
        for plant in ('rounding', 'register', 'sign', 'zero'):
            try:
                run(plant=plant)
            except DivideMismatch as error:
                print('perspective divide:', plant, 'caught:', error, flush=True)
            else:
                raise AssertionError('plant survived: ' + plant)
