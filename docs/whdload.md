# WHDLoad slave — design rules

Lessons from the sibling slaves, with SWOTL's use. Source:
`whdload/SwotlSlave.s` (`make whdload` → `build/whdload/`); test:
`tools/test_whdload.py` (`make test-whdload`; `--option` passes WHDLoad options, `--z3` adds
Zorro III Fast); PreLoad contents: `tools/whdload_preload.py`. Provenance: `Sl` Slicks, `Ve` Vette, `Rv` Revs, `Po`
Pokeri, `RoF` Rescue on Fractalus, `P2` Prince of Persia 2 (each project's `docs/whdload*.md` and
`whdload/*.s`; the merged rules are in AmigaXDev `docs/playbooks/new-port-playbook.md` §13), `SDK` `~/.local/share/amiga/WHDLoad` (`Src/sources/whdload/kick.readme`,
`Docs/en/{howto,opt,cache}.html`). Release packaging: [release.md](release.md).

## Model: kickemu, not takeover

| Rule | Prov |
|---|---|
| Plain slave = no OS (`$4 = $f0000001`, any OS call address-errors). Fits trackloaders only | RoF §0, SDK howto |
| Native port is an AmigaDOS exe (AllocMem, graphics, DOS, CIA resources) → kickemu: boot real Kickstart in WHDLoad space, run the **same** exe as a CLI process | RoF §0, Ve, Sl, Po |
| Rejected alternatives: game-side OS shim (forks startup, unvalidatable), fake exec in slave (struct fragility in asm) | RoF §0 |
| `kick31.s` + `kickfs.s` for 3.x/AGA targets; `kick13.s` only if exe is 1.3-clean (saves 256 KiB ROM image) | Sl, Ve, Po / RoF, Rv |
| Assemble SDK `kick31.s`/`kickfs.s`/`segtracker.s` from `$(WHDLOAD)/Src/sources` (vendor only patched copies; AmigaXDev `docs/projects.md`); never ship SDK binaries | Rv, Sl |
| SWOTL: `kick31.s` kickemu, Kickstart 3.1 + RTB user-supplied (kick40068.A1200 / kick40068.A4000 / kick40063.A600) | Sl, Po |

## Header symbols and flags (newest = Slicks/Pokeri)

| Symbol / flag | Use | Prov |
|---|---|---|
| `BLACKSCREEN` | hide kickemu boot screen | Sl, Po, Ve |
| `INITAGA` | **essential** for a direct-AGA exe | Sl |
| `BOOTDOS` + `HDINIT` | `_bootdos` runs as CLI process; `slv_CurrentDir` drawer mounted via kickfs | Sl, RoF §1 |
| `CACHE` | see Caches; the five siblings use `CACHECHIP` | Alone in the Dark, Prince of Persia 2, TFH |
| `SEGTRACKER` | symbolised dumps | Sl, Po |
| `NO68020` | portable kickemu patches even when game needs 020 | Sl, Ve |
| `NUMDRIVES=0`, `WPDRIVES=0` | no floppy emulation | Sl |
| **not** `STACKSIZE` | kick31 A600 patch at ROM `$2305c` hits MOVE.L opcode (immediate at `$2305e`) → equal stack bounds, corrupt fast free list. Use Exec StackSwap instead | Ve, Sl, Po |
| `DEBUG`, `BOOTEARLY` only under `IFD TEST` | debug checks out of release | Sl, SDK kick.readme |
| `slv_Version = 17` (18 only for SNOOPFS test build) | 17 exposes `ws_config`/Custom tags | Sl, RoF |
| `slv_Flags = WHDLF_NoError\|WHDLF_ReqAGA\|WHDLF_Req68020` | WHDLoad refuses unsuitable machines up front | Sl |
| `WHDLF_EmulLineA` etc. | only if game owns low vectors (moved VBR forwards them) | Ve, Po |
| `slv_keyexit = $59` (F10) | default quit; pick another key if game uses F10 (Rv: keypad `*`; Po: Help `$5f`) | Sl, Rv, Po |
| `slv_info` | "Amiga port by Vesuri", version line, quit-key line | Sl |
| `$VER: <Name>.slave x.yy (dd.mm.yyyy)` | literal, bumped by hand → byte-identical rebuilds | RoF §5, Sl |
| SWOTL: Slicks set verbatim but `slv_Flags = WHDLF_NoError\|WHDLF_Req68020` (1.1: no `ReqAGA`, OCS/ECS run the EGA version, ecs-plan D3); `slv_keyexit = $5f` (Help): Amiga F10 reaches the game as PC F10, Help has no entry in `src/platform/amiga/Input.cpp`'s key table | — |
| SWOTL `slv_config "C1:B:Their Finest Hour sound effects;C2:B:Analog joystick in port 2;C3:B:OCS/ECS display on AGA;"`: Custom1 adds `TFH`, Custom2 `ANALOGJOYSTICK`, Custom3 `OCS` to the argument line the slave builds and passes to `RunCommand` (below); the exe needs no hook | Sl, Ve |

