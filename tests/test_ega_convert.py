"""RTSEGA view converters as device rows (docs/ecs-plan.md E6, docs/native-compute.md
"Device rows"): src/runtime/compute_ega.s against the original x86 with the
Python EGA model (tools/ega_model.py, tools/compute_oracle.py `device`).

Entries: DOSBox snapshots at the routines' entries (tools/native_entries.py
EGA-4AC3 RTSEGA.OVL+4AC3 1 --fixtures ega-m5-player-flight,ega-m7-campaign;
EGA-4BD0 RTSEGA.OVL+4BD0 1,2,8 --fixtures ega-m4-demo-frames,ega-m5-player-flight:
RAM, registers, planes, EGA registers and latches), plus mutations of each
boundary the native distinguishes (every word differing, a destination row
crossing a page-0 row, page 1, odd word counts, row parity, DF set, earlier
D9 marks, other register values) and admission cases that must decline
unchanged. Compared at the original RETF (RC5): registers, live flags with DF,
all RAM (the stored bytes in EGA memory included) and its EGA write addresses,
the planes, every EGA register and latch, and the D9 marks."""
from pathlib import Path
import argparse
import os
import random
import struct
import sys
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
import m68k_blocks as B
from tools import compute_oracle as O
from tools import ega_model as E
from translator import emit
from translator.support import equates
from translator.ir import FLAGS, FLAG_BIT

MODULE = 'RTSEGA.OVL'
ROWS = {'ega_convert_all': (0x4ac3, 0x4bcf, 'EGA-4AC3'),
        'ega_convert_changed': (0x4bd0, 0x4cfe, 'EGA-4BD0')}
EGA_AT = 0x01000000             # runtime data of the native's image (mapped here)
SYMS = {'rt_ega_planes': EGA_AT, 'rt_ega_regs': EGA_AT + 0x100, 'rt_vram_rows': EGA_AT + 0x200,
        'rt_vram_top': EGA_AT + 0x600, 'rt_vram_bottom': EGA_AT + 0x602,
        'rt_vdrv_depth': EGA_AT + 0x604, 'smc_seg_limit': EGA_AT + 0x606}
PLANES_AT = EGA_AT + 0x1000
PLANTS = {
    'mask-parity': ('\tsubq.w #1,d3\t\t; even k: the high byte of CS:32E6[m]', ''),
    'latch-3': ('\tmove.b L_OLD3(a7),EGA_LATCH+3(a1)', '\tmove.b ($30000,a0),EGA_LATCH+3(a1)'),
    'stored-byte': ('\tmove.b d6,(a4,d1.w)\t; the stored byte at ES:DI', ''),
    'mark-bottom': ('\tmove.w d7,rt_vram_bottom\n', '\n'),
    'mark-column': ('\tsub.w #80,d6\n', '\n'),
    'compare': ('\tcmp.w -(a1),d1\n\tbne .diff', '\tcmp.w -(a1),d1\n\tbra .diff'),
    'final-mode': ('\tmove.b #2,EGA_MODE(a1)', '\tmove.b #0,EGA_MODE(a1)'),
    'cs-parity': ('\tmove.w L_PARB(a7),(-$34e6-1,a2)', '\tmove.w L_PARA(a7),(-$34e6-1,a2)'),
    'push-es': ('\tmove.w L_SHSEG(a7),-1(a0,d6.w)', ''),
    'row-bx': ('\tmove.w d2,L_BX(a7)\n', '\n'),
    'cld': ('\tclr.b G_DF(a6)\t\t\t; cld', ''),
    'depth': ('\ttst.w rt_vdrv_depth\n\tbeq .decline', ''),
    'overlap': ('\tbcs .decline\n.apart:', '\tnop\n.apart:'),
    'row-parity': ('\tbtst #0,L_R+1(a7)', '\tbtst #1,L_R+1(a7)'),
}


class ConvertMismatch(AssertionError):
    pass


def entries(tag):
    paths = sorted((ROOT / 'tmp/pc-runs').glob(f'native-{tag}-*/trace/snap-entry*'))
    assert paths, f'{tag}: record the entries (tools/native_entries.py, module docstring)'
    for path in paths:
        ram, regs = O.load_entry(path)
        yield f'{path.parent.parent.name[len("native-" + tag) + 1:]}/{path.name}', ram, regs, \
            E.Ega.from_snapshot(path)


def w16(ram, a):
    return ram[a] | ram[a + 1] << 8


def put16(ram, a, v):
    ram[a], ram[a + 1] = v & 0xff, v >> 8 & 0xff


