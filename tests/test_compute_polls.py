"""U5 poll contract (native-plan C3): admission, emission and generated handoff.

No guest routine is replaced. Rows exist only in memory, and the callback is a
test double driven by the original x86 (tools/compute_oracle.py): these tests
check the contract's protocol (removed polls, the return poll, sync-site visits
and resumes, interrupts between visits, the latency monitor), never a native
implementation, which S6 validates without the x86 results.
"""
import json
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from translator import compute  # noqa: E402
from translator.decode import decode  # noqa: E402
from translator.lower import LowerError  # noqa: E402

# -- admission on synthetic graphs ---------------------------------------------

CODE = {  # node -> (offset, bytes): root a*, callee c*, outside x*
    'a0': (0, 'be1000'),     # mov si,10h        first
    'a1': (5, '4e'),         # dec si            loop head, counter exit
    'a2': (6, '75fd'),       # jnz a1
    'a3': (10, 'e80000'),    # call c0
    'a4': (20, '49'),        # dec cx            loop head, counter exit
    'a5': (21, '75fd'),      # jnz a4
    'a7': (30, 'c3'),        # ret               (an early return when reached)
    'a6': (60, 'c3'),        # ret               resume
    'c0': (100, '40'),       # inc ax
    'c1': (101, 'c3'),       # ret
    'x0': (200, 'e80000'),   # call c0 (outside the row)
    'x1': (203, 'c3'),
}


def graph():
    n = {k: ('M', off) for k, (off, _) in CODE.items()}
    insns = {n[k]: decode(bytes.fromhex(code), off) for k, (off, code) in CODE.items()}
    succ = {n['a0']: [n['a1']], n['a1']: [n['a2']], n['a2']: [n['a1'], n['a3']],
            n['a3']: [n['c0']], n['a4']: [n['a5']], n['a5']: [n['a4'], n['a6']],
            n['a6']: ['ret'], n['a7']: ['ret'], n['c0']: [n['c1']], n['c1']: ['ret'],
            n['x0']: [n['c0']], n['x1']: ['ret']}
    p = NS(succ=succ, call_site={n['a3']: n['a4'], n['x0']: n['x1']},
           loop_heads={n['a1'], n['a4']}, hle={}, diagnostic_hooks={},
           dispatch=set(), far_rows=set(), indirect={},
           units={'M': NS(manager_calls={})}, node_insn=lambda x: insns.get(x))
    return p, n, insns


