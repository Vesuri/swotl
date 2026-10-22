"""U8 contract extensions (native-plan C4): REP, divide-fault decline, multiple
returns and range ends, on real routines with rows only in memory.

No guest routine is replaced. The callback is a test double driven by the
original x86 (tools/compute_oracle.py): it checks the protocol (dispatch to
each return, return polls, exact decline at a divide fault, REP in a removed
loop, flow past the return), never a native implementation (S6 does that).
"""
from copy import copy
import random
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from translator import compute  # noqa: E402
from translator.lower import LowerError  # noqa: E402
from test_compute_polls import base, guest_state, put_state, text_after  # noqa: E402

M = 'SWOTL.EXE'
SERVICE = 'rt_hle_u8_test'
DOUBLE = 0xc40      # stub page offset of the callback (not a harness stub)
INT0 = (M, 0x13735)


def at(o):
    return (M, o)


# name: first, last (before the declared return), polls, end, returns, removed
ROWS = {
    # far, poll-free; returns at DCF8, DD00; div after a guard (no fault)
    'dce9': (0xdce9, 0xdcff, '', None, (0xdcf8, 0xdd00), ()),
    # near 32/32 divide: returns DBAD, DBB8, DBD5; loop DBB9; div bx may fault
    'db9d': (0xdb9d, 0xdbd3, 'return', None, (0xdbad, 0xdbb8, 0xdbd5), (0xdbb9,)),
    # far table walk: REPNE SCASB inside the removed loop at 14477
    '1446a': (0x1446a, 0x14491, 'return', None, (0x14492,), (0x14477,)),
    # near: code past the return (15440..15443) jumps back to 1543B
    '15416': (0x15416, 0x1543c, 'return', 0x15444, (0x1543f,), (0x1543b,)),
}


def program(name, polls=None, end=-1):
    """The real Program with one temporary in-memory row; hle.csv is unchanged."""
    from translator import emit, image
    first, last, row_polls, row_end, _, _ = ROWS[name]
    polls = row_polls if polls is None else polls
    end = row_end if end == -1 else end
    original = image.rows
    row = dict(module=M, first=hex(first), last=hex(last), service=SERVICE[7:],
               kind='compute', args='', reason='C4 protocol test only; no replacement',
               oracle='tests/test_compute_u8.py', polls=polls,
               end=hex(end) if end is not None else '')

    def rows(table):
        return original(table) + ([row] if table == 'hle.csv' else [])

    with patch.object(image, 'rows', rows):
        return emit.Program(units=base().units)


# -- admission and emission ----------------------------------------------------

def emission():
    from translator import emit
    p = base()
    u = p.units[M]
    count = 0
    for name, (first, _, polls, end, returns, removed) in ROWS.items():
        c = program(name)
        row = c.compute_bodies[at(first)]
        rets = tuple(at(r) for r in returns)
        assert row.returns == rets, (name, row.returns)
        cs = emit.cs_expr(u.cs[first])
        lines, _ = c.module_text(M)
        if polls:
            assert row.removed == {at(h) for h in removed}, name
            assert c.loop_heads == (p.loop_heads - row.removed) | set(rets), (name, 'poll set')
            for r in rets:      # every return polls
                assert text_after(lines, emit.label(*r), 3) == emit.poll(emit.label(*r)), (name, r)
        else:
            assert c.loop_heads == p.loop_heads, (name, 'poll set')
        for r in rets:
            assert r in c.leaders and r in c.hle_resumes, (name, r)
            assert c.live_in[r] <= c.live_in[at(first)], (name, 'resume liveness')
        if len(rets) > 1 or polls:
            hook = compute.polled_hook(SERVICE, 0, f'{emit.label(M, first)}_cx', cs)
            stub = compute.polled_dispatch(f'{emit.label(M, first)}_cx',
                                           [emit.label(*r) for r in rets], emit.hx(u.ip_of(first)))
            k = lines.index(stub[0])
            assert lines[k:k + len(stub)] == stub, (name, 'dispatch')
        else:
            hook = compute.hook(SERVICE, emit.label(*rets[0]), cs)
        assert text_after(lines, emit.label(M, first), len(hook)) == hook, (name, 'hook')
        count += 4
    # REP and fault edge in the body; the handler stays outside
    assert at(0x14486) in program('1446a').compute_bodies[at(0x1446a)].body
    assert INT0 not in program('db9d').compute_bodies[at(0xdb9d)].body
    count += candidate_admission()
    count += 2
    for name, polls, end, kind in (('15416', None, None, 'range'),
                                   ('15416', None, 0x1543e, 'end before resume'),
                                   ('1446a', 'return 0x14486', -1, 'REP sync site'),
                                   ('db9d', 'return 0xdbad', -1, 'return as sync site')):
        try:
            program(name, polls, end)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'{name}: {kind} generated')
    return count


