"""U8 contract extensions (native-plan C4): REP, divide-fault decline, multiple
returns and range ends, on real routines with rows only in memory.

No guest routine is replaced. The callback is a test double driven by the
original x86 (tools/compute_oracle.py): it checks the protocol (dispatch to
each return, exact decline at a divide fault, REP inside a loop whose head
leaves the sync set, flow past the return), never a native implementation (S6
does that). Rows are poll-free (RC5, irq-plan I9).
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

M = 'SWOTL.EXE'
SERVICE = 'rt_hle_u8_test'
DOUBLE = 0xc40      # stub page offset of the callback (not a harness stub)
INT0 = (M, 0x13735)


def at(o):
    return (M, o)


_base = {}


def base():
    from translator import emit
    if 'p' not in _base:
        _base['p'] = emit.Program()
    return _base['p']


def text_after(lines, lab, n):
    k = next(i for i, x in enumerate(lines) if x.startswith(lab + ':'))
    return lines[k + 1:k + 1 + n]


def guest_state(m, D):
    """Registers and FLAGS word as the generated ABI holds them at a leader."""
    regs = {r: (m.r(D.M68[r]) ^ D.MIRROR.get(r, 0)) & 0xffff for r in D.REGS}
    st = m.e.read(D.STATE, 16)
    for s, o in (('es', 12), ('ss', 14), ('ds', 16)):
        regs[s] = int.from_bytes(st[16 - o:16 - o + 2], 'big')
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
    for s, o, a in (('es', 12, 'a1'), ('ss', 14, 'a2'), ('ds', 16, 'a3')):
        st[16 - o:16 - o + 2] = regs[s].to_bytes(2, 'big')
        m.e.reg_write(D.U.M68K[a], D.TOP - regs[s] * 16 - 0x7fff)
    f = {k: word >> FLAG_BIT[k] & 1 for k in FLAG_BIT}
    st[15] = st[15] & 0x10 | D.ccr_image(f)
    st[13] = 0 if f['PF'] else 1
    st[12] = f['AF'] << 4 | st[12] & 0xef
    st[11], st[10], st[9] = f['DF'], f['IF'], f['TF']
    st[6:8] = (word & 0xf000).to_bytes(2, 'big')
    m.e.write(D.STATE, bytes(st))


# name: first, last (before the declared return), end, returns, loop heads
# (root loop heads: resumes after the returns; they leave the sync set)
ROWS = {
    # far, loop-free; returns at DCF8, DD00; div after a guard (no fault)
    'dce9': (0xdce9, 0xdcff, None, (0xdcf8, 0xdd00), ()),
    # near 32/32 divide: returns DBAD, DBB8, DBD5; loop DBB9; div bx may fault
    'db9d': (0xdb9d, 0xdbd3, None, (0xdbad, 0xdbb8, 0xdbd5), (0xdbb9,)),
    # far table walk: REPNE SCASB inside the loop at 14477
    '1446a': (0x1446a, 0x14491, None, (0x14492,), (0x14477,)),
    # near: code past the return (15440..15443) jumps back to 1543B
    '15416': (0x15416, 0x1543c, 0x15444, (0x1543f,), (0x1543b,)),
}


def program(name, end=-1, **extra):
    """The real Program with one temporary in-memory row; hle.csv is unchanged.
    `extra`: Program arguments (diagnostic hooks, a sync set)."""
    from translator import emit, image
    first, last, row_end, _, _ = ROWS[name]
    end = row_end if end == -1 else end
    original = image.rows
    row = dict(module=M, first=hex(first), last=hex(last), service=SERVICE[7:],
               kind='compute', args='', reason='C4 protocol test only; no replacement',
               oracle='tests/test_compute_u8.py',
               end=hex(end) if end is not None else '')

    def rows(table):
        return original(table) + ([row] if table == 'hle.csv' else [])

    with patch.object(image, 'rows', rows):
        return emit.Program(units=base().units, **extra)


def poll_set(c, name):
    """RC5: the loop heads in the row's body leave the sync set, nothing else."""
    p = base()
    row = c.compute_bodies[at(ROWS[name][0])]
    assert c.loop_heads == p.loop_heads - (row.body & p.loops), (name, 'poll set')


