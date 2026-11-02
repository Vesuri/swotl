#!/usr/bin/env python3
"""Create the minimal deterministic Amiga LHA distributions (LH5).

    python3 tools/package_release.py amiga/out/Swotl-release.exe dist

  dist/SWotL-<version>.lha          full release (GitHub), with the SWotL executable
  dist/SWotL-<version>-whdload.lha  for whdload.de: no SWotL executable; Install asks for it
  dist/SWotL                        the executable, published beside the full archive
"""
import argparse
from pathlib import Path
import _amigaxdev  # noqa: F401
from amigaxdev import release
from amigaxdev.release import crc16  # noqa: F401  (check_release.py imports it from here)

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_HASHES = {line.split()[0] for line in (ROOT / 'release/originals.sha256').read_text().splitlines() if line.strip()}
PREFIX = 'SWotL Install'
STAMP = release.dos_stamp(2026, 10, 24)
ICONS = ROOT / 'release/icons'
WHDLOAD_DE_OMITS = ('SWotL',)


def archive_names(version):
    """(archive name, omitted members) for the full and the whdload.de archive."""
    return ((f'SWotL-{version}.lha', ()), (f'SWotL-{version}-whdload.lha', WHDLOAD_DE_OMITS))


def installer_icon(game=False):
    # SWotL.inf is distributed as is, renamed and configured by Installer, exactly
    # as RoF.inf in the reference package. No synthetic replacement artwork.
    return release.installer_icon(ICONS, 'Secret Weapons of the Luftwaffe', game=game)


def readme_icon():
    return release.template_icon(ICONS, 'readme.info.b64')


def drawer_icon():
    return release.template_icon(ICONS, 'drawer.info.b64')


def members(executable):
    return {
        'SWotL': executable.read_bytes(),
        'SWotL.slave': (ROOT / 'build/whdload/SWotL.slave').read_bytes(),
        'SWotL.inf': installer_icon(game=True),
        'SWotLInstallData': (ROOT / 'build/install-data/SWotLInstallData.exe').read_bytes(),
        'Install': (ROOT / 'release/Install').read_bytes(),
        'Install.info': installer_icon(),
        'ReadMe': (ROOT / 'release/ReadMe').read_bytes(),
        'ReadMe.info': readme_icon(),
        'LICENSE.LGPL.txt': (ROOT / 'tools/install-data/COPYING.LIB').read_bytes(),
        'blast-license.txt': (ROOT / 'tools/install-data/blast.h').read_bytes(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('executable', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    files = members(args.executable)
    release.refuse_originals(files, ORIGINAL_HASHES)
    for name, omitted in archive_names(version):
        contents = {k: v for k, v in files.items() if k not in omitted}
        archive = release.write(args.output_directory / name,
                                release.archive(PREFIX, contents, drawer_icon(), STAMP))
        print(f'{archive}: {len(contents)} drawer contents plus drawer icon, {archive.stat().st_size} bytes')
    executable = args.output_directory / 'SWotL'
    executable.write_bytes(files['SWotL'])
    print(f'{executable}: the release executable, {executable.stat().st_size} bytes')


if __name__ == '__main__':
    main()
