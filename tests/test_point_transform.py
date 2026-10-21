"""Authorized transform: original x86 vs xform20 adapter, no stored expectations."""
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


def boundaries():
    """Original bytes stay local; inputs cover sign/magnitude and guard edges."""
    ram = bytearray(B.X.RAM)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
    regs = dict(ax=0, bx=0, cx=0, dx=0, si=0, di=0, sp=0xfffe, bp=0x8000,
                cs=B.LOADSEG + 0x49b, ip=0x6b9b, ds=0x5000, ss=0x6000,
                es=0xa000, flags=0x7603)
    rng = random.Random(35)
    cases = []
    for v in (0, 1, 0xffff, 0x10000, 0x7fffffff, 0x80000000, 0xffffffff):
        for cam in (0, 1, 0xffffffff):
            cases.append((f'magnitude-{v:x}-{cam:x}', [v]*3, [cam]*3, [0xffff]*8, [0]*8, 0x5000))
    for mask in range(8):
        cases.append((f'signs-{mask}', [0x12348000,0x98765432,0x80000000], [0]*3,
                      [0x8001]*8, [0x8000 if mask>>(k%3)&1 else 0x1234 for k in range(8)], 0x5000))
    for ds in (0x1cbc, 0x1cbd, 0x1cbe, 0xefff, 0xf000, 0xf001, 0xffff):
        cases.append((f'guard-{ds:x}', [0xffffffff]*3, [1]*3, [0x8000]*8, [0xffff]*8, ds))
    for mul in (0, 1, 0x7fff, 0x8000, 0x8001, 0xffff):
        cases.append((f'product-{mul:x}', [0x10001,0xffff8000,0x7fffffff], [0]*3, [mul]*8, [0]*8, 0x5000))
    for k in range(32):
        cases.append((f'random-{k}', [rng.getrandbits(32) for _ in range(3)],
                      [rng.getrandbits(32) for _ in range(3)], [rng.getrandbits(16) for _ in range(8)],
                      [rng.getrandbits(16) for _ in range(8)], 0x5000))
    for name, points, camera, matrix, signs, ds in cases:
        data, r = bytearray(ram), dict(regs, ds=ds)
        for (hi, lo), v in zip((('ax','bx'),('dx','cx'),('si','di')), points):
            r[hi], r[lo] = v>>16, v & 0xffff
        for i, v in enumerate(camera):
            at = ds*16 + 0x2276 + 4*i
            data[at:at+4] = v.to_bytes(4, 'little')
        for start, values in ((0x224e, matrix), (0x225e, signs)):
            for i, v in enumerate(values):
                at = ds*16 + start + 2*i
                data[at:at+2] = v.to_bytes(2, 'little')
        yield name, bytes(data), r


@lru_cache(maxsize=1)
def program():
    p = emit.Program()
    node, resume = ('SWOTL.EXE', 0xb54b), ('SWOTL.EXE', 0xb708)
    compute.validate(p, node, resume)
    cache = ROOT/'tmp/point-transform'
    cache.mkdir(exist_ok=True)
    binary, addresses = B.program_image(p, cache)
    return p, node, resume, cache, binary, addresses


