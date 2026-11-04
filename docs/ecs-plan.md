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
| D3 | One executable, one slave: no AGA → EGA, AGA → VGA; the `EGA` switch (Shell argument, tooltype, WHDLoad Custom3) forces EGA on AGA; the slave drops `WHDLF_ReqAGA` |
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
| E5 First light, pricing | a. done 2026-11-04: provisional lockstep references `--services --polls`: `ega-` m1, m1b, m2, m4, m5; every EGA row `rep_chunks=1` (DOSBox slices RTSEGA+4C2C `repe cmpsw`; user 2026-11-04). b. done: EGA host lockstep (E4). c. Platform (parallel with E4): `Swotl.cpp` ECS display (BPLCON0 hires, 4 planes, DDFSTRT `$3C`/DDFSTOP `$D4`, FMODE 0, 16 colours 12-bit, present = byte copy of marked spans per plane), D9 framing, frame cap, double buffer and beam-stamped handoff unchanged; pointer sprites on ECS (colour registers 17–31, fetch window clear of sprite slots, as the AGA plant checks); `EGA` switch and release template; `milestone.gdb.in` decodes 4 planes and 16 colours. d. FS-UAE: `a1200` with `EGA`, then `a3000`; EGA flyby profile (m4): share of 4AC3, 4BD0 and the and/or walk | host and FS-UAE milestones pass; converters priced | 2 h |
| E6 Natives (if D5) | device-row contract in native-compute.md: planes, latches and final register values exact; 4AC3, 4BD0 natives; oracle: original x86 on Unicorn with a Python EGA model on memory and `out` hooks, entries from `native_entries.py` EGA fixtures; C model vs Python model differential; sabotage. Regenerate: final sync set | oracles and sabotage pass | 1 h |
| E7 Final EGA corpus | every EGA row `--services --polls` (and `rep_chunks`/`joystick` as its VGA row); `reference.py` determinism; gate set (D7) from a committed cover tool | references stable; gate set listed in the Makefile | unattended + 15 min |
| E8 Verification (one batch) | EGA: `test-host-ega`, `test-blocks`, `make map` (zero unclassified), sabotage, `test-amiga` EGA on `a3000` and the new AmigaXDev presets `a500+-020` (A500+ ECS, 68020, 1 MB Chip, 8 MB Fast) and `a500-020` (A500 OCS, 68020, 512 KB Chip, 8 MB Fast: TFH and silent effects), display audit, restore check, workbench (`EGA`), pointer sprites (replay picture check with the fetch-window plant). VGA, shared translator and runtime changed: `make test`, `test-blocks`, `test-host-all`, `test-amiga`, `test-amiga-replay` with plant, display audit, bench (meter Δ within noise) | all pass | unattended + 30 min |
| E9 Release | slave: no `WHDLF_ReqAGA`, Custom3 `EGA`, sizes by MEMFREE on `a500+-020` and `a3000`; small-Chip slave (D6): BaseMem and ExpMem by MEMFREE on `a500-020`, TFH or silent effects; `test_whdload.py` `--setup a3000`/`a500+-020`/`a500-020`; installer installs RTSEGA.OVL and stops deleting it (record counts) and the small-Chip slave with its own icon, `check_release`, `test-release-installer`, `whdload_preload`; ReadMe and README requirements and history 1.1; docs: AGENTS.md scope, architecture, amiga-arch, translator-design (D9, D16, device lowering), pc-reference-loop, source-inventory, plink, whdload, release, open-work; AmigaXDev lessons and preset (`make share`) | release audits pass | 1 h |

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

## Lessons applied from the VGA port

| VGA experience | ECS rule |
|---|---|
| Surfaces found late, one failure at a time | E2 maps the complete surface before runtime code; the device model is written whole from the reference for the registers in use and fails loudly on the rest |
| References re-recorded after sync-set changes (I8, I10, F8) | lockstep references recorded once, after the natives (trap 2); VGA references never re-recorded (trap 1) |
| Display pipeline built up over many steps (D9, queue, cap, pointer) | D9 and the double-buffered queue reused as they are; planes copied, no new pipeline |
| Speed natives priced one by one | the converters priced from one profile and decided together (E5, D5) |
| Slow A1200 iterations | develop on the existing `a1200` fixtures with `EGA`; ECS fixtures for confirmation |
| Per-change verification churn | implement E3–E6 first, verify once in E8 (batch verification) |
| Item 48 sizes and audits | WHDLoad sizes measured once per machine class with MEMFREE; installer and release audits in one pass |

## Commits

1. Reference tooling and the poll-hash filter (E1, D2): VGA host subset proves the filter.
2. EGA on host and Amiga (E2–E5): translator, runtime, platform, scope in AGENTS.md, EGA
   references definitions, gates.
3. Converter natives (E6, E7).
4. Release (E9).