def admission():
    p, n, _ = graph()
    row = compute.validate_polled(p, n['a0'], n['a6'])
    assert row.removed == {n['a1'], n['a4']} and row.sync == () and row.resume == n['a6']
    assert row.body == {n[k] for k in ('a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'c0', 'c1')}
    row = compute.validate_polled(p, n['a0'], n['a6'], (n['a4'],))
    assert row.removed == {n['a1']} and row.sync == (n['a4'],)
    p.loop_heads.add(n['a3'])   # D8 polls a backward jump's target even without a cycle
    assert n['a3'] in compute.validate_polled(p, n['a0'], n['a6']).removed
    p, n, insns = graph()
    p.dispatch.add(n['a1'])     # an internal entry: kept as a sync site
    assert compute.validate_polled(p, n['a0'], n['a6'], (n['a1'],)).removed == {n['a4']}
    # U8: an early return is another resume (and a poll); a REP at a removed
    # poll is removed with it; the divide-fault edge is a decline edge
    p, n, insns = graph()
    p.succ[n['a2']] = [n['a1'], n['a7']]
    assert compute.validate_polled(p, n['a0'], n['a6']).returns == (n['a7'], n['a6'])
    p, n, insns = graph()
    insns[n['a4']] = decode(bytes.fromhex('f2ae'), 20)   # repne scasb sets the exit's ZF
    assert n['a4'] in compute.validate_polled(p, n['a0'], n['a6']).removed
    p, n, insns = graph()
    insns[n['a4']] = decode(bytes.fromhex('f7f1'), 20)   # div cx; x1 is outside the row
    p.succ[n['a4']], p.int0 = [n['a5'], n['x1']], n['x1']
    assert n['x1'] not in compute.validate_polled(p, n['a0'], n['a6']).body
    count = 7
    for defect in ('pure-wait', 'shared-root-poll', 'shared-callee-poll', 'callee-sync',
                   'recursion', 'unresolved', 'outside-range', 'io', 'rep-sync',
                   'rep-diagnostic', 'fault-edge-not-int0', 'nested-hook', 'diagnostic-body',
                   'resume-not-return', 'sync-resume', 'sync-duplicate', 'sync-outside'):
        p, n, insns = graph()
        sync = ()
        if defect == 'pure-wait':   # cmp word [10h],0 / jne: nothing changes it but an interrupt
            insns[n['a1']] = decode(bytes.fromhex('833e100000'), 5)
        elif defect == 'shared-root-poll': p.dispatch.add(n['a1'])
        elif defect == 'shared-callee-poll':
            p.loop_heads.add(n['c0'])
            p.succ[n['c1']] = ['ret']
        elif defect == 'callee-sync': sync = (n['c0'],)
        elif defect == 'recursion':
            insns[n['c0']] = decode(bytes.fromhex('e80000'), 100)
            p.succ[n['c0']] = [n['c0']]
            p.call_site[n['c0']] = n['c1']
        elif defect == 'unresolved': p.succ[n['a2']] = [n['a1'], 'unknown']
        elif defect == 'outside-range': p.succ[n['a2']] = [n['a1'], n['x1']]
        elif defect == 'io': insns[n['a4']] = decode(b'\xee', 20)
        elif defect == 'rep-sync':
            insns[n['a4']] = decode(bytes.fromhex('f3aa'), 20)
            sync = (n['a4'],)
        elif defect == 'rep-diagnostic':
            insns[n['a4']] = decode(bytes.fromhex('f3aa'), 20)
            p.diagnostic_reps = {n['a4']: 1}
        elif defect == 'fault-edge-not-int0':
            insns[n['a4']] = decode(bytes.fromhex('f7f1'), 20)
            p.succ[n['a4']] = [n['a5'], n['x1']]
        elif defect == 'nested-hook': p.hle[n['a4']] = (n['a6'], 'nested')
        elif defect == 'diagnostic-body': p.diagnostic_hooks[n['a2']] = 1
        elif defect == 'resume-not-return':
            try:
                compute.validate_polled(p, n['a0'], n['a5'])
            except LowerError:
                count += 1
                continue
            raise AssertionError(defect)
        elif defect == 'sync-resume': sync = (n['a6'],)
        elif defect == 'sync-duplicate': sync = (n['a4'], n['a4'])
        elif defect == 'sync-outside': sync = (n['x1'],)
        try:
            compute.validate_polled(p, n['a0'], n['a6'], sync)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'{defect} admitted')
    # A diagnostic hook at a sync site is allowed: the visit stays generated.
    p, n, _ = graph()
    p.diagnostic_hooks[n['a4']] = 1
    compute.validate_polled(p, n['a0'], n['a6'], (n['a4'],))
    return count + 1


# -- emission on a real routine --------------------------------------------------

FIRST = ('SWOTL.EXE', 0x135e0)   # two counted loops: 135EE, 13618; retf at 13633
LOOP1, LOOP2, RESUME = ('SWOTL.EXE', 0x135ee), ('SWOTL.EXE', 0x13618), ('SWOTL.EXE', 0x13633)
SERVICE = 'rt_hle_polled_test'
_base = {}


def base():
    from translator import emit
    if 'p' not in _base:
        _base['p'] = emit.Program()
    return _base['p']


def program(polls, kind='compute'):
    """The real Program with one temporary in-memory row; hle.csv is unchanged."""
    from translator import emit, image
    p = base()
    u = p.units[FIRST[0]]
    last = next(o for o, i in u.insns.items() if o + i.size == RESUME[1])
    original = image.rows
    row = dict(module=FIRST[0], first=hex(FIRST[1]), last=hex(last), service=SERVICE[7:],
               kind=kind, args='', reason='C3 protocol test only; no replacement',
               oracle='tests/test_compute_polls.py', polls=polls)

    def rows(name):
        return original(name) + ([row] if name == 'hle.csv' else [])

    with patch.object(image, 'rows', rows):
        return emit.Program(units=p.units)


def text_after(lines, lab, n):
    k = next(i for i, x in enumerate(lines) if x.startswith(lab + ':'))
    return lines[k + 1:k + 1 + n]


def emission(drop_return_poll=False):
    from translator import emit
    p = base()
    u = p.units[FIRST[0]]
    cs = emit.cs_expr(u.cs[FIRST[1]])
    count = 0
    for polls, sync in (('return', ()), ('return 0x13618', (LOOP2,))):
        c = program(polls)
        if drop_return_poll:
            c.loop_heads.discard(RESUME)
        removed = {LOOP1, LOOP2} - set(sync)
        assert c.compute_bodies[FIRST].removed == removed
        assert c.loop_heads == (p.loop_heads - removed) | set(sync) | {RESUME}, 'poll set'
        lines, _ = c.module_text(FIRST[0])
        for n in removed:   # neither arm polls there
            assert f'{emit.label(*n)}_np:' not in lines, f'removed poll {n} emitted'
        assert f'{emit.label(*RESUME)}_np:' in lines, 'return poll missing'
        assert text_after(lines, emit.label(*RESUME), 3) == emit.poll(emit.label(*RESUME))
        hook = compute.polled_hook(SERVICE, 0, f'{emit.label(*FIRST)}_cx', cs)
        assert text_after(lines, emit.label(*FIRST), len(hook)) == hook
        resumes = [emit.label(*x) for x in (RESUME, *sync)]
        stub = compute.polled_dispatch(f'{emit.label(*FIRST)}_cx', resumes,
                                       emit.hx(u.ip_of(FIRST[1])))
        k = lines.index(stub[0])
        assert lines[k:k + len(stub)] == stub
        for j, s in enumerate(sync, 1):   # the visit precedes re-entering the callback
            lab = emit.label(*s)
            want = emit.poll(lab) + compute.polled_hook(SERVICE, j, f'{lab}_cx', cs)
            assert text_after(lines, lab, len(want)) == want, 'sync site order'
        count += 6
    for polls, kind in (('0x13618', 'compute'), ('return 0x135e2', 'compute'),
                        ('return', 'hook'), ('return 0x13633', 'compute')):
        try:
            program(polls, kind)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'row polls={polls!r} kind={kind} generated')
    return count