def run(entries=(), plant=None, predecessors=False, generated=False):
    p, node, resume, cache, binary, addresses = program()
    callback = (ROOT/'src/runtime/compute_transform.s').read_text()
    if generated:
        callback = 'rt_hle_point_transform:\n\tmoveq #0,d7\n\trts\n'
    if plant == 'missing-store':
        assert '\tmove.w \\3,(\\4,a3)' in callback
        callback = callback.replace('\tmove.w \\3,(\\4,a3)', '')
    elif plant == 'duplicate-store':
        store = '\tmove.w \\3,(\\4,a3)'
        assert store in callback
        callback = callback.replace(store, store + '\n' + store)
    elif plant == 'decline-state':
        callback = callback.replace('.decline:\n', '.decline:\n\tmove.w #1,d0\n')
    elif plant == 'guard':
        assert '\tbhi .decline' in callback
        callback = callback.replace('\tbhi .decline', '')
    elif plant == 'overlap-guard':
        callback = callback.replace('\tbcs .decline', '')
    elif plant == 'sign':
        callback = callback.replace('bpl,movea.l', 'bmi,movea.l', 1)
    elif plant == 'register':
        callback = callback.replace('\tmove.w d2,a5', '\tmove.w #0,a5')
    cases = list(boundaries())
    for path in entries:
        ram, regs = O.load_entry(path)
        cases.append((str(path), ram, regs))
    # This input rewrites future x86 instructions. Both oracle rejection and
    # native unchanged-state refusal are required; never run its static fallback
    # as an equivalence claim for arbitrary self-modifying code.
    _, alias_ram, alias_regs = cases[0]
    alias_ram, alias_regs = bytearray(alias_ram), dict(alias_regs)
    old_ds = alias_regs['ds']
    alias_regs['ds'] = 0x1150
    alias_ram[0x11500+0x224e:0x11500+0x2282] = alias_ram[old_ds*16+0x224e:old_ds*16+0x2282]
    cases.append(('code-alias-refusal', bytes(alias_ram), alias_regs))
    # Every legal predecessor reaches the same compute ABI; its own guest
    # stack effects remain in the generated caller and return protocol.
    modes = ('direct','jump','call','taken','fall','indirect','return') if predecessors else ('direct',)
    count = 0
    with tempfile.TemporaryDirectory(prefix='point-transform-', dir=cache) as scratch:
        for mode in modes:
            intro = {'direct': [], 'jump':['\tbra entry'], 'call':['\tbsr entry','\tjmp T_END'],
                     'taken':['\tcmp.w d0,d0','\tbeq entry','\tillegal'],
                     'fall':['\tcmp.w d0,d0','\tbne T_END'],
                     'indirect':['\tlea entry,a0','\tjmp (a0)'], 'return':['\tpea entry','\trts']}[mode]
            hook = compute.hook('rt_hle_point_transform', f'${addresses[emit.label(*resume)]:x}', '$cbd')
            source = [equates(), f'T_END equ ${B.D.STUB_AT["T_END"]:x}', f'\torg ${B.SNIP:x}', '\tdc.l before_call,result']
            source += intro + ['entry:', hook[0], 'before_call:', hook[1], 'result:'] + hook[2:]
            source += [f'\tjmp ${addresses[emit.label(*node)]:x}', callback]
            code = B.D.assemble('\n'.join(source), Path(scratch)/'callback.bin')
            before_at = int.from_bytes(code[:4], 'big')
            result_at = int.from_bytes(code[4:8], 'big')
            for name, ram, regs in cases:
                end = (regs['cs'], 0x6d58)
                if name == 'code-alias-refusal':
                    try:
                        O.run(ram, regs, end)
                    except ValueError as error:
                        assert str(error) == 'oracle self-modifying code entry', error
                    else:
                        raise AssertionError('oracle admitted code-alias entry')
                    expected = None
                else:
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
                    stop_at = result_at + 2 if expected is None else addresses[emit.label(*resume)]
                    m.extra_stops = {stop_at: 'compute_resume'}
                    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                    got, fl, fx, mem, outs, writes, info = m.run(B.SNIP+8,
                        (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(35), irq=False)
                    assert not info['err'] and info['stop'] == 'compute_resume' and not outs and not info['irq'], info
                    assert outcomes == [not generated and regs['cs'] + 0x1000 <= regs['ds'] <= 0xf000], (name, 'guard outcome', outcomes)
                    if expected is None:
                        assert not writes and not history and m.gread(0, B.X.RAM) == ram, name
                        count += 1
                        continue
                    got.update(cs=end[0], ip=end[1])
                    actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                                  writes=writes, history=history, ram=m.gread(0, B.X.RAM))
                    errors = O.compare(expected, actual, p.live_in[resume])
                    assert not errors, (name, mode, errors)
                    count += 1
                finally:
                    B.U.uc.uc_close(m.e.h)
    return count


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--entries', nargs='*', type=Path, default=[])
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    args = ap.parse_args()
    print('generated transform:', run(args.entries, generated=True), 'cases pass', flush=True)
    print('point transform:', run(args.entries, predecessors=args.predecessors), 'cases pass', flush=True)
    if args.sabotage:
        for plant in ('missing-store', 'duplicate-store', 'decline-state', 'guard', 'overlap-guard', 'sign', 'register'):
            try:
                run(plant=plant)
            except AssertionError as error:
                print('point transform:', plant, 'caught:', error, flush=True)
            else:
                raise AssertionError('plant survived: ' + plant)
