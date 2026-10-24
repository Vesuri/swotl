#!/usr/bin/env python3
"""Run the WHDLoad slave in FS-UAE in an isolated tmp/whdload-test-* fixture.

    python3 tools/test_whdload.py --mode smoke     # Smoke.slave: harness only
    python3 tools/test_whdload.py --mode boot      # BootTest.slave: Kickstart 3.1 kickemu boots
    python3 tools/test_whdload.py --mode load      # LoadTest.slave: LoadSeg + PROGDIR
    python3 tools/test_whdload.py --mode run [--tfh] [--slave build/whdload/MemFree.slave]
    python3 tools/test_whdload.py --mode run --installed DIR [--setup a1200-040]

`run` starts the game under the release slave; WHDLoad TIMEOUT (needs the moved
VBR of a 68020) ends it with COREDUMP and the dump is judged:
  - the reason is the timeout ("DEBUG caused" at the CIA-A event count), not a fault;
  - the game is running: most 64-byte blocks of the original SWOTL.EXE and
    RTSVGA.OVL lie in guest RAM, which holds guest bytes in reverse order
    (overlays come and go; relocated and patched blocks differ);
  - Custom1 (--tfh): the TFH sfx.rsc PCM payload is in Chip RAM; without it,
    no sample block is. Their copy in Chip is what the TFH path makes.
The MemFree slave's low-water marks (Chip, Fast) are read from its $100 slot.
--installed runs an installed Swotl drawer as it is (slave, data/Swotl, data).
--setup a1200-040: full 68040 with its MMU and FPU, JIT off, on $FSUAE_MMU;
the report must show TC=8000 (translation on; AmigaXDev whdload-mmu.md).

Inputs are local, never shipped: Kickstart 3.1 A1200 + RTB, WHDLoad, the
Workbench floppy, the original game files (ref/) and TFH sfx.rsc (TFH_RSC).
Source amiga/env.sh first. The emulator is the one this script started; it is
stopped by its own PID only.
"""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
AMIGA = Path.home() / '.local/share/amiga'
KICKSTARTS = AMIGA / 'Kickstarts'
WHDLOAD = Path(os.environ.get('WHDLOAD', AMIGA / 'WHDLoad')) / 'C/WHDLoad'
WORKBENCH = Path(os.environ.get('WORKBENCH_ADF', AMIGA / 'Workbenchv2.04rev37.67Workbench.adf'))
KICK31 = Path(os.environ.get('KICKSTART_A1200', KICKSTARTS / 'kick40068.A1200'))
TFH_RSC = Path(os.environ.get('TFH_RSC', ROOT / 'tmp/tfh/TheirFinestHour&Missions/data/sfx.rsc'))
SLAVES = {'smoke': 'Smoke.slave', 'boot': 'BootTest.slave', 'load': 'LoadTest.slave', 'run': 'Swotl.slave'}


def rsc_pcm(rsc):
    """The TFH sample payloads (resources 1001+1000+k), as tfh_paula.c reads them."""
    be16 = lambda o: int.from_bytes(rsc[o:o + 2], 'big')
    be32 = lambda o: int.from_bytes(rsc[o:o + 4], 'big')
    d = be32(0)
    entries = {be16(d + 6 + 6 * k): be32(d + 8 + 6 * k) for k in range(be16(d + 4))}
    out = []
    for ident, off in sorted(entries.items()):
        if 2001 <= ident < 3000:
            out.append(rsc[off + 4:off + 4 + (be16(off) & ~1)])
    assert out, 'no TFH sample resources in sfx.rsc'
    return out


