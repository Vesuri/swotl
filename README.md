# Secret Weapons of the Luftwaffe for the Amiga

A port of Totally Games / Lucasfilm Games' 1991 DOS flight simulator to the
A1200 (68020, AGA). The original 16-bit x86 code is translated offline to
68020 assembly by this repository's translator, on a dA JoRMaS framework
platform layer. No x86 emulator, no generated C. See
[docs/architecture.md](docs/architecture.md).

No original game data, manual, generated code, ROM or OS component is in
this repository. Reference work needs the original v2.2 under the ignored
`ref/` and `SetPatch` at `tmp/SetPatch`.

```sh
make amiga        # amiga/out/Swotl.exe
make smoke        # boot under FS-UAE + GDB, check the takeover runs
amiga/run.sh      # interactive A1200 boot
make reference-staging   # the original, from a disposable copy
```

Open work: [docs/open-work.md](docs/open-work.md).
