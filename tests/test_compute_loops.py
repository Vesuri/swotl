"""Poll-free compute rows (irq-plan I9, RC5): admission, the sync set, emission
and generated handoff.

No guest routine is replaced. Rows exist only in memory, and the callback is a
test double driven by the original x86 (tools/compute_oracle.py): these tests
check the contract's protocol (loops admitted, their heads leaving the sync
set, one hook, resumes at returns and root loop heads), never a native
implementation, which S6 validates without the x86 results.
"""
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from translator import check, compute, emit, gen, image  # noqa: E402
from translator.decode import decode  # noqa: E402
from translator.lower import LowerError  # noqa: E402

# -- admission on synthetic graphs ---------------------------------------------

CODE = {  # node -> (offset, bytes): root a*, callee c*, outside x*
    'a0': (0, 'be1000'),     # mov si,10h        first
    'a1': (5, '4e'),         # dec si            loop head
    'a2': (6, '75fd'),       # jnz a1
    'a3': (10, 'e80000'),    # call c0
    'a4': (20, '49'),        # dec cx            loop head
    'a5': (21, '75fd'),      # jnz a4
    'a7': (30, 'c3'),        # ret               (an early return when reached)
    'a6': (60, 'c3'),        # ret               resume
    'c0': (100, '40'),       # inc ax            callee loop head
    'c1': (101, '75fd'),     # jnz c0
    'c2': (103, 'c3'),       # ret
    'x0': (200, 'e80000'),   # call c0 (outside the row)
    'x1': (203, 'c3'),
}


def graph():
    n = {k: ('M', off) for k, (off, _) in CODE.items()}
    insns = {n[k]: decode(bytes.fromhex(code), off) for k, (off, code) in CODE.items()}
    succ = {n['a0']: [n['a1']], n['a1']: [n['a2']], n['a2']: [n['a1'], n['a3']],
            n['a3']: [n['c0']], n['a4']: [n['a5']], n['a5']: [n['a4'], n['a6']],
            n['a6']: ['ret'], n['a7']: ['ret'], n['c0']: [n['c1']], n['c1']: [n['c0'], n['c2']],
            n['c2']: ['ret'], n['x0']: [n['c0']], n['x1']: ['ret']}
    loops = {n['a1'], n['a4'], n['c0']}
    p = NS(succ=succ, call_site={n['a3']: n['a4'], n['x0']: n['x1']},
           loops=loops, sync=dict.fromkeys(loops, 'loop'), hle={}, diagnostic_hooks={},
           dispatch=set(), far_rows=set(), indirect={},
           units={'M': NS(manager_calls={})}, node_insn=lambda x: insns.get(x))
    return p, n, insns


