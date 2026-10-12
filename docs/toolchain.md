# Toolchain

The host is macOS on Apple Silicon. Every version below was checked on this machine on
2026-10-02 with `which`/`--version`/`ls`. "Missing" means it was not found. Sibling
provenance is in brackets.

## Fresh host setup (checked 2026-10-06)

- `brew install unicorn capstone ffmpeg sevenzip lhasa unar dosbox-x dosbox-staging
  openjdk@21 ghidra automake libtool`; pyenv Python 3.12.8 with `pip install
  capstone==5.0.7 numpy Pillow`. Brew's dosbox-x is 2026.10.01; the reference is the
  patched build (`make reference-emulator`); with Command Line Tools 26.6 the default
  MacOSX27 SDK fails to link (`ld: tapi error … arm64e.x1`): build with
  `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk`.
- Amiga toolchain, Kickstarts, SetPatch (Workbench 3.1), WHDLoad, LHa for UNIX and
  `fsuae_common.sh`: AmigaXDev's `make setup`, which installs `~/.local` and
  `~/.local/share/amiga` (BartmanAbyss `vscode-amiga-debug` 1.8.2; its FS-UAE is x86_64,
  under Rosetta). `amiga/env.sh` sources the shared `~/.local/share/amiga/env.sh`.
- Ghidra: `~/.local/share/ghidra/ghidra_12.1_PUBLIC` → `/opt/homebrew/opt/ghidra/libexec`
  (brew 12.1.4). `tools/ghidra_import.py` runs it with Homebrew's openjdk@21
  (`GHIDRA_JAVA_HOME` overrides).

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
| WHDLoad dev files | `~/.local/share/amiga/WHDLoad-20.0` (`$WHDLOAD`; 19.2 in `WHDLoad`) | see [whdload.md](whdload.md), [release.md](release.md) |
| Kickstart | `~/.local/share/amiga/Kickstarts/kick40063.A600` (`$KICKSTART`) | see [headless-fsuae.md](headless-fsuae.md) |

- Generic toolchain rules (space-free install path, matched gcc/gdb/elf2hunk/FS-UAE, flags,
  link audits, `elf2hunk`): AmigaXDev `docs/reference/port-toolchain.md`; paths and variables:
  AmigaXDev `docs/environment.md`.
- `brew install` on this machine triggers a Privileges.app elevation prompt. The user must start installs or approve the prompt. [RoF, Vette]

## Archives

| Tool | Path | Version | Use |
|---|---|---|---|
| LHa for UNIX | `~/.local/share/amiga/lha-compressor/src/lha` (`$LHA`) | 1.14i-ac20260723 | LH5 encoding (Vette: set `LHA` or install as `lha-compress`) |
| Lhasa `lha` | `/opt/homebrew/bin/lha` | 0.6.0 | independent archive verification [Vette] |
| olha | `~/.local/bin/olha` | 0.4.4 | — |
| 7-Zip `7zz` | `/opt/homebrew/bin` | 26.03 | `ref-originals/*.7z` (`7z` missing) |
| unar / lsar | `/opt/homebrew/bin` | 1.10.7 | — |

## Ghidra (headless)

| Item | Value |
|---|---|
| Install | shared `~/.local/share/ghidra/ghidra_12.1_PUBLIC`; `tools/ghidra` is a symlink to it |
| JDK | OpenJDK 21.0.12.1 at `/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home` |
| Project | per-repo `tools/ghidra-proj/` (git-ignored; it is the annotation database and must not be shared) |

- Headless Ghidra rules (`JAVA_HOME`, the symlink ignore entry, no GUI beside headless,
  `MarkEntries` as a `-preScript`, `-process` for re-runs): AmigaXDev
  `docs/reference/port-toolchain.md` §Analysis tools.
- Slicks x86 real-mode invocation (raw runtime image):
  ```sh
  "$GHIDRA/support/analyzeHeadless" tools/ghidra-proj Slicks \
    -import disasm/runtime.bin -processor "x86:LE:16:Real Mode" \
    -loader BinaryLoader -loader-baseAddr 0x10100 -scriptPath "ghidra_scripts;$AMIGA_GHIDRA_SCRIPTS" \
    -preScript MarkEntries.java -postScript ExportAuditListing.java "$ABS/disasm/listing.txt"
  ```
  Slicks also imported its relocation-normalised MZ (`runtime.exe`) with the default loader. It kept separate projects per input (`ghidra-proj`, `-normalized-proj`, `-live-proj`, `-live-normalized-proj`, `-gameplay-proj`). [Slicks `Makefile`]
- AmigaXDev ships the generic scripts in `$AMIGA_GHIDRA_SCRIPTS` (`ExportAuditListing`, `ExportListing`,
  `DumpCallGraph`, `DumpZeroPage`, the Mac scripts); a project keeps only its CPU-specific ones.