def candidate_admission(plant=False):
    # Admission inventory concerns the original generated bodies. Keep the
    # production Program intact and disable only projection in this copy.
    enabled = base()
    original = copy(enabled)
    projection = at(0xb393)
    original.hle = {n: row for n, row in enabled.hle.items() if n != projection}
    count = 0
    for first, sync, returns in ((0xb017, None, 4), (0xb4e2, None, 1), (0xd5a6, (), 1)):
        rets, _ = original.reach(at(first), {})
        def admit(p):
            return (compute.validate(p, at(first), max(rets)) if sync is None else
                    compute.validate_polled(p, at(first), max(rets), sync))
        row = admit(original)
        assert len(row.returns) == returns, hex(first)
        count += 1
        if projection in enabled.hle and projection in row.body:
            try:
                admit(original if plant else enabled)
            except LowerError as error:
                assert 'hook' in str(error) and str(projection) in str(error), error
            else:
                raise AssertionError(f'{first:x}: enabled nested projection admitted')
            count += 1
    return count


# -- generated handoff with an x86-driven double -------------------------------

def entry_case(name, rng):
    import m68k_blocks as B
    import x86_diff as X
    from translator import image
    from translator.lower import LOADSEG
    first, _, _, end, returns, _ = ROWS[name]
    u = base().units[M]
    ram = bytearray(rng.randrange(256) for _ in range(0x10000)) * 16
    ram += bytearray(X.RAM - len(ram))
    mod = B.relocated(image.load()[M])
    cs = (LOADSEG + u.cs[first]) & 0xffff
    stop = max([*returns, end or 0]) + 4
    for o in range(first, stop):
        ram[cs * 16 + u.ip_of(o)] = mod[o]
    word = lambda: rng.choice((0, 1, 2, 0x7fff, 0x8000, 0xffff, rng.randrange(0x10000),
                               rng.randrange(0x10000)))
    regs = dict(ax=word(), bx=word(), cx=word(), dx=word(), sp=0x0400, bp=word(),
                si=word(), di=word(), cs=cs, ip=u.ip_of(first), ss=0x4000, ds=0x5000,
                es=0x6000, flags=0x7202)
    if name == 'db9d' and rng.randrange(4) == 0:
        regs.update(bx=0, cx=0)         # the zero-divisor return at DBAD
    for k in range(0, 12, 2):           # return address and arguments
        ram[0x40400 + k:0x40402 + k] = word().to_bytes(2, 'little')
    if name == '1446a':                 # [key][string 0]... [FFFF] at DS:5D60
        table, keys = bytearray(), []
        for _ in range(rng.randrange(5)):
            key = rng.randrange(0xffff)
            keys.append(key)
            table += key.to_bytes(2, 'little')
            table += bytes(rng.randrange(1, 256) for _ in range(rng.randrange(24))) + b'\0'
        table += b'\xff\xff'
        a = 0x50000 + 0x5d60
        ram[a:a + len(table)] = table
        want = rng.choice(keys + [rng.randrange(0x10000)]) if keys else rng.randrange(0x10000)
        ram[0x40406:0x40408] = want.to_bytes(2, 'little')   # [bp+6] after push bp
    return ram, regs


def expected(name, ram, regs):
    """The original from entry to a return, or to its divide fault."""
    from tools import compute_oracle as O
    u = base().units[M]
    ends = [(regs['cs'], u.ip_of(r)) for r in ROWS[name][4]]
    try:
        out = O.run(O.CapturedRAM(bytes(ram), 0x100000), dict(regs), ends[-1], returns=ends)
    except O.DivideFault as fault:
        s = fault.state
        return ('fault', s['registers']['ip']), s
    return ('return', out['at'][1]), out


