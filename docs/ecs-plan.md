# OCS/ECS version plan (open-work 45)

Goal: the same executable runs the original's EGA version on OCS/ECS Amigas with a 68020 or
better: `swotl E S 5 N Y Y 64`, RTSEGA translated like RTSVGA, its EGA memory and registers
modelled by the runtime, shown as four hires bitplanes. Everything else (game code, DOS, EMS,
timer, sound, input, files, I/O windows, WHDLoad, installer) is reused unchanged.

## Facts (static: capstone over `ref/`, 2026-11-04; E2's corpus confirms and `make map` regenerates them)

| Item | Fact |
|---|---|
| Launch | `E` sets `[9936]=0`, `[2581]=0`, `[233E]=0` and calls RTSEGA+49B6 (root `+3BCE`) |
| RTSEGA | 22,944 B, 5 fixups; data `0030–3141`; tables RTSEGA builds in its own CS at run time in the zero area `350C–450C` (49B6); code `4850–5996` (about 4.4 KB); no indirect transfer, no `in`, no CRTC (`3D4`), status (`3DA`) or attribute (`3C0`) port |
| Driver API | DGROUP `0660–0780`: 25 rows of far pointers (EGA, Tandy, VGA) to PLINK thunks; RTSEGA has 28 thunks: the 25 plus 49B6 (dither and palette set), 48F2 (page copy), 4935 (draw page) |
| Mode | INT 10h AX=000Eh: 640×200, 16 colours, 4 planes, 80 B rows, 16,000 B per page and plane; AX=0007h and BDA `410h` only when `[9D37]≠0` (0 in DATA) |
| Palette | INT 10h AX=1002h from DS:2897 (registers `00–07`, `10–17`, overscan 0) and DS:2886 (all 0, blank); 48BC/48D7 toggle `[A4B6]` bit 0 |
| Ports | `out` only: sequencer 2 (map mask); graphics controller 4 (read map), 5 (write modes 0, 1, 2), 8 (bit mask) |
| Pages | DS:2882 = `A000`, `A400`; draw page `[287C]` (4935); 48F2 copies a page with write mode 1 (`rep movsb`, 16,000 B, latches); the CRTC start never changes, so page 0 is always shown |
| VRAM forms | byte load, byte store, byte `xchg` (latch RMW), byte `and`/`or` RMW, `rep movsb`, `rep stosw` (ES and DS forms; census in E3) |
| Converters | 4AC3 and 4BD0 (rows `0684`/`0690`, VGA 3A22/3B9A) turn the game's 4-bit packed buffer (two pixels per byte, 160 B per row) into planes: per destination byte, four times a map mask `out`, two row-parity dither table reads and an `xchg es:[di]`, about 40 x86 instructions |
| Game side | `[2581]=0`: D16 cells are the file's 9-byte `and byte [bx+w],0Fh; or byte [bx+w],al` (`+6A36`), built at stride 9 by `+E64F..+E6C1` (`self-modifying.csv` `variant`: today a walk meeting one stops). Natives exit on the EGA arms: `sprite_row` SR_EGA (`4F3C`), `rasterize` RZ_C02C/RZ_C2A5. Indirect exclusions `SWOTL+4F7B`, `+50A5`, `FRONTEND+A90D` are EGA paths ([indirect-coverage.md](indirect-coverage.md)) |
| Colour | EGA levels 0/15h/2Ah/3Fh are 12-bit 0/5/A/F exactly; the mode 0Eh DAC comes from the reference (DOSBox-X `svga_s3`) |
| Amiga | EGA plane bytes are Amiga hires plane bytes (MSB leftmost, 80 B rows): no C2P. Two Chip bitmaps of 4 × 16,000 B = the AGA build's 2 × 64,000 B. FM effects need 464,994 B of Chip, more than a 512 KB Chip machine has (D6) |
| Size | translated code 1,247,112 B (`program.o` `.text`, about 3.2 B per 68k instruction); RTSVGA's 3.7 KB of x86 is about 22 KB, RTSEGA's 4.4 KB about 25–30 KB; with the model, display, cells and natives about +30–40 KB (+2–3%) on the 1,395,128 B release executable. EGA pages 0–1 (4 planes × 32 KB) live in the guest's A0000–BFFFF window, which EGA mode leaves unused, in natural order and owned by the model: no extra RAM |

## Traps found in advance

