# Headless FS-UAE and GDB

Running and debugging the Amiga build unattended. These rules were learned in the
sibling ports; the source is given in brackets after each one. Paths such as
`amiga/run.sh` and `debug.sh` refer to the sibling pattern that SWOTL copies. Target-side
lessons are in [amiga-lessons.md](amiga-lessons.md), and timing method and
optimisation are in [perf-method.md](perf-method.md) and [m68k-optimisation.md](m68k-optimisation.md).

## Scripts (sibling pattern to copy)

| Script | Role | Source |
|---|---|---|
| `amiga/env.sh` | PATH: `~/.local/opt/bin` (gcc/gdb), `~/.local` (vasm, elf2hunk), `~/.local/fs-uae`; `KICKSTART` default | all |
| `amiga/run.sh` | audible interactive boot, real speed, wipes `.uss`, `exec fs-uae` + `fsuae_track_self` | Slicks `amiga/run.sh` |
| `amiga/debug.sh [ROM] [fixture.gdb]` | boot under the GDB stub; with a fixture: run it, exit with gdb's status, `trap fsuae_stop EXIT` | Slicks `amiga/debug.sh` |
| `amiga/diag_run.sh [secs]` (copy when needed) | boot, run `$GDBSCRIPT`, SIGINT gdb after `secs`, log to `.run/gdb-out.log`, returns early when gdb exits | Revs/RoF/Vette `amiga/diag_run.sh` |
| `~/.local/share/amiga/fsuae_common.sh` | shared PID/port ownership (below) | all |

- Source `. ./env.sh` **in the same shell command** as the run. Otherwise `fs-uae` is "not found" and gdb exits at once, which leaves the old log in place. [RoF, Revs]
- Copy `fsuae_common.sh` in right after `cd "$(dirname "$0")"`: `. "${FSUAE_COMMON:-$HOME/.local/share/amiga/fsuae_common.sh}"`. [all]

## FS-UAE invocation

Slicks `debug.sh` is the closest template (A1200, AGA, 68020):

```sh
fs-uae --audio_driver=dummy \
  --amiga_model=A1200 --chip_memory=2048 --fast_memory=0 \
  --kickstart_file="$ROM" --hard_drive_0="$DH0" --hard_drive_1="$DH1" \
  --joystick_port_0=mouse --joystick_port_1=nothing \
  --automatic_input_grab=0 --fullscreen=0 --window_width=720 --window_height=568 \
  --remote_debugger=20 --remote_debugger_port="$DEBUG_PORT" \
  --remote_debugger_trigger=<ExeName> \
  --ntsc_mode=0 --state_dir="$RUN/state" > "$RUN/fsuae-dbg.log" 2>&1 &
```

- Boot volume: `dh0/s/startup-sequence` = `C:SetPatch QUIET` / `cd dh1:` / `<ExeName> [MODE]`. The exe is copied into `dh1`, and gdb loads the `.elf` from `out/`. [Slicks]
- AGA launchers copy in the user's own `SetPatch` (`SETPATCH`, default `~/.local/share/amiga/SetPatch`, shared with the sibling ports); never committed. [Slicks `docs/toolchain.md`]
- Wait for the stub with `lsof -nP -iTCP:$DEBUG_PORT -sTCP:LISTEN`, polling 60×1 s. Bail out if the FS-UAE PID dies. [Slicks, Revs]
- gdb preamble: `set pagination off`, `set confirm off`, `set remotetimeout 90`, `target remote 127.0.0.1:$DEBUG_PORT`. Run gdb with `-q -l 10` under `HOME=$RUN/gdbhome XDG_CACHE_HOME=$RUN/gdbhome`. [Slicks, Revs]
- FS-UAE keeps the **first** value of a repeated option, so `EXTRA_ARGS` cannot override the script's `--chip_memory/--fast_memory`. Use `CHIP_KB`/`FAST_KB` variables instead. [Revs]
- FS-UAE echoes every option into its log, including misspelt and unimplemented ones. The config dump does not prove an option took effect. `--volume=0` is unimplemented. Use `--audio_driver=dummy`, checked with `lsof -p <pid> | grep -ic CoreAudio` (3 on a normal run, 0 with dummy). [Revs]
- Diagnostic runs are muted. `run.sh` stays audible. Opt in with `FSUAE_SOUND=1`. [Slicks, Revs]
- Audio capture: SDL2 disk backend `SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/abs/path` with `--audio_driver=sdl`. The path must be absolute, and the script refuses to overwrite. [Slicks `debug.sh`]
- Keyboard joystick: the installed build ignores `keyboard_key_*`. `--joystick_port_1=keyboard` gives arrows plus right Ctrl/Alt as fire. [Slicks `debug.sh`]
- Kickstart 1.3 does not boot from a directory drive (gdb never connects). Use WHDLoad kick13 for 1.3. [Revs]
- Kickstart path on this machine: `~/Documents/RetroPie/BIOS/kick31.rom` → symlink to `kick40063.A600` (KS 3.1 A600, SHA-1 `3b7f1493b27e212830f989f26ca76c02049f09ca`). `kick40068.A1200` is beside it. [verified 2026-10-02]