def double_run(c, name, img, addr, ram, regs, mode, plant=None):
    """One generated run with the double; returns (where, state) at the stop."""
    import m68k_diff as D
    import m68k_blocks as B
    from tools import compute_oracle as O
    from translator import emit
    u = base().units[M]
    first, _, polls, _, returns, _ = ROWS[name]
    ends = [(regs['cs'], u.ip_of(r)) for r in returns]
    stubs = {k: v for k, v in B.STUB_AT.items() if k != SERVICE}
    m = D.M68k(O.CapturedRAM(bytes(ram), 0x100000), stubs)
    m.load(img)
    history = O.watch_native(m)
    service = D.STUB + DOUBLE
    m.e.write(service, b'\x4a\xfc\x4e\x75')
    at_ret = {addr[emit.label(M, r)]: r for r in returns}
    seen = {'irqs': [], 'calls': 0, 'at': None}

    @D.U.CODE_CB
    def code(h, a, size, user):
        if a in at_ret and polls:
            seen['at'] = at_ret[a]
            seen['state'] = guest_state(m, D) + (m.gread(0, 0x100000),
                                                 {k: list(v) for k, v in history.items()})
            m.e.write(D.STATE + 8, b'\1')   # an interrupt posted before the return poll
            m.e.write(D.PENDING, b'\1')
        elif a == stubs['rt_irq']:
            seen['irqs'].append(m.r('d7') & 0xffff)
        elif a == service:
            m.stop = 'double'
            D.U.uc.uc_emu_stop(h)

    def serve():
        if at(first) in c.polled_resumes:   # the legacy hook passes no entry index
            assert m.r('d7') & 0xff == 0, 'entry index'
        seen['calls'] += 1
        if mode == 'decline':
            return 0
        r, w = guest_state(m, D)
        now = O.CapturedRAM(m.gread(0, D.X.RAM), 0x100000)
        try:
            out = O.run(now, dict(r, cs=regs['cs'], ip=u.ip_of(first), flags=w), ends[-1],
                        returns=ends)
        except O.DivideFault as fault:
            if plant == 'mutate-then-decline':
                a = regs['ss'] * 16 + regs['sp'] - 2
                m.gwrite(a, bytes([m.gread(a, 1)[0] ^ 1]))
                history.setdefault(a, []).append(m.gread(a, 1)[0])
            if plant == 'no-decline':   # computes on anyway, as if no fault
                return 1
            return 0
        for a, vs in sorted(out['history'].items()):
            for v in vs:
                m.gwrite(a, bytes([v]))
                history.setdefault(a, []).append(v)
        put_state(m, D, {k: v for k, v in out['registers'].items() if k not in ('cs', 'ip')},
                  out['flags'])
        result = 1 + ends.index(out['at'])
        return 1 if plant == 'wrong-return' else result

    m.e.hook(D.U.HOOK_CODE, code)
    m.irq_calls = []
    if polls:   # after the return poll; a return planted without one stops at its label
        m.extra_stops = {addr.get(f'{emit.label(M, r)}_np', addr[emit.label(M, r)]):
                         f'polled {r:05X}' for r in returns}
    else:
        m.extra_stops = {addr[emit.label(M, r)]: f'return {r:05X}' for r in returns}
    from translator.ir import FLAG_BIT, FLAGS
    flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
    try:
        _, _, _, _, outs, _, info = m.run(addr[emit.label(M, first)],
            (regs, flags, regs['flags'] & 0xf000, regs['ip'], []), random.Random(33), irq=False)
        stop, err = info['stop'], info['err']
        while stop == 'double' and not err:
            m.e.reg_write(D.U.M68K['d7'], serve())
            m.stop = None
            err = m.e.start(service + 2, 0xFFFFFFFF, 4_000_000)   # its rts
            stop = m.stop
        assert not m.outs and not err, (name, mode, plant, stop, err)
        assert seen['calls'] == 1, (name, mode, 'callback calls', seen['calls'])
        if stop == 'rt_fault':
            state = guest_state(m, D) + (m.gread(0, 0x100000),
                                         {k: list(v) for k, v in history.items()})
            return ('fault', m.r('d7') & 0xffff), state, seen['irqs']
        assert stop and stop.split()[0] in ('polled', 'return'), (name, mode, stop)
        r = int(stop.split()[1], 16)
        if polls and seen['at'] == r:
            return ('return', u.ip_of(r)), seen['state'], seen['irqs']
        state = guest_state(m, D) + (m.gread(0, 0x100000),
                                     {k: list(v) for k, v in history.items()})
        return ('return', u.ip_of(r)), state, seen['irqs']
    finally:
        D.U.uc.uc_close(m.e.h)