class Case:
    """A converter entry: guest RAM and registers, the model, the runtime's marks
and driver depth."""

    def __init__(self, name, ram, regs, ega, depth=1, marks=None):
        self.name, self.ram, self.regs, self.ega = name, bytearray(ram), dict(regs), ega
        self.captured = ram.captured_bytes
        self.depth = depth
        if marks:
            ega.rows, ega.top, ega.bottom = marks

    def mutated(self, name, **change):
        c = Case(f'{self.name}+{name}', O.CapturedRAM(bytes(self.ram), self.captured), self.regs,
                 E.Ega(self.ega.planes_image(), **dict(self.ega.r, latch=bytes(self.ega.latch))),
                 self.depth, ([list(r) for r in self.ega.rows], self.ega.top, self.ega.bottom))
        for k, v in change.items():
            setattr(c, k, v)
        return c

    def guest(self):
        return O.CapturedRAM(bytes(self.ram), self.captured)

    def ds(self, off):
        return self.regs['ds'] * 16 + off

    def arg(self, k):   # 4BD0's far pointers: [bp+6] source, [bp+0Ah] shadow (bp = SP - 2)
        return self.regs['ss'] * 16 + self.regs['sp'] + 4 + 2 * k

    def source(self, changed):
        if changed:
            return w16(self.ram, self.arg(1)) * 16 + w16(self.ram, self.arg(0))
        return w16(self.ram, self.ds(0x2579)) * 16 + w16(self.ram, self.ds(0x257b))

    def shadow(self):
        return w16(self.ram, self.arg(3)) * 16 + w16(self.ram, self.arg(2))


