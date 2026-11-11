#!/usr/bin/env python3
"""Play the game under WHDLoad in FS-UAE: real speed, sound, the release slave.

    make run-whdload [RUN_ARGS='--setup a1200-040 --z3 32768']
    python3 tools/run_whdload.py [--setup a1200-040] [--z3 KiB] [--tfh] [--ocs] [--analog]
                                 [--no-preload] [--option FILELOG] [--installed DIR] [--fresh]

The drawer persists in tmp/whdload-run/<setup>[-tfh][-ocs][-analog][-installed]
(boot/ and game/), so a second start reads the sfx.cache and pilot files the first
one wrote; --fresh starts it again from nothing. Each start copies in the current
WHDLoad, slave (build/whdload/SWotL.slave, or --slave) and executable
(amiga/out/Swotl-release.exe, or --exe); ref/ files are copied only where missing.
--installed DIR copies an installed SWotL drawer once and runs its own slave and
SWotL. The game ends from its menu or by the slave's quit key (Help); FS-UAE stays
open until its window is closed. NOWRITECACHE is passed as the ReadMe asks of
8 MiB machines (--write-cache drops it). Machine setups, inputs and the FS-UAE
binaries are those of tools/test_whdload.py; emulated 68030-68060 speed is not
the real machines'. Source amiga/env.sh first.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_whdload as T  # noqa: E402

ROOT = T.ROOT


def copy_missing(src, dst):
    """Copy the files of src that dst lacks (game-written files stay)."""
    for f in src.rglob('*'):
        target = dst / f.relative_to(src)
        if f.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif f.suffix != '.pdf' and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--setup', choices=tuple(T.MACHINES), default='a1200')
    p.add_argument('--tfh', action='store_true', help='Custom1: Their Finest Hour sound')
    p.add_argument('--analog', action='store_true', help='Custom2: analog joystick')
    p.add_argument('--ocs', action='store_true', help='Custom3: OCS/ECS display on AGA')
    p.add_argument('--no-sfx', action='store_true', help='no TFH sfx.rsc in the drawer')
    p.add_argument('--slave', type=Path, default=ROOT / 'build/whdload/SWotL.slave')
    p.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/Swotl-release.exe')
    p.add_argument('--data', type=Path, default=ROOT / 'ref')
    p.add_argument('--installed', type=Path, help='installed SWotL drawer (copied once)')
    p.add_argument('--rom', type=Path, help='Kickstart (default: A1200 3.1 on AGA, A600 3.1 otherwise)')
    p.add_argument('--fast', type=int, default=8192, help='Fast RAM in KiB')
    p.add_argument('--z3', type=int, default=0, help='Zorro III Fast RAM in KiB (68030 or later)')
    p.add_argument('--cpu', default='68020', help='CPU of the a1200 setup (others fix their own)')
    p.add_argument('--no-preload', action='store_true')
    p.add_argument('--write-cache', action='store_true', help='leave out NOWRITECACHE')
    p.add_argument('--option', action='append', default=[], help='extra WHDLoad option, e.g. FILELOG')
    p.add_argument('--fresh', action='store_true', help='delete this setup\'s drawer first')
    p.add_argument('--silent', action='store_true', help='no sound')
    p.add_argument('--warp', action='store_true', help='FS-UAE warp mode')
    args = p.parse_args()

    model, chipset, chip_kb = T.MACHINES[args.setup]
    rom = args.rom or (T.KICK31 if chipset == 'aga' else T.KICK600)
    mmu = args.setup.startswith('a1200-') or args.setup == 'a3000'
    cpu = args.cpu
    if mmu:
        cpu = '68030' if args.setup == 'a3000' else '68' + args.setup[-3:]
    assert not args.z3 or cpu != '68020', '--z3 needs a 68030 or later setup'

    name = args.setup + ''.join(f'-{n}' for n in ('tfh', 'ocs', 'analog', 'installed') if getattr(args, n))
    base = ROOT / 'tmp/whdload-run' / name
    if args.fresh and base.exists():
        shutil.rmtree(base)
    boot, game = base / 'boot', base / 'game'
    data = game / 'data'
    if args.installed and not game.exists():
        shutil.copytree(args.installed, game)
    for d in (boot / 's', boot / 'devs/Kickstarts', data, base / 'state', base / 'fsuae'):
        d.mkdir(parents=True, exist_ok=True)
    for f in (rom, rom.with_name(rom.name + '.RTB')):
        shutil.copyfile(f, boot / 'devs/Kickstarts' / f.name)
    shutil.copyfile(T.WHDLOAD, game / 'WHDLoad')
    if not args.installed:
        shutil.copyfile(args.slave, game / 'SWotL.slave')
        shutil.copyfile(args.exe, data / 'SWotL')
        copy_missing(args.data, data)
        if not args.no_sfx and not (data / 'sfx.rsc').exists():
            shutil.copyfile(T.TFH_RSC, data / 'sfx.rsc')

    options = ['SPLASHDELAY=0']
    if not args.no_preload:
        options.append('PRELOAD')
    if not args.write_cache:
        options.append('NOWRITECACHE')
    options += [f'CUSTOM{n}=1' for n, on in ((1, args.tfh), (2, args.analog), (3, args.ocs)) if on]
    options += args.option
    command = 'WHDLoad SWotL.slave ' + ' '.join(options)
    (boot / 's/WHDLoad.prefs').write_text('Expert\nReadDelay=0\n')
    (boot / 's/startup-sequence').write_text(
        'DF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nStack 16384\nFailAt 999\n'
        f'CD DH1:\n{command}\nEcho "WHDLoad returned; close the FS-UAE window."\n')
    for f in (base / 'state').glob('*.uss'):    # a resumed state would skip the start
        f.unlink()

    fsuae = os.environ.get('FSUAE_MMU' if mmu else 'FSUAE', 'fs-uae')
    extra = {'68030': ['--uae_mmu_model=68030'],
             '68040': ['--uae_mmu_model=68040', '--uae_fpu_model=68040'],
             '68060': ['--uae_mmu_model=68060', '--uae_fpu_model=68060']}.get(cpu, []) if mmu else []
    if mmu:
        extra += ['--uae_cpu_24bit_addressing=false', '--uae_cpu_compatible=true',
                  '--uae_cpu_data_cache=true', '--uae_uaeboard=full+indirect']
    if args.setup in T.FREQUENCY:
        extra += ['--uae_cpu_speed=real', '--uae_cpu_multiplier=0',
                  '--uae_cpu_frequency=%d' % T.FREQUENCY[args.setup]]
    argv = [fsuae, '--amiga_model=' + model, '--uae_chipset=' + chipset, '--cpu=' + cpu,
            '--uae_cpu_model=' + cpu, *extra, '--jit_compiler=0',
            '--chip_memory=' + str(chip_kb), '--slow_memory=0', '--fast_memory=' + str(args.fast),
            *(['--zorro_iii_memory=' + str(args.z3)] if args.z3 else []),
            '--kickstart_file=' + str(rom),
            '--hard_drive_0=' + str(boot), '--hard_drive_0_priority=10', '--hard_drive_1=' + str(game),
            '--floppy_drive_0=' + str(T.WORKBENCH),
            *(['--audio_driver=dummy'] if args.silent else []),
            '--joystick_port_0=mouse', '--joystick_port_1=nothing',
            '--warp_mode=' + ('1' if args.warp else '0'), '--fullscreen=0',
            '--automatic_input_grab=0', '--window_width=720', '--window_height=568',
            '--title=SWotL WHDLoad ' + name,
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')]
    print('Drawer:', game)
    print('Command:', command, flush=True)
    env = dict(os.environ, SDL_AUDIODRIVER='dummy') if args.silent else os.environ
    os.execvpe(fsuae, argv, env)


if __name__ == '__main__':
    main()
