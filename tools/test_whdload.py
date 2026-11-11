#!/usr/bin/env python3
"""Run the WHDLoad slave in FS-UAE in an isolated tmp/whdload-test-* fixture.

    python3 tools/test_whdload.py --mode smoke     # Smoke.slave: harness only
    python3 tools/test_whdload.py --mode boot      # BootTest.slave: Kickstart 3.1 kickemu boots
    python3 tools/test_whdload.py --mode load      # LoadTest.slave: load + PROGDIR; its relocated block checked
    python3 tools/test_whdload.py --mode run [--tfh] [--analog] [--slave build/whdload/MemFree.slave]
    python3 tools/test_whdload.py --mode run --installed DIR [--setup a1200-040]
    python3 tools/test_whdload.py --mode run --setup a1200-030 [--whdload-mmu]
    python3 tools/test_whdload.py --mode run --setup a3000|a500+-020 [--slave build/whdload/MemFree.slave]
    python3 tools/test_whdload.py --mode run --setup a500-020 --slave build/whdload/SWotL512K.slave [--no-sfx]
    python3 tools/test_whdload.py --mode run --ocs            # Custom3: the OCS/ECS display on AGA
    python3 tools/test_whdload.py --mode run --slave build/whdload/CampaignTest.slave --ticks 15000
    (also TourTest.slave: game files written through kickfs)

`run` starts the game under the release slave; WHDLoad TIMEOUT (needs the moved
VBR of a 68020) ends it with COREDUMP and the dump is judged:
  - the reason is the timeout ("DEBUG caused" at the CIA-A event count), not a fault;
  - the game is running: most 64-byte blocks of the original SWOTL.EXE and
    the graphics driver lie in guest RAM, which holds guest bytes in reverse
    order (overlays come and go; relocated and patched blocks differ): RTSVGA.OVL
    on AGA, RTSEGA.OVL on OCS/ECS or with Custom3 (--ocs, the OCS argument);
  - Custom1 (--tfh): the TFH sfx.rsc PCM payload is in Chip RAM; without it,
    no sample block is. Their copy in Chip is what the TFH path makes.
  - Custom2 (--analog): the game's PSP command tail has the joystick argument
    Y (ANALOGJOYSTICK), N without; its driver letter is V (VGA) or E (EGA).
  - 512 KB Chip (--setup a500-020, docs/ecs-plan.md D6): FM effects do not fit,
    so no effect cache is written; the TFH samples are in Chip when sfx.rsc is
    in the drawer, none with --no-sfx (effects silent).
  - the prerendered effects' cache (sfx.cache, docs/sound-plan.md R4) was
    written through kickfs, whole: its header's count of effects (27 for FM,
    1 with TFH) and the file's length agree.
run mode passes NOWRITECACHE, as the ReadMe asks of 8 MiB machines (exit hang).
The MemFree slave's low-water marks (Chip, Fast) are read from its $100 slot.
--installed runs an installed SWotL drawer as it is (slave, data/SWotL, data).
--setup a1200-040: full 68040 with its MMU and FPU, JIT off, on $FSUAE_MMU;
the report must show TC=8000 (translation on; AmigaXDev whdload-mmu.md).
--setup a1200-030: full 68030 with its MMU on $FSUAE_MMU; WHDLoad uses the MMU
only with its MMU option (--whdload-mmu). --setup a1200-060: as the 68040, TC=8000 too.
These setups emulate the data cache. --setup a3000 (A3000, ECS, 68030 + MMU,
2 MB Chip), a500+-020 (A500+, ECS, 1 MB Chip) and a500-020 (A500, OCS,
512 KB Chip), the last two a 68020 with 8 MB Fast, as AmigaXDev's presets, on
the A600 Kickstart 3.1.
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
KICK600 = Path(os.environ.get('KICKSTART_A600', KICKSTARTS / 'kick40063.A600'))
# setup: machine model, chipset, Chip KiB (AmigaXDev share/fsuae_common.sh presets)
MACHINES = {'a1200': ('A1200', 'aga', 2048), 'a1200-030': ('A1200', 'aga', 2048),
            'a1200-040': ('A1200', 'aga', 2048), 'a1200-060': ('A1200', 'aga', 2048),
            'a3000': ('A3000', 'ecs', 2048), 'a500+-020': ('A500+', 'ecs', 1024),
            'a500-020': ('A500', 'ocs', 512)}
# The A500 presets' 68020 card runs at twice the stock 7.09 MHz.
FREQUENCY = {'a500+-020': 14187580, 'a500-020': 14187580}
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


def hunks(exe):
    """The executable's hunks as dos.LoadSeg loads them: (longs, data,
    [(target hunk, offset)...]) each; data is the file's bytes, shorter than
    longs*4 for BSS and uninitialised tails."""
    w = lambda o: int.from_bytes(exe[o:o + 4], 'big')
    assert w(0) == 0x3f3 and w(4) == 0, 'HUNK_HEADER without resident libraries'
    first, last = w(12), w(16)
    sizes = [w(20 + 4 * k) for k in range(last - first + 1)]
    assert not any(s & 0xc0000000 for s in sizes), 'no memory flags'
    out, o, cur = [], 20 + 4 * len(sizes), None
    while o < len(exe):
        t = w(o) & 0x3fffffff
        o += 4
        if t in (0x3e9, 0x3ea, 0x3eb):         # CODE, DATA, BSS
            n = w(o)
            cur = [sizes[len(out)], exe[o + 4:o + 4 + 4 * n] if t != 0x3eb else b'', []]
            out.append(cur)
            o += 4 if t == 0x3eb else 4 + 4 * n
        elif t == 0x3ec:                         # RELOC32
            while w(o):
                n, target = w(o), w(o + 4)
                cur[2] += [(target, w(o + 8 + 4 * k)) for k in range(n)]
                o += 8 + 4 * n
            o += 4
        elif t == 0x3f0:                         # SYMBOL
            while w(o):
                o += 4 + 4 * w(o) + 4
            o += 4
        elif t == 0x3f1:                         # DEBUG
            o += 4 + 4 * w(o)
        elif t == 0x3f2:                         # END
            pass
        else:
            raise SystemExit(f'FAIL: hunk type {t:X} at {o - 4} not checked')
    assert len(out) == len(sizes)
    return out


def check_block(exe, data, base):
    """The slave's resload_Relocate block (LoadTest.slave: test-block and its
    address, size and resload_Relocate's size in test-blockadr) against the
    executable relocated here: every segment linked in order inside the block,
    its bytes the hunk's, relocated to the segments' addresses, BSS zero."""
    adr = (data / 'test-blockadr').read_bytes() if (data / 'test-blockadr').exists() else b''
    if len(adr) != 12:
        raise SystemExit(f'FAIL: load: no relocated block saved: dos.LoadSeg loaded SWotL ({base})')
    at, size, used = (int.from_bytes(adr[k:k + 4], 'big') for k in (0, 4, 8))
    block = (data / 'test-block').read_bytes()
    assert len(block) == size and used <= size, (size, used, len(block))
    hs, segs, link = hunks(exe), [], at + 4
    while link:
        o = link - at
        assert 4 <= o < size and len(segs) < len(hs), f'segment link {link:X} outside the block'
        segs.append(link + 4)
        link = int.from_bytes(block[o:o + 4], 'big') * 4
    if len(segs) != len(hs):
        raise SystemExit(f'FAIL: load: {len(segs)} segments, the executable has {len(hs)} hunks')
    for k, (longs, raw, relocs) in enumerate(hs):
        want = bytearray(raw.ljust(4 * longs, b'\0'))
        for target, off in relocs:
            v = int.from_bytes(want[off:off + 4], 'big') + segs[target]
            want[off:off + 4] = (v & 0xffffffff).to_bytes(4, 'big')
        o = segs[k] - at
        if block[o:o + len(want)] != want:
            bad = next(i for i in range(len(want)) if block[o + i] != want[i])
            raise SystemExit(f'FAIL: load: hunk {k} differs at +{bad:X} ({base})')
    print(f'relocated block: {len(hs)} hunks at {at:X}, {used:,} of {size:,} bytes, matches the executable')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mode', choices=tuple(SLAVES), default='run')
    p.add_argument('--tfh', action='store_true', help='set Custom1 (Their Finest Hour sound)')
    p.add_argument('--analog', action='store_true', help='set Custom2 (analog joystick)')
    p.add_argument('--ocs', action='store_true', help='set Custom3 (OCS/ECS display on AGA)')
    p.add_argument('--no-sfx', action='store_true', help='no sfx.rsc in the drawer')
    p.add_argument('--slave', type=Path, help='slave override (default: build/whdload/ per mode)')
    p.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/Swotl-release.exe',
                   help='stripped (make amiga-release): LoadSeg reads symbol hunks in small pieces')
    p.add_argument('--data', type=Path, default=ROOT / 'ref')
    p.add_argument('--installed', type=Path, help='installed SWotL drawer, used unchanged')
    p.add_argument('--setup', choices=tuple(MACHINES), default='a1200')
    p.add_argument('--whdload-mmu', action='store_true', help="WHDLoad's MMU option (68030)")
    p.add_argument('--rom', type=Path, help='Kickstart (default: A1200 3.1 on AGA, A600 3.1 otherwise)')
    p.add_argument('--fast', type=int, default=8192, help='host Fast RAM in KiB')
    p.add_argument('--z3', type=int, default=0, help='Zorro III Fast RAM in KiB (needs --cpu 68030 or later)')
    p.add_argument('--cpu', default='68020')
    p.add_argument('--ticks', type=int, default=3000, help='WHDLoad TIMEOUT in PAL fields (run)')
    p.add_argument('--no-preload', action='store_true')
    p.add_argument('--option', action='append', default=[], help='extra WHDLoad option, e.g. FILELOG')
    p.add_argument('--seconds', type=int, default=600, help='host safety ceiling')
    args = p.parse_args()
    if args.installed:
        assert args.mode == 'run' and not args.slave, '--installed runs its own slave'
        args.data = args.installed / 'data'
    model, chipset, chip_kb = MACHINES[args.setup]
    args.rom = args.rom or (KICK31 if chipset == 'aga' else KICK600)
    mmu = args.setup.startswith('a1200-') or args.setup == 'a3000'
    if mmu:
        args.cpu = '68030' if args.setup == 'a3000' else '68' + args.setup[-3:]
    ega = chipset != 'aga' or args.ocs
    small = chip_kb < 1024
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
        if not args.no_sfx:
            shutil.copyfile(TFH_RSC, data / 'sfx.rsc')
    options = ['SPLASHDELAY=0', 'NOREQ']
    if not args.no_preload:
        options.append('PRELOAD')
    if args.mode == 'run':
        # Every run creates a file (sfx.cache, A.CBA, A.USA): with PreLoad on 8 MiB,
        # WHDLoad 20.1's write cache hangs at exit (docs/whdload.md, Common failures).
        options += ['COREDUMP', f'TIMEOUT={args.ticks}', 'NOWRITECACHE']
        if args.tfh:
            options.append('CUSTOM1=1')
        if args.analog:
            options.append('CUSTOM2=1')
        if args.ocs:
            options.append('CUSTOM3=1')
    if args.mode == 'load':
        options.append('NOWRITECACHE')      # LoadTest.slave writes test-block (exit hang, as above)
    if args.whdload_mmu:
        options.append('MMU')
    options += args.option
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
        emu = subprocess.Popen([fsuae, '--amiga_model=' + model, '--uae_chipset=' + chipset, '--cpu=' + args.cpu,
            '--uae_cpu_model=' + args.cpu, *cpu, '--jit_compiler=0',
            *(['--uae_cpu_speed=real', '--uae_cpu_multiplier=0', '--uae_cpu_frequency=%d' % FREQUENCY[args.setup]]
              if args.setup in FREQUENCY else []),
            '--chip_memory=' + str(chip_kb), '--slow_memory=0', '--fast_memory=' + str(args.fast),
            *(['--zorro_iii_memory=' + str(args.z3)] if args.z3 else []),
            '--kickstart_file=' + str(args.rom),
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
        if args.mode == 'load':
            check_block(args.exe.read_bytes(), data, base)
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
                      and f.name not in ('SWotL', 'sfx.rsc', 'sfx.cache'))
        print('written:', ', '.join(made) or 'none')
        if made != WRITES[args.slave.name]:
            raise SystemExit(f'FAIL: expected {WRITES[args.slave.name]} ({base})\n' + report[:2000])
    cache = data / 'sfx.cache'
    image = cache.read_bytes() if cache.exists() else b''
    count = int.from_bytes(image[12:16], 'big') if len(image) >= 16 else 0
    length = 16 + 8 * count + sum(int.from_bytes(image[16 + 8 * k + 4:16 + 8 * k + 8], 'big') for k in range(count))
    print(f'sfx.cache: {len(image)} bytes, {count} effects')
    if small and not args.tfh:
        if image:
            raise SystemExit(f'FAIL: an effect cache on 512 KB Chip, where FM effects do not fit ({base})')
    elif image[:4] != b'SWFX' or count != (1 if args.tfh else 27) or len(image) != length:
        raise SystemExit(f'FAIL: the effect cache was not written whole ({base})')
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
    for name in ('SWOTL.EXE', 'RTSEGA.OVL' if ega else 'RTSVGA.OVL'):
        image = blocks((args.data / name).read_bytes(), 64)
        found = sum(1 for b in image if b[::-1] in memory)
        print(f'{name} in guest RAM: {found} of {len(image)} blocks')
        resident &= found >= len(image) // 2
    pcm = [b for s in rsc_pcm(TFH_RSC.read_bytes()) for b in blocks(s)]
    in_chip = sum(1 for b in pcm if b in chip)
    print(f'TFH samples in Chip: {in_chip} of {len(pcm)} blocks')
    if args.slave and args.slave.name.startswith('MemFree'):
        print('MemFree low water: Chip {:,} Fast {:,} bytes'.format(
            int.from_bytes(chip[0x100:0x104], 'big'), int.from_bytes(chip[0x104:0x108], 'big')))
    if not resident:
        raise SystemExit('FAIL: the game is not resident in guest RAM')
    tail = b' %s S 5 %s Y Y 64\r' % (b'E' if ega else b'V', b'Y' if args.analog else b'N')
    print('command tail:', tail.decode().strip(), 'in guest RAM' if tail[::-1] in memory else 'missing')
    if tail[::-1] not in memory:
        raise SystemExit('FAIL: Custom2 did not set the joystick argument' if args.analog
                         else 'FAIL: the joystick argument is not N without Custom2')
    # 512 KB Chip without Custom1: the TFH samples replace the FM effects when
    # sfx.rsc is there (D6); --no-sfx leaves the effects silent.
    tfh = (args.tfh or small) and not args.no_sfx
    if tfh and in_chip != len(pcm):
        raise SystemExit('FAIL: TFH expected but its samples are not in Chip')
    if not tfh and in_chip:
        raise SystemExit('FAIL: TFH samples in Chip' + (' without sfx.rsc' if args.no_sfx else ' without Custom1'))
    print(f'PASS: game runs under WHDLoad on {args.setup} ({"EGA" if ega else "VGA"}), sound '
          + ('TFH' if tfh else 'silent effects' if small else 'FM')
          + (', analog joystick' if args.analog else '')
          + (f', {args.cpu} MMU' + (' in use' if dcache else ' unused') if mmu else '')
          + f', CACR={cacr:X}')


if __name__ == '__main__':
    main()
