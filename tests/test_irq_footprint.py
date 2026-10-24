"""IRQ0 footprint proof (docs/irq-plan.md I2, translator/irq.py).

The proof holds on the program, matches build/gen/irq-footprint.csv and keeps
the facts the later steps rest on (handler-written game variables, ports, the
813C readers as sync accesses). --sabotage (plants only): each plant edits one decoded
instruction (or the compute rows) and must fail the proof with its message."""
from pathlib import Path
import argparse
import dataclasses
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from translator import emit, irq

SPAZ = 'SPAZ.OVL'
# G spans the handler writes (irq-plan Facts): song counters, tick, timer slots, dword
WRITTEN_G = {(0x6564, 0x658a), (0x813c, 0x813d), (0x9bca, 0x9bcb), (0x9c44, 0x9ca9),
             (0x9d32, 0x9d33), (0x9d34, 0x9d35)}
TICK_READERS = [('FLIGHT.OVL', 0x122a), ('FLIGHT.OVL', 0x123b), ('SWOTL.EXE', 0x0180),
                ('SWOTL.EXE', 0x3682), ('SWOTL.EXE', 0x3f94)]


def edit(prog, node, **change):
    u = prog.units[node[0]]
    i = u.insns[node[1]]
    u.insns[node[1]] = dataclasses.replace(i, **change)


def operand(prog, node, k, **change):
    i = prog.node_insn(node)
    ops = list(i.operands)
    ops[k] = dataclasses.replace(ops[k], **change)
    edit(prog, node, operands=tuple(ops))


def handler_main_variable(prog):
    # inc word es:[9BCA] -> es:[9DC0], a dword main code steps with add/adc
    operand(prog, (SPAZ, 0x0804), 0, disp=0x9dc0)
    return None, 'G:9DC0..9DC1 in 2 68k memory accesses'


def split_rmw(prog):
    # mov word ds:[813C],0 -> adc word ds:[813C],0 (load, add, store)
    edit(prog, ('SWOTL.EXE', 0x403b), op='adc')
    return None, 'SWOTL.EXE+0403B: adc word ds:[0x813c], 0x0 meets handler-written G:813C..813D'


def unsaved_register(prog):
    # push bx -> push cx: bx is popped from a slot that never held it
    operand(prog, (SPAZ, 0x07cd), 0, name='cx')
    return None, 'bx'


def undeclared_port(prog):
    # EOI out 20h -> out 21h
    operand(prog, (SPAZ, 0x0a80), 0, value=0x21)
    return None, 'port'


def compute_row_tick(prog):
    # a compute row over FLIGHT's tick reset (mov word ds:[813C],0)
    return {('FLIGHT.OVL', 0x1224)}, 'compute row FLIGHT.OVL+01224 contains sync access FLIGHT.OVL+01224'


def slot_bound(prog):
    # mov byte ds:[9C20],2Ah -> 40h: the handler would count past 9CA9
    operand(prog, ('SWOTL.EXE', 0x10be5), 1, value=0x40)
    return None, 'SWOTL.EXE+10BE5: mov byte ds:[0x9c20], 0x40 writes G:9C20 outside'


PLANTS = {'handler-main-variable': handler_main_variable, 'split-rmw': split_rmw,
          'unsaved-register': unsaved_register, 'undeclared-port': undeclared_port,
          'compute-row-tick': compute_row_tick, 'slot-bound': slot_bound}


def check(proof):
    proof.raise_errors()
    written = {(lo, hi) for (cls, lo, hi, kind) in proof.fp.mem if cls == 'G' and kind == 'w'}
    assert written == WRITTEN_G, sorted(written)
    ports = {p for p, _ in proof.fp.ports}
    assert ports == {0x20, 0x388, 0x389}, ports
    assert proof.paras['G'] == 0x43cd, proof.paras
    sync = {(n, cls, lo) for n, cls, lo, *_ in proof.sync}
    for n in TICK_READERS:
        assert (n, 'G', 0x813c) in sync, n
    csv = ROOT / 'build/gen/irq-footprint.csv'
    if csv.exists():
        want = csv.read_text().splitlines()[1:]
        assert proof.rows() == want, 'build/gen/irq-footprint.csv is stale: run make gen'
    return len(proof.sync)


def plant(name):
    prog = emit.Program()
    rows, expect = PLANTS[name](prog)
    try:
        irq.Proof(prog, compute_rows=rows).raise_errors()
    except irq.Violation as error:
        if expect not in str(error):
            raise AssertionError(f'{name}: caught without {expect!r}: {str(error)[:400]}')
        return str(error).splitlines()[1][:160]
    raise AssertionError(f'{name} escaped')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    if args.sabotage:
        for name in PLANTS:
            print('caught', name, plant(name), flush=True)
    else:
        proof = irq.Proof(emit.Program())
        print('irq footprint:', check(proof), 'sync accesses;', proof.summary())