## A1200 model settings

| Setting | Use | Source |
|---|---|---|
| `A1200`, 2048 KiB chip, 0 fast | Slicks target and every timing run | Slicks `run.sh`/`debug.sh`, `docs/performance.md` |
| fast 2048/4096/8192 | diagnostics only, when snapshots do not fit (`SLICKS_DEBUG_FAST_KB`) | Slicks `debug.sh` |
| A1200, 2 MiB chip + 8 MiB fast | Vette diagnostic default | Vette `docs/development.md` |
| `EXTRA_ARGS=--cpu=68040` | exposes beam-timing races that A1200 alone missed | Revs, Vette |
| `--warp_mode=1` | correctness runs only. Slicks refuses warp for benchmark fixtures. Revs: warp leaves emulated-quantity ratios unchanged (~4.9× faster) | Slicks `debug.sh`, Revs `perf-method.md` |
| `--ntsc_mode=0` | PAL | all |
| A1200 + `--cpu=68030`, 8 MiB fast | SWOTL development default (`AMIGA_CPU`, ~3× the 68020); `A1200/1230` needs the Blizzard 1230-IV ROM (absent); no A4000 ROM here | SWOTL |

The SWOTL chip/fast budget is not chosen yet. Decide it before the first timing run, and never time with diagnostic fast RAM.

## GDB stub quirks

- **Writes are silently dropped.** `set var` on a global, an array element, or emulated memory reads back unchanged, with no error. Put every stimulus in the binary instead: a build flag or a startup-sequence mode word (Slicks: `SlicksDiag OPTIONS`, `NATURALB0`, … chosen by env var in `debug.sh`). The `.gdb` only reads. [Revs, RoF]
- **Reads work**: `printf`, `while $i<N … end` loops, `dump binary memory FILE start end` (Slicks uses it for chunky/bitplane frames and PC-sample buffers). [Slicks]
- **Trigger** = `--remote_debugger_trigger=<name>` must match the program name that the startup-sequence runs. [RoF, all scripts]
- **`cd dh1:` + bare name is load-bearing.** A single `dh1:RoF` line made gdb resolve symbols at base `$7500` instead of `~$21f8e0`, so no breakpoint was ever hit and every run looked like a hang. `$7500` also appears when the program never loads, so treat a `$7500` base as "trigger did not match". `cd` is a ROM shell built-in only from KS 2.0 on. [RoF]
- **Symbols**: link `-Ttext=0 --emit-relocs` and convert with `elf2hunk`. gdb reads `out/X.elf` and the stub supplies the load base. Print `&some_function` (`TEXT_BASE=`) when post-processing PCs. Keep the matching `.elf` with the samples. [Slicks `amiga/Makefile`, `pc_profile.sh`, `diag_pc_sample.gdb`]
- **`continue` in the fixture is load-bearing.** Without it the script runs at connect time while the program is halted at the trigger, and every counter reads 0. [Revs]
- **A gdb script aborts at the first unknown symbol**, from that line onward. When you rename or delete a probe global, grep `amiga/*.gdb`. If output stops after the header, suspect the script. [RoF, Revs]
- **`--gc-sections` drops unused probe globals.** gdb then resolves the name into `.text` and prints garbage, not 0. Keep a `PROBE_SYMS` list plus a link-time audit. [Revs]
- **Judge a verdict by where gdb stopped.** A timeout SIGINT makes the script carry on as if the breakpoint hit, so compare `$pc` with the breakpoint address. Break out-of-line functions by address, because a symbolic break can resolve into inlined copies. [Revs]
- **Conditional breakpoints throttle the emulator about 2.5×.** The host evaluates them on every hit. Count in the program and print once at the end. [Revs]
- **GDB interrupts are serviced only at vsync.** GDB PC sampling is vsync-locked, which distorts shares (C2P doubled, car physics hidden). Use a target-side sampler. [Slicks `docs/performance.md`]
- **The remote debugger greys the display.** A headless run proves state and cost, never appearance. [Revs]
- `Remote connection closed` mid-run usually means another session killed the emulator. Check `pgrep -fl "diag_run.sh|fs-uae"` before suspecting the build. [Revs]

## Diag fixture pattern (`debug.sh "" fixture.gdb`)

