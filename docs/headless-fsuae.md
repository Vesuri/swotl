# Headless FS-UAE and GDB

The shared launcher, which FS-UAE to use, booting from directory drives, the gdb stub and its
quirks, the diag-run pattern, screenshots, determinism and the pitfalls are maintained in
AmigaXDev `docs/reference/headless-fsuae.md`. This page holds what is specific to SWOTL.

## Scripts

| Script | Role |
|---|---|
| `amiga/run.sh` | audible interactive boot through the shared `fsuae_options`/`fsuae_exec`; `DEBUG=1` adds the gdb stub |
| `amiga/debug.sh [ROM] [fixture.gdb] [exe]` | boot under the gdb stub (startup line `Swotl MUSIC`); with a fixture, run it and exit with gdb's status (`make test-amiga` fills `amiga/milestone.gdb.in`) |

Boot volume: `dh0/s/startup-sequence` runs `C:SetPatch QUIET`, `cd dh1:` and the program; the
user's own `SetPatch` comes from `SETPATCH` and is never committed. Kickstart: the shared
`$KICKSTART` (3.1); `$KICKSTART_A1200` is beside it.

`make test-amiga` captures guest state at the original milestone label, then
waits for that exact queued frame's handoff before capturing visible pixels,
and compares both with the DOSBox-X reference (`tests/host_run.py --amiga`).
A replacement publication or missing success marker fails.

`make test-amiga-restore` exits through the game menu (E), then checks
ActiView, the VERTB vector triple, DMACONR and INTENAR against their saved
values. `amiga_restore_status == 31` means all checks passed. The fixture
requires its success marker; a debugger disconnect is a failure.

`tests/test_amiga_input.py` runs production `Input.cpp` against modeled CIA
and mouse registers. It covers serial decoding, mouse wraparound, all button
combinations and CIA vector restoration; it does not prove emulator routing
or physical input. Both normal and planted-fault checks are in `make gates`.

`FSUAE_INPUT=/path/to/fs-uae bash amiga/hardware_input.sh` drives emulator
keyboard and mouse events through CIA-A SDR, JOY0DAT and button registers.
It checks Return make/break scan codes, both mouse-counter wrap directions,
accumulated motion and all three buttons. `KEYS=` supplies only a timeout.
The fixture requires a Lua-enabled Barto build: use AmigaXDev's
`scripts/build-fsuae.sh fs-uae-input /absolute/path/to/tools/fsuae-input-lua.patch`,
then set `FSUAE_INPUT=~/.local/share/amiga/fs-uae-input/fs-uae`.
The patch enables the core Lua event hook, repairs its dormant build, and
deduplicates Lua settings parsed twice by the frontend, and prevents remote
debugger resumes from discarding the next key release (the local debugger
hotkey rule). It does not modify guest state or the normal validation emulator. The probe observes CPU
registers immediately after hardware loads; the debugger cannot read CIA
registers directly. Load sites are derived from the current executable.
This proves emulated register routing, not physical A1200 input.

`bash amiga/display_audit.sh` captures 40 actual handoffs over the attract
sequence. It compares pixels with guest RAM captured at publication, checks
palette values and conversion targets, and rejects late copper switches.
`AMIGA_CPU=68040` exercises the faster CPU as well. Logs and captures use a
private `tmp/display-audit.*` directory.

## Machine settings

| Setting | Use |
|---|---|
| A1200, 2048 KiB Chip, 8192 KiB Fast (`FAST_KB`/`FAST_MEMORY`) | the scripts' default |
| `AMIGA_CPU=68030` (the Makefile's default for `make test-amiga`) | development model, about 3× the 68020; `A1200/1230` needs the Blizzard 1230-IV ROM, which is absent, and there is no A4000 ROM |
| 68020 (`AMIGA_CPU` unset), 8 MiB Fast | the speed-plan measurement model ([speed-plan.md](speed-plan.md) §4) |

Fast RAM is required (D15, [translator-design.md](translator-design.md)); the release's
Chip/Fast budget is open-work 19. Decide it before the first timing run that matters for the
release, and never time with diagnostic Fast RAM as if it were the target.