def mutations(service, base, rng):
    """(case, declines) from one recorded entry."""
    changed = service == 'ega_convert_changed'
    rows, words = w16(base.ram, base.ds(0x2591)), w16(base.ram, base.ds(0x258b))
    out = []

    def with_ram(name, edit, **change):
        c = base.mutated(name, **change)
        edit(c)
        out.append((c, False))

    def ds_word(off, v):
        return lambda c: put16(c.ram, c.ds(off), v)

    def everything_differs(c):
        h = c.shadow()
        for a in range(h, h + rows * words * 2):
            c.ram[a] ^= 0xa5

    if changed:
        with_ram('all-differ', everything_differs)
        with_ram('all-differ-x-wrap', lambda c: (everything_differs(c), put16(c.ram, c.ds(0x257f), 0x0f30)))
        with_ram('all-differ-page1', lambda c: (everything_differs(c), put16(c.ram, c.ds(0x287c), 0xa400)))
        with_ram('all-differ-odd-rows', lambda c: (everything_differs(c), put16(c.ram, c.ds(0x2591), rows - 1)))
        with_ram('all-differ-odd-words', lambda c: (everything_differs(c), put16(c.ram, c.ds(0x258b), words - 1)))
        with_ram('last-word-differs', lambda c: c.ram.__setitem__(c.shadow() + rows * words * 2 - 1,
                                                                    c.ram[c.shadow() + rows * words * 2 - 1] ^ 1))
        with_ram('first-word-differs', lambda c: c.ram.__setitem__(c.shadow(), c.ram[c.shadow()] ^ 0x10))
        with_ram('df', lambda c: None, regs=dict(base.regs, flags=base.regs['flags'] | 0x400))
        with_ram('none-differ', lambda c: c.ram.__setitem__(slice(c.shadow(), c.shadow() + rows * words * 2),
                                                             c.ram[c.source(True):c.source(True) + rows * words * 2]))
    else:
        with_ram('x-wrap', ds_word(0x257f, 0x30))
        with_ram('odd-words', ds_word(0x258b, words - 1))
        with_ram('one-row', ds_word(0x2591, 1))
        with_ram('page0', ds_word(0x287c, 0xa000))
    marks = ([[0, 0] for _ in range(200)], 200, 0)
    for y in rng.sample(range(200), 40):
        lo = rng.randrange(80)
        marks[0][y] = [lo, rng.randrange(lo + 1, 81)]
    with_ram('marks', lambda c: None)
    out[-1][0].ega.rows, out[-1][0].ega.top, out[-1][0].ega.bottom = marks[0], 3, 180
    regs = dict(base.ega.r, bit_mask=rng.randrange(256), read_map=rng.randrange(4), map_mask=rng.randrange(16),
                mode=rng.randrange(3), latch=bytes(rng.randrange(256) for _ in range(4)))
    c = base.mutated('registers')
    c.ega = E.Ega(base.ega.planes_image(), **regs)
    out.append((c, False))
    # admission: these decline unchanged
    cs = base.regs['cs']
    declines = [('depth0', None, dict(depth=0)), ('rows0', ds_word(0x2591, 0), {}),
                ('words0', ds_word(0x258b, 0), {}), ('words81', ds_word(0x258b, 81), {}),
                ('page-low', ds_word(0x287c, 0x0100), {}), ('page-outside', ds_word(0x287c, 0x9000), {}),
                ('page-end', ds_word(0x287c, 0xaf00), {}), ('dest-wrap', ds_word(0x257f, 0xff00), {}),
                ('mask-table', ds_word(0x2591, 0x1f04 // max(1, words // 2) + 1), {}),
                ('sp-low', None, dict(regs=dict(base.regs, sp=10))),
                ('ds-low', None, dict(regs=dict(base.regs, ds=0x0100)))]
    if changed:
        declines += [('source-low', lambda c: put16(c.ram, c.arg(1), 0x0100), {}),
                     ('shadow-low', lambda c: put16(c.ram, c.arg(3), 0x0100), {}),
                     ('source-wrap', lambda c: put16(c.ram, c.arg(0), 0xf000), {}),
                     ('source-on-cs-vars', lambda c: (put16(c.ram, c.arg(1), cs), put16(c.ram, c.arg(0), 0x3000)), {}),
                     ('shadow-on-stack', lambda c: (put16(c.ram, c.arg(3), c.regs['ss']),
                                                    put16(c.ram, c.arg(2), c.regs['sp'] - 0x100)), {}),
                     ('source-in-window', lambda c: put16(c.ram, c.arg(1), 0xa800), {})]
    else:
        declines += [('source-low', ds_word(0x2579, 0x0100), {}), ('source-wrap', ds_word(0x257b, 0xf000), {}),
                     ('source-on-cs-vars', lambda c: (put16(c.ram, c.ds(0x2579), cs), put16(c.ram, c.ds(0x257b), 0x3000)), {}),
                     ('source-in-window', ds_word(0x2579, 0xa800), {})]
    for name, edit, change in declines:
        c = base.mutated(name, **change)
        if edit:
            edit(c)
        out.append((c, True))
    rotate = base.mutated('rotate')
    rotate.ega.r['data_rotate'] = 0x08
    esr = base.mutated('set-reset')
    esr.ega.r['enable_set_reset'] = 0x01
    out += [(rotate, True), (esr, True)]
    return out


def cases(service, rng):
    first, _, tag = ROWS[service]
    for name, ram, regs, ega in entries(tag):
        base = Case(name, ram, regs, ega)
        yield base, False
        if name.endswith('entry0'):
            yield from mutations(service, base, rng)


@lru_cache(maxsize=1)
def program():
    return emit.Program()


def live(service):
    return program().live_in[MODULE, ROWS[service][1]]


@lru_cache(maxsize=None)
def native_image(service, plant=None):
    source = (ROOT / 'src/runtime/compute_ega.s').read_text()
    if plant:
        old, new = PLANTS[plant]
        assert source.count(old) == 1, plant
        source = source.replace(old, new)
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('\txref '))
    text = [equates()] + [f'{n}\tequ\t${a:x}' for n, a in SYMS.items()] + [
        f'\torg ${B.SNIP:x}', '\tdc.l done', '\tmoveq #0,d7', f'\tjsr rt_hle_{service}', '\tbra done',
        'done:', '\tnop', source]
    work = ROOT / f'tmp/ega-convert-{os.getpid()}'
    work.mkdir(exist_ok=True)
    return B.D.assemble('\n'.join(text), work / f'{service}-{plant}.bin')


def runtime_image(case):
    rows = b''.join(struct.pack('>HH', lo, hi) for lo, hi in case.ega.rows)
    return rows, struct.pack('>HHHH', case.ega.top, case.ega.bottom, case.depth, program().smc_limit)


def native_run(binary, case):
    regs = case.regs
    m = B.D.M68k(case.guest(), B.STUB_AT)
    try:
        m.e.map(EGA_AT, 0x42000)
        m.e.write(SYMS['rt_ega_planes'], PLANES_AT.to_bytes(4, 'big'))
        m.e.write(PLANES_AT, case.ega.planes_image())
        m.e.write(SYMS['rt_ega_regs'], case.ega.regs_image())
        rows, scalars = runtime_image(case)
        m.e.write(SYMS['rt_vram_rows'], rows)
        m.e.write(SYMS['rt_vram_top'], scalars)
        m.e.write(B.SNIP, binary)
        m.extra_stops = {int.from_bytes(binary[:4], 'big'): 'done'}
        O.watch_native(m)
        flags = {f: regs['flags'] >> FLAG_BIT[f] & 1 for f in FLAGS}
        got, fl, fx, mem, outs, writes, info = m.run(B.SNIP + 4, (regs, flags, regs['flags'] & 0xf000, regs['ip'], []),
                                                    random.Random(43), irq=False,
                                                    init={'d6': regs['cs']})
        if info['err'] or outs or info['irq'] or info['stop'] != 'done' or info['a7'] != B.D.STACK - 0x100:
            raise ConvertMismatch(('native run', case.name, info))
        top, bottom = struct.unpack('>HH', m.e.read(SYMS['rt_vram_top'], 4))
        marks = (tuple(struct.unpack('>HH', m.e.read(SYMS['rt_vram_rows'] + 4 * y, 4)) for y in range(200)),
                 top, bottom)
        ega = dict(planes=bytes(m.e.read(PLANES_AT, 4 * E.WINDOW)),
                   regs=bytes(m.e.read(SYMS['rt_ega_regs'], E.REGS_BYTES)), marks=marks)
        state = dict(registers=got, flags=fx | sum(fl[f] << FLAG_BIT[f] for f in FLAGS), writes=writes,
                     ram=m.gread(0, B.X.RAM), ega=ega)
        return state, m.r('d7')
    finally:
        B.U.uc.uc_close(m.e.h)


def entry_state(case):
    regs = dict(case.regs)
    return dict(registers=regs, flags=regs['flags'], writes=set(), ram=bytes(case.ram),
                ega=O.ega_state(case.ega))


def check(service, case, decline, expected, plant=None):
    """The native (with `plant`) against `expected` (None: decline unchanged)."""
    first, resume, _ = ROWS[service]
    cs = case.regs['cs']
    actual, result = native_run(native_image(service, plant), case)
    if decline:
        expected = entry_state(case)
        expected['registers'] = {r: v for r, v in case.regs.items() if r != 'flags'}
        actual['registers'] = dict(actual['registers'], cs=cs, ip=case.regs['ip'])
        errors = ([] if result == 0 else ['handled']) + O.compare(dict(expected, undefined=[]), actual, set(FLAGS))
        if actual['writes']:
            errors.append('wrote guest RAM')
        if errors:
            raise ConvertMismatch((case.name, 'decline', errors))
        return
    if result != 1:
        raise ConvertMismatch((case.name, 'declined'))
    actual['registers'] = dict(actual['registers'], cs=cs, ip=resume - 0x20)
    errors = O.compare(expected, actual, live(service))
    if errors:
        raise ConvertMismatch((case.name, errors))


def oracle(service, case):
    """The original x86 with the Python model, from a copy of the case's model."""
    first, resume, _ = ROWS[service]
    if case.regs['ip'] != first - 0x20:
        raise ConvertMismatch((case.name, 'not at the entry', hex(case.regs['ip'])))
    device = E.Ega(case.ega.planes_image(), **dict(case.ega.r, latch=bytes(case.ega.latch)))
    device.attr, device.overscan = case.ega.attr, case.ega.overscan
    device.rows, device.top, device.bottom = [list(r) for r in case.ega.rows], case.ega.top, case.ega.bottom
    return O.run(case.guest(), case.regs, (case.regs['cs'], resume - 0x20), limit=3_000_000, device=device)


def run_all(plants=(), only=None, verbose=False):
    """Every case against the native; with `plants`, each planted native too (one
oracle run per case). Returns the case count and {plant: first mismatch}."""
    total, caught = 0, {}
    for service in ROWS:
        rng = random.Random(f'{service}-e6')
        for case, decline in cases(service, rng):
            if only and only not in case.name:
                continue
            expected = None if decline else oracle(service, case)
            check(service, case, decline, expected)
            for plant in plants:
                if plant not in caught:
                    try:
                        check(service, case, decline, expected, plant)
                    except ConvertMismatch as error:
                        caught[plant] = error
            total += 1
            if verbose:
                print(f'  {case.name}: {"declined" if decline else "handled"}, {len(caught)} plants caught',
                      flush=True)
    return total, caught


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    ap.add_argument('--only', help='cases whose name contains this')
    ap.add_argument('-v', action='store_true', help='one line per case')
    args = ap.parse_args()
    total, caught = run_all(PLANTS if args.sabotage else (), args.only, args.v)
    print('ega convert:', total, 'cases pass', flush=True)
    for plant in PLANTS if args.sabotage else ():
        if plant not in caught:
            raise AssertionError(plant + ' escaped')
        print('caught', plant, str(caught[plant])[:160], flush=True)