# -- generated handoff with a test double ---------------------------------------

DOUBLE = 0xc00      # stub page offset of the callback (not a harness stub)
EFFECT = 0x8c7f     # the second loop's bound (DS): an interrupt handler's write


def guest_state(m, D):
    """Registers, FLAGS word and RAM as the generated ABI holds them at a leader."""
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


def entry_case(rng, bound):
    import m68k_blocks as B
    from translator.lower import LOADSEG
    p = base()
    u = p.units[FIRST[0]]
    import x86_diff as X
    ram = bytearray(rng.randrange(256) for _ in range(0x10000)) * 16
    ram += bytearray(X.RAM - len(ram))   # unmapped beyond the 1 MiB captured extent
    from translator import image
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
    ram[0x50000 + EFFECT] = bound
    return ram, regs


def double_run(c, img, addr, ram, regs, mode, schedule, plant=None, latency=False):
    """One generated run from the row's entry to its return poll.

`mode`: the double declines everywhere, handles everywhere or alternates.
`schedule`: {sync visit number: new bound} delivered by the interrupt there;
the return poll visit always posts one. Returns the visits (state snapshots
before each sync-site poll and at the return), interrupt calls and the stop.
    """
    import m68k_blocks as B
    import m68k_diff as D
    from tools import compute_oracle as O
    from translator import emit
    p = base()
    u = p.units[FIRST[0]]
    site_ip = {u.ip_of(s[1]): s for s in c.sync_sites[FIRST]}
    resume_ip = (regs['cs'], u.ip_of(RESUME[1]))
    stops = [(regs['cs'], ip) for ip in site_ip]
    stubs = {k: v for k, v in B.STUB_AT.items() if k != SERVICE}
    saved = O.CapturedRAM(bytes(ram), 0x100000)
    m = D.M68k(saved, stubs)
    m.load(img)
    history = O.watch_native(m)
    gaps = O.PollGaps(m, img) if latency else None
    trace, irqs, visits, calls = [], [], {'n': 0}, {'n': 0, 'cache': None}
    at_site = {addr[emit.label(*s)]: s for s in c.sync_sites[FIRST]}
    at_resume = addr[emit.label(*RESUME)]
    service = D.STUB + DOUBLE
    if plant == 'latency':   # a callback that runs ~200k loop passes, then declines
        m.e.write(service, bytes.fromhex('2e3c00030d40' '5387' '66fc' '4e75'))
    else:
        m.e.write(service, b'\x4a\xfc\x4e\x75')
    pending = {'effect': None}

    def snapshot(where):
        r, w = guest_state(m, D)
        trace.append((where, r, w, m.gread(0, 0x100000), {a: list(v) for a, v in history.items()}))

    @D.U.CODE_CB
    def code(h, a, size, user):
        if a in at_site:
            visits['n'] += 1
            snapshot(at_site[a])
            if visits['n'] in schedule:
                pending['effect'] = schedule[visits['n']]
                m.e.write(D.STATE + 8, b'\1')
                m.e.write(D.PENDING, b'\1')
        elif a == at_resume:
            snapshot(RESUME)
            pending['effect'] = 'return'
            m.e.write(D.STATE + 8, b'\1')
            m.e.write(D.PENDING, b'\1')
        elif a == stubs['rt_irq']:
            irqs.append((m.r('d7') & 0xffff, pending['effect']))
            if isinstance(pending['effect'], int):   # the handler's store
                m.gwrite(regs['ds'] * 16 + EFFECT, bytes([pending['effect']]))
                history.setdefault(regs['ds'] * 16 + EFFECT, []).append(pending['effect'])
            pending['effect'] = None
        elif a == service and plant != 'latency':
            calls['at'] = a  # served outside the hook: no second engine inside a callback
            m.stop = 'double'
            D.U.uc.uc_emu_stop(h)

    def serve():
        """The double's work for one callback call; returns the d7 result."""
        entry = m.r('d7') & 0xff
        calls['n'] += 1
        if mode == 'decline' or (mode == 'mixed' and calls['n'] % 2):
            return 0
        r, w = guest_state(m, D)
        state = dict(r, cs=regs['cs'], flags=w,
                     ip=u.ip_of(FIRST[1]) if entry == 0 else u.ip_of(c.sync_sites[FIRST][entry - 1][1]))
        now = O.CapturedRAM(m.gread(0, D.X.RAM), 0x100000)
        if plant == 'stale-continuation' and calls['cache'] is not None:
            now, state = calls['cache']
        if plant == 'duplicate-visit' and entry and not calls.get('dup'):
            calls['dup'] = True
            return entry + 1
        out = O.run(now, state, resume_ip, stops=[] if plant == 'skipped-visit' else stops)
        if plant == 'stale-continuation':
            calls['cache'] = (O.CapturedRAM(out['ram'], 0x100000),
                              dict(out['registers'], flags=out['flags']))
        writes = [(a, v) for a, vs in sorted(out['history'].items()) for v in vs]
        if plant == 'missing-store' and writes:
            writes = writes[:-1]
        if plant == 'future-store' and out['at'] != resume_ip:
            ahead = O.run(O.CapturedRAM(out['ram'], 0x100000),
                          dict(out['registers'], flags=out['flags']), resume_ip, stops=stops)
            writes += [(a, vs[0]) for a, vs in sorted(ahead['history'].items())][:1]
        for a, v in writes:   # API writes bypass the hooks: record them as stores would be
            m.gwrite(a, bytes([v]))
            history.setdefault(a, []).append(v)
        r = {k: v for k, v in out['registers'].items() if k not in ('cs', 'ip')}
        if plant == 'stale-register' and out['at'] != resume_ip:
            r['si'] = r['si'] + 1 & 0xffff
        put_state(m, D, r, out['flags'])
        result = 1 if out['at'] == resume_ip else \
            2 + list(c.sync_sites[FIRST]).index(site_ip[out['at'][1]])
        if plant == 'wrong-site' and result > 1:
            result = 1
        return 7 if plant == 'invalid-id' else result

    m.e.hook(D.U.HOOK_CODE, code)
    m.irq_calls = []
    np = addr.get(f'{emit.label(*RESUME)}_np')
    m.extra_stops = {np: 'return_poll_done'} if np else {at_resume: 'no_return_poll'}
    from translator.ir import FLAG_BIT, FLAGS
    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
    try:
        _, _, _, _, outs, _, info = m.run(addr[emit.label(*FIRST)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(33), irq=False)
        stop, err = info['stop'], info['err']
        while stop == 'double' and not err:
            m.e.reg_write(D.U.M68K['d7'], serve())
            m.stop = None
            err = m.e.start(service + 2, 0xFFFFFFFF, 4_000_000)   # its rts
            stop = m.stop
        assert not m.outs and not err, (mode, schedule, plant, stop, err, hex(m.r('pc')))
        return trace, irqs, stop, (gaps.longest() if gaps else None)
    finally:
        D.U.uc.uc_close(m.e.h)


def original(c, ram, regs, schedule):
    """The x86 chain: stop at every sync-site arrival, deliver the scheduled
    interrupt's write there, end before the return; snapshots as double_run."""
    from tools import compute_oracle as O
    p = base()
    u = p.units[FIRST[0]]
    sites = {(regs['cs'], u.ip_of(s[1])): s for s in c.sync_sites[FIRST]}
    resume_ip = (regs['cs'], u.ip_of(RESUME[1]))
    now, state = O.CapturedRAM(bytes(ram), 0x100000), dict(regs)
    history, trace, visit = {}, [], 0
    while True:
        out = O.run(now, state, resume_ip, stops=list(sites))
        for a, vs in out['history'].items():
            history.setdefault(a, []).extend(vs)
        ram_now = bytearray(out['ram'])
        r = {k: v for k, v in out['registers'].items() if k not in ('cs', 'ip')}
        where = sites.get(out['at'], RESUME)
        trace.append((where, r, out['flags'], bytes(ram_now[:0x100000]),
                      {a: list(v) for a, v in history.items()}, out['undefined']))
        if where == RESUME:
            return trace
        visit += 1
        if visit in schedule:
            a = regs['ds'] * 16 + EFFECT
            ram_now[a] = schedule[visit]
            history.setdefault(a, []).append(schedule[visit])
        now = O.CapturedRAM(bytes(ram_now), 0x100000)
        state = dict(out['registers'], flags=out['flags'])


def compare(c, want, got):
    from translator.ir import FLAG_BIT
    if [w[0] for w in want] != [g[0] for g in got]:
        return [f'visits {[w[0][1] for w in want]} != {[g[0][1] for g in got]}']
    errors = []
    for k, (w, g) in enumerate(zip(want, got)):
        where, wr, wf, wram, wh, undef = w
        _, gr, gf, gram, gh = g
        live = (set(c.live_in[where]) | {'DF', 'IF', 'TF'}) - set(undef)
        mask = sum(1 << FLAG_BIT[f] for f in live if f in FLAG_BIT)
        if any(wr[r] != gr[r] for r in wr):
            errors.append(f'visit {k} {where[1]:05X}: registers')
        if (wf ^ gf) & mask:
            errors.append(f'visit {k} {where[1]:05X}: live flags')
        if wram != gram:
            errors.append(f'visit {k} {where[1]:05X}: RAM')
        if wh != gh:
            errors.append(f'visit {k} {where[1]:05X}: write history')
    return errors


def handoff(plant=None, configs=(('return', 'return'), ('return 0x13618', 'sync'))):
    """Protocol differential; with a plant, raises AssertionError when caught."""
    import m68k_blocks as B
    import m68k_diff as D
    from tools import compute_oracle as O
    from translator import emit
    B.STUB_AT[SERVICE] = D.STUB + DOUBLE
    count = 0
    cache = ROOT / 'tmp/compute-polls'
    cache.mkdir(parents=True, exist_ok=True)
    for polls, name in configs:
        c = program(polls)
        if plant == 'missing-return-poll':
            c.loop_heads.discard(RESUME)
        polled = RESUME in c.loop_heads   # the return poll's continuation label exists
        extra = [f'{emit.label(*RESUME)}_np'] if polled else []
        img, addr = B.program_image(c, cache, tuple(extra))
        u = base().units[FIRST[0]]
        ip_resume = u.ip_of(RESUME[1])
        rng = random.Random(7)
        modes = ('decline', 'handle', 'mixed')
        for bound in (0, 1, 7, 40):
            for schedule in ({}, {1: 0}, {2: 30, 4: 3}):
                if name == 'return' and schedule:
                    continue    # no sync site: interrupts wait for the return poll
                ram, regs = entry_case(rng, bound)
                want = original(c, ram, regs, schedule)
                for mode in modes:
                    got, irqs, stop, longest = double_run(c, img, addr, ram, regs, mode,
                                                          schedule, plant, latency=mode == 'decline')
                    if plant == 'invalid-id':   # 'handle' returns one at the first call
                        assert mode != 'handle' or stop == 'rt_stop_unknown', 'invalid id accepted'
                        continue
                    assert stop == 'return_poll_done', (name, mode, stop)
                    errors = compare(c, want, got)
                    assert not errors, (name, bound, schedule, mode, errors[:4])
                    sync_irqs = [e for _, e in irqs if e != 'return']
                    assert sync_irqs == [schedule[k] for k in sorted(schedule)
                                         if k <= len(want) - 1], (name, mode, irqs)
                    assert irqs and irqs[-1] == (ip_resume, 'return'), ('return poll', irqs)
                    if longest is not None:
                        assert longest <= O.PIT_PERIOD_CYCLES, ('latency', longest)
                    count += 1
    return count


def main():
    print('compute polls admission:', admission(), 'controls pass')
    print('compute polls emission:', emission(), 'controls pass')
    print('compute polls handoff:', handoff(), 'visit/state comparisons pass')
    if '--sabotage' not in sys.argv:
        return
    from translator import emit

    def caught(name, f):
        try:
            f()
        except (AssertionError, LowerError) as e:
            print(f'compute polls: {name} plant caught ({str(e)[:90]})')
        else:
            raise AssertionError(f'{name} plant escaped')

    for name, target, stand_in in (('pure-wait admission', 'wait', lambda *a: None),
                                   ('shared-poll admission', 'shared', lambda *a: set())):
        with patch.object(compute, target, stand_in):
            caught(name, admission)
    real = compute.validate_polled
    with patch.object(compute, 'validate_polled',
                      lambda *a: real(*a)._replace(removed=frozenset())):
        caught('kept removed poll', emission)
    caught('missing return poll', lambda: emission(drop_return_poll=True))
    with patch.object(emit.Program, 'sync_poll_first', False):
        caught('hook before sync poll (emission)', emission)
        caught('hook before sync poll (handoff)',
               lambda: handoff(configs=(('return 0x13618', 'sync'),)))
    caught('missing return poll (handoff)', lambda: handoff('missing-return-poll',
                                                          configs=(('return', 'return'),)))
    for plant in ('stale-register', 'missing-store', 'future-store', 'skipped-visit',
                  'duplicate-visit', 'wrong-site', 'stale-continuation', 'latency'):
        caught(plant, lambda: handoff(plant, configs=(('return 0x13618', 'sync'),)))
    handoff('invalid-id', configs=(('return 0x13618', 'sync'),))
    print('compute polls: invalid resume id stops loudly')


if __name__ == '__main__':
    main()
