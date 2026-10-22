"""Admission and emission for opt-in compute HLE rows.

This defines an interface, not any native implementation. The reachable graph,
including callees, proves admission; annotation claims are not a proof.
"""
from typing import NamedTuple

from .ir import STATUS, T
from .lower import LowerError
from .sem import lift


def forbidden(p, n):
    return n in p.loop_heads or n in p.diagnostic_hooks or effect(p, n)


def effect(p, n):
    """Runtime, device and interrupt-control effects: outside every contract.
U8: a REP is no effect; the reference interrupts one only at a poll."""
    i = p.node_insn(n)
    return (n[1] in p.units[n[0]].manager_calls or
            i.op in {'in', 'out', 'int', 'int3', 'into', 'iret', 'hlt',
                     'cli', 'sti', 'popf'} or
            (i.op in {'mov', 'pop'} and i.operands and
             getattr(i.operands[0], 'name', None) == 'ss'))


DIVIDES = {'div', 'idiv', 'aam'}


def successors(p, n):
    """p.succ without the U8 divide-fault edge: the native declines before it."""
    int0 = getattr(p, 'int0', None)
    if int0 is not None and p.node_insn(n).op in DIVIDES:
        return [t for t in p.succ[n] if t != int0]
    return p.succ[n]


class Region(NamedTuple):
    body: frozenset     # nodes the callback covers, callees included
    returns: tuple      # root returns (U8: each a resume), ascending offset


def validate(p, first, resume, end=None):
    """Prove an acyclic, poll-free compute region, transitively.

Unknown transfers and exceptional edges cannot silently disappear, except the
U8 divide-fault edge (the native declines first). Every root return in the
range [first, end) is a resume (U8; end defaults to resume: compiled C may
place loop bodies after the return). Control/device effects are rejected.
Interior entries still execute generated code normally.
    """
    tail = p.node_insn(resume)
    if first == resume or tail is None or tail.op not in {'ret', 'retf'}:
        raise LowerError('compute: resume must be the original RET/RETF')
    limit = resume[1] if end is None else end
    if limit < resume[1]:
        raise LowerError('compute: range end before the resume')
    seen, active, body, rets = set(), set(), set(), {resume}

    def walk(n, callee=False):
        if not callee and n == resume:
            return
        if not isinstance(n, tuple) or n not in p.succ or p.node_insn(n) is None:
            raise LowerError(f'compute: unresolved flow {n}')
        if not callee and (n[0] != first[0] or not first[1] <= n[1] < limit):
            raise LowerError(f'compute: flow outside the declared range at {n}')
        key = (n, callee)
        if key in active:
            raise LowerError(f'compute: cyclic flow {n}')
        if key in seen:
            return
        if forbidden(p, n) or n in p.hle and n != first:
            raise LowerError(f'compute: poll, hook or external effect at {n}')
        i = p.node_insn(n)
        if i.op in {'ret', 'retf'}:
            if callee:
                body.add(n)
            else:
                rets.add(n)
            return
        active.add(key)
        body.add(n)
        succ = successors(p, n)
        if not succ:
            raise LowerError(f'compute: no proved continuation at {n}')
        if i.op in {'call', 'callf'}:
            for target in succ:
                walk(target, True)
            walk(p.call_site.get(n), callee)
        else:
            for target in succ:
                walk(target, callee)
        active.remove(key)
        seen.add(key)

    walk(first)
    return Region(frozenset(body), tuple(sorted(rets)))


def polled_hook(service, entry, dispatch, cs):
    """U5 hook: d7 = entry index in (0 the row's first instruction, k sync site k);
    d7.l out: 0 declines (the original code continues here), 1 resumes at the
    return, 1 + k at sync site k (polled_dispatch)."""
    return [f'\tmove.l #{cs},d6', f'\tmoveq #{entry},d7', f'\tjsr {service}',
            '\ttst.l d7', f'\tbne {dispatch}']


def polled_dispatch(dispatch, resumes, ip):
    """Out of line: the result's resume label; any other value stops loudly."""
    out = [f'{dispatch}:']
    for k, target in enumerate(resumes):
        out += ['\tsubq.l #1,d7', f'\tbne.s {dispatch}{k}', f'\tjmp {target}', f'{dispatch}{k}:']
    return out + [f'\tmove.l #{ip},d7', '\tjmp rt_stop_unknown']


def hook(service, resume, cs):
    # All guest registers/state are the generated-code ABI. d7 is a result,
    # not a guest register: zero declines without changing any guest state.
    return [f'\tmove.l #{cs},d6', f'\tjsr {service}', '\ttst.l d7', f'\tbne {resume}']


# -- U5 poll contract (docs/native-compute.md "Poll contract (U5)") ------------

class Polled(NamedTuple):
    body: frozenset     # nodes the callback may cover, callees included
    removed: frozenset  # polls dropped from the poll set, in both arms
    sync: tuple         # kept polls in the root: extra hook entries and resumes
    resume: tuple       # the row's declared return
    returns: tuple      # every root return, ascending (U8): each a resume and a poll


