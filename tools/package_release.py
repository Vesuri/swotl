#!/usr/bin/env python3
"""Create the minimal deterministic Amiga LHA distribution (LH5).

    python3 tools/package_release.py amiga/out/Swotl-release.exe dist
"""
import argparse
from pathlib import Path
import _amigaxdev  # noqa: F401
from amigaxdev import release
from amigaxdev.release import crc16  # noqa: F401  (check_release.py imports it from here)

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_HASHES = {line.split()[0] for line in (ROOT / 'release/originals.sha256').read_text().splitlines() if line.strip()}
PREFIX = 'Swotl Install'
STAMP = release.dos_stamp(2026, 10, 24)
ICONS = ROOT / 'release/icons'


def installer_icon(game=False):
    # Swotl.inf is distributed as is, renamed and configured by Installer, exactly
    # as RoF.inf in the reference package. No synthetic replacement artwork.
    return release.installer_icon(ICONS, 'Secret Weapons of the Luftwaffe', game=game)


def readme_icon():
    return release.template_icon(ICONS, 'readme.info.b64')


def drawer_icon():
    return release.template_icon(ICONS, 'drawer.info.b64')


def members(executable):
    return {
        'Swotl': executable.read_bytes(),
        'Swotl.slave': (ROOT / 'build/whdload/Swotl.slave').read_bytes(),
        'Swotl.inf': installer_icon(game=True),
        'SwotlInstallData': (ROOT / 'build/install-data/SwotlInstallData.exe').read_bytes(),
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
    archive = release.write(args.output_directory / f'Swotl-{version}.lha',
                            release.archive(PREFIX, files, drawer_icon(), STAMP))
    print(f'{archive}: {len(files)} drawer contents plus drawer icon, {archive.stat().st_size} bytes')


if __name__ == '__main__':
    main()