# -- admission and emission ----------------------------------------------------

def emission():
    from translator import emit
    p = base()
    u = p.units[M]
    count = 0
    for name, (first, _, end, returns, loops) in ROWS.items():
        c = program(name)
        row = c.compute_bodies[at(first)]
        rets = tuple(at(r) for r in returns)
        assert row.returns == rets, (name, row.returns)
        assert row.loops == tuple(at(h) for h in loops), (name, row.loops)
        assert {at(h) for h in loops} <= p.loop_heads, (name, 'loop heads were sync points')
        cs = emit.cs_expr(u.cs[first])
        lines, _ = c.module_text(M)
        poll_set(c, name)
        for h in row.loops:     # no poll at a loop head that left the set
            assert text_after(lines, emit.label(*h), len(emit.poll(''))) != emit.poll(emit.label(*h)), (name, h)
        resumes = [*rets, *row.loops]
        for r in resumes:
            assert r in c.leaders and r in c.hle_resumes, (name, r)
            assert c.live_in[r] <= c.live_in[at(first)], (name, 'resume liveness')
        if len(resumes) > 1:
            hook = compute.hook(SERVICE, f'{emit.label(M, first)}_cx', cs)
            stub = compute.resume_dispatch(f'{emit.label(M, first)}_cx',
                                           [emit.label(*r) for r in resumes], emit.hx(u.ip_of(first)))
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
    # RC5/I2: a sync point other than a loop head, or a diagnostic hook (a REP
    # slice too), inside the body rejects the row
    sync = {**emit.sync_points(), at(0x14486): 'access'}
    for name, end, extra, kind in (('15416', None, {}, 'range'),
                                   ('15416', 0x1543e, {}, 'end before resume'),
                                   ('1446a', -1, {'sync': sync}, 'sync access in body'),
                                   ('1446a', -1, {'diagnostic_reps': {at(0x14486): 1}}, 'REP slice hook in body'),
                                   ('db9d', -1, {'diagnostic_hooks': {at(0xdbb9): 1}}, 'diagnostic hook in body')):
        try:
            program(name, end, **extra)
        except LowerError:
            count += 1
        else:
            raise AssertionError(f'{name}: {kind} generated')
    return count


def candidate_admission(plant=False):
    # Admission inventory concerns the original generated bodies. Keep the
    # production Program intact and disable the enabled nested hooks in this copy.
    enabled = base()
    original = copy(enabled)
    hooks = {at(0xb017), at(0xb393), at(0xb4e2), at(0xd5da)} & enabled.hle.keys()
    original.hle = {n: row for n, row in enabled.hle.items() if n not in hooks}
    count = 0
    for first, returns in ((0xb017, 4), (0xb4e2, 1), (0xd5a6, 1)):
        rets, _ = original.reach(at(first), {})
        def admit(p):
            return compute.validate(p, at(first), max(rets))
        row = admit(original)
        assert len(row.returns) == returns, hex(first)
        count += 1
        for hook in sorted((hooks & row.body) - {at(first)}):
            nested = copy(original)
            nested.hle = {**original.hle, hook: enabled.hle[hook]}
            try:
                admit(original if plant else nested)
            except LowerError as error:
                assert 'hook' in str(error) and str(hook) in str(error), error
            else:
                raise AssertionError(f'{first:x}: enabled nested hook {hook} admitted')
            count += 1
    return count


# -- generated handoff with an x86-driven double -------------------------------

