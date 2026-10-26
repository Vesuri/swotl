"""Authorized projection B017 with its divide B4E2, whole: original x86 vs the native.

Four returns (B15F, B163, B392, B4E1); every path: the 16-bit path and its
rejects, the 32-bit paths (B17C, B1A5 near/far, 25C8, 25D0 bits) and B393.
"""
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

SERVICE = 'rt_hle_point_projection'
NODE = ('SWOTL.EXE', 0xb017)
RETURNS = (0xb15f, 0xb163, 0xb392, 0xb4e1)
CS = 0x49b      # B017's code segment, relative to the load segment
SNAPSHOTS = sorted(ROOT.glob('tmp/pc-runs/native-N2-projection-*/trace/snap-entry*'))


class ProjectionMismatch(AssertionError):
    """An executed projection case disagrees with its oracle or ABI checks."""

    def __init__(self, cases, detail):
        super().__init__(detail)
        self.cases = cases


def predecessor_cases():
    """Report only comparison failures through the block differential protocol."""
    # Sabotage workers reuse the process with different translator patches.
    program.cache_clear()
    try:
        return run(predecessors=True), []
    except ProjectionMismatch as error:
        return error.cases, [str(error)]


def reporting_controls():
    from unittest.mock import patch
    module = sys.modules[__name__]
    with patch.object(module, 'run', return_value=7):
        assert predecessor_cases() == (7, [])
    with patch.object(module, 'run', side_effect=ProjectionMismatch(3, 'wrong return')):
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
        region = compute.Region(frozenset(), tuple(('SWOTL.EXE', r) for r in RETURNS))
        with patch.object(emit, 'Program') as make_program, \
                patch.object(compute, 'validate', return_value=region), \
                patch.object(B, 'program_image', return_value=(b'', {})), \
                patch.object(module, 'run', side_effect=lambda **kw: (program(), 7)[1]):
            assert predecessor_cases() == (7, [])
            with patch.object(emit, 'cold_return', lambda lab: []):
                assert predecessor_cases() == (7, [])
            assert make_program.call_count == 2, 'projection program reused across plants'
    finally:
        program.cache_clear()


def magnitude(n, divisor):
    """B4E2's rounded magnitude for B017's scale B4h: (|n| << 16) / divisor."""
    q = (abs(n - 0x10000 if n & 0x8000 else n) << 16) // divisor if divisor else \
        abs(n - 0x10000 if n & 0x8000 else n) << 16
    return (q * 0xb4 + 0x8000) >> 16 & 0xffffffff


def scale_edges(rng, count):
    """16-bit path inputs whose scaled sum has low byte 80h before the rounding
    add (B128): rounding by 7Fh or 81h would differ. Python only picks inputs;
    the x86 oracle supplies every expected value."""
    def signed(m, n):
        return (-m if n & 0x8000 else m) & 0xffffffff
    out = []
    while len(out) < count:
        n1, n2, d = rng.getrandbits(16), rng.getrandbits(16), rng.getrandbits(16) | 0x100
        c6e, c70, s72, s74 = (rng.getrandbits(16) for _ in range(4))
        m1, m2 = magnitude(n1, d), magnitude(n2, d)
        if m1 >> 16 or m2 >> 16:
            continue
        hi1, hi2 = signed(m1, n1) >> 16, signed(m2, n2) >> 16
        t3 = (m1 * c6e + 0x8000) >> 16
        t3 = -t3 if (hi1 ^ s72) & 0x8000 else t3
        t4 = (m2 * c70 + 0x8000) >> 16
        t4 = -t4 if (hi2 ^ s74) & 0x8000 else t4
        total = (t3 + t4) & 0xffff
        if (((-total & 0xffff) if total & 0x8000 else total) * 0xe9) & 0xff == 0x80:
            out.append({0x22ba: n1, 0x22be: n2, 0x22c2: d, 0x226e: c6e, 0x2270: c70,
                        0x2272: s72, 0x2274: s74, 0x22fc: 0, 0x2302: 1, 0x258f: 0xffff,
                        0x2599: rng.choice((0xffff, rng.getrandbits(16)))})
    return out


