#!/usr/bin/env python3
"""Diagnostic assembly hook ABI: real 68020 execution and a planted loss."""
import argparse
from pathlib import Path
import random
import struct
import tempfile

import m68k_diff as D
import uc as U
from translator import emit

ROOT = Path(__file__).resolve().parents[1]


def check(body, broken=False):
    # Link the actual diagnostic wrapper with hostile C-ABI caller-clobbers.
    body = '\n'.join(line for line in body.splitlines()
                     if not line.strip().startswith(('xref ', 'xdef ', 'section ')))
    stubs = '''
replay_point:
 move.l #$12345678,d1
 movea.l #$87654321,a0
 movea.l #$76543210,a1
 moveq #0,d0
 rts
replay_rep:
replay_enter:
replay_return:
 move.l #$12345678,d0
 move.l #$23456789,d1
 movea.l #$34567890,a0
 movea.l #$45678901,a1
 rts
replay_next:
 moveq #0,d0
 rts
rt_irq:
 rts
replay_cs: dc.l 0
replay_ip: dc.l 0
'''
    rng = random.Random(14)
    with tempfile.TemporaryDirectory(prefix='swotl-replay-abi-') as tmp:
        for hook in ('rt_replay_point', 'rt_replay_enter', 'rt_replay_return', 'rt_replay_rep'):
            source = ' org $10000\n pea 7.w\n jsr ' + hook + '\n lea 4(sp),sp\n jmp $20000\n' + body + stubs
            code = D.assemble(source, Path(tmp) / 'hook.bin')
            for ccr in (0, 1, 4, 15, 31):
                e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
                e.map(0, 0x40000)
                e.write(0x10000, code)
                regs = {n: rng.getrandbits(32) for n in
                        ['d' + str(i) for i in range(8)] + ['a' + str(i) for i in range(7)]}
                e.reg_write(U.M68K['sr'], 0x2700 | ccr)
                for n, v in regs.items():
                    e.reg_write(U.M68K[n], v)
                e.reg_write(U.M68K['a7'], 0x3f000)
                err = e.start(0x10000, 0x20000, timeout_us=1_000_000)
                actual = {n: e.reg_read(U.M68K[n]) for n in regs}
                passed = not err and actual == regs and e.reg_read(U.M68K['a7']) == 0x3f000 \
                    and e.reg_read(U.M68K['sr']) & 31 == ccr
                if broken:
                    if not passed:
                        print('replay hook: planted register loss caught')
                        return
                else:
                    assert passed, (hook, err, regs, actual, ccr, e.reg_read(U.M68K['sr']))
    assert not broken, 'replay register-loss plant survived'
    print('replay hooks: all guest registers, scratch registers, stack and CCR preserved')


def check_terminal(body, broken=False):
    body = '\n'.join(line for line in body.splitlines()
                     if not line.strip().startswith(('xref ', 'xdef ', 'section ')))
    source = (' org $10000\n pea 7.w\n jsr rt_replay_point\n lea 4(sp),sp\n'
              ' moveq #99,d0\n jmp $20000\n' + body +
              '\nreplay_point: moveq #-1,d0\n rts\n'
              'replay_rep:\nreplay_enter:\nreplay_return:\nreplay_next:\nrt_irq: rts\n'
              'replay_cs: dc.l 0\nreplay_ip: dc.l 0\n')
    with tempfile.TemporaryDirectory(prefix='swotl-replay-end-') as tmp:
        code = D.assemble(source, Path(tmp) / 'end.bin')
    e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
    e.map(0, 0x40000)
    e.write(0x10000, code)
    regs = {n: 0x12340000 + k for k, n in enumerate(
            ['d' + str(i) for i in range(8)] + ['a' + str(i) for i in range(7)])}
    for n, v in regs.items():
        e.reg_write(U.M68K[n], v)
    e.reg_write(U.M68K['sr'], 0x271f)
    e.reg_write(U.M68K['a7'], 0x3f000)
    assert not e.start(0x10000, 0x20000, count=500)
    pc = e.reg_read(U.M68K['pc'])
    passed = pc != 0x20000 and all(e.reg_read(U.M68K[n]) == v for n, v in regs.items()) \
        and e.reg_read(U.M68K['a7']) == 0x3eff8 and e.reg_read(U.M68K['sr']) == 0x271f
    if passed:
        assert not e.start(pc, 0x20000, count=100)
        passed = e.reg_read(U.M68K['pc']) == pc
    assert passed != broken, (pc, broken)
    print('replay terminal: planted guest advance caught' if broken else
          'replay terminal: final guest state held for display handoff')


