# Plan: phases 1–2 (reference loop, static/live map)

Step plan for [phases.md](phases.md) gates 1–2. Each step: deliverable, how,
done-when. Methods come from Slicks ([pc-reference-loop.md](pc-reference-loop.md),
[toolchain.md](toolchain.md)); copy its tools and patches before writing new
ones. All outputs under `tmp/` unless tracked tooling. Open items in
[open-work.md](open-work.md) map onto these steps.

## Phase 1 — PC reference loop

| Step | Deliverable | How | Done when |
|---|---|---|---|
| 1.1 | `make inspect` | Port Slicks `tools/mz_info.py`: SHA-256 of every `ref/` file, MZ header, relocation table, overlay table words, PLINK strings. Record in `docs/source-inventory.md`. | Facts reproduce from `ref/`; hashes recorded. |
| 1.2 | Disposable root | `make prepare-reference`: `rsync -a ref/ tmp/pc-root/`; conf mounts `tmp/pc-root`. | Original runs; `ref/` unchanged after a run (hash check). |
| 1.3 | Instrumented DOSBox-X | Vendor tag `dosbox-x-v2026.08.31` to `tools/vendor/`; apply Slicks patches renamed `SWOTL_*`; keep `tools/patches/ORDER`. | Patched build runs the game headless. |
| 1.4 | Arming + module map | Arm at the MZ entry (`CS:IP` = load seg + `1617:0382`). Log INT 21h opens/reads with name, handle, buffer `seg:off`, length. Maintain a residency table: area -> loaded `.OVL`. All addresses normalised to `(module, offset)`. | Every `.OVL` load appears with name and destination segment. |
| 1.5 | Trace hooks | Per-instruction executed bitmap + edges keyed by module; interrupts with registers; port aggregates; VGA reads/writes; writes into executed ranges, tagged "overlay load" when inside an INT 21h read. | Outputs written on clean exit; a run's outputs parse with the summarizers. |
| 1.6 | Snapshot hook | Env-armed dump at a named `(module, offset)` or event: 1 MiB RAM, registers, segment regs, PIT/PIC state, `A0000` 64 KB, DAC palette. | Two dumps of the same milestone are identical, or the diffs are listed and explained. |
| 1.7 | Headless runner | `tools/pc_run.py <script>`: `SDL_VIDEODRIVER=dummy`, `-time-limit`, distinct exit reasons (success signal / limit / unsupported / guest fault), outputs in `tmp/pc-runs/<name>/`. | A limit never reports success. |
| 1.8 | Launcher arguments | Find the argv parser from the entry (trace + Ghidra); decode `V S 5 N Y Y 64`. Pin one set in `docs/source-inventory.md`. | Each argument's effect named with code evidence. |
| 1.9 | CPU personality | Trace for CPU probes (`PUSHF`/`POPF` bit tests, `0x66`/`0x0F` 386 opcodes). Pick primary (286 or 386) + comparison emulator. | Choice recorded with evidence; milestones agree on both, or the difference is attributed. |
| 1.10 | Determinism | Identify PIT reprogramming (ports `40h`/`43h`), INT 8/9 hooks, RNG routine and its seed source. Pin via patch or input. Record time acceleration as milestone state. | Two runs of a script reach identical RAM at each milestone. |
| 1.11 | Input injection | Keys injected when the menu-poll routine is reached (guest-state trigger in the patch), not by pace. Joystick/mouse via env-armed device patch (Slicks mouse patch). Evaluate `DEMO*.DEM` and film replay for flight input. | Each injection is acknowledged by a guest state change. |
| 1.12 | Milestones | M0 entry; M1 mode 13h set; M2 FRONTEND resident + menu poll; M3 FLIGHT resident + first flight frame; M4 N flight frames with advancing sim state; M5 film replay. Each: positive guest signal + snapshot. | `make reference` runs all and reports per-milestone hashes. |
| 1.13 | Image proof | `tools/load_image.py`: root from EXE + relocations at the captured load segment; overlays from `.OVL` (+ fixups once 2.2 knows them). `cmp` against M0/M2/M3 snapshots with data ranges masked. | Byte-identical code ranges for root and every loaded overlay. **Gate 1.** |

## Phase 2 — static/live map

| Step | Deliverable | How | Done when |
|---|---|---|---|
| 2.1 | Ghidra project | Headless import of the proved root at its load segment; each overlay as an overlay block at its area. Port Slicks `ExportListing`, `MarkEntries`, `SeedLiveMap`. | Listing exports for every module; traced entries seeded. |
| 2.2 | PLINK mechanism | Start from the manager's strings ("Ovl stack ..."). Determine call path to non-resident overlays (stubs / far call / interrupt), return stack, residency rules, fixups, which overlays coexist. Write `docs/plink.md`. | A model predicts every overlay load and return in the M2–M5 traces. |
| 2.3 | Compiler runtime | Identify startup code, prologues, helpers (long math, far pointers, stack check). Write calling convention into `x86-notes.md`. | Every runtime helper called in traces is named and classified. |
| 2.4 | Recursive-descent decoder | `tools/sweep.py` (Capstone) from annotated entries + traced edges, per module. Output: code/data/padding/unresolved per byte; indirect sites. No linear sweep. | Executed bytes all classified as code; residue counted. |
| 2.5 | Surface inventory | `docs/external-surface.md`: INT (vector, AH) with call sites; ports; EMS (INT 67h); mouse (INT 33h); keyboard and timer hooks; VGA mode and access pattern (chained/unchained, CRTC start address for page flips); driver overlay call tables (RTS*, SFXA, SPAZ). | Every traced interrupt/port/device access listed with owner and frequency. |
| 2.6 | Code-write audit | Classify every write into executed ranges: overlay load, relocation, or self-modifying. | Non-load writes listed with writer PC; zero unexplained. |
| 2.7 | Indirect closure | `annotations/indirect.csv`: each executed indirect site with its observed target set; jump-table patterns recognised statically. | Every executed indirect site has targets; static-only sites listed. |
| 2.8 | Coverage plan | Executed vs decoded code per module; extra scripts (campaign, each aircraft, replay, options) until coverage stops rising or residue is explained. | Coverage table in `docs/source-inventory.md`. **Gate 2.** |

## Evidence handed to the translator design

| Decision ([translator-design.md](translator-design.md)) | Evidence step |
|---|---|
| D1 return mapping | 2.2, 2.3, 2.6 |
| D2 overlay model | 1.4, 2.2 |
| D3 segment model | 2.3, 2.4 |
| D7 indirect control flow | 2.7 |
| D8 interrupt delivery | 1.10, 2.5 |
| D9/D10 drivers, sound | 2.5 |
| D15 memory target | 1.4, 2.2 |
| D16 self-modifying code | 2.6 |
