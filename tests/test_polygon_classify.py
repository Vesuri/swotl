"""Deferred polygon classification: retained original/generated coverage."""
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

STUB_AT = dict(B.STUB_AT, rt_hle_polygon_classify=B.D.STUB + 4 * len(B.STUBS))


class ClassifyMismatch(AssertionError):
    """An executed polygon-classify case disagrees with its oracle or ABI checks."""

    def __init__(self, cases, detail):
        super().__init__(detail)
        self.cases = cases


def predecessor_cases():
    """Report only comparison failures through the block differential protocol."""
    # Sabotage workers reuse the process with different translator patches.
    program.cache_clear()
    try:
        return run(predecessors=True), []
    except ClassifyMismatch as error:
        return error.cases, [str(error)]


def reporting_controls():
    from unittest.mock import patch
    module = sys.modules[__name__]
    with patch.object(module, 'run', return_value=7):
        assert predecessor_cases() == (7, [])
    with patch.object(module, 'run', side_effect=ClassifyMismatch(3, 'wrong return')):
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
        with patch.object(emit, 'Program') as make_program, patch.object(module, 'check_body'), \
                patch.object(B, 'program_image', return_value=(b'', {})), \
                patch.object(module, 'run', side_effect=lambda **kw: (program(), 7)[1]):
            assert predecessor_cases() == (7, [])
            with patch.object(emit, 'cold_return', lambda lab: []):
                assert predecessor_cases() == (7, [])
            assert make_program.call_count == 2, 'classify program reused across plants'
    finally:
        program.cache_clear()


def boundaries():
    ram = bytearray(B.X.RAM)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
    base = dict(ax=0x1234, bx=0x5678, cx=0x9abc, dx=0xdef0, si=0xabcd,
                di=0x4321, sp=0xf000, bp=0x8000, cs=B.LOADSEG+0x49b,
                ip=0x71c0, ds=0x5000, ss=0x5000, es=0xa000, flags=0x7603)
    rng = random.Random(39)
    specs = [ [(x,y) for x,y in points] for points in (
        [(0,0),(1,1)], [(1,1),(0,0)], [(0,-1),(1,-2)],
        [(0,1),(1,1),(2,1)], [(0,1),(1,3),(2,1),(3,2)],
        [(0,3),(1,1),(2,2),(3,3)], [(0,1),(1,2),(2,3),(3,1)],
        [(-1,0),(-2,1)], [(320,0),(321,1)],
        [(0,200),(1,201)], [(0x7fffffff,0),(-0x80000000,1)]
    )]
    specs += [[(rng.randrange(-400,401),rng.randrange(-300,301))
               for _ in range(n)] for n in range(2,17) for _ in range(4)]
    variants=[(points,0x2600,0xf000) for points in specs]
    variants += [([(0,0),(1,1)], ptr, sp) for ptr,sp in
                 ((0x300,0xf000),(0xfff8,0xf000),(0x2600,0xc400))]
    variants += [([(j,j) for j in range(17)],0x2600,0xf000)]
    variants += [([(0,-1)],0x2600,0xf000)]
    variants += [([(0,-1),(1,-2)],ptr,0xf000) for ptr in
                 (0x23e2,0x23e3,0x2491,0x2492,0x24a2,0x24a3,0xc3e8,0xc3e9)]
    variants += [([(0,0),(1,1)],0x2600,sp) for sp in (0xc40f,0xc410,0xfff8,0xfff9)]
    for ix, (points,ptr,stack) in enumerate(variants):
        regs=dict(base,sp=stack)
        data = bytearray(ram)
        def word(seg,off,value):
            at=seg*16+(off&65535)
            data[at:at+2]=(value&65535).to_bytes(2,'little')
        ds,ss,sp=regs['ds'],regs['ss'],regs['sp']
        word(ss,sp+4,ptr); word(ss,sp+6,len(points))
        word(ds,0x2338,200); word(ds,0x233c,320)
        for j in range(16): word(ds,0x23c3+j*2,1<<j)
        for j,(x,y) in enumerate(points):
            for k,value in enumerate((x,x>>16,y,y>>16)):
                word(ds,ptr+j*8+k*2,value)
        yield f'classify-{ix}',bytes(data),regs


def fast_entry(ram, regs):
    # Expected admission only; never supplies a native result.
    ds,ss,sp=regs['ds'],regs['ss'],regs['sp']
    def word(off):
        at=ss*16+((sp+off)&65535)
        return int.from_bytes(ram[at:at+2],'little')
    ptr,n=word(4),word(6)
    end=ptr+8*n
    return (ss==ds and regs['cs']+0x1000<=ds<=0x9000 and
            0xc410<=sp<=0xfff8 and 2<=n<=16 and
            ((0x23e3<=ptr and end<=0x24a1) or (0x24a3<=ptr and end<=0xc3f8)))


def check_body(p, node, resume):
    # Program proves the body before installing its sync-entry hooks.
    row = p.compute_bodies[node]
    sync = tuple(('SWOTL.EXE', off) for off in
                 (0xbbac, 0xbbb3, 0xbc55, 0xbc73, 0xbcc4, 0xbd14, 0xbd44))
    assert row.returns == (resume,)
    assert tuple(row.sync) == sync
    assert node in row.body and resume not in row.body
    assert set(sync) <= row.body
    assert set(sync) | {resume} <= p.loop_heads
    for entry, site in enumerate((node, *sync)):
        assert p.polled_entry[site] == entry
        assert p.polled_resumes[site] == [resume, *sync]