## `_bootdos` sequence (Slicks, newest)

1. `OldOpenLibrary` dos; `SetArgStr` to a null/LF-terminated arg string if exe uses `GetArgStr` (Sl; SWOTL: none, step 5).
2. `LoadSeg(_program)`; fail → `TDREASON_FAILMSG` / abort, never hang (Sl, Rv).
3. Patch magic-tagged config blocks (below), then `resload_FlushCache` (Sl).
4. **Lock the actual current drawer** (`ACCESS_READ`) + `SetProgramDir`. `DupLock(0)` left `pr_HomeDir` 0 → invisible PROGDIR requester hang (Ve).
5. `AllocMem` 16 KiB stack, Exec `StackSwap`, call entry (Ve, Sl, Po). SWOTL instead
   `RunCommand` with a 16 KiB stack: DOS allocates and swaps the stack and puts the
   argument line in `Input()`'s buffer, which `ReadArgs` reads (its `?` prompt does not
   work from an `RDA_Source`, so `SetArgStr` alone is not enough); FM, TFH and analog pass
   `make test-whdload`.
6. On return: restore stack/args/PROGDIR, `UnLoadSeg`, `resload_Abort(TDREASON_OK)` — not back to CLI (BLACKSCREEN hides it; 68000 has no QuitKey) (RoF §1, Sl).
7. Exe return 20 (missing/bad originals) → `TDREASON_FAILMSG` with readable text (Rv).

## Talking to the game: magic-tagged blocks

| Rule | Prov |
|---|---|
| Game never knows about WHDLoad; same binary runs standalone/Shell/WHDLoad | RoF §6, Sl |
| Slave scans loaded hunks (longword-aligned) for an 8-byte magic (`RoF!HOOK`, `VET!HIRE`, `SLKSIO01`, `POK!SAVE`) | RoF §6, Ve, Sl, Po |
| Block carries version + size; slave patches only a layout it knows; reserved fields must be zero | RoF §6, Ve, Sl |
| Optional hook absent → game uses own DOS path; **required** hook absent → loud `FAILMSG` | RoF §6, Sl |
| Custom options: `slv_config "C1:B:<text>;"`, read `WHDLTAG_CUSTOM1_GET`, patch a retained config word; game snapshots once | Ve, RoF §1 |
| Hook calls use GCC m68k C ABI (args on stack, D0 result, D2-D7/A2-A6 saved); verify with objdump after game changes | RoF §6 |

## Memory

