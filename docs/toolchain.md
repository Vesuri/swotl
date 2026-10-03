# Toolchain

The host is macOS on Apple Silicon. Every version below was checked on this machine on
2026-10-02 with `which`/`--version`/`ls`. "Missing" means it was not found. Sibling
provenance is in brackets.

## Amiga cross-build (`. amiga/env.sh`, same shell command as the use)

| Tool | Path | Version / note |
|---|---|---|
| `m68k-amiga-elf-gcc` (+`as`, `ld`, `objdump`, `addr2line`, `gstack`) | `~/.local/opt/bin` | GCC 15.1.0; binutils 2.44.50.20250202 |
| `m68k-amiga-elf-gdb` | `~/.local/opt/bin` | GDB 17.0.50.20250202-git |
| `vasmm68k_mot` | `~/.local` | prints no version |
| `elf2hunk` | `~/.local` | AROS, "Modified 2018-2020, Bartman/Abyss" |
| gcc8 support | `~/.local/support/gcc8_{a_support.s,c_support.c,c_support.h}` | Slicks: `SUPPORT = $(dir $(which CC))../../support` |
| NDK headers | `~/.local/opt/m68k-amiga-elf/sys-include` | Slicks: `SDKDIR` |
| FS-UAE | `~/.local/fs-uae/fs-uae` | `0.0.0-remote_debug.0`, SDL2 bundled |
| Shrinkler, exe2adf | `~/.local` | Shrinkler dev build (Bartman stats) |
| WHDLoad dev files | `~/.local/share/amiga/WHDLoad` | see [whdload.md](whdload.md), [release.md](release.md) |
| Kickstart | `~/Documents/RetroPie/BIOS/kick31.rom` → `kick40063.A600` | see [headless-fsuae.md](headless-fsuae.md) |

- The toolchain comes from BartmanAbyss `vscode-amiga-debug`. Its gcc, gdb, elf2hunk and FS-UAE are matched builds, which is what makes source-level debugging work. [RoF `docs/toolchain.md`]
- The toolchain must sit at a space-free path. GCC LTO bakes the install path into `COLLECT_LTO_WRAPPER` and `posix_spawnp`s it, so a path like `…/Secret Weapons of Luftwaffe/…` breaks. Hence `~/.local`. [RoF]
- Slicks flags: `-m68020 -msoft-float -O2 -nostdlib -fomit-frame-pointer -ffunction-sections -fdata-sections -Wall -Wextra -Werror`, vasm `-m68020 -Felf -quiet -x -no-opt`, link `-Wl,--emit-relocs,--gc-sections,-Ttext=0,-Map=…`, then `elf2hunk X.elf X.exe` under `.DELETE_ON_ERROR`. [Slicks `amiga/Makefile`]
- Pokeri and Vette audit every link and fail the build if 32-bit software mul/div (`__mulsi3` and similar) is linked. [Pokeri `amiga/ARCH.md`, Vette old `docs/toolchain.md`]
- `brew install` on this machine triggers a Privileges.app elevation prompt. The user must start installs or approve the prompt. [RoF, Vette]

## Archives

| Tool | Path | Version | Use |
|---|---|---|---|
| LHa for UNIX | `~/.local/opt/lha/bin/lha`, `~/.local/bin/lha-compress` | 1.14i-ac20260723 | LH5 encoding (Vette: set `LHA` or install as `lha-compress`) |
| Lhasa `lha` | `/opt/homebrew/bin/lha` | 0.6.0 | independent archive verification [Vette] |
| olha | `~/.local/bin/olha` | 0.4.4 | — |
| 7-Zip `7zz` | `/opt/homebrew/bin` | 26.03 | `tmp/*.7z` (`7z` missing) |
| unar / lsar | `/opt/homebrew/bin` | 1.10.7 | — |

## Ghidra (headless)

| Item | Value |
|---|---|
| Install | shared `~/.local/share/ghidra/ghidra_12.1_PUBLIC`; `tools/ghidra` is a symlink to it |
| JDK | OpenJDK 21.0.12.1 at `/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home` |
| Project | per-repo `tools/ghidra-proj/` (git-ignored; it is the annotation database and must not be shared) |

- Set `JAVA_HOME` (the Slicks Makefile exports it). `/usr/bin/java` is the macOS stub ("Unable to locate a Java Runtime"). Headless gives "no TTY detected" instead of prompting. [Slicks, Vette; stub verified]
- The `.gitignore` entry `tools/ghidra` has no trailing slash, because a trailing slash does not match a symlink to a directory. [RoF, Vette]
- Do not open a project in the GUI and headless at the same time, because Ghidra locks it. [RoF, Revs, Vette]
- `MarkEntries` must be a `-preScript`, so new entries are disassembled by the analysis that follows. `-noanalysis` is only for export-only runs. [Vette, Revs]
- Re-run against an existing program with `-process <name>` instead of `-import`. [RoF, Revs]
- Slicks x86 real-mode invocation (raw runtime image):
  ```sh
  "$GHIDRA/support/analyzeHeadless" tools/ghidra-proj Slicks \
    -import disasm/runtime.bin -processor "x86:LE:16:Real Mode" \
    -loader BinaryLoader -loader-baseAddr 0x10100 -scriptPath ghidra_scripts \
    -preScript MarkEntries.java -postScript ExportListing.java "$ABS/disasm/listing.txt"
  ```
  Slicks also imported its relocation-normalised MZ (`runtime.exe`) with the default loader. It kept separate projects per input (`ghidra-proj`, `-normalized-proj`, `-live-proj`, `-live-normalized-proj`, `-gameplay-proj`). [Slicks `Makefile`]
