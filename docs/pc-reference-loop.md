# PC reference loop

Ground truth is the original v2.2 game running unattended under a PC emulator,
never a host approximation and never the Amiga build compared with itself
([../CLAUDE.md](../CLAUDE.md)). This doc distils how Slicks built its loop, plus the
general lessons of the BBC (Revs) and Mac (Vette) loops. **[PLAN]** marks SWOTL
adaptations that do not exist yet. Tool versions are in [toolchain.md](toolchain.md).

## Slicks: what was built

| Piece | How | Source |
|---|---|---|
| Disposable root | `rsync -a ref/ tmp/pc-root/`, so the game never writes into `ref/` | `Makefile prepare-reference` |
| Fixed-input root | `tmp/pc-fixed/` keeps only one track (`TRACKS/BASIC.SS`) to remove random track choice | `prepare-fixed-reference` |
| Two CPU personalities | DOSBox-X `cputype=286` = primary semantic trace. DOSBox Staging 386 = independent comparison. The runtime has a CPU probe and an optional 386 library path. A milestone must agree on both, or the difference is attributed to CPU-dependent library code | `docs/reference-contract.md` |
| 286 config | `machine=svga_s3`, `memsize=2`, `core=normal`, `cputype=286`, `cycles=3000` (overridden by `-set "cpu cycles=12000"` for scripted runs), `nosound=true`, `output=surface`, `[log] logfile=` | `reference/dosbox-x-286.conf` |
| Headless run | `env SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -conf … -set "cpu cycles=12000" -nogui -nomenu -silent -fastlaunch -time-limit 36 -c "mount c $ROOT" -c "c:" -c "autotype -w 15 -p 0.2 down enter , enter , enter , esc , up enter" -c "dx-capture /v /-a /-d slicks.exe"` | `reference-race` |
| Input | DOSBox-X `autotype -w <initial wait s> -p <pace s> keys…` (`,` = extra pause). A patched `mouse.cpp` adds an env-armed click: `SLICKS_MOUSE_CLICK_MS/_X/_Y`, release after 100 ms, logged with `PIC_FullIndex()` | Makefile, `dosbox-x-slicks-mouse.patch` |
| Frames | `dx-capture /v` → AVI. `ffmpeg -ss T -i avi -frames:v 1 [-vf crop=…] -f rawvideo -pix_fmt rgb24 -` → SHA-256 | `tools/verify_reference_race.py` |
| DOS/video log | DOSBox-X log parsed for `Executing interrupt 21, ah=`, filenames, `Set Video Mode` | `tools/summarize_dosbox_x.py` |
| Instrumented emulator | vendored source + patches, built separately (`DOSBOX_X_TRACE`). Run with `cd $ROOT` because outputs go to cwd | `reference-trace`, `tools/patches/` |

### Instrumentation hooks (DOSBox-X patches)

| Hook point | Output (cwd) | Content |
|---|---|---|
| per instruction, `CPU_Core_Normal_Run` and `CPU_Core286_Normal_Run` after `LOADIP` | `slicks-executed.bin`, `slicks-edges.csv` | byte bitmap of executed instruction starts + unique `(from,to)` transitions, offsets relative to the runtime base |
| `cpu.cpp` interrupt entry | `slicks-interrupts.csv` | sequence, vector, type, source/target CS:IP, normalised offsets, AX..FLAGS |
| `paging.h` mem read/write inlines | `slicks-memory.csv` | aggregates of VGA (`A0000–BFFFF`) reads/writes and writes into the runtime image |
| `iohandler.cpp` | `slicks-ports.csv` | port in/out aggregates |
| fixed guest offsets in the 286 core | `slicks-primitive-calls.csv`, sprite blobs, palettes, `slicks-race-state.csv`, `slicks-race-data.bin`, `slicks-engine-state.csv` | call-time argument tuples, VGA palettes and application state at named routines |
| optional probes | `LOG_MSG("SLICKS_… key=value")` lines | gated by env (`SLICKS_TRACE_LAYERS`, `_POOL`, `_PAGES`, `_ENGINE`, `SLICKS_TITLE_TIMING`, `SLICKS_PITCH_PROBE`) |