def admission():
    p, n, _ = graph()
    row = compute.validate(p, n['a0'], n['a6'])
    assert row.body == {n[k] for k in ('a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'c0', 'c1', 'c2')}
    assert row.returns == (n['a6'],) and row.loops == (n['a1'], n['a4']), 'root loop heads resume'
    count = 2
    # shared entries (a dispatch row inside, a callee others call) and pure
    # waits are admitted: nothing observes the row's intermediate state
    p, n, insns = graph()
    p.dispatch.add(n['a1'])
    insns[n['a4']] = decode(bytes.fromhex('833e100000'), 20)   # cmp word [10h],0
    assert n['a1'] in compute.validate(p, n['a0'], n['a6']).body
    # U8: an early return is another resume; the divide-fault edge declines
    p, n, insns = graph()
    p.succ[n['a2']] = [n['a1'], n['a7']]
    assert compute.validate(p, n['a0'], n['a6']).returns == (n['a7'], n['a6'])
    p, n, insns = graph()
    insns[n['a4']] = decode(bytes.fromhex('f7f1'), 20)   # div cx; x1 is outside the row
    p.succ[n['a4']], p.int0 = [n['a5'], n['x1']], n['x1']
    assert n['x1'] not in compute.validate(p, n['a0'], n['a6']).body
    # continuation endpoints: a5 ends the row; a4 stays a loop head inside it
    p, n, insns = graph()
    row = compute.validate(p, n['a0'], n['a5'], endpoint=True)
    assert row.returns == (n['a5'],) and n['a5'] not in row.body
    count += 4
    for defect in ('recursion', 'unresolved', 'outside-range', 'io', 'cli', 'int',
                   'fault-edge-not-int0', 'nested-hook', 'diagnostic-body', 'diagnostic-rep',
                   'access', 'int-sync', 'clear', 'if', 'callee-access', 'resume-not-return',
                   'endpoint-unreachable', 'endpoint-in-callee', 'endpoint-return'):
        p, n, insns = graph()
        end, endpoint = n['a6'], False
        if defect == 'recursion':
            insns[n['c0']] = decode(bytes.fromhex('e80000'), 100)
            p.succ[n['c0']] = [n['c0']]
            p.call_site[n['c0']] = n['c1']
        elif defect == 'unresolved': p.succ[n['a2']] = [n['a1'], 'unknown']
        elif defect == 'outside-range': p.succ[n['a2']] = [n['a1'], n['x1']]
        elif defect == 'io': insns[n['a4']] = decode(b'\xee', 20)
        elif defect == 'cli': insns[n['a4']] = decode(b'\xfa', 20)
        elif defect == 'int': insns[n['a4']] = decode(b'\xcd\x21', 20)
        elif defect == 'fault-edge-not-int0':
            insns[n['a4']] = decode(bytes.fromhex('f7f1'), 20)
            p.succ[n['a4']] = [n['a5'], n['x1']]
        elif defect == 'nested-hook': p.hle[n['a4']] = (n['a6'], 'nested')
        elif defect == 'diagnostic-body': p.diagnostic_hooks[n['a2']] = 1
        elif defect == 'diagnostic-rep':
            insns[n['a4']] = decode(bytes.fromhex('f3aa'), 20)
            p.diagnostic_reps = {n['a4']: 1}
        elif defect in ('access', 'int-sync', 'clear', 'if'):   # I2: meets the handler
            p.sync[n['a5']] = defect.removesuffix('-sync')
        elif defect == 'callee-access': p.sync[n['c1']] = 'access'
        elif defect == 'resume-not-return': end = n['a5']
        elif defect == 'endpoint-unreachable':
            end, endpoint = n['a7'], True
            insns[n['a7']] = decode(b'\x40', 30)
        elif defect == 'endpoint-in-callee': end, endpoint = n['c1'], True
        elif defect == 'endpoint-return': endpoint = True
        try:
            compute.validate(p, n['a0'], end, endpoint=endpoint)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'{defect} admitted')
    return count


# -- the sync set and emission on a real routine ---------------------------------

FIRST = ('SWOTL.EXE', 0x135e0)   # two counted loops: 135EE, 13618; retf at 13633
LOOP1, LOOP2, RESUME = ('SWOTL.EXE', 0x135ee), ('SWOTL.EXE', 0x13618), ('SWOTL.EXE', 0x13633)
SERVICE = 'rt_hle_loops_test'
RESUME_DISPATCH = compute.resume_dispatch   # the expected stub, independent of plants
_base = {}


def base():
    if 'p' not in _base:
        _base['p'] = emit.Program()
    return _base['p']


def program(kind='compute', **extra):
    """The real Program with one temporary in-memory row; hle.csv is unchanged."""
    p = base()
    u = p.units[FIRST[0]]
    last = next(o for o, i in u.insns.items() if o + i.size == RESUME[1])
    original = image.rows
    row = dict(module=FIRST[0], first=hex(FIRST[1]), last=hex(last), service=SERVICE[7:],
               kind=kind, args='', reason='I9 protocol test only; no replacement',
               oracle='tests/test_compute_loops.py', **extra)

    def rows(name):
        return original(name) + ([row] if name == 'hle.csv' else [])

    with patch.object(image, 'rows', rows):
        return emit.Program(units=p.units)


def text_after(lines, lab, n):
    k = next(i for i, x in enumerate(lines) if x.startswith(lab + ':'))
    return lines[k + 1:k + 1 + n]


def emission():
    p = base()
    u = p.units[FIRST[0]]
    cs = emit.cs_expr(u.cs[FIRST[1]])
    assert {LOOP1, LOOP2} <= p.loop_heads, 'base: the routine\'s loops are sync points'
    c = program()
    row = c.compute_bodies[FIRST]
    assert row.returns == (RESUME,) and row.loops == (LOOP1, LOOP2)
    left = {n for n in row.body if p.sync.get(n) == 'loop'}
    assert left == {LOOP1, LOOP2}, left
    assert c.loop_heads == p.loop_heads - left, 'only the body\'s loop heads leave the sync set'
    assert set(c.sync) == c.loop_heads and not left & set(c.sync)
    assert c.compute_resumes[FIRST] == [RESUME, LOOP1, LOOP2], 'resumes: returns, then root loops'
    lines, _ = c.module_text(FIRST[0])
    for n in (FIRST, *left):
        assert f'{emit.label(*n)}_np:' not in lines, f'poll at {n}'
    lab = emit.label(*FIRST)
    hook = compute.hook(SERVICE, f'{lab}_cx', cs)
    assert text_after(lines, lab, len(hook)) == hook, 'one hook at the first instruction'
    assert sum(f'\tjsr {SERVICE}' == x for x in lines) == 1, 'hook elsewhere'
    stub = RESUME_DISPATCH(f'{lab}_cx', [emit.label(*x) for x in (RESUME, LOOP1, LOOP2)],
                           emit.hx(u.ip_of(FIRST[1])))
    k = lines.index(stub[0])
    assert lines[k:k + len(stub)] == stub, 'resume dispatch'
    count = 9
    for extra in ({'kind': 'hook', 'end': hex(RESUME[1])}, {'polls': 'exact'}, {'polls': 'return'},
                  {'resume': 'continue'}):
        try:
            program(**extra)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'row {extra} generated')
    return count