1. **Poll hash.** RTSEGA adds rows to `build/gen/poll-points.csv`; `tests/host_run.py` and
   `tests/amiga_replay.py` compare each reference's `polls=` with the FNV-1a of the whole file,
   so every VGA reference would fail. Fix: compare with the file without the rows of graphics
   driver modules the run never loaded. A sync point in a module that never runs cannot move an
   interrupt. This is a test change (D2); re-recording all VGA references is the rejected alternative.
2. **Sync set before references.** Native rows take their loop heads out of the sync set (RC5),
   so EGA lockstep references are recorded only after the converter natives exist (E6 → E7).
   First light uses a few provisional references.
3. **Device natives.** native-compute admits no device effects; converter natives need a
   device-row extension (D5).
4. **Converter speed.** Translated through the EGA model, 4BD0 costs on the order of a second
   per full view on a 68020 (about 40 x86 instructions × 4 model accesses per destination byte);
   a table native about 50 cycles per byte. E5 prices it before anything is decided.
5. **VRAM outside RTSEGA** (none expected; external-surface shows only the driver for VGA) would
   need device lowering in other modules: E2 stops on it.
6. **Hires 4-plane DMA** takes every Chip slot in the fetch window; guest planes stay in Fast,
   only the present and Paula touch Chip.
7. **512 KB Chip budget** is unmeasured: two 64,000 B bitmaps, the TFH samples, the FM music
   voices' 64 KB page pool, sprites and copper lists must fit the small-Chip slave's BaseMem
   (at most `$80000`) and a Workbench start. E9 measures it; a shortfall is reported, not cut
   around.

## Decisions (user 2026-11-04)

