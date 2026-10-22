#!/usr/bin/env python3
"""Build/run a separate diagnostic Amiga image against existing DOSBox traces.

The normal image and its wall-clock hardware gates remain mandatory. Generated
hooks, event arrays and snapshots stay in tmp/. No reference is re-recorded.
"""
import argparse
import json
import os
import signal
import socket
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import host_run as H
import rep_replay
import joystick_replay
from translator import cfg, emit, gen
from translator.lower import LOADSEG

ROOT = H.REPO


def prepare(name, out, trace=None):
    script = H.milestone_script(name)
    trace = trace or ROOT / f'tmp/pc-runs/ref-{name}/trace'
    irqs, releases = H.reference_inputs(trace)
    reps = rep_replay.read(trace, required=script["rep_chunks"])
    joystick = joystick_replay.read(trace / 'joystick.csv', required=script['joystick'])
    if joystick and not script['joystick']:
        raise ValueError('undeclared joystick recording')
    summary = dict(x.split('=', 1) for x in (trace / 'summary.txt').read_text().split())
    assert int(summary['polls'], 16) == H.fnv(H.POLLS.read_bytes()), 'reference poll points differ'
    services = H.reference_services(trace)
    points = sorted({t[0] for t, _ in script['keys']} |
                    {t[0] for t in script['snapshots']} | {lab for _, lab, _, _ in irqs} | {c.label for c in reps})
    ids = {lab: i for i, lab in enumerate(points)}
    units = cfg.build()
    nodes = {emit.label(mod, off): (mod, off) for mod, u in units.items() for off in u.insns}
    hooks = {nodes[lab]: ids[lab] for lab in points}
    rep_hooks = {nodes[c.label]: ids[c.label] for c in reps}
    program = emit.Program(units, diagnostic_hooks=hooks, diagnostic_reps=rep_hooks)
    assert all(nodes[lab] in program.loop_heads for _, lab, _, _ in irqs)
    out.mkdir(parents=True, exist_ok=True)
    gen.generate(out / 'gen', program=program)
    hashes, digest = [], 2166136261
    for kind, r in services:
        values = [r[n] for n in H.REGS + ('es', 'ss', 'ds', 'vector')]
        values += [r['flags'] & 0x600, int(kind == 'svc_ret')]
        for byte in struct.pack('>' + 'H' * len(values), *values):
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        hashes.append(digest)
    steps = []
    release = iter(releases)
    for (lab, _, hits), key in script['keys']:
        if isinstance(key, str):
            kind, value, end = (5 if key.startswith('j') else {'x': 2, 'y': 3, 'b': 4}[key[1]]), int(key[2:]), 0
        else:
            base = key & 0xffff
            kind, value, end = (1, base >> 8 | (0x100 if base in H.GREY else 0) |
                                ((key >> 7) & 0xe00), next(release))
        steps.append((ids[lab], hits, kind, value, end))
    assert next(release, None) is None
    steps += [(ids[lab], hits, 0, 0, 0) for lab, _, hits in script['snapshots']]
    locations = []
    for lab in points:
        mod, off = nodes[lab]
        locations.append((LOADSEG + units[mod].cs[off], units[mod].ip_of(off)))
    def array(ctype, name, rows):
        return f'static const {ctype} {name}[] = {{\n' + ''.join(
            '{' + ','.join(map(str, row)) + '},\n' for row in rows) + '};\n'
    text = ('/* Generated from the existing original reference; local only. */\n'
            'struct replay_point_info { uint32_t cs, ip; };\n'
            'struct replay_irq { uint32_t service, point, hits, vector; };\n'
            'struct replay_step { uint32_t point, hits, kind; int32_t value; uint32_t release; };\n'
            f'#define REPLAY_POINTS {len(points)}u\n#define REPLAY_IRQS {len(irqs)}u\n'
            f'#define REPLAY_SERVICES {len(services)}u\n#define REPLAY_STEPS {len(steps)}u\n')
    text += ('struct replay_rep { uint32_t service, hits; uint16_t point, cx, si, di, end_cx, end_si, end_di, restart, repeat; };\n'
             f'#define REPLAY_REPS {len(reps)}u\n')
    text += array('struct replay_rep', 'replay_reps',
                  [(c.service, c.hits, ids[c.label], *c.start, *c.end, int(c.restart), n)
                   for c, n in rep_replay.compact(reps)])
    text += array('struct replay_point_info', 'replay_points', locations)
    text += array('struct replay_irq', 'replay_irqs', [(s, ids[l], h, v) for s, l, h, v in irqs])
    text += array('struct replay_step', 'replay_script', steps)
    text += 'static const uint32_t replay_service_hashes[] = {\n' + ','.join(map(str, hashes)) + '};\n'
    if joystick:
        text += '#define REPLAY_JOYSTICK 1\n'
        (out / 'joystick_data.h').write_text(joystick_replay.c_header(joystick))
    else:
        (out / 'joystick_data.h').unlink(missing_ok=True)
    (out / 'replay_data.h').write_text(text)
    calendar, clock = H.reference_clocks(trace)
    stamp = H.dos_file_stamp(clock) if clock is not None else (0, 0)
    (out / 'replay_clocks.h').write_text(
        '/* Recorded external calendar inputs, diagnostic build only. */\n'
        f'#define REPLAY_CALENDAR_DATE {calendar or 0}u\n'
        f'#define REPLAY_FILE_TIME {stamp[0]}u\n'
        f'#define REPLAY_FILE_DATE {stamp[1]}u\n')
    (out / 'expected.json').write_text(json.dumps(dict(services=len(services), interrupts=len(irqs), steps=len(steps))))
    print(f'{name}: {len(points)} diagnostic points, {len(irqs)} interrupts, {len(services)} service events', flush=True)