def dispatch_table(plant=None):
    """resume_dispatch on the 68020: chain (< 5) and table (>= 5) forms; ids
1..n reach their target, others stop at rt_stop_unknown with the IP."""
    import m68k_blocks as B
    count = 0
    for n in (3, 6):
        targets = [f't{k}' for k in range(n)]
        stub = compute.resume_dispatch('cx', targets, '$1234')
        if plant == 'table-off-by-one' and n >= 5:
            stub = [x.replace('\tsubq.l #1,d7', '\tnop') if x == '\tsubq.l #1,d7' else x for x in stub]
        assert (n >= 5) == any(x.startswith('cxt:') for x in stub)
        source = f'rt_stop_unknown equ ${B.STUB_AT["rt_stop_unknown"]:x}\n org ${B.SNIP:x}\n dc.l done\n'
        source += '\n'.join(stub) + '\n'
        source += ''.join(f't{k}:\n moveq #{k},d0\n bra done\n' for k in range(n)) + 'done:\n nop\n'
        with tempfile.TemporaryDirectory(prefix='resume-dispatch-') as directory:
            binary = B.D.assemble(source, Path(directory) / 'probe.bin')
        done = int.from_bytes(binary[:4], 'big')
        for d7 in (*range(1, n + 1), n + 1, 0x10001, 0xffffffff):
            m = B.D.M68k(bytes(B.X.RAM), B.STUB_AT)
            try:
                m.e.write(B.SNIP, binary)
                m.e.reg_write(B.U.M68K['d0'], 0xff)
                m.e.reg_write(B.U.M68K['d7'], d7)
                m.extra_stops = {done: 'done'}
                err = m.e.start(B.SNIP + 4, 0xffffffff, 1000)
                assert not err, err
                if 1 <= d7 <= n:
                    assert (m.stop, m.r('d0')) == ('done', d7 - 1), (n, d7, m.stop)
                else:
                    assert (m.stop, m.r('d7')) == ('rt_stop_unknown', 0x1234), (n, hex(d7), m.stop)
                count += 1
            finally:
                B.U.uc.uc_close(m.e.h)
    return count