- Slicks scripts: `MarkEntries.java`, `ExportListing.java`, `SeedLiveMap.java` (live entry points and VGA sites from reference traces), plus `entrypoints.csv` and `vga-symbols.csv`. Earlier ports add `ApplyNames.java` (`disasm/symbols.csv` → project), `DumpHwAccesses`, `DumpCallGraph`, `DumpZeroPage`. [Slicks `ghidra_scripts/`, RoF, Revs]
- SWOTL: `make ghidra` (`tools/ghidra_import.py`): one program per in-scope module at its link address, entries from the sweep (`ghidra_scripts/MarkEntries.java`), listings `tmp/ghidra/<module>.txt`. Ghidra's auto-analysis decodes more than the sweep proves; the sweep is the classification of record.
- Track only curated `disasm/symbols.csv`. Listings and images are regenerable and ignored (SWOTL `.gitignore` already does this). [RoF]

## PC reference emulators

| Tool | Path | Version | Role in Slicks |
|---|---|---|---|
| DOSBox Staging | `/opt/homebrew/bin/dosbox-staging` | 0.83.0 | interactive reference; independent 386 comparison; handoff capture (patched build) |
| DOSBox-X | `/opt/homebrew/bin/dosbox-x` | 2026.08.31 SDL2 | primary 286 reference (`cputype=286`), scripted runs, AVI capture |
| Bochs | `/opt/homebrew/bin/bochs` | 3.1 | listed as instruction/memory/branch/I/O instrumentation. No Slicks Makefile target uses it |
| ffmpeg | `/opt/homebrew/bin/ffmpeg` | 9.0.2 | RGB24 frame extraction and hashing from DOSBox-X AVI captures |

- **Instrumented builds**: Slicks vendored source under the git-ignored `tools/vendor/` and kept its changes as `tools/patches/*.patch` (1,691 lines). [Slicks]
  - DOSBox-X: tag `dosbox-x-v2026.08.31` (4f19017c), `./configure --enable-debug=heavy --enable-sdl2 --disable-sdl2test --disable-sdl --disable-sdltest`, binary `tools/vendor/dosbox-x/src/dosbox-x` (Makefile `DOSBOX_X_TRACE`). The patches hook `core_normal.cpp`/`core_normal_286.cpp` (per-instruction), `cpu.cpp` (interrupts), `paging.h` (memory), `iohandler.cpp` (ports) and `mouse.cpp` (scripted click).
  - DOSBox Staging: `v0.83.0`, CMake/Ninja in `build-trace/`, one patch (`dosbox-staging-slicks-handoff.patch`). Its working tree also carries unrecorded CMake/renderer edits.
  - The patches stack: later patches' context contains earlier patches' lines (e.g. `pitch-probe` contains `actor-pages`). No order file was kept. **Record the order** if SWOTL copies this approach.
  - The hooks and outputs are summarised in [pc-reference-loop.md](pc-reference-loop.md).

## x86 decoding and oracles

| Tool | Where | Version | Slicks use |
|---|---|---|---|
| Unicorn (C library) | `/opt/homebrew/opt/unicorn` | 2.1.4 | Compack unpack capture (`build/unpack_compack`). x86-16 vs M68k differential executors `verify_*.c`, built with `cc -I$(UNICORN_PREFIX)/include … -lunicorn` |
| Unicorn Python binding | — | **missing**; SWOTL uses `tests/uc.py` (ctypes over `libunicorn.2.dylib`, no install) | not used by Slicks |
| Capstone C + `cstool` | `/opt/homebrew/opt/capstone` | 5.0.9 | 16-bit decode |
| Capstone Python | pyenv 3.11.10 site-packages | 5.0.7 | `from capstone import CS_ARCH_X86, CS_MODE_16, Cs` in `mz_info.py`, `analyze_execution_trace.py`, `analyze_vga_sites.py`, `summarize_memory_trace.py` |
| Intel XED | — | **missing** (`/usr/bin/xed` is Xcode's editor launcher) | listed as optional second decoder |
| iced-x86 | — | **missing** | not used by Slicks |

- Slicks rule: every instruction semantic and every lowering is differentially tested against an independent x86 oracle (Unicorn x86-16 vs Unicorn 68020 on assembled bytes). [Slicks `CLAUDE.md`, `docs/validation-harness.md`]. Details are in [translation-lessons.md](translation-lessons.md).
- Slicks: no LLVM and no generated-C backend until there is a measured need. [Slicks `docs/toolchain.md`]
- SWOTL translator and tests (Python 3.11, stdlib + capstone): `make gen` (build/gen), `make
  gen-check` (G1), `make lint` (G2), `make test` (lint, decoder vs Capstone, x86 differential vs
  Unicorn, guard plants, gen-check; ~7 min), `make test-sabotage` (~3 min). Unicorn x86 quirks the
  harness works around: [x86-notes.md](x86-notes.md#unicorn-x86-16-as-oracle).

## Host language and build

| Tool | Version |
|---|---|
| Python (pyenv default) | 3.11.10. Also 2.7.18, 3.9.16, 3.12.4; Homebrew 3.13/3.14 (Homebrew python lacks capstone) |
| Python packages (3.11) | capstone 5.0.7, numpy 2.4.6, Pillow 12.2.0 |
| uv | 0.12.18 |
| cc | Apple clang 21.0.0 |
| make | GNU Make 3.81 (Slicks Makefile is 3.81-safe: mode stamps, not same-second timestamps) |
| pdftotext | `/opt/homebrew/bin` (reads the manual PDF in `ref/`) |
| lsof | 4.91 (port polling in launchers) |

- Slicks `tools/*.py` use only the stdlib plus capstone, Pillow and numpy. [Slicks `tools/`]
