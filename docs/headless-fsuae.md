# Headless FS-UAE and GDB

The shared launcher, which FS-UAE to use, booting from directory drives, the gdb stub and its
quirks, the diag-run pattern, screenshots, determinism and the pitfalls are maintained in
AmigaXDev `docs/reference/headless-fsuae.md`. This page holds what is specific to SWOTL.

## Scripts

| Script | Role |
|---|---|
| `amiga/run.sh` | audible interactive boot through the shared `fsuae_options`/`fsuae_exec`; `DEBUG=1` adds the gdb stub |
| `amiga/debug.sh [ROM] [fixture.gdb]` | boot under the gdb stub; with a fixture, run it and exit with gdb's status (`make test-amiga` fills `amiga/milestone.gdb.in`) |

Boot volume: `dh0/s/startup-sequence` runs `C:SetPatch QUIET`, `cd dh1:` and the program; the
user's own `SetPatch` comes from `SETPATCH` and is never committed. Kickstart: the shared
`$KICKSTART` (3.1); `$KICKSTART_A1200` is beside it.

## Machine settings

| Setting | Use |
|---|---|
| A1200, 2048 KiB Chip, 8192 KiB Fast (`FAST_KB`/`FAST_MEMORY`) | the scripts' default |
| `AMIGA_CPU=68030` (the Makefile's default for `make test-amiga`) | development model, about 3× the 68020; `A1200/1230` needs the Blizzard 1230-IV ROM, which is absent, and there is no A4000 ROM |
| 68020 (`AMIGA_CPU` unset), 8 MiB Fast | the speed-plan measurement model ([speed-plan.md](speed-plan.md) §4) |

The chip/fast budget of the release is not chosen yet. Decide it before the first timing run
that matters for the release, and never time with diagnostic Fast RAM as if it were the target.