def header_audit():
    """The generated include of the native rows gets the same integrity check as code."""
    with tempfile.TemporaryDirectory(prefix='native-equates-') as directory:
        out = Path(directory)
        gen.write(out, 'program.s', gen.PROGRAM, b'; synthetic code\n')
        gen.write(out, 'equates.i', gen.PROGRAM, b'; synthetic equates\n')
        assert not check.check_gen(False, out)
        include = out / 'equates.i'
        include.write_bytes(include.read_bytes() + b'; planted edit\n')
        errors = check.check_gen(False, out)
        assert any('equates.i: body does not match' in e for e in errors), errors
    return 2


# -- generated handoff with a test double ---------------------------------------

DOUBLE = 0xc00      # stub page offset of the callback (not a harness stub)


def guest_state(m, D):
    """Registers and FLAGS word as the generated ABI holds them at a leader."""
    regs = {r: (m.r(D.M68[r]) ^ D.MIRROR.get(r, 0)) & 0xffff for r in D.REGS}
    st = m.e.read(D.STATE, 16)
    for s, at in (('es', 12), ('ss', 14), ('ds', 16)):
        regs[s] = int.from_bytes(st[16 - at:16 - at + 2], 'big')
    fl = st[15]
    f = {'CF': fl & 1, 'OF': fl >> 1 & 1, 'ZF': fl >> 2 & 1, 'SF': fl >> 3 & 1,
         'PF': int(bin(st[13]).count('1') % 2 == 0), 'AF': st[12] >> 4 & 1,
         'DF': st[11], 'IF': st[10], 'TF': st[9]}
    from translator.ir import FLAG_BIT
    word = int.from_bytes(st[6:8], 'big') | sum(f[k] << FLAG_BIT[k] for k in f)
    return regs, word


def put_state(m, D, regs, word):
    from translator.ir import FLAG_BIT
    for r in D.REGS:
        old = m.r(D.M68[r])
        m.e.reg_write(D.U.M68K[D.M68[r]], old & 0xffff0000 | regs[r] ^ D.MIRROR.get(r, 0))
    st = bytearray(m.e.read(D.STATE, 16))
    for s, at, a in (('es', 12, 'a1'), ('ss', 14, 'a2'), ('ds', 16, 'a3')):
        st[16 - at:16 - at + 2] = regs[s].to_bytes(2, 'big')
        m.e.reg_write(D.U.M68K[a], D.TOP - regs[s] * 16 - 0x7fff)
    f = {k: word >> FLAG_BIT[k] & 1 for k in FLAG_BIT}
    st[15] = st[15] & 0x10 | D.ccr_image(f)
    st[13] = 0 if f['PF'] else 1
    st[12] = f['AF'] << 4 | st[12] & 0xef
    st[11], st[10], st[9] = f['DF'], f['IF'], f['TF']
    st[6:8] = (word & 0xf000).to_bytes(2, 'big')
    m.e.write(D.STATE, bytes(st))