def boundaries():
    ram = bytearray(B.X.RAM)
    raw = B.relocated(image.load()['SWOTL.EXE'])
    ram[B.LOADSEG * 16:B.LOADSEG * 16 + len(raw)] = raw
    base = dict(ax=0x1234, bx=0x5678, cx=0x9abc, dx=0xdef0, si=0xabcd,
                di=0x4321, sp=0xfffe, bp=0x8000, cs=B.LOADSEG + CS,
                ip=0xb017 - CS * 16, ds=0x5000, ss=0x6000, es=0xa000, flags=0x7603)
    rng = random.Random(37)
    words = (0, 1, 0x7fff, 0x8000, 0x8001, 0xffff)
    specs = []
    for k in range(480):
        nz = lambda: rng.choice((0, 0, 1, 0x8000, rng.getrandbits(16) | 1))
        spec = dict(name=f'random-{k}', c22fc=nz(), c2300=nz(), c22fe=nz(), c233e=nz(),
                    c25c8=nz(), c25d0=rng.getrandbits(16), c2302=rng.getrandbits(1),
                    n1=rng.choice(words + (rng.getrandbits(16),) * 3),
                    n2=rng.choice(words + (rng.getrandbits(16),) * 3),
                    d=rng.choice((0, 1, 2, 0xb4, 0x100, 0x7fff, 0x8000, 0xffff) + (rng.getrandbits(16),) * 4),
                    limit=None, sp=0xfffe, ds=0x5000)
        # Reject edges: the limit equal to, or one above, the magnitude.
        which = rng.randrange(3)
        if which:
            m = magnitude(spec['n1' if which == 1 else 'n2'], spec['d'])
            spec['limit'] = (m + rng.getrandbits(1)) & 0xffff
        specs.append(spec)
    # 32-bit paths with 8000h coefficients: an odd magnitude puts 8000h in the
    # product's low word, where the rounding add decides the carry.
    variants = [dict(c22fe=0, c233e=1, c25c8=c8, c25d0=d0, far=far)
                for c8 in (0, 1) for d0 in (0, 1, 2, 3) for far in (0, 1)]
    variants += [dict(c22fe=1, c233e=0, c25c8=0, c25d0=0, far=0), dict(c22fe=0, c233e=0, c25c8=0, c25d0=0, far=0)]
    for k, v in enumerate(variants):
        for odd in range(4):
            n1, n2 = rng.getrandbits(16), rng.getrandbits(16)
            extra = {0x22ba: n1, 0x22be: n2, 0x22c2: rng.getrandbits(8) | 1, 0x226e: 0x8000,
                     0x2270: 0x8000, 0x25ce: 0x8000, 0x22fc: 1, 0x2300: 1 if odd else 0,
                     0x22fe: v['c22fe'], 0x233e: v['c233e'], 0x25c8: v['c25c8'], 0x25d0: v['c25d0'],
                     0x22ee: 0x8000 if v['far'] else 0x7fff}
            specs.append(dict(specs[0], name=f'round-edge-{k}-{odd}', extra=extra))
    for k, extra in enumerate(scale_edges(rng, 8)):
        specs.append(dict(specs[0], name=f'scale-edge-{k}', extra=extra))
    for sp in (0, 1, 2, 3):
        specs.append(dict(specs[0], name=f'stack-{sp}', sp=sp))
    for ds in (0, 0x1cbc, 0x1cbd, 0x1cbe, 0xefff, 0xf000, 0xf001, 0xffff):
        specs.append(dict(specs[0], name=f'guard-{ds:x}', ds=ds))
    for s in specs:
        data, ds = bytearray(ram), s['ds']
        regs = dict(base, ds=ds, sp=s['sp'])
        # Distinct nonzero initial data exposes missing intermediate writes.
        for off in range(0x2260, 0x25e0):
            data[ds * 16 + off] = rng.randrange(256)

        def put(off, v):
            data[ds * 16 + off:ds * 16 + off + 2] = v.to_bytes(2, 'little')
        for off, key in ((0x22fc, 'c22fc'), (0x2300, 'c2300'), (0x22fe, 'c22fe'), (0x233e, 'c233e'),
                         (0x25c8, 'c25c8'), (0x25d0, 'c25d0'), (0x2302, 'c2302'),
                         (0x22ba, 'n1'), (0x22be, 'n2'), (0x22c2, 'd')):
            put(off, s[key])
        if s['limit'] is not None:
            put(0x258f, s['limit'])
        for off in (0x226e, 0x2270, 0x25ce):     # coefficient extremes now and then
            if rng.randrange(4) == 0:
                put(off, rng.choice(words))
        for off, v in s.get('extra', {}).items():
            put(off, v)
        yield s['name'], bytes(data), regs