- Tracing is **armed by a proven guest event**: the Compack decoder's far `JMP` (`EA`) at a known CS:IP. The runtime base and size come from the live registers, so traces are load-address independent. [`dosbox-x-slicks-trace.patch`]
- Files are written from `std::atexit`, so a run must end cleanly (`-time-limit`).
- Staging patch `dosbox-staging-slicks-handoff.patch` dumps the image at the same event (`slicks-handoff.bin` + `-state.json` registers). The image is normalised (relocation delta, five load-specific words) and `cmp`'d against an independent Unicorn unpack. This is milestone R0. [`make verify-runtime`]
- Post-processing: `tools/summarize_{execution,interrupt,port,memory}_trace.py`, `summarize_primitive_calls.py`, `analyze_execution_trace.py` (capstone decode + async-interrupt correlation), `analyze_vga_sites.py`. Their outputs feed `ghidra_scripts/SeedLiveMap.java`.
- Trace products per milestone: executed addresses and blocks, direct and indirect edges, interrupts with registers, port I/O, writes to executable regions, DOS file open/read/write/seek with names, framebuffer and app-state hashes. Addresses are normalised to the load segment. All are local-only. [`docs/reference-contract.md`]

### Contract rules

- Every milestone has a **positive completion signal** from guest state. A time limit is never a success. The harness stops with a distinct reason: success, limit, unsupported event, or guest failure. [`reference-contract.md`]
- A negative observation needs a positive control proving that the surrounding path ran. [`validation-harness.md`]
- Gate on stable crops, not full frames, once the simulation runs. AI and timer state drift across runs, so full race frames only prove advancement (they differ within a run) and are not a cross-run gate. [`reference-contract.md`]

## What went wrong (Slicks)

| Belief | Reality | Fix |
|---|---|---|
| The 8 s title frame waits for input | it was a loading splash. At 12,000 cycles the game reaches the menu unattended | identify input waits from guest state, not from a stable frame |
| Keys do not dismiss the title, so mouse injection is needed | the frame was not waiting for input at all | mouse patch built anyway. Confirm the wait first |
| A single Enter on `GO !!!` starts a race | the defaults are three CPU opponents and no human. Enter only ran setup and returned to the menu | script: `PLAYERS` → add player → `GO !!!` |
| A one-key reference was a sustained race | disproved later. The refreshed trace changed the coverage | re-verify the reference whenever the script changes |
| Random track | removed by a single-track disposable root | constrain inputs at the filesystem level |
| Wall/video-time `autotype` is deterministic | still open in Slicks: replace it with a guest-state-triggered key | trigger input on guest state |

## General lessons (Revs BBC, Vette Mac)

- **Build the loop first**, before the port needs it. A composed or loaded image is a reconstruction until it is diffed against a live dump. [Revs `bbc-reference-loop.md`]
- **Acknowledge every stimulus on guest state.** Press the key the code is polling, and hold until the state variable changes. Timed taps and "buffer already holds the byte" checks failed silently. [Revs]
- Prove injection where success is visible (e.g. a prompt) before blaming it inside a blind game state. [Revs]
- **Check that the scene changes**. A parked or static scene gives byte-identical, confident, useless samples. Provoke the state before you record a cell as dead. [Revs]
- Snapshot at a **named guest PC**, not at a frame boundary, and use the same PC on both sides. Use write-watch with the writer PC, and tuple peeks per frame. [Revs `make viewdiff`]
- Match **game state, not ordinal frame numbers**. Use absolute frame/event anchors, never guessed waits. Fix RNG seeds on both sides. [Vette `mac-reference-loop.md`, Revs]
- Headless hygiene: `SDL_VIDEODRIVER=dummy` (MAME `-video none` alone still opened a window), explicit cfg/nvram/output dirs so state does not leak into the repo, `timeout -k`, and kill only your own PID. [Vette]
- Code identity is (live segment, offset), not a raw address. Attribute callers live. [Vette]
- The pointer cursor can be **in the pixels**. Park it outside the crop before a capture. [Vette]
- Emulator speed flags (`-nothrottle`, cycles) change host speed, not emulated-time quantities. [Vette]