def entry_case(rng):
    import m68k_blocks as B
    import x86_diff as X
    from translator.lower import LOADSEG
    p = base()
    u = p.units[FIRST[0]]
    ram = bytearray(rng.randrange(256) for _ in range(0x10000)) * 16
    ram += bytearray(X.RAM - len(ram))   # unmapped beyond the 1 MiB captured extent
    if 'mod' not in _base:
        _base['mod'] = B.relocated(image.load()[FIRST[0]])
    mod = _base['mod']
    cs = (LOADSEG + u.cs[FIRST[1]]) & 0xffff
    for o in range(FIRST[1], RESUME[1] + 1):
        ram[cs * 16 + u.ip_of(o)] = mod[o]
    regs = dict(ax=rng.randrange(0x10000), bx=rng.randrange(0x10000), cx=rng.randrange(0x10000),
                dx=rng.randrange(0x10000), sp=0x0400, bp=rng.randrange(0x10000),
                si=rng.randrange(0x10000), di=rng.randrange(0x10000),
                cs=cs, ip=u.ip_of(FIRST[1]), ss=0x4000, ds=0x5000, es=0x6000, flags=0x7202)
    ram[0x40400:0x40404] = rng.randrange(1 << 32).to_bytes(4, 'little')  # far return
    return ram, regs