@lru_cache(maxsize=1)
def program():
    from unittest.mock import patch
    original = image.rows
    row = dict(module='SWOTL.EXE', first='0xBB70', last='0xBD66',
               service='polygon_classify', args='', kind='compute',
               reason='Test-only U5 body; native candidate deferred',
               oracle='tests/test_polygon_classify.py',
               polls='return 0xBBAC 0xBBB3 0xBC55 0xBC73 0xBCC4 0xBD14 0xBD44')
    with patch.object(image, 'rows', lambda name: original(name) +
                      ([row] if name == 'hle.csv' else [])):
        p = emit.Program()
    node, resume = ('SWOTL.EXE', 0xbb70), ('SWOTL.EXE', 0xbd67)
    check_body(p, node, resume)
    cache = ROOT/'tmp/polygon-classify'
    cache.mkdir(exist_ok=True)
    with patch.object(B, 'STUB_AT', STUB_AT):
        binary, addresses = B.program_image(p, cache)
    return p, node, resume, cache, binary, addresses


def run(entries=(), predecessors=False, generated=True, broken=False):
    p, node, resume, cache, binary, addresses = program()
    callback = 'rt_hle_polygon_classify:\n\tmoveq #0,d7\n\trts\n'
    if broken:
        callback = 'rt_hle_polygon_classify:\n\tmoveq #1,d7\n\trts\n'
    cases = list(boundaries())
    for path in entries:
        ram, regs = O.load_entry(path)
        cases.append((str(path), ram, regs))
    # Every legal predecessor reaches the same compute ABI; its own guest
    # stack effects remain in the generated caller and return protocol.
    modes = ('direct','jump','call','taken','fall','indirect','return') if predecessors else ('direct',)
    count, longest = 0, 0.0
    with tempfile.TemporaryDirectory(prefix='polygon-classify-', dir=cache) as scratch:
        for mode in modes:
            intro = {'direct': [], 'jump':['\tbra entry'], 'call':['\tbsr entry','\tjmp T_END'],
                     'taken':['\tcmp.w d0,d0','\tbeq entry','\tillegal'],
                     'fall':['\tcmp.w d0,d0','\tbne T_END'],
                     'indirect':['\tlea entry,a0','\tjmp (a0)'], 'return':['\tpea entry','\trts']}[mode]
            hook = compute.polled_hook('rt_hle_polygon_classify', 0, 'handled_dispatch', '$cbd')
            source = [equates(), f'T_END equ ${B.D.STUB_AT["T_END"]:x}',
                      f'rt_stop_unknown equ ${B.STUB_AT["rt_stop_unknown"]:x}',
                      f'\torg ${B.SNIP:x}', '\tdc.l before_call,result']
            source += intro + ['entry:'] + hook[:2] + ['before_call:', hook[2], 'result:'] + hook[3:]
            source += [f'\tjmp ${addresses[emit.label(*node)]:x}']
            source += compute.polled_dispatch('handled_dispatch',
                [f'${addresses[emit.label(*resume)]:x}'], '$71c0') + [callback]
            code = B.D.assemble('\n'.join(source), Path(scratch)/'callback.bin')
            before_at = int.from_bytes(code[:4], 'big')
            result_at = int.from_bytes(code[4:8], 'big')
            for name, ram, regs in cases:
                end = (regs['cs'], 0x73b7)
                expected = O.run(ram, regs, end)
                m = B.D.M68k(ram, STUB_AT, {p.hle[n][1] for n in p.compute_rows})
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
                    latency = O.PollGaps(m, binary)
                    stop_at = addresses[emit.label(*resume)]
                    m.extra_stops = {stop_at: 'compute_resume'}
                    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                    got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
                        (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(36), irq=False)
                    if info['err'] or info['stop'] != 'compute_resume' or outs or info['irq']:
                        raise ClassifyMismatch(count + 1, (name, mode, 'execution', info, outs))
                    if outcomes != [not generated and fast_entry(ram, regs)]:
                        raise ClassifyMismatch(count + 1, (name, mode, 'guard outcome', outcomes))
                    got.update(cs=end[0], ip=end[1])
                    actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                                  writes=writes, history=history, ram=m.gread(0, B.X.RAM))
                    errors = O.compare(expected, actual, p.live_in[resume])
                    if errors:
                        raise ClassifyMismatch(count + 1, (name, mode, errors))
                    longest = max(longest, latency.longest())
                    if latency.longest() > O.PIT_PERIOD_CYCLES:
                        raise ClassifyMismatch(count + 1, (name, mode, "latency", latency.longest()))
                    count += 1
                finally:
                    B.U.uc.uc_close(m.e.h)
    print("classify latency:", "generated" if generated else "native", longest, "model cycles", flush=True)
    return count


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--entries', nargs='*', type=Path, default=[])
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    args = ap.parse_args()
    reporting_controls()
    print('generated classify:', run(args.entries, predecessors=args.predecessors), 'cases pass', flush=True)
    from test_polygon_classify_sync import run as sync_run
    print('classifier sync handoffs:', sync_run(), 'pass', flush=True)
    if args.sabotage:
        try:
            run(broken=True)
        except ClassifyMismatch:
            print('classification: premature handled return caught', flush=True)
        else:
            raise AssertionError('premature return escaped')
        try:
            sync_run(broken=True)
        except AssertionError:
            print('classification: skipped sync handoff caught', flush=True)
        else:
            raise AssertionError('skipped sync escaped')
        from unittest.mock import patch
        try:
            with patch.object(program, 'cache_clear', lambda: None):
                cache_reporting_control()
        except AssertionError:
            print('classification: stale-program cache caught', flush=True)
        else:
            raise AssertionError('stale-program cache escaped')
        finally:
            program.cache_clear()
