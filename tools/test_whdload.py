#!/usr/bin/env python3
"""Run the WHDLoad slave in FS-UAE in an isolated tmp/whdload-test-* fixture.

    python3 tools/test_whdload.py --mode smoke     # Smoke.slave: harness only
    python3 tools/test_whdload.py --mode boot      # BootTest.slave: Kickstart 3.1 kickemu boots
    python3 tools/test_whdload.py --mode load      # LoadTest.slave: LoadSeg + PROGDIR
    python3 tools/test_whdload.py --mode run [--tfh] [--slave build/whdload/MemFree.slave]
    python3 tools/test_whdload.py --mode run --installed DIR [--setup a1200-040]
    python3 tools/test_whdload.py --mode run --setup a1200-030 [--whdload-mmu]
    python3 tools/test_whdload.py --mode run --slave build/whdload/CampaignTest.slave --ticks 15000
    (also TourTest.slave: game files written through kickfs)

`run` starts the game under the release slave; WHDLoad TIMEOUT (needs the moved
VBR of a 68020) ends it with COREDUMP and the dump is judged:
  - the reason is the timeout ("DEBUG caused" at the CIA-A event count), not a fault;
  - the game is running: most 64-byte blocks of the original SWOTL.EXE and
    RTSVGA.OVL lie in guest RAM, which holds guest bytes in reverse order
    (overlays come and go; relocated and patched blocks differ);
  - Custom1 (--tfh): the TFH sfx.rsc PCM payload is in Chip RAM; without it,
    no sample block is. Their copy in Chip is what the TFH path makes.
The MemFree slave's low-water marks (Chip, Fast) are read from its $100 slot.
--installed runs an installed SWotL drawer as it is (slave, data/SWotL, data).
--setup a1200-040: full 68040 with its MMU and FPU, JIT off, on $FSUAE_MMU;
the report must show TC=8000 (translation on; AmigaXDev whdload-mmu.md).
--setup a1200-030: full 68030 with its MMU on $FSUAE_MMU; WHDLoad uses the MMU
only with its MMU option (--whdload-mmu). --setup a1200-060: as the 68040, TC=8000 too.
These setups emulate the data cache.
The dump's CACR must match the slave's cache policy (docs/whdload.md, Caches):
data cache on where WHDLoad uses the MMU (68040/060, 68030 with MMU), otherwise the
instruction cache alone.

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
# Test slaves whose key script writes game files through kickfs: the new
# files and their sizes, as in DOSBox (c10, c11; A.USA byte-identical).
WRITES = {'CampaignTest.slave': ['A.CBA 11183'], 'TourTest.slave': ['A.USA 540']}
SLAVES = {'smoke': 'Smoke.slave', 'boot': 'BootTest.slave', 'load': 'LoadTest.slave', 'run': 'SWotL.slave'}


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
    p.add_argument('--installed', type=Path, help='installed SWotL drawer, used unchanged')
    p.add_argument('--setup', choices=('a1200', 'a1200-030', 'a1200-040', 'a1200-060'), default='a1200')
    p.add_argument('--whdload-mmu', action='store_true', help="WHDLoad's MMU option (68030)")
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
    mmu = args.setup != 'a1200'
    if mmu:
        args.cpu = '68' + args.setup[-3:]
    assert not args.whdload_mmu or args.cpu == '68030', '--whdload-mmu is for --setup a1200-030'
    # Where WHDLoad uses the MMU, the slave's CACHE policy holds (data cache on).
    dcache = args.cpu in ('68040', '68060') or args.whdload_mmu

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
        shutil.copyfile(args.slave or ROOT / 'build/whdload' / SLAVES[args.mode], game / 'SWotL.slave')
    if args.mode != 'smoke':
        shutil.copyfile(args.rom, boot / 'devs/Kickstarts' / args.rom.name)
        shutil.copyfile(args.rom.with_name(args.rom.name + '.RTB'), boot / 'devs/Kickstarts' / (args.rom.name + '.RTB'))
    if args.mode in ('load', 'run') and not args.installed:
        shutil.copyfile(args.exe, data / 'SWotL')
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
    if args.whdload_mmu:
        options.append('MMU')
    command = 'WHDLoad SWotL.slave ' + ' '.join(options)
    print('Command:', command, flush=True)
    (boot / 's/WHDLoad.prefs').write_text('Expert\nReadDelay=0\n')
    (boot / 's/startup-sequence').write_text(
        'DF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nStack 16384\nFailAt 999\n'
        f'CD DH1:\n{command} >DH0:result\n'
        'If WARN\nEcho failed >DH0:failed\nElse\nEcho passed >DH0:passed\nEndIf\n')

    fsuae = os.environ.get('FSUAE_MMU' if mmu else 'FSUAE', 'fs-uae')
    # Data-cache emulation needs the compatible core and, with directory drives, the
    # indirect UAE board (AmigaXDev headless-fsuae.md); otherwise FS-UAE drops it.
    cpu = {'68030': ['--uae_mmu_model=68030'],
           '68040': ['--uae_mmu_model=68040', '--uae_fpu_model=68040'],
           '68060': ['--uae_mmu_model=68060', '--uae_fpu_model=68060']}.get(args.cpu, []) if mmu else []
    if mmu:
        cpu += ['--uae_cpu_24bit_addressing=false', '--uae_cpu_compatible=true', '--uae_cpu_data_cache=true',
                '--uae_uaeboard=full+indirect']
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
    fsuae_log = base / 'fsuae/Cache/Logs/fs-uae.log.txt'
    if mmu and 'Data cache emulation' in (fsuae_log.read_text(errors='replace') if fsuae_log.exists() else 'Data cache emulation'):
        raise SystemExit(f'FAIL: FS-UAE did not keep data-cache emulation ({fsuae_log})')
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
    if args.slave and args.slave.name in WRITES:
        # Files the key script makes the game write (kickfs: docs/whdload.md).
        made = sorted(f'{f.name} {f.stat().st_size}' for f in data.iterdir()
                      if not (args.data / f.name).exists() and f.suffix != '.uaem'
                      and f.name not in ('SWotL', 'sfx.rsc'))
        print('written:', ', '.join(made) or 'none')
        if made != WRITES[args.slave.name]:
            raise SystemExit(f'FAIL: expected {WRITES[args.slave.name]} ({base})\n' + report[:2000])
    if args.cpu in ('68040', '68060') and 'TC=8000' not in report:
        raise SystemExit(f'FAIL: {args.cpu} MMU translation was not enabled (no TC=8000)\n' + report[:2000])
    # CACR alone does not show the policy: with the MMU, WHDLoad enables both
    # caches whatever the slave asks; setcpu= holds the slave's request.
    cacr = int(re.search(r'CACR=([0-9A-F]+)', report)[1], 16)
    setcpu = re.search(r'setcpu=\S+', report)[0]
    ic, dc = (0x8000, 0x80000000) if args.cpu in ('68040', '68060') else (0x1, 0x100)
    print(f'CACR={cacr:X}', setcpu)
    if not cacr & ic or bool(cacr & dc) != dcache or (',DC,' in setcpu) != dcache:
        raise SystemExit(f'FAIL: CACR={cacr:X}: expected the instruction cache'
                         + (' and the data cache' if dcache else ' without the data cache'))
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
          + (f', {args.cpu} MMU' + (' in use' if dcache else ' unused') if mmu else '')
          + f', CACR={cacr:X}')


if __name__ == '__main__':
    main()
