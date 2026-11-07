# Secret Weapons of the Luftwaffe — Amiga

An unofficial Amiga port of the 1991 PC flight simulator **Secret Weapons of the
Luftwaffe 2.2** by Lucasfilm Games and Totally Games, designed by Lawrence Holland.
Fly the Luftwaffe's jet and rocket aircraft or the American fighters and bombers
sent against them over Europe in 1943–45: training, historical missions, tours of
duty and the full campaign.

The port runs the original game code, translated offline from 16-bit x86 to 68020
by this repository's static translator; there is no x86 emulator. On AGA the game
runs as the original's VGA version (256 colours), on OCS and ECS as its EGA version
(16 colours, 640×200), both on bitplanes with a hardware sprite mouse pointer. The AdLib music and effects are
resynthesised on Paula, the effects once at start into samples; optionally, the
sampled effects of the Amiga **Their Finest Hour** replace the AdLib ones.

Current Amiga release: **1.1 (07.11.2026)**.

## Requirements and installation

- PAL or NTSC Amiga, 68020 or better; **68030 or better recommended**. Flight is slow
  on a 68020; the world still runs at real-time speed. On a 68030, add the WHDLoad
  tooltype `MMU` so the data cache is used (68040 and 68060 use it without). AGA runs
  the VGA version, OCS and ECS the EGA version; the `Custom3` tooltype (1), or `OCS`
  without WHDLoad, selects the EGA version on AGA.
- **1 MB Chip RAM and 8 MB Fast RAM**; with 8 MB, PreLoad holds all game files unless
  other programs use more than about 1 MB of it. With **512 KB Chip RAM**, start the
  **SWotL512K** icon: the AdLib effects do not fit, so it plays the Their Finest Hour
  effects if installed, otherwise none; music plays either way. With 8 MB and PreLoad, add the WHDLoad
  tooltype `NoWriteCache`: WHDLoad 20.1 can hang at exit and lose files the game created.
- WHDLoad 17+, Installer 43+, and a supported Kickstart 3.1 image with its RTB.
- The three 1.44 MB PC floppies of **Air Combat Classics** (LucasArts, 1993), which
  hold version 2.2, as `Disk1.img`–`Disk3.img` or as the files `CLASSICS.001`–`.003`.
  The images are available, for example, in the "The Good Old Days" floppy image
  collection (ID 496). Other releases are not supported.

Extract `SWotL-1.1.lha`, open its **SWotL Install** drawer and run **Install**.
The whdload.de archive leaves out the game executable: download `SWotL` from the
matching [release](https://github.com/Vesuri/swotl/releases) and the installer asks for it.
Select the destination and the drawer with the disks; every file is checked and
damaged or other disks are refused. For Their Finest Hour effects, choose them in
the installer and select `sfx.rsc` from your Their Finest Hour installation; the
`Custom1` tooltype switches later (1 Their Finest Hour, 0 AdLib). Updating keeps
pilots, films and missions (an install of 1.0 or older gets its game files again from
the disks: it lacks `RTSEGA.OVL`). Start the installed **SWotL** icon, or **SWotL512K**
with 512 KB Chip RAM.

No original game code/data, Kickstart image or WHDLoad binary is distributed.
See [the release ReadMe](release/ReadMe) for supported ROM filenames and full
installation instructions.

## Controls

Keyboard and mouse work as in the PC original, with keys at their US keyboard
positions; see the original manual. In flight the mouse's sensitivity is the
same at any frame rate (as the original at about 3 fps). A joystick in port 2 works as the cursor keys,
its two buttons as the left and right mouse buttons. With the `Custom2` tooltype
(1), or `ANALOGJOYSTICK` without WHDLoad, port 2 takes a proportional (analog)
joystick instead: the game calibrates it at start, and Alt+C recalibrates in
flight. Quit from the game's menus; the WHDLoad QuitKey (**Help**) quits immediately.

## Building

The game uses `m68k-amiga-elf-gcc`, `elf2hunk` and vasm; the WHDLoad slave also
needs the WHDLoad SDK includes. Release packaging needs Python 3 and an
LH5-capable LHa encoder. The environment comes from AmigaXDev's `make setup`
([toolchain.md](docs/toolchain.md)).

```sh
. amiga/env.sh
make release          # dist/SWotL-1.1.lha, -whdload.lha (no executable), dist/SWotL; clean tree
make amiga            # standalone executable: amiga/out/Swotl.exe
```

Without WHDLoad, the installed game runs from a Shell in its `data` drawer as
`SWotL`, adding `TFH` for the Their Finest Hour effects, `ANALOGJOYSTICK` for
an analog joystick and `OCS` for the EGA version on AGA (also icon tooltypes). Translator design, tests and the reference setup against the
original under DOSBox are in [architecture.md](docs/architecture.md),
[toolchain.md](docs/toolchain.md) and [pc-reference-loop.md](docs/pc-reference-loop.md);
remaining work is in [open-work.md](docs/open-work.md). The
[documentation index](docs/README.md) lists the rest.

## Credits and licensing

Secret Weapons of the Luftwaffe and its original assets belong to their respective
copyright holders. This is an unofficial fan port, not affiliated with or endorsed
by them. Amiga port by Vesa Halttunen (Vesuri).

The install helper uses the AmigaXDev installer helpers (LGPL-2.1-or-later; see
[its README](tools/install-data/README.md)) and Mark Adler's blast (zlib licence).
Those licences apply to the helper only, not to the original game.