- Empty first argument = default ROM. A mode env var selects the startup-sequence argument. gdb's exit status is the verdict. [Slicks]
- Break on named marker functions (`*_ready`, `*_system_restored` = early exit → `quit 1`). In `commands … silent`, print `KEY=value` lines (`BENCHMARK`, `FINAL_STATE`, `*_INVALID`), then `quit` or `quit 1`. The script ends with `continue` / `quit 1`. [Slicks `diag_benchmark.gdb`, `diag_pc_sample.gdb`]
- Validate the instrument before the result. Examples: `*_INVALID` when profile flags, frame count or spill counters are wrong; Revs' `accounted ≈100%` and `body ticks/field ≈1` sanity lines. [Slicks, Revs]
- One run directory has one owner. Run captures serially when scripts share dump filenames. For long validations, freeze the exe and elf (`POKERI_EXE/POKERI_ELF`). [Pokeri `docs/testing.md`]
- Read `.run/gdb-out.log`, not `diag_run.sh` stdout, which is `tail -40` and drops headers and early phases. Copy the log per arm as soon as the run ends. [Revs]
- **A failed run leaves the old log.** Check it with `date; ls -l amiga/.run/gdb-out.log`, or grep for a string that only the new script prints. [Revs]
- The `secs` argument is a safety ceiling. Reaching it is not success. Require an explicit PASS record. [Vette, Revs]

## Screenshots and frames

- Interactive: hold F12 and press S. The destination comes from env `FSEMU_SCREENSHOTS_DIR`. `--screenshots_output_dir` is parsed but ignored. [Revs, Vette]
- Headless: `dump binary memory` the chunky buffer or bitplanes from gdb, then compare on the host (Slicks `tools/verify_amiga_frame.py`: 320×200 chunky vs 8 interleaved planes, 40 B/plane row). [Slicks]
- Appearance checks need `run.sh` with a wiped `.uss`. [Revs]

## State-file pitfalls

- `--state_dir="$RUN/state"`. `run.sh` does `rm -f "$RUN"/state/*.uss` on every run. Diag runs share the state dir and can leave a state saved while the CPU was halted on a grey first frame. Resuming that state makes any build look frozen and grey, which cost hours of false bisecting. [Revs, Slicks `run.sh`]
- Never rebuild (`make` or `make clean`) while a run is live. gdb reads symbols from `out/*.elf` in place. [Revs, Slicks, Pokeri]
- **Stale build**: the Amiga Makefile tracks neither `-D` flags nor header dependencies in RoF/Revs. `make clean` after a flag toggle or a shared-header edit. A partial rebuild links a working-but-wrong binary. Slicks avoids this with mode-stamp files (`obj/inner-profile-$(X).stamp`) and `-MMD`, but SHADOW/RETCHECK still need a forced rebuild. [RoF, Revs, Slicks `docs/performance.md`]
- After editing a shared harness script, rerun a known-good control on an unchanged binary in the same session. [RoF]

## Port and process ownership (`fsuae_common.sh`)

| Function | Effect |
|---|---|
| `DEBUG_PORT` default | `2345 + cksum($PWD) % 40`, deterministic per checkout. Override with `$DEBUG_PORT` |
| `fsuae_stop_previous` | kill the PID in `$FSUAE_RUN/fsuae.pid` (default `.run`) only if it is still `fs-uae` |
| `fsuae_claim_port` | reclaim the port from our own leftover fs-uae. Exit if a non-fs-uae process holds it |
| `fsuae_track PID` / `fsuae_track_self` | record the emulator (use `_self` before `exec`) |
| `fsuae_stop` | kill the tracked emulator. Safe in `trap … EXIT` |
| `fsuae_gdb_script F` | copy of F with `127.0.0.1:NNNN` patched to `$DEBUG_PORT` |

- Never `pkill fs-uae` or `pkill gdb`, because that kills other projects' runs. Kill by PID. [Revs, Pokeri]
- Parallel runs need a distinct `FSUAE_RUN` and `DEBUG_PORT` (Slicks `pc_profile.sh`: `FSUAE_RUN=.run/pcprof-$LABEL DEBUG_PORT=2394`). [Slicks]
- Close every emulator session you start. [Slicks `docs/development-verification.md`]

## Timing under emulation

| Rule | Source |
|---|---|
| Measure in raster lines (64 µs; PAL frame = 312 lines) or PAL fields/beam phase. Do not use host wall time | Slicks `performance.md`, Pokeri, Vette |
| Use no gdb stop inside a timed window. A breakpoint only at the end-of-window marker | Slicks `diag_benchmark.gdb`, Revs |
| Target-side CIA-B PC sampler (~614 Hz, xorshift-jittered, level-6 frame) adds ~12% uniform overhead, so use it for shares only | Slicks `pc_profile.sh`, `performance.md` |
| Compare against a parent-commit control from the same session. A behaviour-preserving change must reproduce `FINAL_STATE` exactly | Slicks |
| Instrumented builds are for counting only, never timing. Never diff share tables across builds | Revs `perf-method.md` |
| Emulated timings are not physical-hardware timings | Vette `performance.md` |
| `cpu_speed=max` or disabled cycle accuracy invalidates speed evidence. Audit `fsuae-dbg.log` for overrides | Pokeri `rom-set.md` |
| An instrument change must be shown to leave measurements unchanged (silent vs audible: 17.181 vs 17.194 ms) | Revs |

The cost model and 68020 optimisation are in [perf-method.md](perf-method.md) and [m68k-optimisation.md](m68k-optimisation.md).