def differences(c, name, where, want, got):
    from translator.ir import FLAG_BIT
    u = base().units[M]
    gr, gf, gram, gh = got
    wr = {k: v for k, v in want['registers'].items() if k not in ('cs', 'ip')}
    if where[0] == 'fault':     # the flags the INT 00h handler reads (open-work 24)
        live = set(c.live_in[INT0]) | {'DF', 'IF', 'TF'}
    else:
        r = next(x for x in ROWS[name][4] if u.ip_of(x) == where[1])
        live = set(c.live_in[at(r)]) | {'DF', 'IF', 'TF'}
    mask = sum(1 << FLAG_BIT[f] for f in live - set(want['undefined']) if f in FLAG_BIT)
    errors = [f'register {k}' for k in wr if wr[k] != gr[k]]
    if (want['flags'] ^ gf) & mask:
        errors.append('live flags')
    if bytes(want['ram'][:0x100000]) != gram:
        errors.append('RAM')
    if {a: list(v) for a, v in want['history'].items()} != gh:
        errors.append('write history')
    return errors


def handoff(plant=None, names=tuple(ROWS), cases=24, rows=None):
    import m68k_blocks as B
    import m68k_diff as D
    from translator import emit
    B.STUB_AT[SERVICE] = D.STUB + DOUBLE
    cache = ROOT / 'tmp/compute-u8'
    cache.mkdir(parents=True, exist_ok=True)
    count, reached = 0, {}
    u = base().units[M]
    for name in names:
        c = (rows or {}).get(name) or program(name)
        polls, returns = ROWS[name][2], ROWS[name][4]
        extra = tuple(f'{emit.label(M, r)}_np' for r in returns
                      if polls and at(r) in c.loop_heads)
        img, addr = B.program_image(c, cache, extra)
        rng = random.Random(11)
        for _ in range(cases):
            ram, regs = entry_case(name, rng)
            where, want = expected(name, ram, regs)
            reached.setdefault(name, set()).add(where)
            for mode in ('decline', 'handle'):
                got_where, got, irqs = double_run(c, name, img, addr, ram, regs, mode, plant)
                assert got_where == where, (name, mode, where, got_where)
                errors = differences(c, name, where, want, got)
                assert not errors, (name, mode, where, errors)
                if polls and where[0] == 'return':   # the return poll took the interrupt
                    assert irqs == [where[1]], (name, mode, 'return poll', irqs)
                count += 1
    for name in names:   # every return of each row, and the fault, are exercised
        want = {('return', u.ip_of(r)) for r in ROWS[name][4]}
        assert want <= reached[name], (name, sorted(reached[name]))
    if 'db9d' in names:
        assert ('fault', u.ip_of(0xdbb6)) in reached['db9d'], 'no divide fault exercised'
    return count


def main():
    print('compute U8 emission:', emission(), 'controls pass')
    print('compute U8 handoff:', handoff(), 'state comparisons pass')
    if '--sabotage' not in sys.argv:
        return

    def caught(name, f):
        try:
            f()
        except (AssertionError, LowerError) as e:
            print(f'compute U8: {name} plant caught ({str(e)[:90]})')
        else:
            raise AssertionError(f'{name} plant escaped')

    caught('nested hook admitted', lambda: candidate_admission(plant=True))
    real_effect, real_validate, real_polled = compute.effect, compute.validate, compute.validate_polled
    with patch.object(compute, 'effect', lambda p, n: real_effect(p, n) or bool(p.node_insn(n).rep)):
        caught('REP as effect', emission)
    with patch.object(compute, 'successors', lambda p, n: p.succ[n]):
        caught('fault edge as flow', emission)
    with patch.object(compute, 'validate',
                      lambda *a: real_validate(*a)._replace(returns=(real_validate(*a).returns[-1],))):
        caught('returns dropped (poll-free)', lambda: handoff(names=('dce9',)))
    with patch.object(compute, 'validate_polled',
                      lambda *a: real_polled(*a)._replace(returns=(real_polled(*a).returns[-1],))):
        caught('returns dropped (U5)', lambda: handoff(names=('db9d',)))
    c = program('db9d')
    c.loop_heads.discard(at(0xdbad))
    caught('early return without poll', lambda: handoff(names=('db9d',), rows={'db9d': c}))
    for plant in ('mutate-then-decline', 'no-decline', 'wrong-return'):
        caught(plant, lambda: handoff(plant, names=('db9d',)))


if __name__ == '__main__':
    main()
