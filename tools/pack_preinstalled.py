#!/usr/bin/env python3
"""Pack an installed Swotl drawer as a preinstalled LHA (local only: game data).

    python3 tools/pack_preinstalled.py tmp/preinstalled/Swotl dist/Swotl-$(cat VERSION)-preinstalled-TFH.lha

Members: Swotl.info (the drawer icon beside DIR), then Swotl/<every file>.
The installed drawer comes from tools/test_release_installer.py --keep. The
archive holds the user's original files and must never be committed or shared.
"""
import argparse
from pathlib import Path
import _amigaxdev  # noqa: F401
from amigaxdev import release


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('drawer', type=Path)
    p.add_argument('archive', type=Path)
    args = p.parse_args()
    files = {f.relative_to(args.drawer).as_posix(): f.read_bytes()
             for f in sorted(args.drawer.rglob('*')) if f.is_file() and f.suffix != '.uaem'}
    assert {'Swotl.slave', 'Swotl.info', 'data/Swotl', 'data/SWOTL.EXE'} <= files.keys(), 'not an installed drawer'
    icon = args.drawer.with_name(args.drawer.name + '.info').read_bytes()
    stamp = release.dos_stamp(2026, 10, 24)
    out = release.write(args.archive, release.archive(args.drawer.name, files, icon, stamp))
    print(f'{out}: {len(files)} files plus drawer icon, {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