def build(out):
    work = out / 'amiga'
    work.mkdir(exist_ok=True)
    makefile = work / 'Makefile'
    if not makefile.exists():
        makefile.symlink_to(ROOT / 'amiga/Makefile')
    subprocess.run(['make', '-s', '-C', str(work), f'REPO={os.path.relpath(ROOT, work)}',
                    'GEN=../gen', 'REPLAY=..'], check=True)


def fresh_run_directory(out):
    # debug.sh copies the original data but deliberately does not delete game
    # writes. A replay must not inherit files from an earlier failed attempt.
    return Path(tempfile.mkdtemp(prefix='run-', dir=out))


def run(name, out, trace=None):
    capture = out / 'capture'
    capture.mkdir(exist_ok=True)
    template = (ROOT / 'amiga/milestone.gdb.in').read_text()
    template = template.replace('@LABEL@', 'rt_replay_done').replace('@OUT@', os.path.relpath(capture, ROOT / 'amiga'))
    expected = json.loads((out / 'expected.json').read_text())
    check = '\n'.join(f'if replay_{key} != {value}\n  printf "SWOTL_REPLAY_INCOMPLETE\\n"\n  quit 1\nend'
                      for key, value in expected.items())
    template = template.replace('set $bm = &amiga_bitmap', check + '\nset $bm = &amiga_bitmap')
    template = template.replace('    printf "SWOTL_MILESTONE_WRONG_HANDOFF',
        '    printf "SWOTL_REPLAY_HANDOFF expected=%u actual=%u late=%u line=%u fields=%u d0=%u sp=%x queued=%u count=%u\\n", $serial, *(unsigned int *)($sp+4), amiga_display_late, amiga_display_line, amiga_frames, $d0, $sp, $display->queuedSerial, amiga_display_count\n'
        '    printf "SWOTL_MILESTONE_WRONG_HANDOFF')
    (capture / 'fixture.gdb').write_text(template)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED='1',
               AMIGA_CPU=os.environ.get('AMIGA_CPU', '68030'),
               SWOTL_ELF=str(out / 'amiga/out/Swotl.elf'), FSUAE_RUN=os.path.relpath(fresh_run_directory(out), ROOT / 'amiga'), FSUAE_CLAIM_STRICT='1', SWOTL_ARGS='')
    with (capture / 'gdb.log').open('w') as log:
        command = [str(ROOT / 'amiga/debug.sh'), '', str(capture / 'fixture.gdb'),
                   str(out / 'amiga/out/Swotl.exe')]
        process = subprocess.Popen(command, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            result = process.wait(timeout=2400)
        except BaseException:
            # Only the process group created above belongs to this capture.
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        if result:
            raise subprocess.CalledProcessError(result, command)
    lines = (capture / 'gdb.log').read_text().splitlines()
    assert 'SWOTL_MILESTONE_OK' in lines, lines[-20:]
    regs = [line.removeprefix('SWOTL_REGS ') for line in lines if line.startswith('SWOTL_REGS ')]
    assert len(regs) == 1
    (capture / 'regs.txt').write_text(regs[0])
    problems = H.check(name, 2400, capture, None, trace=trace)
    assert not problems, '\n'.join(problems)
    print(f'Amiga diagnostic replay {name}: state, shown pixels and service history match DOSBox', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--milestone', required=True)
    args = ap.parse_args()
    out = ROOT / 'tmp/amiga-replay' / args.milestone
    prepare(args.milestone, out)
    build(out)
    run(args.milestone, out)