def check_copy(hook, target, body, broken=False):
    body = '\n'.join(line for line in body.splitlines()
                     if not line.strip().startswith(('xref ', 'xdef ', 'section ')))
    if broken:
        hook = hook.replace('bne ', 'beq ')
    for posted in (0, 1):
        source = (' org $10000\n' + hook + '\n jmp $20000\n' + target + ':\n jmp $20004\n' + body +
                  f'\nreplay_point: moveq #{posted},d0\n rts\n'
                  'replay_rep:\nreplay_enter:\nreplay_return:\nreplay_next: moveq #0,d0\n rts\n'
                  'rt_irq: move.l #$1234,d5\n rts\nreplay_cs: dc.l 0\nreplay_ip: dc.l 0\n')
        with tempfile.TemporaryDirectory(prefix='swotl-replay-copy-') as tmp:
            code = D.assemble(source, Path(tmp) / 'copy.bin')
        e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(0, 0x40000)
        e.write(0x10000, code)
        e.reg_write(U.M68K['sr'], 0x2700)
        e.reg_write(U.M68K['a7'], 0x3f000)
        e.reg_write(U.M68K['d5'], 0x5678)
        stops = []
        @U.CODE_CB
        def stop(_h, address, _size, _user):
            stops.append(address)
            e.stop()
        e.hook_range(U.HOOK_CODE, stop, 0x20000, 0x20004)
        assert not e.start(0x10000, 0x30000, timeout_us=1_000_000)
        passed = stops == [0x20004 if posted else 0x20000] and \
            e.reg_read(U.M68K['d5']) == (0x1234 if posted else 0x5678)
        assert passed != broken, (posted, stops, broken)
    print('replay copy: planted wrong continuation caught' if broken else
          'replay copy: interrupt changing BP resumes exact code; no IRQ stays in copy')


def check_generation(body, sabotage):
    normal = emit.Program()
    # A recorded key/snapshot trigger in the middle of a production block.
    node = ('SWOTL.EXE', 0x44e2)
    assert node not in normal.leaders
    diagnostic = emit.Program(normal.units, diagnostic_hooks={node: 7})
    assert diagnostic.loop_heads == normal.loop_heads
    assert node in diagnostic.leaders
    lines, _ = diagnostic.module_text(node[0])
    label = emit.label(*node)
    hooks = 0
    for k, line in enumerate(lines):
        if line.startswith((label + ':', label + '_bp:')):
            assert lines[k + 1:k + 4] == ['\tpea 7.w', '\tjsr rt_replay_point', '\tlea 4(sp),sp']
            hooks += 1
    assert hooks >= 1
    normal_lines, _ = normal.module_text(node[0])
    assert not any('rt_replay_point' in line for line in normal_lines)
    print(f'replay generation: {hooks} entries hooked, original poll points unchanged, normal output has no hooks')
    copied = set().union(*(nodes for _, _, nodes, _ in normal.comps))
    node = sorted(copied & normal.loop_heads)[0]
    diagnostic = emit.Program(normal.units, diagnostic_hooks={node: 7})
    lines, _ = diagnostic.module_text(node[0])
    copy, target = emit.copy_label(*node), emit.label(*node) + '_np'
    k = next(k for k, line in enumerate(lines) if line.startswith(copy + ':'))
    hook = lines[k + 1:k + 5]
    assert hook == ['\tpea 7.w', '\tjsr rt_replay_point', '\ttst.l (sp)+', f'\tbne {target}']
    check_copy('\n'.join(hook), target, body)
    if sabotage:
        check_copy('\n'.join(hook), target, body, True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    body = (ROOT / 'tests/amiga_replay.s').read_text()
    check_generation(body, args.sabotage)
    check(body)
    check_terminal(body)
    if args.sabotage:
        check_terminal(body.replace("bra.s rt_replay_done", "rts"), True)
        check(body.replace('movem.l (sp)+,d0-d7/a0-a6',
                           'movem.l (sp)+,d0-d7/a0-a6\n moveq #0,d1'), True)
