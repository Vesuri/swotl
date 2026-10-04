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

## SWOTL loop

Facts about the originals: [source-inventory.md](source-inventory.md).

| Piece | How |
|---|---|
| Emulator | DOSBox-X `dosbox-x-v2026.08.31` + `tools/patches/` in `ORDER`; `make reference-emulator` (tree in `~/.local/src/swotl-dosbox-x`, linked from `tools/vendor/dosbox-x`: autoconf fails on the repo path's spaces) |
| Config | `reference/dosbox-x.conf`: `svga_s3`, 4 MB, `core=normal`, `cputype=386`, `cycles=fixed 12000`, `nosound`, SB16 220/7/1 |
| Run | `make reference-run RUN=name RUN_ARGS=...` → `tools/pc_run.py`: fresh `tmp/pc-runs/<name>/root/` copy of `ref/`, headless, `swotl V S 5 N Y Y 64`. Exit 0 = `SWOTL_EXIT_AFTER` snapshot reached, 2 = time limit, 3 = guest fault (INT 0/6), 4 = no trace output |
| Arming | first instruction at `PSP+10h+1617h:0382h`; off unless `SWOTL_TRACE` |
| Addresses | `(module, offset)`: root = image offset; overlay = `.OVL` file offset of the bytes the last DOS read put at that paragraph; `-` = unowned linear address |
| Determinism | BIOS tick count set to `SWOTL_BIOS_TICKS` (0) at arming; DOS time and INT 1Ah derive from it, so the RNG seed (DOS time) is fixed. Every milestone repeats byte-identical |
| Input | `SWOTL_KEYS=MODULE+HEX[#N]=key,...`: press when the guest reaches that instruction (Nth time since the previous key's release), release after `SWOTL_KEY_HOLD` instructions |
| Snapshot | `SWOTL_SNAPSHOTS=name@MODULE+HEX[#N],...`: counted after the key script, each after the previous; `snap-<name>/` with `ram.bin` (1 MiB; the EMS frame E0000h–EFFFFh read through its page handlers, i.e. the mapped pages), `vram.bin`, `dac.bin`, `regs.txt`, `residency.csv`, `writes.csv` (last CPU writer per byte of module-owned paragraphs since load) |
| Summary | `make trace-summary RUN=name` |
| Image proof | `tools/load_image.py <snap>` (gate 1, also run by `make reference`): rebuilds root + overlays from `ref/` with the loader model ([source-inventory.md](source-inventory.md)); every byte of every resident row equals the rebuilt byte, the last traced DOS read, or has a CPU writer. Lists self-modified executed bytes by writer |

Trace outputs (`tmp/pc-runs/<name>/trace/`, written at exit):

| File | Content |
|---|---|
| `events.csv` | ordered: arm, DOS open/read/seek/close (name, linear buffer, file pos), INT 10h/33h/67h and selected INT 21h with registers, faults, keys, snapshots; with `--services` (`SWOTL_SERVICES`, on in `make reference`) `svc`/`svc_ret`: every software INT raised by module code with all registers and FLAGS at entry and when execution is back at its return address with the entry SP (the runtime's service oracle); with `--polls` (`SWOTL_POLLS` = `build/gen/poll-points.csv`, on in `make reference`) hardware interrupts are taken only before a translator poll point (D8) and logged as `irq`: vector, service events so far, the poll point's executions since the last one (taken before the instruction, so interrupts arriving during a handler repeat the same count after its IRET); `summary.txt` `polls=` is the FNV-1a of that file |
| `modules.csv`, `executed-<module>.bin` | per-module instruction-start bitmap |
| `edges.csv` | unique consecutive-instruction pairs |
| `interrupts.csv`, `ports.csv`, `vga.csv` | aggregates by source site (AX for software INTs; port value; 256-byte VGA page) |
| `code-writes.csv` | CPU writes into paragraphs that have executed since their last load |
| `residency.csv` | paragraph ranges → module at exit |
| `plink.csv` | calls of the PLINK load routine: caller, overlay id, via thunk, resident before, loaded, caller intact, count ([plink.md](plink.md)) |

Milestones: `reference/milestones.csv`, run by `make reference`
(`tools/reference.py`): every snapshot reached, modules resident, BIOS
video mode, consecutive snapshots differ in RAM and VRAM, image proof,
last-snapshot RAM/VRAM/DAC hashes equal to the previous run
(`tmp/reference-hashes.csv`). Frames: `tools/snap_png.py <snap>`.

Keys `K2` = Enter at `kbhit` (`SWOTL.EXE+13ED3`) #3000 (skips the logo),
Enter at the mouse poll `+44E2` #300 (leaves the demo). Menu keys are the
red letters, pressed at `+44E2` #200 after the previous release. `+44E2`
runs once per frame in flight, every ~645 instructions in menus.

| Milestone | Input | Signal |
|---|---|---|
| m0-entry | none | `SWOTL.EXE+164F2` (MZ entry) |
| m1-mode13h | none | `RTSVGA.OVL+390D`, after INT 10h AX=0013h |
| m2-choose-side | K2 | "CHOOSE A SIDE" (FRONTEND + NOTCAMP), `+44E2` #600 |
| m3-demo-flight | none | `REPLAY.OVL+31E6` #1: `DEMO1.DEM` attract flight |
| m4-demo-frames | none | `+44E2` #150 and 50 frames later; scene advances |
| m5-player-flight | K2, U (US), F (flight school), 1 (P-47), 1 (gunnery), S (start) | FLIGHT + PANEL cockpit, `+44E2` #400 and 50 frames later |
| m6-film-room | K2, U, V | film viewing room (REPLAY + FLIGHT) |
| m7-campaign | K2, U, B, S | new campaign (CAMPAIGN) |

All nine in-scope overlays are captured and pass the image proof.

Coverage scripts: `reference/coverage.csv`, run by `make coverage` (same
checks; no determinism history needed). They feed the phase 2 map
(`make map`: sweep, PLINK check, code-write audit, surface).

| Script | Input after K2 | Reaches |
|---|---|---|
| c1-historical | U, H, 1, 1, S | historical mission flight |
| c2-german-school | G, F, 1, 1, S | Luftwaffe flight school flight |
| c3-custom | U, C, 1, 1, S | custom missions menus |
| c4-tour | U, T, 1, 1, S | tour of duty menus |
| c5-records | U, R | combat records (CAMPAIGN) |
| c6-flight-keys | m5 path, then 47 keys at 30-frame intervals in flight | in-flight controls, gun camera film room (REPLAY, `RP*.TMP` written) |

Facts from these runs:

- Unattended: logo, then the `DEMO1.DEM` attract flight (FRONTEND, FLIGHT,
  REPLAY). Esc on the logo asks "DO YOU WANT TO EXIT? (Y/N)". No code-wheel
  screen on the path to m2.
- During the demo the only input polled is INT 33h (`+44E2`/`+44FA`);
  keyboard input there arrives without an observed poll (BIOS buffer read
  likely).
- Determinism: RAM/VRAM/DAC at every milestone are identical across runs.
  Without `--polls` the instruction count at a milestone can differ
  (interrupt arrival points vary with host tick interleaving); with it,
  interrupts wait for a poll point and the run repeats exactly, instruction
  count included.
- RNG: root `+DC91`, 16 rounds of shift/XOR over `[255E..255F]` with carry
  into `[255C]` (returned); seeded at `+DCB1` from INT 21h AH=2Ch DX (DOS
  time, fixed by the pinned tick count). Not the MS C `rand`.
- CPU: executed code is 8086-only (no 186/286/386 opcodes outside the
  self-modified block, no CPU probe). Primary `cputype=386`; 286 differs
  only in interrupt arrival points and PUSHF's upper flag bits (PLINK saves
  `7202h` vs `0202h`).
- Video: chained mode 13h; mode and palette only via INT 10h (AX=0013h,
  1012h, 1017h); no guest VGA port access, no page flipping; only RTSVGA
  writes VGA memory. DOSBox-X stores chained byte `a` at
  `vram[((a & ~3) << 2) | (a & 3)]`.
- Self-modifying code: `SWOTL.EXE+4FF0/+4FFC` rewrite single bytes at 678
  sites in the unrolled block `+6A4D..+899A` (+5132/+513D, +52CE/+52DA
  likewise); `+8FD5/+9030/+908E` patch words in `+7C3F..+8998`. Writes
  around `+E4E0` and `+49B0` look like code-segment variables.
