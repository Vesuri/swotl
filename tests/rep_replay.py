"""Exact original REP decoder slices, used only by diagnostic replay builds."""
import csv
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translator import cfg, emit, gen

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('module', 'offset', 'service', 'hits', 'cx', 'si', 'di',
          'end_cx', 'end_si', 'end_di', 'restart')


@dataclass(frozen=True)
class Chunk:
    label: str
    service: int
    hits: int
    start: tuple
    end: tuple
    restart: bool


def read(trace, required=False):
    path = trace / 'rep.csv'
    if not path.exists():
        if required:
            raise ValueError('required REP metadata is missing')
        return []
    result = []
    with path.open() as f:
        rows = csv.DictReader(f)
        if tuple(rows.fieldnames or ()) != FIELDS:
            raise ValueError('REP metadata schema differs')
        for r in rows:
            values = [int(r[k], 0) for k in FIELDS[1:]]
            off, service, hits, cx, si, di, end_cx, end_si, end_di, restart = values
            if min(values) < 0 or max(values[3:9]) > 65535 or restart not in (0, 1):
                raise ValueError(f'invalid REP metadata: {r}')
            if end_cx > cx or restart and not 0 < end_cx < cx:
                raise ValueError(f'invalid REP progress: {r}')
            result.append(Chunk(emit.label(r['module'], off), service, hits,
                                (cx, si, di), (end_cx, end_si, end_di), bool(restart)))
    if required and not result:
        raise ValueError('required REP metadata is empty')
    return result


def compact(chunks):
    """Lossless runs of adjacent identical slice steps; boundaries stay exact."""
    groups = []
    for c in chunks:
        if groups:
            a, n = groups[-1]
            delta = tuple((y - x) & 65535 for x, y in zip(a.start, a.end))
            expected = tuple((x + n * d) & 65535 for x, d in zip(a.start, delta))
            if (a.restart and c.restart and n < 65535 and a.label == c.label and
                    a.service == c.service and a.hits + n == c.hits and
                    c.start == expected and
                    tuple((y - x) & 65535 for x, y in zip(c.start, c.end)) == delta):
                groups[-1] = (a, n + 1)
                continue
        groups.append((c, 1))
    return groups


class Replay:
    def __init__(self, chunks):
        self.chunks = chunks
        self.labels = sorted({c.label for c in chunks})
        self.index = 0
        self.active = False

    def checkpoint(self, point, registers, service, visits, done):
        if self.index == len(self.chunks):
            raise ValueError('unrecorded REP execution')
        c = self.chunks[self.index]
        if not 0 <= point < len(self.labels) or self.labels[point] != c.label:
            raise ValueError(f'REP point differs at slice {self.index}')
        if service != c.service or visits != c.hits + 1:
            raise ValueError(f'REP epoch/visit differs at slice {self.index}: '
                             f'{service}/{visits} != {c.service}/{c.hits + 1}')
        if not self.active:
            if registers != c.start:
                raise ValueError(f'REP entry differs at slice {self.index}: {registers} != {c.start}')
            self.active = True
        if done or c.restart and registers[0] == c.end[0]:
            if registers != c.end or bool(done) == c.restart:
                raise ValueError(f'REP end differs at slice {self.index}: {registers} != {c.end}')
            self.index += 1
            self.active = False
            return c.restart
        if registers[0] < c.end[0]:
            raise ValueError(f'REP passed recorded endpoint at slice {self.index}')
        return False

    def complete(self):
        if self.active or self.index != len(self.chunks):
            raise ValueError(f'REP slices incomplete: {self.index}/{len(self.chunks)}')


def host_image(labels, joystick_header=None):
    """Link generated diagnostic REP lowering with the unchanged host runtime."""
    objects = [ROOT / 'build/host' / (p.stem + '.o') for p in sorted((ROOT / 'src/runtime').glob('*.c'))]
    objects += [ROOT / 'build/host' / n for n in ('host_s.o', 'host.o', 'rt_entry.o')]
    tail_objects = [ROOT / 'build/host' / n for n in ('compute_projection.o', 'compute_divide.o', 'compute_normalise.o', 'compute_scenery.o')]
    inputs = [Path(__file__)] + sorted((ROOT / 'translator').glob('*.py')) + sorted((ROOT / 'build/gen').glob('*.s')) + objects + tail_objects
    digest = hashlib.sha256(('\n'.join(labels)).encode())
    if joystick_header is not None:
        digest.update(joystick_header.encode())
        digest.update((ROOT / 'tests/joystick_replay.c').read_bytes())
    for p in inputs:
        digest.update(p.name.encode()); digest.update(p.read_bytes())
    out = ROOT / 'tmp/rep-host' / digest.hexdigest()[:20]
    elf = out / 'swotl.elf'
    if elf.exists():
        return elf
    units = cfg.build()
    nodes = {emit.label(mod, off): (mod, off) for mod, u in units.items() for off in u.insns}
    hooks = {nodes[lab]: n for n, lab in enumerate(labels)}
    for node in hooks:
        if not units[node[0]].insns[node[1]].rep:
            raise ValueError(f'REP metadata names a non-REP instruction: {node}')
    program = emit.Program(units, diagnostic_reps=hooks)
    if not set(hooks) <= program.loop_heads:
        raise ValueError('REP metadata outside the original poll set')
    gen.generate(out / 'gen', program=program)
    vasm = str(os.environ.get('VASM') or Path.home() / '.local/vasmm68k_mot')
    subprocess.run([vasm, '-quiet', '-m68020', '-Felf', '-x', '-nowarn=62',
                    '-o', str(out / 'program.o'), 'program.s'], cwd=out / 'gen', check=True)
    # The host hook supplies the result in the argument slot; no guest work here.
    (out / 'rep.s').write_text(' section .text,code\n xdef rt_replay_rep\nrt_replay_rep:\n rts\n')
    subprocess.run([vasm, '-quiet', '-m68020', '-Felf', '-o', str(out / 'rep.o'),
                    str(out / 'rep.s')], check=True)
    toolchain = Path(os.environ.get('AMIGA_TOOLCHAIN') or Path.home() / '.local/opt')
    extra = []
    if joystick_header is not None:
        (out / 'joystick_data.h').write_text(joystick_header)
        # The host records software-service epochs; this value is set at wrapper entry.
        (out / 'joystick_host.c').write_text(
            '#include "runtime.h"\nvolatile uint32_t replay_services;\n'
            '#include "joystick_replay.c"\n')
        subprocess.run([str(toolchain / 'bin/m68k-amiga-elf-gcc'), '-m68020', '-msoft-float',
                        '-O2', '-ffreestanding', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(ROOT / 'src/runtime'), '-I' + str(ROOT / 'tests'), '-I' + str(out),
                        '-c', str(out / 'joystick_host.c'), '-o', str(out / 'joystick.o')], check=True)
        extra = [str(out / 'joystick.o'), '--wrap=rt_port_in', '--wrap=rt_port_out']
    subprocess.run([str(toolchain / 'bin/m68k-amiga-elf-ld'), '-Ttext=0x10000', '-e', '_start',
                    '-o', str(elf), *(str(p) for p in objects), str(out / 'program.o'), *(str(p) for p in tail_objects), str(out / 'rep.o'), *extra], check=True)
    return elf