@lru_cache(maxsize=1)
def program():
    p = emit.Program()
    region = compute.validate(p, NODE, ('SWOTL.EXE', RETURNS[-1]))
    assert region.returns == tuple(('SWOTL.EXE', r) for r in RETURNS), region.returns
    cache = ROOT / 'tmp/point-projection'
    cache.mkdir(exist_ok=True)
    binary, addresses = B.program_image(p, cache)
    return p, cache, binary, addresses


VRAM_BYTE = B.D.TOP - 0xa0000     # guest A000:0000 on the host (reversed RAM)


def run(entries=(), plant=None, predecessors=False, generated=False, broken=False):
    p, cache, binary, addresses = program()
    callback = (ROOT / 'src/runtime/compute_projection.s').read_text() if not generated and not broken else ''
    if broken:
        callback = f'{SERVICE}:\n\tmoveq #4,d7\n\trts\n'
    if generated:
        callback = f'{SERVICE}:\n\tmoveq #0,d7\n\trts\n'
    plants = {
        'missing-store': ('\tmove.l \\1,(\\2-2,a3)\n', ''),
        # RC5: only the code/VRAM written-address set is observed besides RAM:
        # a VRAM byte rewritten with its own value leaves RAM equal.
        'vram-write': ('\tmove.l \\1,(\\2-2,a3)\n', f'\tmove.b ${VRAM_BYTE:x},${VRAM_BYTE:x}\n\tmove.l \\1,(\\2-2,a3)\n'),
        'half-store': ('\tmove.l d3,($5d1e,a3)\n', '\tmove.w d3,($5d20,a3)\n'),
        'missing-push': ('\tmove.w #$66a7,-1(a2,d7.w)\n', ''),
        'decline-state': ('.decline:\n', '.decline:\n\tmove.w #1,d0\n'),
        'guard': ('\tbhi .decline', ''),
        'overlap-guard': ('\tbcs .decline', ''),
        'rounding': ('\tadd.l #$8000,d7\n\tbcc.b .carry\\@', '\tadd.l #$7fff,d7\n\tbcc.b .carry\\@'),
        'short-rounding': ('\tadd.l #$80,d0', '\tadd.l #$7f,d0'),
        'register': ('\tswap d7\n\tmove.w d7,d5\n\teori.w #$7fff,d5\n\tendm', '\tmove.w #0,d5\n\tendm'),
        'wrong-return': ('\tmoveq #2,d0\n\tmoveq #2,d7', '\tmoveq #2,d0\n\tmoveq #1,d7'),
        'zero-divisor': ('\tbeq.b .quotient\\@\n', ''),
        'limit-signed': ('\tcmp.w ($5a65,a3),d2\n\tbcc .reject', '\tcmp.w ($5a65,a3),d2\n\tbge .reject'),
    }
    if plant:
        old, new = plants[plant]
        assert old in callback, plant
        callback = callback.replace(old, new, 1)
    cases = list(boundaries())
    for path in entries:
        ram, regs = O.load_entry(path)
        cases.append((str(path), ram, regs))
    resumes = [addresses[emit.label('SWOTL.EXE', r)] for r in RETURNS]
    # Every legal predecessor reaches the same compute ABI; its own guest
    # stack effects remain in the generated caller and return protocol.
    modes = ('direct', 'jump', 'call', 'taken', 'fall', 'indirect', 'return') if predecessors else ('direct',)
    count, seen = 0, set()
    with tempfile.TemporaryDirectory(prefix='point-projection-', dir=cache) as scratch:
        for mode in modes:
            intro = {'direct': [], 'jump': ['\tbra entry'], 'call': ['\tbsr entry', '\tjmp T_END'],
                     'taken': ['\tcmp.w d0,d0', '\tbeq entry', '\tillegal'],
                     'fall': ['\tcmp.w d0,d0', '\tbne T_END'],
                     'indirect': ['\tlea entry,a0', '\tjmp (a0)'], 'return': ['\tpea entry', '\trts']}[mode]
            hook = compute.hook(SERVICE, 'dispatch', f'${B.LOADSEG + CS:x}')
            dispatch = compute.resume_dispatch('dispatch', [f'${r:x}' for r in resumes], '$6667')
            source = [equates(), f'T_END equ ${B.D.STUB_AT["T_END"]:x}', f'\torg ${B.SNIP:x}', '\tdc.l before_call,result']
            source += intro + ['entry:', hook[0], 'before_call:', hook[1], 'result:', *hook[2:]]
            # An unknown result stops at an illegal instruction.
            source += [f'\tjmp ${addresses[emit.label(*NODE)]:x}', *dispatch, 'rt_stop_unknown:', '\tillegal', callback]
            code = B.D.assemble('\n'.join(source), Path(scratch) / 'callback.bin')
            before_at = int.from_bytes(code[:4], 'big')
            result_at = int.from_bytes(code[4:8], 'big')
            for name, ram, regs in cases:
                ends = [(regs['cs'], r - CS * 16) for r in RETURNS]
                expected = O.run(ram, regs, ends[-1], returns=ends)
                m = B.D.M68k(ram, B.STUB_AT, {p.hle[n][1] for n in p.compute_rows})
                outcomes, before = [], []

                @B.U.CODE_CB
                def result(h, addr, size, user):
                    saved = tuple(m.r(r) for r in ('d0', 'd1', 'd2', 'd3', 'd4', 'd5', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'))
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
                    O.watch_native(m)
                    m.extra_stops = {a: f'return {r:05X}' for a, r in zip(resumes, RETURNS)}
                    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                    got, fl, fx, mem, outs, writes, info = m.run(B.SNIP + 8,
                        (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(36), irq=False)
                    stop = info['stop'] or ''
                    if info['err'] or not stop.startswith('return') or outs or info['irq']:
                        raise ProjectionMismatch(count + 1, (name, mode, 'execution', info, outs))
                    if outcomes != [not generated and regs['cs'] + 0x1000 <= regs['ds'] <= 0xf000]:
                        raise ProjectionMismatch(count + 1, (name, mode, 'guard outcome', outcomes))
                    at = int(stop.split()[1], 16)
                    if (regs['cs'], at - CS * 16) != tuple(expected['at']):
                        raise ProjectionMismatch(count + 1, (name, mode, 'return', hex(at), expected['at']))
                    seen.add(at)
                    got.update(cs=regs['cs'], ip=at - CS * 16)
                    actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                                  writes=writes, ram=m.gread(0, B.X.RAM))
                    errors = O.compare(expected, actual, p.live_in[('SWOTL.EXE', at)])
                    if errors:
                        raise ProjectionMismatch(count + 1, (name, mode, errors))
                    count += 1
                finally:
                    B.U.uc.uc_close(m.e.h)
    if seen != set(RETURNS):
        raise ProjectionMismatch(count, ('returns not reached', sorted(map(hex, set(RETURNS) - seen))))
    return count


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--entries', nargs='*', type=Path, default=SNAPSHOTS)
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--predecessors', action='store_true')
    ap.add_argument('--generated-only', action='store_true')
    ap.add_argument('--broken', action='store_true')
    args = ap.parse_args()
    reporting_controls()
    print('generated projection:', run(args.entries, generated=True), 'cases pass', flush=True)
    if args.generated_only:
        raise SystemExit(0)
    print('point projection:', run(args.entries, predecessors=args.predecessors, broken=args.broken), 'cases pass', flush=True)
    if args.sabotage:
        from unittest.mock import patch
        try:
            with patch.object(program, 'cache_clear', lambda: None):
                cache_reporting_control()
        except AssertionError as error:
            print('point projection: stale-program cache caught:', error, flush=True)
        else:
            raise AssertionError('plant survived: stale-program cache')
        finally:
            program.cache_clear()
        for plant in ('missing-store', 'vram-write', 'half-store', 'missing-push', 'decline-state', 'guard',
                      'overlap-guard', 'rounding', 'short-rounding', 'register', 'wrong-return',
                      'zero-divisor', 'limit-signed'):
            try:
                run(plant=plant)
            except ProjectionMismatch as error:
                print('point projection:', plant, 'caught:', str(error)[:300], flush=True)
            else:
                raise AssertionError('plant survived: ' + plant)
