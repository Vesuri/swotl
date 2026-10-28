# Secret Weapons of the Luftwaffe — Amiga

An unofficial Amiga port of the 1991 PC flight simulator **Secret Weapons of the
Luftwaffe 2.2** by Lucasfilm Games and Totally Games, designed by Lawrence Holland.
Fly the Luftwaffe's jet and rocket aircraft or the American fighters and bombers
sent against them over Europe in 1943–45: training, historical missions, tours of
duty and the full campaign.

The port runs the original game code, translated offline from 16-bit x86 to 68020
by this repository's static translator; there is no x86 emulator. Graphics use AGA
bitplanes with a hardware sprite mouse pointer. The AdLib music and effects are
resynthesised on Paula; optionally, the sampled effects of the Amiga
**Their Finest Hour** replace the AdLib ones.

Current Amiga release: **0.90 (24.10.2026)**.

## Requirements and installation

- PAL AGA Amiga, 68020 or better; **68030 or better recommended**. Flight is slow
  on a 68020; the world still runs at real-time speed.
- **2 MB Chip RAM and 8 MB Fast RAM**; about 12 MB Fast RAM lets PreLoad hold all
  game files.
- WHDLoad 17+, Installer 43+, and a supported Kickstart 3.1 image with its RTB.
- The three 1.44 MB PC floppies of **Air Combat Classics** (LucasArts, 1993), which
  hold version 2.2, as `Disk1.img`–`Disk3.img` or as the files `CLASSICS.001`–`.003`.
  The images are available, for example, in the "The Good Old Days" floppy image
  collection (ID 496). Other releases are not supported.

Extract `SWotL-0.90.lha`, open its **SWotL Install** drawer and run **Install**.
Select the destination and the drawer with the disks; every file is checked and
damaged or other disks are refused. For Their Finest Hour effects, choose them in
the installer and select `sfx.rsc` from your Their Finest Hour installation; the
`Custom1` tooltype switches later (1 Their Finest Hour, 0 AdLib). Updating keeps
pilots, films and missions. Start the installed **SWotL** icon.

No original game code/data, Kickstart image or WHDLoad binary is distributed.
See [the release ReadMe](release/ReadMe) for supported ROM filenames and full
installation instructions.

## Controls

Keyboard and mouse work as in the PC original, with keys at their US keyboard
positions; see the original manual. There is no Amiga joystick support. Quit from
the game's menus; the WHDLoad QuitKey (**Help**) quits immediately.

## Building

The game uses `m68k-amiga-elf-gcc`, `elf2hunk` and vasm; the WHDLoad slave also
needs the WHDLoad SDK includes. Release packaging needs Python 3 and an
LH5-capable LHa encoder. The environment comes from AmigaXDev's `make setup`
([toolchain.md](docs/toolchain.md)).

```sh
. amiga/env.sh
make release          # dist/SWotL-0.90.lha, needs a clean tree
make amiga            # standalone executable: amiga/out/Swotl.exe
```

Without WHDLoad, the installed game runs from a Shell in its `data` drawer as
`SWotL`, or `SWotL TFH` for the Their Finest Hour effects. Translator design, tests and the reference setup against the
original under DOSBox are in [architecture.md](docs/architecture.md),
[toolchain.md](docs/toolchain.md) and [pc-reference-loop.md](docs/pc-reference-loop.md);
remaining work is in [open-work.md](docs/open-work.md).

## Credits and licensing

Secret Weapons of the Luftwaffe and its original assets belong to their respective
copyright holders. This is an unofficial fan port, not affiliated with or endorsed
by them. Amiga port by Vesa Halttunen (Vesuri).

The install helper uses the AmigaXDev installer helpers (LGPL-2.1-or-later; see
[its README](tools/install-data/README.md)) and Mark Adler's blast (zlib licence).
Those licences apply to the helper only, not to the original game.