HALF = {'al': 'ax', 'ah': 'ax', 'bl': 'bx', 'bh': 'bx',
        'cl': 'cx', 'ch': 'cx', 'dl': 'dx', 'dh': 'dx'}
CALLS = {'call', 'callf'}
RETURNS = {'ret', 'retf'}


def validate_polled(p, first, resume, sync=(), end=None, endpoint=False, exits=()):
    """Prove a U5 row: root returns (U8), resolved flow, no effects, chosen polls.

Polls reachable only through the row are removed in both arms; the return gets
one. A sync site is a root-body poll the callback resumes at and is re-entered
from, so every visit stays in generated code. A poll that flow from outside
reaches without passing a hook entry must be a sync site; sync sites in callees
and recursion are rejected. Each removed loop must not be a pure wait (wait()).
    """
    tail = p.node_insn(resume)
    if first == resume or tail is None or (not endpoint and tail.op not in RETURNS):
        raise LowerError('compute: resume must be the original RET/RETF')
    if endpoint and (tail.op in RETURNS or end is not None):
        raise LowerError('compute: continuation needs a non-return endpoint and no range extension')
    exits = tuple(exits)
    if exits and not endpoint:
        raise LowerError('compute: extra exits require continuation endpoints')
    endpoints = {resume, *exits}
    if len(endpoints) != 1 + len(exits):
        raise LowerError('compute: duplicate continuation endpoint')
    for target in exits:
        insn = p.node_insn(target)
        if target == first or target[0] != first[0] or insn is None or insn.op in RETURNS:
            raise LowerError(f'compute: invalid continuation endpoint {target}')
    limit = resume[1] if end is None else end
    if limit < resume[1]:
        raise LowerError('compute: range end before the resume')
    sync = tuple(sync)
    if len(set(sync)) != len(sync) or endpoints & set(sync):
        raise LowerError('compute: sync sites must be distinct and not the resume')
    callees: dict = {}
    rets = endpoints.copy()
    reached_endpoint = False
    reached = set()

    def function(entry, root, stack):
        nonlocal reached_endpoint
        nodes, work = set(), [entry]
        while work:
            n = work.pop()
            if root and n in endpoints:
                reached.add(n)
                reached_endpoint = reached == endpoints
                continue
            if endpoint and not root and n in endpoints:
                raise LowerError(f'compute: continuation endpoint in callee {n}')
            if n in nodes:
                continue
            if not isinstance(n, tuple) or n not in p.succ or p.node_insn(n) is None:
                raise LowerError(f'compute: unresolved flow {n}')
            if root and (n[0] != first[0] or not first[1] <= n[1] < limit):
                raise LowerError(f'compute: flow outside the declared range at {n}')
            if effect(p, n) or n in p.hle and n != first:
                raise LowerError(f'compute: hook or external effect at {n}')
            if n in p.diagnostic_hooks and not (root and n in sync):
                raise LowerError(f'compute: diagnostic hook inside the body at {n}')
            nodes.add(n)
            i = p.node_insn(n)
            if i.op in RETURNS:
                if root:    # U8: another resume, outside the body like the declared one
                    if endpoint:
                        raise LowerError('compute: return before continuation endpoint')
                    nodes.discard(n)
                    rets.add(n)
                continue
            succ = successors(p, n)
            if not succ:
                raise LowerError(f'compute: no proved continuation at {n}')
            if i.op in CALLS:
                for t in succ:
                    if t in stack:
                        raise LowerError(f'compute: recursion at {t}')
                    if t not in callees:
                        callees[t] = None   # reserved: a shared callee is walked once
                        callees[t] = function(t, False, stack | {t})
                work.append(p.call_site.get(n))
            else:
                work.extend(succ)
        return nodes

    root = function(first, True, frozenset())
    if endpoint and not reached_endpoint:
        raise LowerError('compute: continuation endpoint is unreachable')
    body = set(root).union(*(c for c in callees.values() if c))
    for s in sync:
        if s not in root:
            raise LowerError(f'compute: sync site {s} is not in the root body')
        if p.node_insn(s).rep is not None:   # U8: a REP at a kept poll stays out
            raise LowerError(f'compute: REP at sync site {s}')
    graph = edges(p, body)
    polls = body & set(p.loop_heads)
    for n in sorted(polls & shared(p, body, graph, {first, *sync}) - set(sync)):
        raise LowerError(f'compute: poll {n} is reachable from outside the row')
    removed = frozenset(polls - set(sync))
    for h in sorted(removed & set(getattr(p, 'diagnostic_reps', {}))):
        raise LowerError(f'compute: diagnostic REP hook at removed poll {h}')
    for h in sorted(removed):
        wait(p, graph, body, h)
    return Polled(frozenset(body), removed, sync, resume, tuple(sorted(rets)))


