"""Near poll trampolines preserve the exact native tail-handoff ABI."""
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import m68k_blocks as B
from translator import emit
from translator.ir import FLAGS
from translator.support import equates


def run(diagnostic=False, plant=None):
    root = ('SWOTL.EXE', 0x100)
    lab = emit.label(*root)
    program = SimpleNamespace(exact_rows={root}, hle={root: (root, 'probe')},
                              compute_bodies={root: SimpleNamespace(sync=(root,))},
                              diagnostic_hooks={root: 1} if diagnostic else {})
    macros = emit.Program.native_poll_text(program)
    assert 'probe_poll_0_local macro' in macros, 'missing local poll macro'
    if plant == 'missing':
        macros = macros.replace('bne.s \\1', 'nop').replace('bra.s \\1', 'nop')
    source = equates() + f'\nrt_irq equ ${B.STUB_AT["rt_irq"]:x}\n' + macros
    source += f'''
 org ${B.SNIP:x}
 dc.l done,{lab}_native_poll,{lab}_native_np
start:
 jsr native
 cmp.l #2,d7
 beq start
 bra done
pending:
 probe_poll_0_tail
native:
 bra body
again:
 probe_poll_0_local pending
body:
 addq.w #1,d0
 subq.w #1,d1
 bne again
 moveq #1,d7
 rts
done:
 nop
'''
    source += '\n'.join(emit.native_poll_stub(lab, 0x5678, '$1234', 2))
    if plant == 'stack':
        source = source.replace('pending:\n', 'pending:\n move.l d0,-(sp)\n')
    with tempfile.TemporaryDirectory(prefix='native-local-poll-') as directory:
        binary = B.D.assemble(source, Path(directory) / 'probe.bin')
    done, poll, after = (int.from_bytes(binary[i:i+4], 'big') for i in (0, 4, 8))
    assert after - poll == (2 if diagnostic else 6), 'poll branch not short'
    m = B.D.M68k(bytes(B.X.RAM), B.STUB_AT)
    m.irq_calls = []
    visits, errors = [], []

    @B.U.CODE_CB
    def hook(h, address, size, user):
        if address == poll:
            visits.append((m.r('d0') & 65535, m.r('d1') & 65535))
            if m.r('a7') != B.D.STACK - 0x104:
                errors.append('poll stack')
            if not diagnostic and len(visits) == 1:
                m.e.write(B.D.STATE + 8, b'\1')
                m.e.write(B.D.PENDING, b'\1')
        if address == B.STUB_AT['rt_irq']:
            if m.r('a7') != B.D.STACK - 0x108:
                errors.append('handoff stack')
                B.U.uc.uc_emu_stop(h)
            if not diagnostic:
                m.e.reg_write(B.U.M68K['d0'], 100)
                m.e.reg_write(B.U.M68K['d1'], 2)

    regs = dict(ax=0, bx=23, cx=4, dx=31, si=45, di=67, sp=0xec00,
                bp=0xf000, ds=0x5000, es=0x6000, ss=0x7000)
    flags = {k: int(k == 'IF') for k in FLAGS}
    try:
        m.e.write(B.SNIP, binary)
        m.extra_stops = {done: 'done'}
        m.e.hook(B.U.HOOK_CODE, hook)
        got, fl, fx, mem, outs, writes, info = m.run(
            B.SNIP + 12, (regs, flags, 0x7000, 0, []), random.Random(42), irq=False)
        assert not errors, errors
        assert not info['err'] and info['stop'] == 'done', info
        assert visits == ([(1, 3), (2, 2), (3, 1)] if diagnostic else
                          [(1, 3), (101, 1)]), visits
        assert got['ax'] == (4 if diagnostic else 102) and got['cx'] == 0, got
        assert all(got[k] == v for k, v in regs.items() if k not in ('ax', 'cx')), got
        assert len(m.irq_calls) == (3 if diagnostic else 1), m.irq_calls
        assert m.r('a7') == B.D.STACK - 0x100, 'final stack'
        assert not outs and not writes, (outs, writes)
    finally:
        B.U.uc.uc_close(m.e.h)


if __name__ == '__main__':
    for diagnostic in (False, True):
        run(diagnostic)
    print('local native polls: normal and diagnostic handoffs pass', flush=True)
    if '--sabotage' in sys.argv:
        for plant in ('missing', 'stack'):
            try:
                run(plant=plant)
            except AssertionError as error:
                print('caught', plant, str(error), flush=True)
            else:
                raise AssertionError('plant escaped: ' + plant)