| Rule | Prov |
|---|---|
| kickemu: `ws_BaseMemSize = CHIPMEMSIZE`; `ws_ExpMem = ROM image + FASTMEMSIZE` (3.1: `$80000`, 1.3: `$40000`) | RoF §2, Po |
| Host also needs Fast RAM for ROM image, OS backup, PRELOAD; slave reservation ≠ machine requirement | Sl, Po |
| `FASTMEMSIZE = 0` keeps WHDLoad identical to a 2 MiB Chip-only standalone (Slicks) | Sl |
| Size from measurement: `MEMFREE = $200` tune slave (largest free chunk at `$200` chip / `$204` fast, sampled only at AllocMem) or gdb free-list walk | RoF §2, Rv, Po |
| Enhanced/optional paths need their own measurement (RoF: 52 KiB chip left → silent bitmap alloc failure) | RoF §1 |
| Checker asserts exact slave chip/exp sizes so drift is caught | Po |
| SWOTL (1.1): `SWotL.slave` `CHIPMEMSIZE = $C0000`, `SWotL512K.slave` (`SMALLCHIP`, 512 KB Chip machines, ecs-plan D6) `$80000`; both `FASTMEMSIZE = $440000` (D15: code + guest RAM + EMS store in Fast; the store backs the 35 EMS pages the game allocates, runtime.h; the EGA version adds its model's four 64 KiB planes, `ega.c`). MemFree variants (`-DMEMFREE=$100`, `MemFree512K`; low-water largest free chunks in the core dump at $100/$104), 68020 + 8 MiB Fast unless noted, attract into flight (3,000 fields), 2026-11-06, Chip / Fast: A1200 VGA 70,184 / 277,016; A1200 EGA (Custom3) 70,184 / 14,864; A3000 (68030) and A500+ (ECS, 1 MB Chip) 70,760 / 21,400; `SWotL512K` on A500 (OCS, 512 KB Chip): TFH (Custom1) 127,032 / 224,496, without Custom1 FM rendering exhausts Chip (15,352) and the TFH samples or silence follow. Fail: `$400000`–`$420000` Fast under EGA (A1200 Custom3, A3000, A500+): at `$400000` the FM effects do not fit in Chip (Fast full, `MEMF_ANY` allocations land in Chip), at `$410000`/`$420000` the effect cache is not written (as 1.0 at `$3F0000`). 1.0 (`$400000`, VGA only, 2026-11-04): FM 70,184 / 68,560, TFH 388,600 / 271,656; Campaign and Tour scripts (15,000 fields, saves) 70,184 / 68,272; `$A0000` Chip fails (FM effects do not fit, Chip 17,816). Host needs 8 MiB Fast | — |
| WHDLoad's host Fast holds ExpMem, a backup of all of BaseMem (`FullChip` widens it to all Chip) and the file cache; PreLoad stops at the first file that does not fit. Files in `ws_DontCache` are never cached; each read of an uncached file is an OS switch, so they must be read in few large reads. kick31.s hard-codes `ws_DontCache` 0: the build copies it to `build/whdload/include` with the field pointed at `slv_DontCache` | SDK |
| SWOTL PreLoad: `ws_DontCache` `(SWotL\|SWOTL.EXE\|sfx.cache)`, the files read once at start (LoadSeg: 65 reads; `exec_root` reads relocations in 1 KiB blocks); the installer leaves out the three files the port never opens (release.md). 1.1 (`$C0000`/`$440000`, installed TFH drawer: 537 files without SWotL, 3,335,212 bytes, A1200/68020, 8 MiB Fast, 2026-11-06): only those files are read after the preload; margin full at +1 MiB (`$540000`), partial at +1.25 MiB (22 game files read after it), +1.5 MiB 30. Installed drawer (TFH, 536 files without SWotL, 3,312,268 bytes), `tools/whdload_preload.py`, A1200/68020, KS 3.1, 8 MiB Fast, 2026-11-04: at `$C0000`/`$400000` only those files are read after the preload; margin (variants with larger ExpMem) full at +1 MiB, partial at +1.25 MiB (36 game files read after it). Other sizes, game files read after: `$100000`/`$480000` 0 (full at +384 KiB), `$180000` 36, `$200000` 45; 1.0 (`$200000`, only `SWotL` uncached) 53, at 9 MiB 33, 10 MiB 0. `$100000`/`$480000` stops the 68030 `MMU` option on 8 MiB (rc 10 before the game, no dump, no requester): WHDLoad lacks under 256 KiB of host Fast (`$440000` Fast passes, as do 16 MiB more Fast and no PreLoad). PreLoad takes the whole drawer whatever the sound mode. `Avail` before WHDLoad: 8,270,072 free Fast (2026-10-28) | — |

## Caches (68020)

| Fact | Prov |
|---|---|
| 68020: 256-byte I-cache only, no data cache | SDK cache.html |
| WHDLoad default: BaseMem NonCachable, ExpMem/slave CopyBack; without MMU any noncacheable region → all caches off | SDK cache.html |
| kickemu without any `CACHE*` symbol = **all caches off** | SDK kick.readme |
| `CACHECHIP` = I-cache on for chip+exp, D-cache off; MMU-independent. Used by Sl, Ve, Rv, Po, RoF | SDK, all |
| `CACHE` = full caches on ExpMem only (needs MMU to split); `CACHECHIPDATA` caches chip data → blitter/DMA incoherence | SDK kick.readme |
| WHDLoad uses the MMU on 68040/060 by default, on 68030 only with its `MMU` option | SDK opt.html |
| SWOTL: `CACHE`; `_bootdos` reads CACR and, if the instruction cache is off (no MMU in use: CACR 0), sets `CACHECHIP`'s value. Measured CACR: 68020 `1`, 68030 `2011`, 68030 + `MMU` `2111`, 68040 `80008000`, 68060 `A0808000` | — |
| Cache policy check: `.whdl_register` holds `setcpu=` (the slave's request) and `CACR=`; `test_whdload.py` requires both. 0.90's `CACHECHIP` left the D-cache off on 68040/060 (CACR `8000`, `20808000`) | — |
| `resload_FlushCache` after LoadSeg/patching code | Sl, Po |
| User options `NoCache`/`Cache` override slave; release icon must not need them | SDK cache.html, Sl, Po |

## File I/O through resload/kickfs

| Rule | Prov |
|---|---|
| Every OS switch is a visible pause; each physical write adds WHDLoad write delay (3 s default) | Sl |
| Whole-file reads/writes, minimum op count; no `.new`/`.bak`/rename/delete; rewrite only changed bytes (CRC+length) | Sl, Po |
| Saves via one `resload_SaveFile` through slave hook | Sl, Po, RoF §6 |
| kickfs has no `ACTION_CHANGE_MODE` ($404), `ACTION_SET_FILE_SIZE` ($3FE), `ACTION_PARENT_FH` ($407, `NameFromFH`) or `ACTION_RENAME_OBJECT`; without `DEBUG` an unknown packet runs its lookup past the action table (Access Fault in task `DH0`) | P2 `docs/release.md`, SDK `kickfs.s` |
| SWOTL: create = `MODE_NEWFILE`, `Close`, `MODE_OLDFILE` (shared, as DOS); O_TRUNC (`3D01h`, 0-byte write at 0) makes the file anew the same way; close stamps by the opened path. `CampaignTest`/`TourTest.slave` write A.CBA and A.USA (c10, c11) on 68020 and 68060 | — |
| SWOTL: `sfx.cache` (prerendered effects, sound-plan R4) is written at the first start by one `Write`: one save, one write delay (two with the create); read per effect after. `test_whdload.py --mode run` requires it whole | — |
| `WHDLF_NoError`: `resload_SaveFile`/`LoadFile` return only on success (error requester otherwise); use `resload_GetFileSize` for optional files | RoF §6 |
| resload names relative to the slave's data dir | RoF §6 |
| Creating **new** files via write cache hung at exit in low-memory fixtures; Installer pre-creates fixed-size save slots, game refuses if missing | Po |
| WHDLoad 20.1 [build 7190] exit hang: the "dircache clearing" walk (after "clock restored") loops on an entry flagged 1 at +232 without advancing; the entry is a file the game created that is still in the write cache, so it never reaches disk and `COREDUMP` writes nothing. Nothing in the loop clears the flag. `NoWriteCache` (option or tooltype only; no slave flag) avoids it. Found from gdb stops in WHDLoad's code and a Chip/Fast dump | SWOTL, Ferrari F1 |
| `CBSWITCH` callback: no stack, return via `jmp (a0)`, only D0/D1 clobberable — useful to count OS switches in tests | Sl |
| `IOCACHE` sizes the kickfs per-file cache (≥ savegame size) | SDK kick.readme |
| PRELOAD in icon; no `NoWriteCache`/`NoVBRMove` needed (SWOTL on 8 MiB: `NoWriteCache`, exit hang below) | Sl, Po |
| F10/QuitKey is immediate: cannot run deferred saves; normal game exit must save | Sl, Ve, Po |
| QuitKey and `TIMEOUT` need moved VBR (68010+); harmless for A1200 | RoF §1, Rv |

## Build

- Host `vasm` 1.9: `-pic -x -devpac -Fhunkexe -nosym`, SDK + NDK includes, `make -C whdload`; always reassemble (Ve, RoF §3).
- Ve needed build-local include aliases for SDK short LVO names / NDK `_lib.i`; vendored RoF/Rv sources already use `_lib.i` (Ve, RoF §3).
- Test slaves (`BOOTONLY`, `LOADONLY`, `*TEST` with diagnostic args) are separate targets, never packaged (Sl, Ve).
- Toolchain detail: see [toolchain.md](toolchain.md).

## Debugging

| Rule | Prov |
|---|---|
| WHDLoad core dumps (`COREDUMP`, `TIMEOUT`, `FILELOG`) beat emulator-debugger traces; both Vette slave faults were found from dumps | Ve |
| Staged test slaves: plain marker (no ROM) → kick only → LoadSeg only → full game | Ve, Sl |
| Markers: `resload_SaveFile` of a tiny file per stage (`test-bootdos`, `test-loaded`, `test-returned`) | Sl |
| Dump tools: waiting-task inspector, planar-buffer decoder from real dump (not reference images) | Ve, Sl |
| `FILELOG` on 68000 can outlast timeouts (LoadSeg's many small reads) | Rv |
| Harness: isolated `tmp/whdload-test-*` fixture per run, kill only own emulator, `--no-preload` variant, 4 MiB Fast default | Ve, Sl |
| SWOTL harness: `--installed DIR` runs an installed drawer unchanged; `--setup a1200-040`/`-060` = 68040/060 + MMU + FPU on `$FSUAE_MMU`, requires TC=8000 in the report; `--setup a1200-030` (+ `--whdload-mmu`) = full 68030. These emulate the data cache (compatible core, indirect UAE board; a FS-UAE fixup fails the run). `--setup a3000` (ECS, 68030 + MMU), `a500+-020` (ECS, 1 MB Chip), `a500-020` (OCS, 512 KB Chip; with `--slave build/whdload/SWotL512K.slave`) as AmigaXDev's presets on the A600 Kickstart 3.1; `--ocs` sets Custom3. EGA (OCS/ECS or Custom3): RTSEGA.OVL resident and the tail's driver `E`; 512 KB Chip: no effect cache, TFH samples in Chip with sfx.rsc, none with `--no-sfx` (silent effects) | — |
| SWOTL harness: `--mode run` ends by `TIMEOUT` + `COREDUMP` (reported as "DEBUG caused" at the CIA-A event count); oracles: original SWOTL.EXE/RTSVGA.OVL blocks in guest RAM (byte-reversed), TFH PCM in Chip only with `--tfh`, the PSP command tail's joystick argument `Y` only with `--analog` (Custom2). The quit key needs a Lua FS-UAE to press; not tested headlessly | Rv |
| Headless emulator mechanics: [headless-fsuae.md](headless-fsuae.md) | — |

## Common failures

| Symptom | Cause | Prov |
|---|---|---|
| Hang at start, nothing visible | `pr_HomeDir` 0 → hidden PROGDIR requester | Ve |
| LoadSeg never returns | unstripped exe: symbol hunks read in small pieces through kickfs (SWOTL: 165k symbols); install the `elf2hunk -s` exe | SWOTL |
| Corrupt fast free list / weird crashes | SDK `STACKSIZE` A600 patch | Ve |
| `_program_err` | `slv_CurrentDir` vs Installer `#sub-dir` disagree on where exe lives | RoF §5 |
| Error requester on save | `WHDLF_NoError` + full/write-protected drawer | RoF §6 |
| Exit hang | new-file creation via write cache, low memory | Po |
| Exit hang, empty Workbench screen, no core dump, the new file lost | WHDLoad 20.1 dircache walk on a new file still in the write cache (above). SWOTL, A1200/68020, 8 MiB Fast, PreLoad, `$C0000`/`$400000`, 2026-11-04: any file created during the run, on the game-menu exit as on `TIMEOUT`: `sfx.cache` at the first start, the 540-byte pilot `A.USA` (TourTest) with `sfx.cache` present; a run that creates nothing exits. Passes: `NOWRITECACHE`, no PreLoad, 68030 with 8 MiB more Z3 Fast (1 run). Still hangs: ExpMem `$3D0000`–`$3F0000`, Chip `$B0000`, WHDLoad output to `NIL:`, `CONFIGDELAY=0`. ReadMe tells 8 MiB users to set the `NoWriteCache` tooltype, and `test_whdload.py --mode run` passes `NOWRITECACHE` (user decisions) | SWOTL |
| Run never ends in test | QuitKey/TIMEOUT unseen on 68000 (no moved VBR) | Rv |