- Slicks scripts: `MarkEntries.java`, `SeedLiveMap.java` (live entry points and VGA sites from reference traces), plus `entrypoints.csv` and `vga-symbols.csv`. Earlier ports add `ApplyNames.java` (`disasm/symbols.csv` → project), `DumpHwAccesses`, `DumpCallGraph`, `DumpZeroPage`. [Slicks `ghidra_scripts/`, RoF, Revs]
- SWOTL: `make ghidra` (`tools/ghidra_import.py`): one program per in-scope module at its link address, entries from the sweep (`ghidra_scripts/MarkEntries.java`), listings `tmp/ghidra/<module>.txt` (AmigaXDev's `ExportAuditListing.java`). Ghidra's auto-analysis decodes more than the sweep proves; the sweep is the classification of record.
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
| Unicorn Python binding | — | **missing**; SWOTL uses `tests/uc.py` (ctypes over `$AMIGA_UNICORN/lib/libunicorn.2.dylib`, AmigaXDev `make unicorn`: 2.1.4 with QEMU 707b45a2; Homebrew's dies with SIGILL where an addx/subx folds to a constant; `UNICORN_LIB` overrides) | not used by Slicks |
| Capstone C + `cstool` | `/opt/homebrew/opt/capstone` | 5.0.9 | 16-bit decode |
| Capstone Python | pyenv 3.11.10 site-packages | 5.0.7 | `from capstone import CS_ARCH_X86, CS_MODE_16, Cs` in `mz_info.py`, `analyze_execution_trace.py`, `analyze_vga_sites.py`, `summarize_memory_trace.py` |
| Intel XED | — | **missing** (`/usr/bin/xed` is Xcode's editor launcher) | listed as optional second decoder |
| iced-x86 | — | **missing** | not used by Slicks |

- Slicks rule: every instruction semantic and every lowering is differentially tested against an independent x86 oracle (Unicorn x86-16 vs Unicorn 68020 on assembled bytes). [Slicks `AGENTS.md`, `docs/validation-harness.md`]. Details are in [translation-lessons.md](translation-lessons.md).
- Slicks: no LLVM and no generated-C backend until there is a measured need. [Slicks `docs/toolchain.md`]
- SWOTL translator and tests (Python 3.12, stdlib + capstone; numpy for `tools/profile_report.py`): `make gen` (build/gen: `.ir`, `.s`,
  audit), `make gen-check` (G1), `make lint` (G2), `make test` (lint, decoder vs Capstone, x86
  differential vs Unicorn, 68020 instruction differential, generated-program block differential,
  guard plants, gen-check, host run m1–m3; ~6 min), `make test-sabotage` (x86, 68020 and runtime plants, one plant per
  worker process; the 68020 plants reuse the x86 side `make test`'s boundary run records in
  `tmp/test/x86-side-boundary.pkl`, matched per case; ~12 min), `make test-host-all` (m1–m7 and coverage
  c6-flight-keys, ~9 min), `make gates` (all step gates: test, then the others at once; ~18 min, logs in
  `tmp/gates/`). Checks run in parallel (`JOBS`, default all cores;
  the differentials in `--shard K/N` pieces), each logging to `tmp/test/<name>.log`. Unicorn x86
  quirks the harness works around: [x86-notes.md](x86-notes.md#unicorn-x86-16-as-oracle).
  Multi-instruction RETF wrap checks and `tests/test_dosbox_retf.py` also need
  the existing heavy-debug DOSBox-X binary (`make reference-emulator`).
  They single-step through its debugger; no saved reference is generated.
- Phase 5 link: `make host` assembles `build/gen/program.s` (one unit, `vasm -m68020 -Felf -x`,
  default optimisations; external branches are emitted `.l`), compiles `src/runtime/*.c` with
  `-ffreestanding` (the Amiga sys-include has no hosted `stdint.h`; the framework's `Util.h`
  typedefs must not meet it in C++ units) and links with `m68k-amiga-elf-ld -Ttext=0x10000`;
  `tests/host_run.py` loads the ELF itself (no objcopy in the toolchain). `make test-amiga` fills
  `amiga/milestone.gdb.in` (label from `tests/host_run.py --label`) and runs it under
  `amiga/debug.sh` (8 MiB Fast, `--cpu=$AMIGA_CPU` when set, 68030 from the Makefile, `ref/` copied to dh1; gdb output in `tmp/amiga-<m>/gdb.log`):
  gdb types a0–a7 as pointers, symbols without debug type need a cast, `dump` splits its
  arguments at spaces (casts via `$variables`), and an error inside a breakpoint's commands
  leaves gdb waiting at its prompt; a 1 MiB `dump binary memory` over the FS-UAE stub takes
  a few seconds.
- 68020 side: vasm `-quiet -m68020 -Fbin` with its default optimisations (branch sizes;
  `-no-opt` disables them); it drops a `bra` to the next instruction, so labels can share an
  address and `tests/m68k_blocks.py` matches stops by address. Unicorn 68020: write SR before A7
  (A7 is the active stack pointer; at open S=1, so A7 is the SSP). Test images assemble per batch
  into `tmp/m68k/`.

## Host language and build

| Tool | Version |
|---|---|
| Python (pyenv default) | 3.12.8 |
| Python packages | capstone 5.0.7, numpy 2.5.3, Pillow 12.3.0 |
| uv | 0.12.18 |
| cc | Apple clang 21.0.0 |
| make | GNU Make 3.81 (Slicks Makefile is 3.81-safe: mode stamps, not same-second timestamps) |
| pdftotext | `/opt/homebrew/bin` (reads the manual PDF in `ref/`) |
| lsof | 4.91 (port polling in launchers) |

- Slicks `tools/*.py` use only the stdlib plus capstone, Pillow and numpy. [Slicks `tools/`]
