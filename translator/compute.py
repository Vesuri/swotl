"""Admission and emission for opt-in compute HLE rows (docs/native-compute.md, RC5).

This defines an interface, not any native implementation. The reachable graph,
including callees, proves admission; annotation claims are not a proof.
"""
from typing import NamedTuple

from .lower import LowerError


def forbidden(p, n):
    """Diagnostic hooks (REP slices too), sync points other than loop heads (I2:
the row would meet the IRQ0 handler's footprint) and external effects."""
    return (n in p.diagnostic_hooks or n in getattr(p, 'diagnostic_reps', {}) or
            getattr(p, 'sync', {}).get(n, 'loop') != 'loop' or effect(p, n))


def effect(p, n):
    """Runtime, device and interrupt-control effects: outside every contract.
U8: a REP is no effect."""
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


CALLS = {'call', 'callf'}
RETURNS = {'ret', 'retf'}


class Region(NamedTuple):
    body: frozenset     # nodes the callback covers, callees included
    returns: tuple      # root returns (U8) or continuation endpoints, ascending
    loops: tuple = ()   # root loop heads, ascending: resumes after the returns


def validate(p, first, resume, end=None, endpoint=False, exits=(), entries=()):
    """Prove a compute region (RC5): resolved flow, no effects, transitively.

Nothing observes a row's intermediate state, so loops are allowed; their heads
leave the sync set (emit.Program). Unknown transfers and exceptional edges
cannot silently disappear, except the U8 divide-fault edge (the native
declines first). Every root return in the range [first, end) is a resume (U8;
end defaults to resume: compiled C may place loop bodies after the return);
with endpoint, `resume` and `exits` are non-return continuation endpoints
instead. Recursion and diagnostic hooks are rejected. A root loop head is a
resume too: a native may continue there in generated code. Interior entries
still execute generated code normally; `entries` (I10) are re-entry hooks of
this row, walked as roots like `first`.
    """
    tail = p.node_insn(resume)
    if first == resume or tail is None or (not endpoint and tail.op not in RETURNS):
        raise LowerError('compute: resume must be the original RET/RETF')
    if endpoint and tail.op in RETURNS:
        raise LowerError('compute: continuation needs a non-return endpoint')
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
    callees: dict = {}
    rets = endpoints.copy()
    reached = set()

    def function(entry, root, stack):
        nodes, work = set(), [entry]
        while work:
            n = work.pop()
            if root and n in endpoints:
                reached.add(n)
                continue
            if endpoint and not root and n in endpoints:
                raise LowerError(f'compute: continuation endpoint in callee {n}')
            if n in nodes:
                continue
            if not isinstance(n, tuple) or n not in p.succ or p.node_insn(n) is None:
                raise LowerError(f'compute: unresolved flow {n}')
            if root and (n[0] != first[0] or not first[1] <= n[1] < limit):
                raise LowerError(f'compute: flow outside the declared range at {n}')
            if forbidden(p, n) or n in p.hle and n != first or n in getattr(p, 'entry_of', {}) \
                    and p.entry_of[n][0] != first:
                raise LowerError(f'compute: sync point, hook or external effect at {n}')
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
    for entry in entries:
        if entry in endpoints:
            raise LowerError(f'compute: entry {entry} is an endpoint')
        root |= function(entry, True, frozenset())
    if endpoint and reached != endpoints:
        raise LowerError('compute: continuation endpoint is unreachable')
    body = frozenset(root.union(*(c for c in callees.values() if c)))
    return Region(body, tuple(sorted(rets)), tuple(sorted(root & set(getattr(p, 'loops', ())))))


def hook(service, resume, cs):
    # All guest registers/state are the generated-code ABI. d7 is a result,
    # not a guest register: zero declines without changing any guest state.
    # A row with several resumes branches to resume_dispatch on d7.
    return [f'\tmove.l #{cs},d6', f'\tjsr {service}', '\ttst.l d7', f'\tbne {resume}']


def resume_dispatch(dispatch, resumes, ip):
    """Out of line: d7 = 1 + k resumes at resumes[k] (returns or endpoints, then
    root loop heads); any other value stops loudly."""
    if len(resumes) >= 5:
        # PC-relative long offsets: constant time for any resume id.
        out = [f'{dispatch}:', '\tsubq.l #1,d7', f'\tcmp.l #{len(resumes)-1},d7',
               f'\tbhi.s {dispatch}u', f'\tmove.l ({dispatch}t,pc,d7.w*4),d7',
               f'\tjmp ({dispatch}t,pc,d7.l)',
               f'{dispatch}t:'] + [f'\tdc.l {t}-{dispatch}t' for t in resumes] + [f'{dispatch}u:']
        return out + [f'\tmove.l #{ip},d7', '\tjmp rt_stop_unknown']
    out = [f'{dispatch}:']
    for k, target in enumerate(resumes):
        out += ['\tsubq.l #1,d7', f'\tbne.s {dispatch}{k}', f'\tjmp {target}', f'{dispatch}{k}:']
    return out + [f'\tmove.l #{ip},d7', '\tjmp rt_stop_unknown']
