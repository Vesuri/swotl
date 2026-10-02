# Secret Weapons of the Luftwaffe for the Amiga

A port of Totally Games / Lucasfilm Games' 1991 DOS flight simulator Secret
Weapons of the Luftwaffe to the Amiga. Work has not started yet; the porting
approach is still being decided.

No original game data, manual, ROM or OS component is in this repository.
Reference work needs the original version 2.2 game installed under the
ignored `ref/` directory.

## Running the original

```sh
dosbox-staging -conf reference/dosbox-staging.conf
```

## Amiga toolchain

The cross-toolchain and FS-UAE are the shared `~/.local` install used by the
sibling ports (Slicks 'N' Slide, Rescue on Fractalus, Revs, Vette, Pokeri):

```sh
. amiga/env.sh
```
