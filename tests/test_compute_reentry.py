"""Native continuations re-enter BP copies only through their current guard."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from translator import emit, region
import m68k_diff as D
import uc as U
emit.Program.polled_rows = True  # the exact/U5-poll rows, dormant in the game until I9 (irq-plan I8)

NODE = ('SWOTL.EXE', 0x10a53)
PREDECESSORS = {
    'direct': [], 'jump': ['bra entry'],
    'call': ['bsr entry', 'illegal'],
    'taken': ['cmp.w d0,d0', 'beq entry', 'illegal'],
    'fall': ['cmp.w d0,d0', 'bne finished'],
    'indirect': ['lea entry,a0', 'jmp (a0)'],
    'return': ['pea entry', 'rts'],
}


class ReentryMismatch(AssertionError):
    pass


def predecessor_cases():
    try:
        return guards(), []
    except ReentryMismatch as error:
        return 1, [str(error)]


def guards():
    count = 0
    directory = ROOT / 'tmp/compute-reentry'
    directory.mkdir(exist_ok=True)
    for rng in ((-32760,32039), (-32768,123), (-123,32767), (-32768,32767)):
        p = SimpleNamespace(comps=[(set(),set(),{NODE},rng)])
        cold = []
        target = emit.Program.compute_resume(p, NODE, 'resume_guard', cold)
        assert target == 'resume_guard', 'native continuation bypasses re-entry guard'
        empty = []
        assert emit.Program.compute_resume(p, ('SWOTL.EXE',0), 'unused', empty) == emit.label('SWOTL.EXE',0)
        assert not empty, 'unrelated continuation changed'
        for predecessor, prefix in PREDECESSORS.items():
            # Both destinations stop before any guest instruction. This tests
            # current d5, independently of whatever the native entry had.
            source = [f'\torg ${D.CODE:x}', '\tdc.l start,finished', 'start:']
            source += ['\t'+line for line in prefix] + ['entry:', '\tbra '+target]
            source += [line.replace('.?', '.l') for line in cold]
            source += [emit.label(*NODE)+':', '\tmoveq #0,d7', '\tbra finished',
                       emit.copy_label(*NODE)+':', '\tmoveq #1,d7', 'finished:', '\tnop']
            binary = D.assemble('\n'.join(source),directory/'guard.bin')
            start, end = (int.from_bytes(binary[i:i+4],'big') for i in (0,4))
            e = U.Engine(U.ARCH_M68K,U.MODE_BIG_ENDIAN,U.CPU_M68K_M68020)
            try:
                e.map(D.CODE,0x2000); e.write(D.CODE,binary)
                e.map(D.STACK,0x2000)
                sentinel = bytes(range(256))
                e.write(D.STACK,sentinel)
                values = {-32768,32767,0,rng[0],rng[1]}
                values |= {v for v in (rng[0]-1,rng[1]+1) if -32768<=v<=32767}
                for value in sorted(values):
                    for upper in (0,0xffff,0xa35c):
                        for i in range(8):
                            e.reg_write(U.M68K[f'd{i}'],0x12340000+i)
                            e.reg_write(U.M68K[f'a{i}'],D.STACK+0x1000+i*4)
                        d5 = upper<<16 | (value&65535)
                        e.reg_write(U.M68K['d5'],d5)
                        assert not e.start(start,end,100), 'guard execution failed'
                        expected = int(rng[0]<=value<=rng[1])
                        if e.reg_read(U.M68K['d7']) != expected:
                            raise ReentryMismatch(('guard outcome',rng,value,predecessor))
                        assert e.reg_read(U.M68K['d5']) == d5
                        for i in (0,1,2,3,4,6):
                            assert e.reg_read(U.M68K[f'd{i}']) == 0x12340000+i
                        for i in range(1,7):
                            assert e.reg_read(U.M68K[f'a{i}']) == D.STACK+0x1000+i*4
                        assert e.read(D.STACK,256)==sentinel
                        count += 1
            finally:
                U.uc.uc_close(e.h)
    return count


def emission():
    p = emit.Program()
    root = ('SWOTL.EXE',0x10a2f)
    assert NODE in p.polled_resumes[root]
    lines, _ = p.module_text(root[0])
    for entry in (emit.label(*root),emit.copy_label(*root)):
        tag = entry+'_cr0'
        dispatch = lines.index(entry+'_cx:')
        assert '\tjmp '+tag in lines[dispatch:dispatch+5], 'native dispatch bypasses guard'
        guard_at = lines.index(tag+':')
        body = lines[guard_at+1:guard_at+6]
        assert sum('cmp.w' in line for line in body)==2
        assert sum(emit.label(*NODE) in line and '_bp' not in line for line in body)==2
        assert any(emit.copy_label(*NODE) in line for line in body)
    # Re-entry reaches the existing poll, never its no-poll alias; an IRQ
    # still leaves the copy because its handler may have changed BP again.
    for lab in (emit.label(*NODE),emit.copy_label(*NODE)):
        at = next(i for i,line in enumerate(lines) if line.startswith(lab+':'))
        assert lines[at+1:at+1+len(emit.poll(lab))] == emit.poll(lab)
    irq = lines.index(emit.copy_label(*NODE)+'_irq:')
    assert '\tbra '+emit.label(*NODE)+'_np' in lines[irq:irq+20]
    return 5


if __name__ == '__main__':
    print('compute re-entry guards:',guards(),'cases pass',flush=True)
    print('compute re-entry emission:',emission(),'controls pass',flush=True)
    if '--sabotage' in sys.argv:
        with patch.object(region,'guard',return_value=[]):
            try: guards()
            except AssertionError as error:
                assert 'guard outcome' in str(error), error
                print('compute re-entry: missing guard caught',flush=True)
            else: raise AssertionError('missing guard escaped')

        with patch.object(emit.Program,'compute_resume',
                          lambda self,node,tag,cold:emit.label(*node)):
            try: emission()
            except AssertionError as error:
                assert 'dispatch bypasses guard' in str(error), error
                print('compute re-entry: bypassed routing caught',flush=True)
            else: raise AssertionError('bypassed routing escaped')
