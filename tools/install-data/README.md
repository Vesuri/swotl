# SWotLInstallData

Standalone C99 installer helper. Installs the SWOTL 2.2 files from the user's
three Air Combat Classics floppies (`Disk1-3.img` FAT12 images or
`CLASSICS.001-003`), or copies the user's Amiga Their Finest Hour `sfx.rsc`.

- ACC volumes are one INSTALIT archive: one PKWARE DCL stream per file, the
  808-record catalog (55 bytes each) at CLASSICS.001 offset 1,204,461. Format:
  `docs/release.md`, Original data.
- Checks: each volume's size and SHA-256 first, each file's catalog size and
  CRC-32; `sfx.rsc` by size and SHA-256. No game bytes in the helper.
- Destination must be new; on failure or Ctrl-C the files and drawers it
  created are removed. Exit 0 or 20.
- `io*`, `sha256*`, `start.s`, `COPYING.LIB`: AmigaXDev install-data
  (LGPL-2.1-or-later); `blast*`: zlib contrib/blast 1.3 (zlib licence).
  Vendored unchanged, pinned in `vendored.sha256`. `install.c`, `amiga/`:
  LGPL-2.1-or-later.

Source `amiga/env.sh`, then `make -C tools/install-data amiga` (68020,
freestanding, no unresolved symbols) or `make -C tools/install-data test`
(host: the 539 files against the original DOS ACC install, sources, refusals,
cleanup, cancel). Test inputs are local: `ACC_IMAGES`, `ACC_REFERENCE`, `TFH_RSC`.