| # | Decision |
|---|---|
| D1 | Three recording passes: exploration (every EGA row, no `--polls`), provisional lockstep (`ega-` m1, m1b, m2, m4, m5), final lockstep (every row, after the natives). The tracer adds the snapshot file `ega.txt`; existing outputs unchanged |
| D2 | Poll-hash comparison without the rows of graphics driver modules the run never loaded (trap 1); no VGA reference re-recorded. Extended (user 2026-11-04): also without the rows in game code only such a driver selects (`annotations/driver-code.csv`: FRONTEND +1B94, +1BC2, loop head +1BD7); `host_run.polls_match` accepts the whole file or that filter for any set of drivers the run never loaded |
| D3 | One executable, one slave: no AGA → EGA, AGA → VGA; the `OCS` switch (Shell argument, tooltype, WHDLoad Custom3; named for the Amiga chipset, user 2026-11-04) forces EGA on AGA; the slave drops `WHDLF_ReqAGA` |
| D4 | Hardware sprite pointer on ECS too, in this project: an EGA masking path restores the pointer's plane bytes from RTSEGA's save buffer at present; `Pointer.cpp`'s sprites (OCS/ECS sprite pixels are lowres: one logical pixel) |
| D5 | Natives for RTSEGA 4AC3 and 4BD0 and the device-row extension authorized, built only if E5's profile prices them high |
| D6 | 68020 or better, no 68000. 1 MB Chip: as AGA. 512 KB Chip: TFH effects (the player's `sfx.rsc`), or with no `sfx.rsc` music only and silent effects; a second, small-Chip slave (BaseMem measured, at most `$80000`) |
| D7 | Routine EGA host gate: a greedy cover of EGA-only executed code (RTSEGA, the `[9936]`/`[2581]` arms, and/or cells) by a committed tool; the full corpus feeds `make map` |
| D8 | Release 1.1 after E9: AGA and OCS/ECS in one archive (and the whdload.de archive) |

## Steps

Times are active work; recording runs unattended, at most 4 runs in parallel at nice 10.

| Step | Work | Exit | Time |
|---|---|---|---|
| E0 | D1–D8 | answered 2026-11-04 | — |
| E1 Reference tooling | done 2026-11-04: `dosbox-x-swotl-ega.patch` (snapshot `ega.txt`); `reference/milestones-ega.csv`, `reference/coverage-ega.csv` (`ega-` rows, [pc-reference-loop.md](pc-reference-loop.md)); `make reference-ega-explore`; `snap_png.py` mode 0Eh. `host_run.py` planes: E4 | `ega-m0-entry`, `ega-m1-mode0eh`, `ega-m1b-logo` recorded and repeat; `snap_png` draws the logo | — |
| E2 Exploration | done 2026-11-04: 92 rows (`ega-c7` dropped), results in §E2 results; RTSEGA in `swotl_model.SCOPE`; `sweep.py` takes interrupt-entry targets from polled traces only; `pointer_static.py` EGA driver checks and census | complete EGA surface; every script reaches its snapshot | — |
| E3 Translator | done 2026-11-04: RTSEGA translated (`EGA`, both drivers' thunks D9); device lowering through `rt_ega_*` (stops until E4; [translator-design.md](translator-design.md)); D16 and/or forms in the exact walk; `indirect.csv` from VGA + EGA traces; D2 filter (extended); `test-blocks` runs `rt_ega_read/write` as plain RAM and skips `rt_ega_string` cases (user 2026-11-04); compare chains size their branches (vasm 1.9 converged in 799 of its 1,000 passes before, 247 now) | `make gen` zero unclassified over VGA + EGA traces; `make test`; `make test-blocks`; poll points without RTSEGA rows = before plus FRONTEND +1BD7 (D2) | — |
| E4 Runtime | done 2026-11-04: `ega.c` model (write modes 0–2, read modes 0–1, latches, surface-only registers stop); rt_ega_* entries (`rt_entry.s`; strings run element-wise in C, continuation `{label}_egap`, cmps/scas into the window stop); `ports.c` 3C4/3C5/3CE/3CF; `video.c` mode 0Eh, AX=1002h, `plat_present_ega`/`plat_palette_ega` (rects in bytes, multiples of 2); `input.c` AX=3 unmasked in 0Eh; `machine.c` tail `E`; `pointer.c` EGA masking (D4); D6 Chip fallback in `Audio.cpp` (verified in E8); `host_run.py` planes, registers, latches, attribute palette, overscan and DAC vs `vram.bin`/`ega.txt`/`dac.bin`, plants `ega-bit-mask`, `ega-latch` (ega-m1b) and `ega-write-mode-1` (ega-m2); `make test-host-ega` | host lockstep on E5a's references | — |
| E5 First light, pricing | done 2026-11-05: a. provisional lockstep references `--services --polls`: `ega-` m1, m1b, m2, m4, m5; every EGA row `rep_chunks=1` (DOSBox slices RTSEGA+4C2C `repe cmpsw`; user 2026-11-04). b. EGA host lockstep (E4). c. `Swotl.cpp` OCS/ECS display: 640×200 hires, 4 planes of 80 B, `FMODE 0`, DDFSTRT `$3C`/DDFSTOP `$D4`, 32 colour registers (0–15 the 16 colours in 12 bits, sprites 25 and 30, BPLCON4 `$0011` on AGA), present = span copy per plane; options before the display (`amiga_options`); `OCS` switch (Shell, tool type, release template); `milestone.gdb.in` dumps the bitmap's planes and the EGA model; `host_run --amiga` EGA checks (`compare_shown_ega`, `compare_video_ega`, `amiga_sprites.compose_ega`); `make test-amiga-replay-ega`; replay images over 6 MB get 16 MB Zorro III RAM (EGA m5's REP slices). d. FS-UAE: `ega-` m1b (plain and replay), m2, m4, m5 replays pass on `a1200` with `OCS`, m1b on `a3000` without it; flyby priced (§E5 results). No provisional row ends with the pointer shown: ECS pointer sprites are composed in E7/E8 | host and FS-UAE milestones pass; converters priced | — |
| E6 Natives (if D5) | done 2026-11-05: device-row contract (native-compute "Device rows", `hle.csv` `kind=device`, `compute.validate(device=True)`); natives `ega_convert_all` (4AC3) and `ega_convert_changed` (4BD0) in `src/runtime/compute_ega.s`; oracle `tests/test_ega_convert.py` (original x86 on Unicorn with `tools/ega_model.py` on memory and `out` hooks; DOSBox entries from `native_entries.py` EGA rows, mutations and declines; 14 plants); `tests/test_ega_model.py` (`ega.c` vs `tools/ega_model.py`, 7 plants). Sync set regenerated (§E6 results) | oracles and sabotage pass | — |
| E7 Final EGA corpus | done 2026-11-05: every EGA row `--services --polls`, `rep_chunks`/`joystick` as its VGA row (none: 4C2C is inside 4BD0's row); two passes byte-identical (`reference.py` hashes); `ega-c81` 300 s, `ega-c84` dropped (user 2026-11-05); gate set `HOST_EGA` from `tools/ega_cover.py` (`make t-ega-cover`; §E7 results) | references stable; gate set listed in the Makefile | — |
| E8 Verification (one batch) | EGA: `test-host-ega`, `test-blocks`, `make map` (zero unclassified), sabotage, `test-amiga` EGA on `a3000` and the new AmigaXDev presets `a500+-020` (A500+ ECS, 68020, 1 MB Chip, 8 MB Fast) and `a500-020` (A500 OCS, 68020, 512 KB Chip, 8 MB Fast: TFH and silent effects), display audit, restore check, workbench (`OCS`), pointer sprites (replay picture check with the fetch-window plant). VGA, shared translator and runtime changed: `make test`, `test-blocks`, `test-host-all`, `test-amiga`, `test-amiga-replay` with plant, display audit, bench (meter Δ within noise) | all pass; run 2026-11-05 (§E8 results): two open, user decisions: `ega-c82` (stale-stack read) and meter +1.57 % (4BD0 resume ZF) | unattended + 30 min |
| E9 Release | slave: no `WHDLF_ReqAGA`, Custom3 `OCS`, sizes by MEMFREE on `a500+-020` and `a3000`; small-Chip slave (D6): BaseMem and ExpMem by MEMFREE on `a500-020`, TFH or silent effects; `test_whdload.py` `--setup a3000`/`a500+-020`/`a500-020`; installer installs RTSEGA.OVL and stops deleting it (record counts) and the small-Chip slave with its own icon, `check_release`, `test-release-installer`, `whdload_preload`; ReadMe and README requirements and history 1.1; docs: AGENTS.md scope, architecture, amiga-arch, translator-design (D9, D16, device lowering), pc-reference-loop, source-inventory, plink, whdload, release, open-work; AmigaXDev lessons and preset (`make share`) | release audits pass | 1 h |

Speed work beyond the converters (and/or cell cache, present copy) only when measured
afterwards, under speed-plan rules.

## E2 results (exploration corpus, 2026-11-04)

| Item | Result |
|---|---|
| Corpus | 92 EGA rows reach their snapshots, deterministic (c20, c22, c23 rerun to equal hashes). `ega-c7` dropped: FLIGHT+4817 skips the EA74 cell-walk driver (and its +EC5B dispatch) when `[233E]=0`, which `E` sets. `ega-c20/c22/c23` end on the in-flight map (NOTCAMP), as their VGA rows do (open-work 49) |
| Surface | VRAM: RTSEGA only (48 sites), byte reads and writes. Ports: `out` 3C4h (8 and 16 bit), 3C5h, 3CEh (8 and 16 bit), 3CFh, all RTSEGA; otherwise the VGA set (PIC, PIT, AdLib, joystick). INT 10h: AH=00h and AX=1002h (RTSEGA), AH=0Fh (SWOTL); INT 33h: 0, 3, 0Bh. No stop condition |
| Executed | RTSEGA 1,551 instruction starts (3,897 of 4,413 static code bytes). EGA-only starts in other modules: SWOTL 2,609, FLIGHT 490, FRONTEND 185, SPAZ 14, CAMPAIGN 13, PANEL 12, NOTCAMP 7, REPLAY 2 |
| Translator gap | `make gen` with the EGA traces: 45 FRONTEND starts unclassified (bodies unchanged): targets +1B94, +1BC2 of the near calls `[28EC]`/`[28EE]` (+1958, +1AEC, +1B54) and the RTSEGA thunk targets of the driver calls (EGA-only `indirect.csv` targets). The exclusions SWOTL+4F7B, +50A5 (cell walk) and FRONTEND+A90D (call to RTSEGA+4AC3) execute |
| D16 | Builders +E68D, +E690, +E694, +E697, +E6AD, +E6B0, +E6B4, +E6B7 (annotated `variant`) write 9-byte and/or cells at stride 9 over runs +6A4D, +7C3D (640 bytes per writer) and +758E, +877E (376 bytes per writer). `ret` written and restored at a cell start by +4F71/+4F7F and +509B/+50A9 (the VGA +4FF0/+4FFC, +5132/+513D). Operand words patched by +8E83..+8F4E (24 writers; VGA +8FD5, +9030, +908E). No reload form (+E616/+E619) |
| Pointer | EGA entries RTSEGA save +52C0, restore +535D, draw +53E2 (`pointer_static.py`): logical x = two hires pixels; save buffer 4-bit nibbles, high first, w bytes per row; restore and draw use write mode 2 and the bit mask, so colour FEh shows as Eh, FDh transparent; draw page ds:287C. Census: 52 mode 0Eh snapshots with the pointer complete |

## E5 results (2026-11-05)

| Item | Result |
|---|---|
| First light | `ega-m1b-logo`: shown planes, 16 registers (the EGA palette 000 00A 0A0 0AA A00 A0A A50 AAA 555 55F 5F5 5FF F55 F5F FF5 FFF), the model's planes, registers and latches and the real video equal DOSBox; corrupted captures (a hires bit, a gun, the depth, a model byte) are caught |
| Flyby profile | 68020 A1200 with `OCS`, `amiga/perf_flyby.gdb` (from drawn frame 12, 5 × 100 fields; captures in `tmp/`), `tools/profile_tree.py`: 142.1 M cycles. `EGA_04BD0` 55.24% inclusive, 5 calls of 15.7 M cycles (about 1.1 s each): model writes 21.66%, reads 14.12%, map mask `out`s 10.63%, its own code about 8.8%. `EGA_04FD3` 5.47% (50 calls), `EGA_051E0` 2.26%; the and/or walk (`SWOTL+4DAE`) 0.37%; `EGA_04AC3` not executed |
| Frame period | drawn frames 4–11 of the demo 33 fields each (660 ms; VGA frames fixture about 300 ms); about 110 fields per frame in the profile window |
| 4AC3 | not in the flyby window; host census from the entry (`tools/host_census.py --whole --labels`, `ega-m2`, which stopped short of the snapshot after 32 frames): one call, at a screen change |
| D5 | 4BD0 priced high: E6 builds its native. 4AC3 is not per frame; E6 prices one call before building it |

## E6 results (2026-11-05)

| Item | Result |
|---|---|
| 4AC3 price | generated: one call 322 fields (6.4 s) on the 68020 A1200 with `OCS` (attract demo, fields 2922→3244; gdb at `EGA_04AC3`/`EGA_04BCF`); native: 11 fields |
| 4BD0 | native: 22 calls in the flyby window (perf_flyby.gdb's, from drawn frame 12, 500 fields) 63 fields, 2.9 each, at most 10 (generated, E5: about 55 fields a call) |
| Frame period | drawn frames 4–11 15.3 fields (306 ms; E5 33); flyby window 24.8 fields a frame |
| Oracles | 114 converter cases: entries (m4, m5 4BD0; m5, m7 4AC3; m2's 4AC3 runs before its key script ends) and mutations equal the original with the Python model: planes, registers, latches, marks, guest RAM, final registers and live flags (CF, ZF); declines unchanged; every plant caught. Model differential: 84,783 steps, all plants caught |
| Sync set | `make gen`: RTSEGA loop heads 4AFA, 4B1F, 4C13, 4C2C leave `poll-points.csv` (inside the rows); no unclassified starts |
| References | E5's provisional EGA references carried the old polls fingerprint; E7 re-recorded every row without REP slices. VGA unaffected (D2 filter) |

## E7 results (2026-11-05)

| Item | Result |
|---|---|
| Corpus | 91 rows (`milestones-ega.csv` 9, `coverage-ega.csv` 82), `tools/reference.py` per table in 4 shards at nice 10, poll points of `3874464`'s `make gen`; RAM, VRAM and DAC of every last snapshot equal across two passes. m2, m4, m5 differ from E5's provisional hashes (REP slices gone, new sync set) |
| c81, c84 | under polled timing the scripts' damage comes later or not at all: `ega-c81` reaches `PANEL+315D` at 2.67 G instructions (limit 120 → 300 s); `ega-c84` has no wing damage by 3.23 G (dropped; E2's unpolled run mapped its code); both repeat their events byte-identical |
| Gate set (D7) | EGA-only instruction starts (executed in an EGA row, in no VGA row): 5,528, mostly RTSEGA and SWOTL, a few SPAZ (timing). Greedy cover from the five milestones: 20 rows, `HOST_EGA`; `t-ega-%` takes `coverage-ega.csv` for `c` rows (4,800 s host timeout) |

## E8 results (2026-11-05)

| Item | Result |
|---|---|
| Fixes | translator: a PLINK manager call takes its return site's live flags (`passes_flags`; 251 of 251 calls; terrain-polygons' live-flag check at SWOTL+101E1). `compute_ega.s` equates `ER_` (an `EGA_` equate at 0 moved `host_run`'s code range to 0: machine byte 0496). `m68k_blocks` restores a skipped case's planted bytes (7 mismatches on seed 1). Plants re-anchored to moved source: `compute-u8` (E6 `device` argument), `pointer-model` equality (E4), `ega-convert` (`ER_`). `make map`: `indirect.csv` from the final traces (9 rows) |
| Translator, VGA | `make test` 108 ok; fails only replay-run-isolation, host-replay-visits, display-palette (fail at 811c783 too). `blocks` 0 mismatches. `make map` 190 traces, 0 unclassified, 0 conflicts. `test-host-all` 91/91 (3,823 s). Sabotage: all but those three |
| EGA host | `test-host-ega` 20/21. `ega-c82` fails identically at 5d1520e: FLIGHT 2F7C:0F2F (target re-check) indexes z by `[bp-0Ch]`, never set on that path; DOSBox's BIOS interrupt code left 0089h there, the runtime's private IRQ stack (irq-plan I4) leaves 0000h; the reference drops target 2, ours keeps it (frame of service 39674; irq #8050 not reached). irq-plan's named risk; RAM equal at service 39674 |
| Amiga | `test-amiga` VGA m1b; EGA `ega-m1b-logo` on `a3000`, `a500+-020`, `a500-020` (AmigaXDev 4cf0a24; chipset, CPU, Chip checked in `debug.uae`). Replays: VGA 5 + fetch-window plant (14 pixels), EGA 5 + `ega-c9-mouse-menu` + sprite-colour plant (`SWOTL_PLANT_SPRITE_COLOUR`, 28 hires pixels; pointer sprites composed). Restore VGA, `OCS`, `a500-020`; smoke; workbench incl. `icon-ocs` |
| D6 | `a500-020`: no `sfx.rsc`: "FM effects do not fit in Chip; effects silent"; with TFH `sfx.rsc`: "sound TFH" |
| Display audit | EGA (`OCS` on `a1200`, `a3000`) and VGA: 40/40 captures; EGA plants (plane bit, colour, model byte) caught. The TICKS check fails in all three and at 811c783 (posted 26,065, run 25,874: effect-capture ticks held, sound-plan R1) |
| Meter | m4, pre-ECS (811c783) → now: 141,801,558 → 144,029,707 model cycles (+1.57 %), generated +2,229,360. SWOTL+150EA `__aFlshl` loop (77,720 runs) stores the CCR then merges CF: ZF live at its wrapper's `retf 4` (481 return sites). Source: 4BD0's resume RTSEGA+4C2C `repe cmpsw` (CX=0 passes ZF) makes ZF live at the 4BD0 entry (`compute_resumes`), a dispatch entry, so UNKNOWN carries ZF to every indirect call. Already at 5d1520e |

## Lessons applied from the VGA port

| VGA experience | ECS rule |
|---|---|
| Surfaces found late, one failure at a time | E2 maps the complete surface before runtime code; the device model is written whole from the reference for the registers in use and fails loudly on the rest |
| References re-recorded after sync-set changes (I8, I10, F8) | lockstep references recorded once, after the natives (trap 2); VGA references never re-recorded (trap 1) |
| Display pipeline built up over many steps (D9, queue, cap, pointer) | D9 and the double-buffered queue reused as they are; planes copied, no new pipeline |
| Speed natives priced one by one | the converters priced from one profile and decided together (E5, D5) |
| Slow A1200 iterations | develop on the existing `a1200` fixtures with `OCS`; ECS fixtures for confirmation |
| Per-change verification churn | implement E3–E6 first, verify once in E8 (batch verification) |
| Item 48 sizes and audits | WHDLoad sizes measured once per machine class with MEMFREE; installer and release audits in one pass |

## Commits

1. Reference tooling and the poll-hash filter (E1, D2): VGA host subset proves the filter.
2. EGA on host and Amiga (E2–E5): translator, runtime, platform, scope in AGENTS.md, EGA
   references definitions, gates.
3. Converter natives (E6, E7).
4. Release (E9).