def shared(p, body, graph, hooks):
    """Body nodes flow from outside the row reaches without a hook entry."""
    # Runtime entry rows (dispatch, far rows, indirect targets), not decoder seeds.
    outside = body & (set(getattr(p, 'dispatch', ())) | set(getattr(p, 'far_rows', ())))
    for sw, tr in getattr(p, 'indirect', {}).values():
        outside |= body & (set(sw) | set(tr))
    for m, ss in p.succ.items():
        if m not in body:
            outside |= body & {t for t in ss if isinstance(t, tuple)}
    for m, r in p.call_site.items():
        if m not in body and r in body:
            outside.add(r)
    reached, work = set(), list(outside - hooks)
    while work:
        n = work.pop()
        if n in reached or n in hooks:
            continue
        reached.add(n)
        work.extend(t for t in graph.get(n, ()) if t in body)
        if p.node_insn(n).op in CALLS:
            work.extend(t for t in p.succ[n] if t in body)
    return reached


def edges(p, body):
    """Function-level successors inside the body: a call goes to its return site."""
    out = {}
    for n in body:
        i = p.node_insn(n)
        if i.op in RETURNS:
            out[n] = []
        elif i.op in CALLS:
            out[n] = [p.call_site.get(n)]
        else:
            out[n] = [t for t in successors(p, n) if isinstance(t, tuple)]
    return out


def loop_of(graph, body, h):
    """The strongly connected nodes through loop head h."""
    pred = {}
    for n, ss in graph.items():
        for t in ss:
            pred.setdefault(t, []).append(n)

    def closure(start, nexts):
        seen, work = set(), [start]
        while work:
            n = work.pop()
            if n in seen or n not in body:
                continue
            seen.add(n)
            work.extend(nexts.get(n, ()))
        return seen

    return closure(h, graph) & closure(h, pred)


def wait(p, graph, body, h):
    """Reject a pure wait: a loop no exit of which can change without an interrupt.

Proved invariant: constants, registers and flags the loop never writes or only
writes with invariant values, and loads from invariant addresses when the loop
stores nothing (calls count as stores and writes of everything). A removed
loop needs an exit whose branch condition or target is not invariant. That is
not a termination proof; the S3 inputs and the latency bound are its evidence.
    """
    loop = loop_of(graph, body, h)
    if not any(h in graph[n] for n in loop):
        return  # a backward jump that closes no cycle (D8 polls its target too)
    exits = [n for n in loop if any(t not in loop for t in graph[n])]
    lifted = {n: lift(p.node_insn(n)) for n in loop}
    calls = any(p.node_insn(n).op in CALLS for n in loop)
    stores = calls or any(o.op == 'store' for ops in lifted.values() for o in ops)
    written = set()
    for ops in lifted.values():
        for o in ops:
            if o.op == 'put':
                written.add(HALF.get(o.args[0], o.args[0]))
            elif o.op == 'setflag':
                written.add(o.args[0])
            elif o.op in ('flags', 'bcd'):
                written |= set(STATUS) | ({'ax'} if o.op == 'bcd' else set())
    if calls:
        return  # a callee may change anything: not provably a wait

    def values(ops, inv):
        known = set()  # invariant temporaries
        for o in ops:
            args = [a for a in o.args if isinstance(a, T)]
            if o.dst is None:
                continue
            if o.op == 'get':
                ok = HALF.get(o.args[0], o.args[0]) in inv
            elif o.op == 'flag':
                ok = o.args[0] in inv
            elif o.op == 'cond':
                ok = set(STATUS) <= inv
            elif o.op == 'load':
                ok = not stores and all(a in known for a in args)
            elif o.op == 'in':
                ok = False
            else:
                ok = all(a in known for a in args)
            if ok:
                known.add(o.dst)
        return known

    names = {'ax', 'bx', 'cx', 'dx', 'sp', 'bp', 'si', 'di', 'cs', 'ds', 'es', 'ss',
             *STATUS, 'DF', 'IF', 'TF', 'flagsx'}
    inv, invariant = names - written, None
    while invariant != inv:  # grow: a name whose every write is invariant
        invariant = set(inv)
        for name in written - inv:
            ok = True
            for ops in lifted.values():
                known = values(ops, inv)
                for o in ops:
                    if o.op == 'put' and HALF.get(o.args[0], o.args[0]) == name:
                        ok &= isinstance(o.args[1], int) or o.args[1] in known
                    elif o.op == 'setflag' and o.args[0] == name:
                        ok &= isinstance(o.args[1], int) or o.args[1] in known
                    elif o.op == 'flags' and name in STATUS:
                        ok &= all(isinstance(a, (int, str)) or a in known for a in o.args)
                    elif o.op == 'bcd' and (name in STATUS or name == 'ax'):
                        ok = False
            if ok:
                inv.add(name)
    for n in exits:
        known = values(lifted[n], inv)
        for o in lifted[n]:
            control = [o.args[0]] if o.op == 'br' else \
                [a for a in o.args if isinstance(a, T)] if o.op in ('jump', 'jumpf') else []
            if any(isinstance(c, T) and c not in known for c in control):
                return
    raise LowerError(f'compute: loop at {h} is a pure wait (no exit can change without an interrupt)')