def blocks(data, size=256):
    return [data[a:a + size] for a in range(0, len(data) - size + 1, size)
            if len(set(data[a:a + size])) > 8]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mode', choices=tuple(SLAVES), default='run')
    p.add_argument('--tfh', action='store_true', help='set Custom1 (Their Finest Hour sound)')
    p.add_argument('--slave', type=Path, help='slave override (default: build/whdload/ per mode)')
    p.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/Swotl-release.exe',
                   help='stripped (make amiga-release): LoadSeg reads symbol hunks in small pieces')
    p.add_argument('--data', type=Path, default=ROOT / 'ref')
    p.add_argument('--installed', type=Path, help='installed Swotl drawer, used unchanged')
    p.add_argument('--setup', choices=('a1200', 'a1200-040'), default='a1200')
    p.add_argument('--rom', type=Path, default=KICK31)
    p.add_argument('--fast', type=int, default=8192, help='host Fast RAM in KiB')
    p.add_argument('--cpu', default='68020')
    p.add_argument('--ticks', type=int, default=3000, help='WHDLoad TIMEOUT in PAL fields (run)')
    p.add_argument('--no-preload', action='store_true')
    p.add_argument('--seconds', type=int, default=600, help='host safety ceiling')
    args = p.parse_args()
    if args.installed:
        assert args.mode == 'run' and not args.slave, '--installed runs its own slave'
        args.data = args.installed / 'data'
    mmu = args.setup == 'a1200-040'
    if mmu:
        args.cpu = '68040'

    (ROOT / 'tmp').mkdir(exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix='whdload-test-', dir=ROOT / 'tmp'))
    print('Fixture:', base, flush=True)
    boot, game = base / 'boot', base / 'game'
    data = game / 'data'
    if args.installed:
        shutil.copytree(args.installed, game)
    for d in (boot / 's', boot / 'devs/Kickstarts', data, base / 'state'):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WHDLOAD, game / 'WHDLoad')
    if not args.installed:
        shutil.copyfile(args.slave or ROOT / 'build/whdload' / SLAVES[args.mode], game / 'Swotl.slave')
    if args.mode != 'smoke':
        shutil.copyfile(args.rom, boot / 'devs/Kickstarts' / args.rom.name)
        shutil.copyfile(args.rom.with_name(args.rom.name + '.RTB'), boot / 'devs/Kickstarts' / (args.rom.name + '.RTB'))
    if args.mode in ('load', 'run') and not args.installed:
        shutil.copyfile(args.exe, data / 'Swotl')
    if args.mode == 'run' and not args.installed:
        shutil.copytree(args.data, data, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.pdf'))
        shutil.copyfile(TFH_RSC, data / 'sfx.rsc')
    options = ['SPLASHDELAY=0', 'NOREQ']
    if not args.no_preload:
        options.append('PRELOAD')
    if args.mode == 'run':
        options += ['COREDUMP', f'TIMEOUT={args.ticks}']
        if args.tfh:
            options.append('CUSTOM1=1')
    command = 'WHDLoad Swotl.slave ' + ' '.join(options)
    print('Command:', command, flush=True)
    (boot / 's/WHDLoad.prefs').write_text('Expert\nReadDelay=0\n')
    (boot / 's/startup-sequence').write_text(
        'DF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nStack 16384\nFailAt 999\n'
        f'CD DH1:\n{command} >DH0:result\n'
        'If WARN\nEcho failed >DH0:failed\nElse\nEcho passed >DH0:passed\nEndIf\n')

    fsuae = os.environ.get('FSUAE_MMU' if mmu else 'FSUAE', 'fs-uae')
    cpu = ['--uae_mmu_model=68040', '--uae_fpu_model=68040', '--uae_cpu_24bit_addressing=false'] if mmu else []
    with (base / 'emulator.log').open('w') as log:
        emu = subprocess.Popen([fsuae, '--amiga_model=A1200', '--cpu=' + args.cpu,
            '--uae_cpu_model=' + args.cpu, *cpu, '--jit_compiler=0',
            '--chip_memory=2048', '--fast_memory=' + str(args.fast),
            '--kickstart_file=' + str(KICK31),
            '--hard_drive_0=' + str(boot), '--hard_drive_0_priority=10', '--hard_drive_1=' + str(game),
            '--floppy_drive_0=' + str(WORKBENCH), '--audio_driver=dummy',
            '--joystick_port_0=mouse', '--joystick_port_1=nothing', '--warp_mode=1', '--fullscreen=0',
            '--automatic_input_grab=0', '--window_width=720', '--window_height=568',
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')],
            stdout=log, stderr=log, env=dict(os.environ, SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline and not any((boot / n).exists() for n in ('passed', 'failed')):
                if emu.poll() is not None:
                    raise SystemExit(f'FAIL: FS-UAE exited unexpectedly ({base})')
                time.sleep(.25)
            time.sleep(1)
        finally:
            emu.terminate()
            try:
                emu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emu.kill()
                emu.wait()

    output = (boot / 'result').read_text(errors='replace') if (boot / 'result').exists() else ''
    report = (game / '.whdl_register').read_text(encoding='latin1') if (game / '.whdl_register').exists() else ''
    if not any((boot / n).exists() for n in ('passed', 'failed')):
        raise SystemExit(f'FAIL: WHDLoad did not return within {args.seconds} s ({base})\n{output}')
    if args.mode != 'run':
        if not (boot / 'passed').exists():
            raise SystemExit(f'FAIL: {args.mode} ({base})\n{report[:2000]}{output}')
        if args.mode == 'smoke':
            assert (game / 'smoke-passed').read_bytes() == b'PASS'
        print(f'PASS: {args.mode} slave returned normally')
        return

    if not report:
        raise SystemExit(f'FAIL: no WHDLoad core dump ({base})\n{output}')
    first = next((l for l in report.splitlines() if l.strip()), '')
    print('WHDLoad:', first.strip())
    chip = (game / '.whdl_memory').read_bytes()
    exp = (game / '.whdl_expmem').read_bytes() if (game / '.whdl_expmem').exists() else b''
    # TIMEOUT reports as "DEBUG caused" once the CIA-A TOD event count passes it.
    event = re.search(r'event=([0-9A-F]+)', report)
    if 'DEBUG caused' not in report or not event or int(event[1], 16) < args.ticks:
        raise SystemExit('FAIL: the run did not end by TIMEOUT\n' + report[:2000])
    if mmu and 'TC=8000' not in report:
        raise SystemExit('FAIL: 68040 MMU translation was not enabled (no TC=8000)\n' + report[:2000])
    memory = chip + exp
    resident = True
    for name in ('SWOTL.EXE', 'RTSVGA.OVL'):
        image = blocks((args.data / name).read_bytes(), 64)
        found = sum(1 for b in image if b[::-1] in memory)
        print(f'{name} in guest RAM: {found} of {len(image)} blocks')
        resident &= found >= len(image) // 2
    pcm = [b for s in rsc_pcm(TFH_RSC.read_bytes()) for b in blocks(s)]
    in_chip = sum(1 for b in pcm if b in chip)
    print(f'TFH samples in Chip: {in_chip} of {len(pcm)} blocks')
    if args.slave and args.slave.name == 'MemFree.slave':
        print('MemFree low water: Chip {:,} Fast {:,} bytes'.format(
            int.from_bytes(chip[0x100:0x104], 'big'), int.from_bytes(chip[0x104:0x108], 'big')))
    if not resident:
        raise SystemExit('FAIL: the game is not resident in guest RAM')
    if args.tfh and in_chip != len(pcm):
        raise SystemExit('FAIL: Custom1 set but the TFH samples are not in Chip')
    if not args.tfh and in_chip:
        raise SystemExit('FAIL: TFH samples in Chip without Custom1')
    print('PASS: game runs under WHDLoad, sound ' + ('TFH' if args.tfh else 'FM')
          + (', 68040 MMU on' if mmu else ''))


if __name__ == '__main__':
    main()