def double_run(c, img, addr, ram, regs, mode, plant=None):
    """One generated run from the row's entry to its return.

`mode`: the double declines, handles to the return, or runs the original to a
root loop head and resumes there (generated code finishes). Returns the guest
state at the return and the stop."""
    import m68k_blocks as B
    import m68k_diff as D
    from tools import compute_oracle as O
    u = base().units[FIRST[0]]
    resumes = c.compute_resumes[FIRST]
    at_ip = {(regs['cs'], u.ip_of(x[1])): k + 1 for k, x in enumerate(resumes)}
    stubs = {k: v for k, v in B.STUB_AT.items() if k != SERVICE}
    m = D.M68k(O.CapturedRAM(bytes(ram), 0x100000), stubs)
    m.load(img)
    O.watch_native(m)
    service = D.STUB + DOUBLE
    m.e.write(service, b'\x4a\xfc\x4e\x75')
    calls = {'n': 0}

    @D.U.CODE_CB
    def code(h, a, size, user):
        if a == service:
            m.stop = 'double'   # served outside the hook: no second engine inside a callback
            D.U.uc.uc_emu_stop(h)

    def serve():
        """The double's work for one callback call; returns the d7 result."""
        calls['n'] += 1
        if mode == 'decline':
            return 0
        r, w = guest_state(m, D)
        state = dict(r, cs=regs['cs'], ip=u.ip_of(FIRST[1]), flags=w)
        now = O.CapturedRAM(m.gread(0, D.X.RAM), 0x100000)
        target = RESUME if mode == 'handle' else LOOP1 if mode == 'loop1' else LOOP2
        ends = [(regs['cs'], u.ip_of(x[1])) for x in (RESUME, target)]
        out = O.run(now, state, ends[1], returns=ends)
        writes = sorted(out['writes'])
        if plant == 'missing-store' and writes:
            writes = writes[:-1]
        for a in writes:   # API writes bypass the hooks
            m.gwrite(a, out['ram'][a:a + 1])
        r = {k: v for k, v in out['registers'].items() if k not in ('cs', 'ip')}
        if plant == 'stale-register':
            r['si'] = r['si'] + 1 & 0xffff
        put_state(m, D, r, out['flags'])
        result = at_ip[out['at']]
        if plant == 'wrong-resume' and result > 1:
            result = 1
        return len(resumes) + 1 if plant == 'invalid-id' else result

    m.e.hook(D.U.HOOK_CODE, code)
    m.irq_calls = []
    m.extra_stops = {addr[emit.label(*RESUME)]: 'resume'}
    from translator.ir import FLAG_BIT, FLAGS
    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
    try:
        _, _, _, _, outs, writes, info = m.run(addr[emit.label(*FIRST)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(33), irq=False)
        stop, err = info['stop'], info['err']
        while stop == 'double' and not err:
            m.e.reg_write(D.U.M68K['d7'], serve())
            m.stop = None
            err = m.e.start(service + 2, 0xFFFFFFFF, 4_000_000)   # its rts
            stop = m.stop
        assert not m.outs and not err and not m.irq_calls, (mode, plant, stop, err, hex(m.r('pc')))
        assert calls['n'] == (stop == 'resume' or stop == 'rt_stop_unknown'), ('one hook call', calls)
        r, w = guest_state(m, D)
        return dict(registers=r, flags=w, writes=set(), ram=m.gread(0, 0x100000)), stop
    finally:
        D.U.uc.uc_close(m.e.h)


def handoff(plant=None):
    """Protocol differential; with a plant, raises AssertionError when caught."""
    import m68k_blocks as B
    import m68k_diff as D
    from tools import compute_oracle as O
    B.STUB_AT[SERVICE] = D.STUB + DOUBLE
    cache = ROOT / 'tmp/compute-loops'
    cache.mkdir(parents=True, exist_ok=True)
    c = program()
    img, addr = B.program_image(c, cache)
    u = base().units[FIRST[0]]
    rng = random.Random(7)
    count = 0
    for _ in range(4):
        ram, regs = entry_case(rng)
        resume = (regs['cs'], u.ip_of(RESUME[1]))
        want = O.run(O.CapturedRAM(bytes(ram), 0x100000), regs, resume)
        want = dict(want, registers={k: v for k, v in want['registers'].items() if k not in ('cs', 'ip')},
                    ram=want['ram'][:0x100000])
        for mode in ('decline', 'handle', 'loop1', 'loop2'):
            got, stop = double_run(c, img, addr, ram, regs, mode, plant)
            if plant == 'invalid-id':   # every handled result is out of range
                assert mode == 'decline' or stop == 'rt_stop_unknown', 'invalid id accepted'
                continue
            assert stop == 'resume', (mode, stop)
            errors = O.compare(want, got, c.live_in[RESUME])
            assert not errors, (mode, errors)
            count += 1
    return count


def main():
    print('compute loops admission:', admission(), 'controls pass')
    print('compute loops sync set and emission:', emission(), 'controls pass')
    print('compute loops resume dispatch:', dispatch_table(), 'ids pass')
    print('compute loops equates audit:', header_audit(), 'controls pass')
    print('compute loops handoff:', handoff(), 'resume-state comparisons pass')
    if '--sabotage' not in sys.argv:
        return

    def caught(name, f):
        try:
            f()
        except (AssertionError, LowerError) as e:
            print(f'compute loops: {name} plant caught ({str(e)[:90]})')
        else:
            raise AssertionError(f'{name} plant escaped')

    with patch.object(compute, 'forbidden', lambda p, n: n in p.diagnostic_hooks or
                      n in getattr(p, 'diagnostic_reps', {}) or compute.effect(p, n)):
        caught('sync kinds ignored', admission)
    real = compute.validate
    with patch.object(compute, 'validate',
                      lambda *a, **k: real(*a, **k)._replace(loops=())):
        caught('missing root loop resumes', emission)
    with patch.object(compute, 'validate',
                      lambda *a, **k: real(*a, **k)._replace(body=frozenset())):
        caught('body loop head kept in the sync set', emission)
    with patch.object(compute, 'resume_dispatch', lambda d, rs, ip: RESUME_DISPATCH(d, rs[:-1], ip)):
        caught('resume list missing a loop head', emission)
    caught('table dispatch off by one', lambda: dispatch_table('table-off-by-one'))
    real_check = check.check_gen
    with patch.object(check, 'check_gen',
                      lambda *a: [e for e in real_check(*a) if not e.startswith('equates.i')]):
        caught('unaudited equates.i', header_audit)
    for plant in ('stale-register', 'missing-store', 'wrong-resume'):
        caught(plant, lambda: handoff(plant))
    handoff('invalid-id')
    print('compute loops: invalid resume id stops loudly')


if __name__ == '__main__':
    main()