def entry_case(name, rng):
    import m68k_blocks as B
    import x86_diff as X
    from translator import image
    from translator.lower import LOADSEG
    first, _, end, returns, _ = ROWS[name]
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
    ends = [(regs['cs'], u.ip_of(r)) for r in ROWS[name][3]]
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
    first, _, _, returns, _ = ROWS[name]
    ends = [(regs['cs'], u.ip_of(r)) for r in returns]
    stubs = {k: v for k, v in B.STUB_AT.items() if k != SERVICE}
    m = D.M68k(O.CapturedRAM(bytes(ram), 0x100000), stubs)
    m.load(img)
    O.watch_native(m)
    service = D.STUB + DOUBLE
    m.e.write(service, b'\x4a\xfc\x4e\x75')
    seen = {'irqs': [], 'calls': 0}

    @D.U.CODE_CB
    def code(h, a, size, user):
        if a == stubs['rt_irq']:
            seen['irqs'].append(m.r('d7') & 0xffff)
        elif a == service:
            m.stop = 'double'
            D.U.uc.uc_emu_stop(h)

    def serve():
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
            if plant == 'no-decline':   # computes on anyway, as if no fault
                return 1
            return 0
        for a in sorted(out['writes']):
            m.gwrite(a, out['ram'][a:a + 1])
        put_state(m, D, {k: v for k, v in out['registers'].items() if k not in ('cs', 'ip')},
                  out['flags'])
        result = 1 + ends.index(out['at'])
        return 1 if plant == 'wrong-return' else result

    m.e.hook(D.U.HOOK_CODE, code)
    m.irq_calls = []
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
        state = guest_state(m, D) + (m.gread(0, 0x100000),)
        if stop == 'rt_fault':
            return ('fault', m.r('d7') & 0xffff), state, seen['irqs']
        assert stop and stop.split()[0] == 'return', (name, mode, stop)
        return ('return', u.ip_of(int(stop.split()[1], 16))), state, seen['irqs']
    finally:
        D.U.uc.uc_close(m.e.h)


def differences(c, name, where, want, got):
    from translator.ir import FLAG_BIT
    u = base().units[M]
    gr, gf, gram = got
    wr = {k: v for k, v in want['registers'].items() if k not in ('cs', 'ip')}
    if where[0] == 'fault':     # the flags the INT 00h handler reads (open-work 24)
        live = set(c.live_in[INT0]) | {'DF', 'IF', 'TF'}
    else:
        r = next(x for x in ROWS[name][3] if u.ip_of(x) == where[1])
        live = set(c.live_in[at(r)]) | {'DF', 'IF', 'TF'}
    mask = sum(1 << FLAG_BIT[f] for f in live - set(want['undefined']) if f in FLAG_BIT)
    errors = [f'register {k}' for k in wr if wr[k] != gr[k]]
    if (want['flags'] ^ gf) & mask:
        errors.append('live flags')
    if bytes(want['ram'][:0x100000]) != gram:
        errors.append('RAM')
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
        img, addr = B.program_image(c, cache)
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
                assert not irqs, (name, mode, 'interrupt in a native row', irqs)
                count += 1
    for name in names:   # every return of each row, and the fault, are exercised
        want = {('return', u.ip_of(r)) for r in ROWS[name][3]}
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
    real_effect, real_validate = compute.effect, compute.validate
    with patch.object(compute, 'effect', lambda p, n: real_effect(p, n) or bool(p.node_insn(n).rep)):
        caught('REP as effect', emission)
    with patch.object(compute, 'successors', lambda p, n: p.succ[n]):
        caught('fault edge as flow', emission)
    with patch.object(compute, 'validate',
                      lambda *a, **k: real_validate(*a, **k)._replace(returns=(real_validate(*a, **k).returns[-1],))):
        caught('returns dropped (far)', lambda: handoff(names=('dce9',)))
        caught('returns dropped (loop row)', lambda: handoff(names=('db9d',)))
    with patch.object(compute, 'validate',
                      lambda *a, **k: real_validate(*a, **k)._replace(loops=())):
        caught('loop head not a resume', emission)
    c = program('db9d')
    c.loop_heads.add(at(0xdbb9))
    caught('body loop head kept in the sync set', lambda: poll_set(c, 'db9d'))
    for plant in ('mutate-then-decline', 'no-decline', 'wrong-return'):
        caught(plant, lambda: handoff(plant, names=('db9d',)))


if __name__ == '__main__':
    main()
