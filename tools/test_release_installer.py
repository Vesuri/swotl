#!/usr/bin/env python3
"""Run release/Install in real Installer 43 under FS-UAE with scripted answers.

    python3 tools/test_release_installer.py [mode ...] [--archive LHA] [--keep DIR]

The installation files are the package members (tools/package_release.py
from the current build), or with --archive those decoded from a release
archive. --keep copies the last mode's installed SWotL drawer to DIR.

Modes: fresh (images, AdLib), tfh (CLASSICS files, TFH sfx.rsc), keep (Use
existing), replace (images over a damaged install), remove, bad-disks
(Replace with a corrupted image), bad-sfx. SWotLInstallData runs on the emulated 68020; installed game files
must equal the original DOS ACC install, pilots and films must survive Keep
and Replace, and a refused source must leave the install as it was.
Inputs are local: ACC images, the DOS ACC install and TFH sfx.rsc (as
tools/install-data/test_install.py), Installer 43, WHDLoad, Kickstart 3.1,
the Workbench floppy. Each emulator is stopped by its own PID.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/install-data'))
from test_install import IMAGES, REFERENCE, SKIPPED, TFH_RSC, fat12_file  # noqa: E402
from test_install import tree as host_tree  # noqa: E402
from package_release import PREFIX, members  # noqa: E402

AMIGA = Path.home() / '.local/share/amiga'
WORKBENCH = Path(os.environ.get('WORKBENCH_ADF', AMIGA / 'Workbenchv2.04rev37.67Workbench.adf'))
INSTALLER = Path(os.environ.get('INSTALLER43', AMIGA / 'Installer43/Installer'))
WHDLOAD = Path(os.environ.get('WHDLOAD', AMIGA / 'WHDLoad')) / 'C/WHDLoad'
KICK = Path(os.environ.get('KICKSTART_A1200', AMIGA / 'Kickstarts/kick40068.A1200'))
SCRIPT = os.environ.get('INSTALL_SCRIPT')  # sabotage override of the package's Install
PACKAGE = {}
MODES = ('fresh', 'tfh', 'keep', 'replace', 'remove', 'bad-disks', 'bad-sfx')
PILOT = b'pilot roster written by the game'


def tree(base):
    # FS-UAE keeps Amiga protection bits and dates in .uaem sidecar files.
    return {k: p for k, p in host_tree(base).items() if not k.endswith('.UAEM')}


def replace_form(text, start, replacement):
    a = text.index(start)
    depth, quoted, i = 0, False, a
    while i < len(text):
        c = text[i]
        if quoted and c == '\\':
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        elif not quoted:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return text[:a] + replacement + text[i + 1:]
        i += 1
    raise ValueError('unbalanced Installer form: ' + start)


def mark(name, then=''):
    return f'((textfile (dest "DH2:{name}") (append "yes")) {then})'


def script(mode):
    s = (Path(SCRIPT).read_bytes() if SCRIPT else PACKAGE['Install']).decode('latin-1')
    s = replace_form(s, '(welcome)', '(if 0 (welcome))')
    s = replace_form(s, '(set #source', '(set #source "DH0:")')
    s = s.replace('SYS:Utilities/MultiView', 'Execute DH0:multiview').replace('SYS:Utilities/More', 'Execute DH0:more')
    s = replace_form(s, '(set #parent', mark('parent-asked', '(set #parent "DH2:out")'))
    s = replace_form(s, '(set #remove-existing', mark('remove-asked', f'(set #remove-existing {int(mode == "remove")})'))
    s = replace_form(s, '(set #install-data\n', mark('reuse-asked', f'(set #install-data {int(mode in ("replace", "bad-disks"))})'))
    disks = 'DH2:files' if mode == 'tfh' else 'DH2:disks'
    s = replace_form(s, '(set #disks', mark('disks-asked', f'(set #disks "{disks}")'))
    tfh = int(mode in ('tfh', 'bad-sfx'))
    s = replace_form(s, '(set #tfh\n', mark('sound-asked', f'(set #tfh {tfh})'))
    s = replace_form(s, '(set #sfx', mark('sfx-asked', '(set #sfx "DH2:TheirFinestHour/data/sfx.rsc")'))
    s = replace_form(s, '(abort "The Air Combat Classics disks', mark('disks-refused', '(exit (quiet))'))
    s = replace_form(s, '(abort "This sfx.rsc', mark('sfx-refused', '(exit (quiet))'))
    s = replace_form(s, '(exit)', '(exit (quiet))')
    return s.encode('latin-1')


def fixture(mode, base):
    boot, out = base / 'boot', base / 'out'
    for p in (boot / 's', boot / 'env', boot / 'devs/Kickstarts', out, base / 'state'):
        p.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(INSTALLER, boot / 'Installer')
    shutil.copyfile(WHDLOAD, boot / 'WHDLoad')
    for name, data in PACKAGE.items():
        (boot / name).write_bytes(data)
    (boot / 'Install').write_bytes(script(mode))
    (boot / 'devs/Kickstarts/kick40068.A1200').touch()
    (boot / 'devs/Kickstarts/kick40068.A1200.RTB').touch()
    for viewer, rc in (('multiview', 20 if mode == 'fresh' else 0), ('more', 0)):
        (boot / viewer).write_text(f'.key FILE/A\nEcho "<FILE>" >DH2:{viewer}-readme\nQuit {rc}\n')
    (boot / 'env/WHDLInstPath').write_text('DH2:previous parent')
    images = [IMAGES / f'disk{n}.img' for n in (1, 2, 3)]
    (base / 'disks').mkdir()
    for n, image in enumerate(images, 1):
        data = bytearray(image.read_bytes())
        if mode == 'bad-disks' and n == 2:
            data[900000] ^= 1
        (base / f'disks/Disk{n}.img').write_bytes(data)
    if mode == 'tfh':
        (base / 'files').mkdir()
        for n, image in enumerate(images, 1):
            (base / f'files/CLASSICS.00{n}').write_bytes(fat12_file(image, f'CLASSICS00{n}'))
    rsc = bytearray(TFH_RSC.read_bytes())
    if mode == 'bad-sfx':
        rsc[1000] ^= 1
    (base / 'TheirFinestHour/data').mkdir(parents=True)
    (base / 'TheirFinestHour/data/sfx.rsc').write_bytes(rsc)
    data = out / 'SWotL/data'
    if mode in ('keep', 'replace', 'remove', 'bad-disks', 'bad-sfx'):
        data.mkdir(parents=True)
        for name, path in REFERENCE_FILES.items():
            (data / name).parent.mkdir(exist_ok=True)
            shutil.copyfile(path, data / name)
        (data / 'PILOT.PLT').write_bytes(PILOT)
        (data / 'A.RPY').write_bytes(PILOT)
        if mode in ('keep', 'replace'):
            (data / 'AC/P38L.SPC').write_bytes(b'damaged')
        (out / 'SWotL/old-marker').touch()
    (out / 'unrelated').write_text('keep')
    (boot / 's/startup-sequence').write_text(
        'CD DH0:\nStack 16384\nDF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nDF0:C/Assign ENV: RAM:\nDF0:C/Assign ENVARC: DH0:env\n'
        'Copy ENVARC:WHDLInstPath ENV:WHDLInstPath\nDF0:C/Assign T: RAM:\nPath DH0: ADD\nC:LoadWB\n'
        'Installer SCRIPT DH0:Install APPNAME SWotL MINUSER NOVICE DEFUSER NOVICE '
        'LOGFILE DH2:installer.log NOPRETEND >DH2:console.log\nEcho done >DH2:finished\n')


def emulate(base, seconds):
    with (base / 'emulator.log').open('w') as log:
        emu = subprocess.Popen([os.environ.get('FSUAE', 'fs-uae'), '--amiga_model=A1200', '--cpu=68020',
            '--uae_cpu_model=68020', '--jit_compiler=0', '--chip_memory=2048', '--fast_memory=8192',
            '--kickstart_file=' + str(KICK), '--hard_drive_0=' + str(base / 'boot'), '--hard_drive_0_priority=10',
            '--hard_drive_2=' + str(base), '--floppy_drive_0=' + str(WORKBENCH), '--audio_driver=dummy',
            '--warp_mode=1', '--fullscreen=0', '--automatic_input_grab=0',
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')],
            stdout=log, stderr=log, env=dict(os.environ, SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and not (base / 'finished').exists():
                if emu.poll() is not None:
                    raise SystemExit(f'FAIL: emulator exited ({base})')
                time.sleep(.25)
            time.sleep(1)
        finally:
            emu.terminate()
            try:
                emu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emu.kill()
                emu.wait()
    assert (base / 'finished').exists(), f'Installer did not finish: {base}'


def check(mode, base):
    asked = lambda name: (base / name).exists()
    dest = base / 'out/SWotL'
    data = dest / 'data'
    assert (base / 'multiview-readme').read_text().strip() == 'DH0:ReadMe'
    assert asked('more-readme') == (mode == 'fresh')
    assert (base / 'boot/env/WHDLInstPath').read_text().strip() == 'DH2:out'
    assert (base / 'out/unrelated').read_text() == 'keep'
    assert not (dest / 'InstallStaging').exists(), 'staging drawer left behind'
    existing = mode != 'fresh' and mode != 'tfh'
    assert asked('remove-asked') == existing
    assert asked('reuse-asked') == (mode in ('keep', 'replace', 'bad-disks', 'bad-sfx'))
    if mode == 'bad-disks':
        assert asked('disks-refused') and asked('sound-asked')
    elif mode == 'bad-sfx':
        assert asked('sfx-refused') and not (data / 'sfx.rsc').exists()
    else:
        assert asked('disks-asked') == (mode in ('fresh', 'tfh', 'replace', 'remove'))
        assert asked('sfx-asked') == (mode == 'tfh')
    if mode in ('bad-disks', 'bad-sfx'):
        # Refused before anything was copied: the earlier install is unchanged.
        assert not (data / 'SWotL').exists() and not (dest / 'SWotL.slave').exists()
        files = {k: p for k, p in tree(data).items() if k not in ('PILOT.PLT', 'A.RPY')}
        assert files.keys() == REFERENCE_FILES.keys()
        assert (data / 'PILOT.PLT').read_bytes() == PILOT
        return
    files = tree(data)
    assert files.pop('SWOTL') and (data / 'SWotL').read_bytes() == PACKAGE['SWotL']
    kept = mode in ('keep', 'replace')
    for name in ('PILOT.PLT', 'A.RPY'):
        assert (files.pop(name, None) is not None) == kept, name
    tfh = files.pop('SFX.RSC', None)
    assert (tfh is not None) == (mode == 'tfh')
    if tfh:
        assert tfh.read_bytes() == TFH_RSC.read_bytes()
    assert files.keys() == REFERENCE_FILES.keys(), sorted(files.keys() ^ REFERENCE_FILES.keys())[:8]
    for name, path in REFERENCE_FILES.items():
        expected = b'damaged' if mode == 'keep' and name == 'AC/P38L.SPC' else path.read_bytes()
        assert files[name].read_bytes() == expected, name
    assert (dest / 'SWotL.slave').read_bytes() == PACKAGE['SWotL.slave']
    assert (dest / 'ReadMe').exists() and (dest / 'ReadMe.info').exists()
    assert (dest / 'old-marker').exists() == kept
    icon = (dest / 'SWotL.info').read_bytes()
    assert b'WHDLoad\0' in icon
    icon = icon.lower()
    assert b'slave=swotl.slave\0' in icon and b'preload\0' in icon
    assert (b'custom1=1\0' in icon) == (mode == 'tfh') and (b'custom1' in icon) == (mode == 'tfh'), 'Custom1 tooltype'


REFERENCE_FILES = {}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('modes', nargs='*', default=MODES)
    p.add_argument('--archive', type=Path)
    p.add_argument('--keep', type=Path)
    args = p.parse_args()
    assert set(args.modes) <= set(MODES), args.modes
    if args.archive:
        names = subprocess.run(['lha', 'lq', str(args.archive)], check=True, capture_output=True, text=True).stdout
        for line in names.splitlines():
            m = re.search(r' \d\d:\d\d (.+)$', line)  # lha lq: ... Oct 24 00:00 NAME
            name = m[1] if m else ''
            if name.startswith(PREFIX + '/'):
                PACKAGE[name[len(PREFIX) + 1:]] = subprocess.run(['lha', 'pq', str(args.archive), name],
                                                                 check=True, capture_output=True).stdout
        assert {'Install', 'SWotL', 'SWotL.slave', 'SWotLInstallData'} <= PACKAGE.keys(), sorted(PACKAGE)
    else:
        PACKAGE.update(members(ROOT / 'amiga/out/Swotl-release.exe'))
    REFERENCE_FILES.update((k, p) for k, p in host_tree(REFERENCE).items() if k not in SKIPPED)
    (ROOT / 'tmp').mkdir(exist_ok=True)
    for mode in args.modes:
        base = Path(tempfile.mkdtemp(prefix=f'installer-{mode}-', dir=ROOT / 'tmp'))
        print(base, flush=True)
        fixture(mode, base)
        emulate(base, 900)
        check(mode, base)
        print(f'PASS: Installer {mode}', flush=True)
        if args.keep and mode == args.modes[-1]:
            shutil.rmtree(args.keep, ignore_errors=True)
            shutil.copytree(base / 'out/SWotL', args.keep, ignore=shutil.ignore_patterns('*.uaem'))
            shutil.copyfile(base / 'out/SWotL.info', args.keep.with_name(args.keep.name + '.info'))
            print('Installed drawer:', args.keep)
        shutil.rmtree(base)


if __name__ == '__main__':
    main()
