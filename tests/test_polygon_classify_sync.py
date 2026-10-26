"""Original x86 at the classifier's first root loop head versus the generated code.

RC5: a native may continue at a root loop head (a resume after the return),
so the generated code must arrive there in the original's state; an equal final
result alone would not show that.
"""
import random
import tempfile
from pathlib import Path

from test_polygon_classify import B, O, ROOT, boundaries, program, STUB_AT
from translator import compute, emit
from translator.ir import FLAGS, FLAG_BIT
from translator.support import equates


def run(broken=False):
    p = program()[0]
    node = ('SWOTL.EXE', 0xbb70)
    row = p.compute_bodies[node]
    resumes = p.compute_resumes[node]
    assert resumes == [*row.returns, *row.loops]
    unit = p.units[node[0]]
    cache = ROOT / 'tmp/polygon-classify-sync'
    cache.mkdir(exist_ok=True)
    binary, addresses = program()[4:6]
    callback = 'rt_hle_polygon_classify:\n\tmoveq #'+str(int(broken))+',d7\n\trts\n'
    count = 0
    with tempfile.TemporaryDirectory(prefix='handoff-', dir=cache) as scratch:
        for name, ram, regs in list(boundaries())[:11]:
            stops = {(regs['cs'], unit.ip_of(n[1])): n for n in resumes}
            expected = O.run(ram, regs, (regs['cs'], unit.ip_of(row.returns[0][1])),
                             returns=stops)
            destination = stops[expected['at']]
            source = [equates(), f'\torg ${B.SNIP:x}',
                      f'rt_stop_unknown equ ${B.STUB_AT["rt_stop_unknown"]:x}']
            source += compute.hook('rt_hle_polygon_classify', 'handled', '$cbd')
            source += [f'\tjmp ${addresses[emit.label(*node)]:x}']
            source += compute.resume_dispatch('handled',
                [f'${addresses[emit.label(*n)]:x}' for n in resumes], '$71c0')
            source += [callback]
            code = B.D.assemble('\n'.join(source), Path(scratch) / 'callback.bin')
            m = B.D.M68k(ram, STUB_AT, {p.hle[n][1] for n in p.compute_rows})
            try:
                m.load(binary)
                m.e.write(B.SNIP, code)
                O.watch_native(m)
                m.extra_stops = {addresses[emit.label(*n)]: str(n) for n in resumes}
                flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
                got, fl, fx, mem, outs, writes, info = m.run(B.SNIP,
                    (regs, flags, regs['flags'] & 0xf000, regs['ip'], []),
                    random.Random(39), irq=False)
                assert not info['err'] and not outs and not info['irq'], info
                assert info['stop'] == str(destination), (name, 'wrong loop-head resume',
                                                          info['stop'], destination)
                got.update(cs=expected['at'][0], ip=expected['at'][1])
                actual = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS),
                              writes=writes, ram=m.gread(0, B.X.RAM))
                errors = O.compare(expected, actual, p.live_in[destination], O.code_addresses(p, B.LOADSEG))
                assert not errors, (name, errors)
                count += 1
            finally:
                B.U.uc.uc_close(m.e.h)
    return count


if __name__ == '__main__':
    print('classifier sync handoffs:', run(), 'pass', flush=True)