## SWOTL adaptation [PLAN]

Facts (verified 2026-10-02):

| Item | Value |
|---|---|
| Launcher | `ref/sw.bat` = `swotl V S 5 N Y Y 64` (no trailing newline). Per the manual, written by INSTALL option 2. Argument meanings not decoded |
| `SWOTL.EXE` | 100,112 B, SHA-256 `0223a4e3fc063a591d17cf789b8e9b3ec03eac925c935688ab78a98f05444915`. MZ: 1,006 relocs, 256-paragraph header, CS:IP `1617:0382`, SS:SP `4A9E:0800`. String "Copyright (C) 1984, 1985, 1986 by Phoenix Software Associates Ltd." |
| Overlays | `FRONTEND`, `CAMPAIGN`, `NOTCAMP`, `FLIGHT`, `PANEL`, `REPLAY`, `DATA`, `SFXA`, `SPAZ`, `RTSVGA`, `RTSEGA`, `RTSTANDY` `.OVL` (4–103 KB) |
| Demo/film data | `DEMO1.DEM`, `DEMO2.DEM` (915 B), `514.DEM` (7 B). The manual's Film Viewing Room replays recorded film. Format unknown |
| Memory | READ.ME: ≥592,000 B free, or 550,000 B with EMS |
| Current config | `reference/dosbox-staging.conf`: `memsize=4`, `cpu_cycles=12000`, `core/cputype=auto`, SB16 220/7/1, autoexec `mount c "ref"` → `call sw.bat` → `exit` |

Plan, adapted from Slicks:

- **[PLAN]** Run from a disposable `tmp/pc-root` copy, not `ref/`. The current conf mounts `ref` directly, and the game saves pilots, missions and films.
- **[PLAN]** No Compack, so arm tracing on the MZ entry (`1617:0382` relative to the load segment). Log every INT 21h open/read of `*.OVL` with its destination segment. Normalise addresses as **(module, offset)**, where module = EXE or overlay name. One overlay buffer can hold different code over time (the Vette segment lesson).
- **[PLAN]** Overlay residency: the executed-bitmap and edge traces must be keyed per resident overlay. Writes into the overlay area are expected at load and must be told apart from self-modifying code.
- **[PLAN]** Decode the `sw.bat` arguments, likely video/sound/control/memory choices (`RTSVGA/RTSEGA/RTSTANDY`, `ADLIB.SFX`/`SFX.SFX`), from the EXE's argv parsing before relying on them. Pin one argument set for the reference.
- **[PLAN]** CPU personality: check SWOTL for a CPU probe or 386 paths before choosing 286 vs 386. Keep one primary plus one independent comparison, as Slicks did.
- **[PLAN]** Video is mode 13h. Capture the 64,000-byte `A0000` framebuffer and the DAC palette at a named guest PC (an emulator hook), not only from AVI, so the Amiga side can compare chunky bytes directly (Slicks `verify_amiga_frame.py` pattern).
- **[PLAN]** Input: keyboard via `autotype` for menus, triggered on guest state (menu-poll routine) rather than pace. Joystick and mouse via an env-armed emulator patch like Slicks' mouse patch. Evaluate `DEMO*.DEM` and film replay as deterministic flight-input sources.
- **[PLAN]** Determinism: find the RNG and timer sources (PIT, BIOS tick) and seed or pin them. Manual time acceleration (2/4/8/16×) affects frame/tick relations, so record it as part of milestone state.
- **[PLAN]** Milestones, each with a positive guest signal: entry reached → mode 13h set → each overlay loaded → front-end menu → mission start → N flight frames advancing.
