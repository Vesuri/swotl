"""Controls for stopping before a CFG exit that aliases a zero-code jump."""
from types import SimpleNamespace
import sys
import m68k_blocks as B


def check(boundary):
    mod = 'SWOTL.EXE'
    nodes = [(mod, n) for n in range(1, 6)]
    p = SimpleNamespace(succ={n: [] for n in nodes}, fall={})
    p.succ[nodes[2]] = [nodes[3]]
    p.fall[nodes[0]], p.fall[nodes[1]] = nodes[1], nodes[2]
    for copy in (False, True):
        suffix = '_bp' if copy else ''
        addr = {B.emit.label(*n)+suffix: a for n, a in zip(nodes, (100, 102, 104, 104, 110))}
        empty = {B.emit.label(*nodes[2])+suffix}
        inside, is_empty = boundary(p, mod, [1, 2, 3], addr, 110, empty, copy)
        assert inside == {102} and not is_empty, (inside, is_empty)
        inside, is_empty = boundary(p, mod, [3], addr, 110, empty, copy)
        assert not inside and is_empty
        # A real self-loop must execute on entry, then stop on its back edge.
        p.succ[nodes[2]] = [nodes[2]]
        inside, is_empty = boundary(p, mod, [3], addr, 110, set(), copy)
        assert not inside and not is_empty
        p.succ[nodes[2]] = [nodes[3]]
    lines = ['R_00001:', 'R_00002:', '\tbra R_00001',
             'R_00003:', '\t; comment', 'R_00004:', '\tmove.w d0,d1']
    assert B.empty_guest_entries(lines) == {'R_00001', 'R_00003'}
    assert B.empty_guest_entries(['R_00001: move.w d0,d1', 'R_00002:', '\trts']) == set()
    assert B.empty_guest_entries(['R_00001:', '  nop', 'R_00002:', '\trts']) == set()
    return 9


def main():
    print(f'block boundaries: {check(B.block_boundary)} controls pass')
    if '--sabotage' in sys.argv:
        def broken(p, mod, run, addr, end, empties, copy=False):
            lab = B.emit.copy_label if copy else B.emit.label
            return {addr[lab(mod, o)] for o in run[1:]} - {end}, end == addr[lab(mod, run[0])]
        try:
            check(broken)
        except AssertionError:
            print('block boundaries: old alias-boundary fault caught')
        else:
            raise AssertionError('boundary fault escaped')


if __name__ == '__main__':
    main()
