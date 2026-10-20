"""Admission and emission for opt-in compute HLE rows.

This defines an interface, not any native implementation. The reachable graph,
including callees, proves admission; annotation claims are not a proof.
"""
from .lower import LowerError


def forbidden(p, n):
    i = p.node_insn(n)
    return (n in p.loop_heads or n in p.diagnostic_hooks or i.rep is not None or
            n[1] in p.units[n[0]].manager_calls or
            i.op in {'in', 'out', 'int', 'int3', 'into', 'iret', 'hlt',
                     'cli', 'sti', 'popf'} or
            (i.op in {'mov', 'pop'} and i.operands and
             getattr(i.operands[0], 'name', None) == 'ss'))


def validate(p, first, resume):
    """Prove a single-return, acyclic, poll-free compute region, transitively.

Unknown transfers and exceptional edges cannot silently disappear. The initial
contract rejects control/device effects; a later contract needs approval for
those. Interior entries still execute generated code normally.
    """
    end = p.node_insn(resume)
    if first == resume or end is None or end.op not in {'ret', 'retf'}:
        raise LowerError('compute: resume must be the original RET/RETF')
    seen, active, body = set(), set(), set()

    def walk(n, callee=False):
        if not callee and n == resume:
            return
        if not isinstance(n, tuple) or n not in p.succ or p.node_insn(n) is None:
            raise LowerError(f'compute: unresolved flow {n}')
        if not callee and (n[0] != first[0] or not first[1] <= n[1] < resume[1]):
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
            if not callee:
                raise LowerError(f'compute: return bypasses resume at {n}')
            body.add(n)
            return
        active.add(key)
        body.add(n)
        succ = p.succ[n]
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
    return body


def hook(service, resume, cs):
    # All guest registers/state are the generated-code ABI. d7 is a result,
    # not a guest register: zero declines without changing any guest state.
    return [f'\tmove.l #{cs},d6', f'\tjsr {service}', '\ttst.l d7', f'\tbne {resume}']
