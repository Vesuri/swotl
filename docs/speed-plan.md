# Speed plan (phase 7)

Rules, measurement and work order for all speed work on the A1200 build.
An implementing agent follows it literally, one step at a time. Step
details (prices, coverage, plants, FS-UAE checks) are in the step's commit
message (`git log --grep '^R[0-9]'`); round 1 (T1–T15) at `781975e`, the
sections of R16–R34 in this file at `e2cedc6`.
Method background: [perf-method.md](perf-method.md). Open-work item: 14b.

## 1. Target and state

- **Bar (user, 2026-10-07):** a 14 MHz 80286's frame rate on the 68020 +
  8 MB Fast model (`AMIGA_CPU` unset): frames 4–11 median ≤ 12 fields
  (240 ms); stretch ≤ 10.
- **Status:** R16 alignment repair, R17 palette validity, R18 flag extraction kept; R20 cell
  cache, R21 string layout, R22 call layout, R24 REP STOSW fill, R25 BP as data, R26 REPE CMPSW, R27 cold
  branch sides, R28 carry in X, R29 far push, R30 repeated segment loads,
  R31 push/pop runs, R32 conditional-over-jump fusion and R33 packed far returns
  kept; R34 FM continuity accepted as a quality tradeoff. Item 14b's 240 ms target
  remains unmet; only the N1 transform pilot is authorized (native-plan U2);
  none is enabled.
  Next: [native-plan.md](native-plan.md).
- **Frames fixture** (A3, `6bf8aef`, 2026-10-21): medians 370, 390 and
  400 ms; run-median span 370–400 ms. Frames 4–11 intervals (fields):
  `[26,15,21,18,22,18,19,16]`, `[26,15,21,19,22,18,20,16]`,
  `[25,17,28,20,19,20,23,18]`. Interval spans 15–26, 15–26 and 17–28
  fields. Baseline only; no same-session parent comparison or speedup claim.
- **Bench** (A3, `6bf8aef`, 2026-10-21): opening frames 4–11 sums 68,525,
  68,536 and 68,493 lines; median 68,525, span 43 lines (0.063%). Corresponding
  profiler cycles: 62,220,700; 62,230,688; 62,191,644 (908/line).
  All three final guest RAM hashes match the established bench endpoint
  (`951adbe5…39b6c63`). This spread exceeds the introduction's two-line observation
  (§4); no build-to-build claim. Palette window 38,392–38,405 lines (R17).
- **Meter** (m4, A4 weights/rule, unchanged `e891ace`): generated + walk +
  runtime 173,907,930 model cycles; host platform adds 2,035. Recalibration of
  the same work changes the old 172,620,455 estimate by +0.7458%; no game speed
  change. R32 removes 46,981 JMP executions from the label-derived guest count;
  historical label-derived counts omit those executions.
- **Capture** (A3, second frames run, 100 fields): generated code 76.18%
  (cell walk 3.75%), runtime/platform 19.52% (`render`, `fm_field`, `loop_for`
  12.11%), no PC 2.23%, Kickstart 1.03%, IRQ transition 1.03%.
  2,183,599 semantic guest instructions (10,765 recovered zero-code entries),
  5,130,676 generated 68k instructions: 2.35 per guest instruction,
  9.92 cycles/guest instruction, 6.59 weighted static code bytes/guest instruction.
  Run 1's semantic count fails loudly on an unknown capture-start predecessor;
  run 2 is the first complete accounting. Run 3: 2,211,424 guest instructions,
  9.61 cycles each. All three timing/share reports retained in `tmp/native/A3/`.

## 2. Hard rules

Breaking any of these voids the step, whatever it measures.

1. **No guest code by hand.** No guest routine in C or asm, no edit of
   `build/gen/`, no runtime or platform code that tests a guest address,
   label, segment value or module offset (`if (ip == 0x3C0F)`, helpers named
   after `VGA_03C2D`, tables of guest addresses in `src/`). Guest code
   changes only through `translator/` lowerings or `annotations/`, then
   `make gen`.
2. **Where a change may live:** translator lowerings, the runtime surface
   (`src/runtime/`, named by surface: interrupts, display, ports) and the
   platform layer (`src/platform/amiga/`). **No native replacement of any
   guest routine** (HLE, G3 entries, hand-written 68k or C doing a guest
   routine's work, pattern-matched intrinsics), however small, until the
   user authorizes that routine in the conversation. Nothing in this file,
   open-work, a profile or "the translator work is done" is an
   authorization.
3. **Semantics are not traded for speed.** Every fast path is guarded by
   the exact condition that makes it exact (DF, CX, no 16-bit offset wrap,
   no overlap) and falls back to an exact body otherwise. Flags live after
   the instruction keep their exact x86 values. No dropped return check,
   poll point, fail-loud stop or wrap handling; no "usually true" or "never
   seen" assumption; no annotation asserting what the translator must prove.
4. **D16:** every cell is matched against the writer forms from the guest RAM
   bytes when a walk first reaches it and after every change its cache sees
   (R20, D3); a dropped cache walks exactly.
5. **Relevant gates stay green and unchanged** at every commit. Select checks
   by the change's dependencies and affected contracts under AGENTS.md's
   validation-scope rules; state the selection before running. Isolated audio
   synthesis does not require translator, DOS/input, whole-game host or replay
   suites. `make gates` remains the full-suite option for cross-cutting changes
   or explicit user requests, not a per-step requirement. Never skip a relevant
   failing check, mask, loosen or re-record a test, reference or tolerance to
   make a step pass. R1's representation change (D1) may change how the harness
   maps memory and registers, never what is compared. A plant is retired only
   with its template, after an equivalent plant on the new template is caught.
6. **New lowerings get differential coverage first.** Add the new form to
   the x86 corpora (`make test-m68k`, Unicorn x86-16 vs Unicorn 68020)
   with its guard edges (CX 0, 1, 0xFFFF; SI/DI near 0xFFFF; DF 1;
   mismatch at the first, a middle and the last element), see the test
   fail against a deliberately broken fast path, and add a sabotage plant
   so `make test-sabotage` fails if the guard is removed.
7. **Never compare the port with itself as correctness evidence.** Oracles:
   Unicorn x86, the host run against DOSBox references, the reference
   framebuffer. The display checks (host run: guest stores to A0000h vs the
   present's rectangles; `amiga/display_audit.gdb`: shown bitplanes vs guest
   A0000h) check the presentation, not the game; run the audit after any
   display change.
8. **No unmeasured claims.** Numbers in commits and docs come from runs in
   the same session, measured as §4 says.
9. **Out of bounds** (ask the user first): changing the frame fixture (CPU
   model, Fast RAM, FS-UAE options, fixture, game data and settings, warp
   and speed); presenting a frame before the game publishes it (D9: the
   outermost graphics driver call returns), reading the frame to find
   changes, or skipping published frames; changing the PIT or timer rate
   or the order of interrupt delivery; removing or thinning poll points or
   return checks; shortening the guest's own delay loops (SPAZ OPL waits
   are guest semantics); a double buffer or copper display;
   Chip-only memory (19). Exception: the deterministic frame bench (§4,
   user 2026-10-08) posts PIT ticks on a fixed schedule in its own runtime
   mode, as an instrument only.
10. **One step, one commit**, before/after numbers in the message; §1, the §7
    row and `docs/open-work.md` 14b updated in the same commit. Do not start the
    next step on an unproven one.

## 3. Acceptance (D0, user 2026-10-08: any speed or size improvement is welcome)

- Gates green (§2.5).
- **Meter (§4) on the m4 window:** model cycles lower; or equal
  (|Δ| < 0.001%) with a smaller code payload. Report Δ model cycles,
  Δ executed code bytes, Δ data reads/writes, Δ code payload. No minimum gain.
- **Layout and Amiga platform work outside the host meter (D5):** accept
  lower fixed-work 68020 bench cycles, with identical final guest RAM, all relevant
  fidelity gates green and no slowdown. Report the unchanged meter and
  actual code payload; do not infer a frames-fixture gain from the bench.
- **Code growth** only with lower model cycles (D2), or lower bench cycles
  for work covered by D5. Stop and ask before
  the payload exceeds 1,325,164 bytes by more than 25% (open-work 19).
- **FS-UAE check** after every third kept step and after any memory-model,
  cell-walk or layout step: a bench run (§4) per arm with a capture; the meter's Δ must have the
  sign of `ab_labels.py`'s mix-adjusted Δ over the changed labels. D5 exempts
  effects the host meter does not represent, not contradictory measurements
  of represented work. If they
  disagree, stop: fix the meter, never tune lowerings to FS-UAE noise.
  Report the bench's frames 4–11 cycles (they include layout effects).
- **Frame-rate claims:** the bench (§4) for build-to-build progress; the
  target itself is the frames fixture (§4, with the interval lists),
  measured at each re-profile. Neither is a per-step gate.

**Stop and ask the user** when: a gate fails for a reason that is not a
plain bug; a step needs any of §2 beyond what was approved; references
need re-recording or an interrupt delivery moves; two consecutive steps
are rejected by the meter; meter and FS-UAE disagree on represented work; a step is ambiguous.

**Per step:** price from meter counts (D5: fresh target capture and census);
write the price in a §7 step section before coding (at the commit its
details move to the commit message; the §7 row stays);
coverage first (§2.6; cases appended at the end of corpora, `m68k_blocks`
cases for multi-block changes); implement in `translator/` or
`src/runtime/` or `src/platform/amiga/`; `make gen` if translation inputs changed;
selected gates; meter (D5: bench); keep or revert (revert keeps the
passing new tests; one line in §10); one commit (§2.10); report in a few
lines.

## 4. Measurement

- **Frame period (P).** `amiga/perf_frames.gdb` under `amiga/debug.sh`
  (68020, 8 MB Fast): field at each of the first 12 drawn frames of the
  attract demo flight (one gdb stop per frame at the frame loop `R_044E2`).
  P = median of the frame-4…11 intervals × 20 ms. Emulated fields, never
  wall time; the 68020 model (`AMIGA_CPU` unset), never the 68030 for a
  claim; no warp, no `cpu_speed=max`; control = the parent commit, built
  and run in the same session with the same fixture; three runs per arm;
  quote ms per drawn frame. The start field varies run to run (4299, 4334,
  5274 seen: the hard-drive folder completes I/O on host time). Claim a
  frame-rate gain only when the arms' ranges do not overlap; frame times
  fall into trajectory modes (§5.1).
- **Shares.** The same fixture then captures 100 fields
  (`monitor profile` stops at 100) into `tmp/prof/frames.bin`;
  `tools/profile_report.py tmp/prof/frames.bin amiga/out/Swotl.elf
  --objdump m68k-amiga-elf-objdump --count rt_irq --count deliver --count
  plat_present`; per x86 form `tools/lowering_cost.py`. A capture is
  1.1 GB: delete it after the report. Use `lowering_cost.py` semantic guest
  counts for ratios: it excludes helpers
  and recovers zero-code entries using incoming guest control flow. Supply the
  exact generated assembly/IR with `--gen`. Unknown or ambiguous edges fail
  loudly. Older ratios include helper hits and omit zero-code entries;
  `profile_report.py` still reports label-derived counts.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop. Per drawn
  frame (m4): `repe cmpsw` `VGA_03BE9` 19,290 words (the whole view vs the
  previous frame), `rep stosw` `R_0C1CA` 16,075 words, `rep movsw`
  `VGA_03C2D` 151 words to A0000h (median 6 rows).
- **Reference cadence** (DOSBox-X `cycles=fixed 12000`, m4): a drawn frame
  every 9 PIT ticks ≈ 36 ms, ≈ 408K x86 instructions per frame.
- **Meter** (`tools/cost_meter.py`, deterministic): `--out tmp/meter/ARM.json`
  per arm, `--compare A B` for the §3 deltas. Weights `tools/cost_model.json`,
  fit at A4 on the `e891ace` bench capture: per code byte 1.038 (0.912 inside
  a loop of ≤ 256 bytes whose back branch was taken in the workload), read
  1.795, write 3.219, taken transfer 5.113 outside such a loop and 1.712 inside,
  word/general mul/div 23.317. Unsigned register long arithmetic uses a separately
  probed total of 4.125025 cycles (no additional fetch/muldiv charge;
  `m68k-optimisation.md`, B3 calibration). R² 0.9224, model −2.25% of measured. U1 selects executed
  back edges; this remains a workload-level cache approximation. The doubling
  plant is caught (419,726 extra instructions, 839,452 extra bytes). The
  per-instruction weight still fits to 0. Recalibrate (`--calibrate CAPTURE
  ELF --write`, then `--plant-check`) at the next re-profile or when the FS-UAE
  check disagrees. `tools/ab_labels.py` serves the FS-UAE check.
- **Bench** (`SWOTL_ARGS=BENCH ./debug.sh "" bench_frames.gdb`, same model;
  runtime.h `rt_bench`): no CIA timer; 9 PIT ticks per 4 runtime services
  (the flight makes 4 per frame, m4 draws a frame every 9 ticks), plus one
  per 8,956 consecutive visits to a poll point in a spin (SPAZ's rate
  calibration gets the reference count 8,956; the demo waits for a tick
  after loading its replay). Every build does the same guest work: demo
  after 1,628 services (reference 261,320), the guest's elapsed ticks 9 per
  frame, frames 0–56 the static opening view (rendered, compared, not
  blitted; the reference's 27 frames at 18 ticks), about 830K guest
  instructions each. Output: field and beam line at frames 0–12, the guest
  RAM at frame 12 (`shasum tmp/bench/ram.bin`; equal to the host run's at
  that frame), a 100-field capture. Two runs: equal RAM hash, frames 4–11
  sums within 2 lines (single frames within 16), window guest
  instructions within 0.02% (measured at its introduction). Not comparable to P
  (different frames and tick rate); compare arms by the frames 4–11 sum.
  Its window (the static opening view) runs no cell walk: the FS-UAE check
  of a walk change uses a frames-fixture capture per arm (cycles per mov
  cell, `move.b d0` executions in the walk).
- **Palette bench (D6).** `SWOTL_ARGS=BENCH ./debug.sh ""
  bench_palette.gdb`, same model and runtime schedule. Measure intervals
  60–67, dump guest RAM at frame 68, then capture 100 fields. Require equal
  final RAM between arms and display publications in the profile. This
  supplements the opening bench and normal frames fixture; neither changes.
- **Stops are free (S0).** Fields from `rt_run_guest` to m1b-logo
  (`VGA_039AD`), 68020: 99–100 with no stop between (3 runs), 99–100 with
  110, 364 and 731 stops (5 runs). `amiga_io_frames` counts the fields
  inside I/O windows (host-timed disk I/O, 7–17 here); the total does not
  move because the guest waits on the PIT.

## 5. Why round 1 stalled (do not repeat)

1. **The per-step measurement could not resolve the steps.** Frame
   intervals fall into trajectory modes (23, 29, 23, 30, … / 28, 24, 34,
   25, … / 30, 26, 36, 27, …); one executable gave run medians 24.5 and
   28.5. Cycles/guest follows the window's instruction mix (14.64–15.45 on
   unchanged or near-unchanged code). T7 and T10–T15 were priced at
   0.0007–0.07% of P, T8 at 0.28%: 10–10,000× below that noise. S5 (cell
   walk 14.1% → 12.0% of CPU) was rejected on the same unresolvable frame time.
2. **Layout noise of the same size.** Moving code changes the cost of
   untouched forms (T8: `jne near` 6.07 → 6.87 cycles; T12: `loop`,
   `shl`). Mix-adjusted per-form A/B from the saved reports (same weights
   for both arms): T3 −0.94%, T4-local −6.24%, T6 −2.19% are real; T7
   +0.26%, T8 +0.51%, T10 +0.23%, T11 −0.14%, T12 +0.72%, T13 +0.50%,
   T4 cross-block −0.63% lie inside ±0.7% layout noise. Their keep/revert
   verdicts were noise, and keeping lucky layouts biased later parents.
3. **Prizes shrank by narrowing.** Each step was confined to block-local
   sites under the unchanged register contract (little-endian memory,
   zero-extended registers, SI/DI in address registers, flags in a memory
   image). That contract is where the cost is (§6): a 19.9% group yielded a
   1.19% candidate, and T10–T15 0.0007–0.07% each.
4. **The 1% threshold** deferred T3/T5 and drove the narrowing. Removed by
   the user (2026-10-08): every speed or size improvement is welcome.
5. **Wrong cost unit.** Steps were priced in 68k instructions; on this
   model the cost is code bytes and data accesses (§6).

## 6. Cost model

Per-PC fit on the replan capture (13,608 non-branch PCs, 5.5M executions):
**cycles ≈ 1.09 × code bytes + 2.27 × data reads + 3.07 × data writes**
(R² 0.83). Outside the 256-byte i-cache a 2-byte register op costs ≈ 2
cycles, 4 bytes ≈ 4, `and.l #$ffff` (6 bytes) ≈ 6. Inside cached loops
bytes are nearly free. Price and accept in executed bytes, data accesses
and taken branches, never in instruction counts. FS-UAE is the user's
instrument; a real 68020 may weigh these differently. The meter's current
weights: §4.

The meter's runtime is the host run's (the reference's interrupts
replayed); the frames capture adds the CIA timer at its own rate.

## 7. Step index

Kept steps, one row each (names cited in code comments; M1 is the meter and label A/B,
M2 the frame bench, §4). The generated-code
contract they produce is in [translator-design.md](translator-design.md);
details in each commit. Δ is the meter's at the step (weights of its time).

| Step | Change | Where | Meter Δ |
|---|---|---|---:|
| T3, T4-local, T6, T10, T11 | round 1: block-local byte order, carry in X, masks, byte copies | `lower.py`, `flags.py` | (frames) |
| T8 | AH-class register writes as one `bfins` | `lower.py` | −0.242% |
| T7 | word MUL/DIV high results only where live | `lower.py` | −0.005% |
| R1a | runtime guest-memory accessors | `src/runtime/` | −0.0001% |
| R1b | reversed guest memory, biased segment bases, mirrored SP/BP (D1) | `lower.py`, runtime, harness | −1.916% |
| R1d | word memory operands folded into the 68k op | `lower.py` | −1.231% |
| R2 | poll point falls through; call in an out-of-line stub | `emit.py` | −1.029% |
| R3a | adc/sbb skip the Z preset where ZF is dead | `lower.py` | −0.991% |
| R3b | flags reach a reader across plain instructions | `flags.py` | −0.188% |
| R4 | guest registers' upper words undefined; zero-extend where consumed | `lower.py`, `compact.py` | −2.646% |
| R5 | return checks to local trampolines; ret pops keep upper words; `rt_lookup` cache per CS:IP | `emit.py`, `lower.py`, runtime | −2.036% |
| R6 | guarded copies address `[bp+d]` directly (D2) | `region.py`, `tools/bp_regions.py` | −1.213% |
| R7 | cell walk runs mov cells as a counted run (matching kept) | `smc.py` | −9.037% |
| R8 | hot branch targets aligned by pads that never run | `tools/align_targets.py`, `gen.pad` | 0 (bench −0.30%) |
| R9 | mul/div without DX masks; operands straight into `mulu` | `lower.py` | −1.615% |
| R10 | runtime: table flag helpers, one-move guest words, OPL/EOI in `rt_out8` | `support.py`, `src/runtime/` | −0.299% |
| R11 | re-profile, meter recalibrated | `tools/cost_model.json` | — |
| R12 | REPE CMPSW and REP STOSW two words per iteration | `lower.py` | −5.207% |
| R13 | repeated index formation or CS base in a run dropped | `reuse.py` | −0.354% |
| R14a–d, g, i | high-byte idioms, CCR through jump chains, memory compares without `lea`, SI/DI self-test, cold divide errors | `lower.py`, `flags.py`, `emit.py` | −2.600% |
| R14e | dispatch rows say near-only or far; returns per row kind | `emit.py`, runtime | −0.140% |
| R14f | displacements folded into d8 under no-wrap guards | `reuse.py` | −0.288% |
| R15 | interrupt delivery in one runtime round trip | `src/runtime/` | −0.092% |
| R16 | alignment convergence, fresh targets and profiler/meter repair | translator, tools | 0 (bench −1.18%, D5) |
| R17 | palette validity per physical back buffer | Amiga platform | outside meter (later bench −2.81–3.61%, D5/D6) |
| R18 | TF/IF/DF extraction with register bitfields; meter operand and A/B selection fixes | `support.py`, tools | −0.0126% |
| R20 | cell cache: cells matched once, runs of destinations stored by longs, exact invalidation (D3) | `smc.py`, `lower.py`, runtime | −15.3114% (bench +0.9424%, user-approved tradeoff) |
| R21 | backward string bodies outlined; forward path falls through | `lower.py` | −0.1080% |
| R22 | first matched walk call returns into its check; fallback outlined | `lower.py` | −0.0246% |
| R24 | REP STOSW: eight longs per pass, long-aligned stores, odd word last | `lower.py` | −1.1239% |
| R25 | native BP kept in a run, dead mirror stores dropped | `reuse.py` | −1.1354% |
| R26 | REPE CMPSW: eight long compares per pass, remainder pairs first | `lower.py` | −0.8031% |
| R27 | cold sides of hot forward jcc out of line, profile-chosen | `emit.py`, `tools/outline_sites.py` | −0.6278% (bench −0.481%) |
| R28 | carry in X kept across an adc/sbb operand setup in d6 | `lower.py` | −0.4796% |
| R29 | CALLF pushes CS:IP as one long; SP wrap out of line | `lower.py` | −0.4660% |
| R30 | segment loads that mostly repeat compare first; store, check and base out of line | `lower.py`, `tools/seg_repeat.py` | −0.5926% (bench −1.816%) |
| R31 | push (pop) runs step SP once; SP wrap out of line | `reuse.py` | −0.0821% |
| R32 | invert conditional over a lone jump; preserve jump entry aliases | `emit.py` | −0.1766% |
| R33 | guarded packed far-return pop and full CS:IP check | `lower.py`, `emit.py`, `rt_entry.s` | −0.7089% (bench −2.318%) |
| R34 | canonical FM phase, 0.75 dB envelopes, stable four-voice allocation | `fm_paula.c` | meter unchanged; bench +0.0453%, user-approved quality tradeoff |
| A2 | semantic guest-entry accounting, helper exclusion and zero-code aliases | `lowering_cost.py` | tooling only |
| A3 | HEAD frame, bench and native-candidate baseline | docs | measurement only |
| A4 | executed-back-edge loop classification and recalibration (U1) | cost meter/model | tooling only |
| B3-cal | separately probed unsigned register long-arithmetic cost | cost meter/model | 0 on saved A4 workload |
| B3 | native candidate prices under both U3 rules; unpriced rows retain ceilings | rendering map | pricing only |
| B4 | consolidate 14 candidates; record U0–U4, authorize only the transform pilot | docs | no code change |

No priced translator candidate remains. Unchanged (§2): poll points
(`(a6)` is guest byte 0; no thinning), `mulu`/`divu` themselves. The translator helpers
`__set_flags` (POPF/IRET) and `__flags_word` are the largest runtime-side
items left.

## 8. User decisions (D0–D4 2026-10-08)

- **D0.** Per-step acceptance by the meter (§3), instead of FS-UAE frame A/B.
- **D1.** R1's memory model, with the harness converting memory and
  registers. Plants whose templates R1/R4 remove are replaced first, then
  retired: "word loads not byte-swapped", "ror for ror.w on memory dest",
  "native word store skips byte swap", "native byte-order restoration
  omitted", "address word not restored", "stack pointer not restored",
  "address restoration copies stale scratch", "SP not 16-bit", "RETF CS
  pop uses linear SP", "mask trusts dirty upper word".
- **D2.** R6 may grow the code beyond +5% when each guarded copy lowers
  model cycles; the +25% stop in §3 remains.
- **D3.** Cell cache (R7b) with exact invalidation. Re-price approved 2026-10-17:
  RET-aware, consecutive destinations a long at a time; priced −17.2% of the
  meter, built as R20 (−15.31%, §7).
- **D4.** Deterministic frame bench (§4).
- **D5 (2026-10-14).** Bench-based acceptance for layout and Amiga platform
  work outside the host meter; all fidelity gates and no slowdown remain.
- **D6 (2026-10-14).** Add a separate frames-60–67 fixed-work palette bench,
  with equal final guest RAM, exercised palette calls and all fidelity gates.
  Keep the existing bench and normal frame-rate fixture unchanged.
- **D7 (2026-10-14).** R19 flag-word packing rejected (§10). Trap flag:
  TF = 1 stops loudly at POPF/IRET, no single-step delivery
  (translator-design.md).
- Native replacement: [native-plan.md](native-plan.md); each routine needs the user's
  authorization (§2.2).

## 9. Gap

A3's frames-fixture medians are 370, 390 and 400 ms: the middle run needs
150 ms (38.5%) less to reach 240 ms; the run range needs 130–160 ms less.
No priced translator candidate remains (§7). Next: the authorized transform pilot (N1), in
[native-plan.md](native-plan.md).

Current candidate costs, A3 run 2 (`6bf8aef`, 100 fields, 28,420,399 profiler cycle
units). Own cost groups generated instructions by call-target boundary; inclusive
cost follows completed A7 call scopes, excluding hardware and guest interrupt
delivery (`tmp/item30/inclusive.py` method). All listed observed calls finish inside
this window. `B8A1` is an explicit extra boundary; neither it nor `CE3C` executes.
Zero here does not prove a routine unreachable. Inclusive rows overlap; do not add them.

| SWOTL | Function | Own share | Calls/100 fields | Own cycles/call | Inclusive cycles/call |
|---|---|---:|---:|---:|---:|
| `B52D` | transform wrapper | 1.02% | 1,483 | 196 | 1,378 |
| `B54B` | point transform | 6.17% | 1,483 | 1,182 | 1,182 |
| `B4E2` | perspective divide | 1.82% | 2,072 | 249 | 249 |
| `B017` | projection | 2.99% | 1,036 | 819 | 1,318 |
| `D5A6` | normalise/project | 2.07% | 836 | 703 | 2,048 |
| `B8A1` | face-facing test | 0% | 0 | — | — |
| `BB70` | polygon bounds/classify | 1.33% | 177 | 2,140 | 2,140 |
| `109D6` | ground objects | 2.64% | 109 | 6,893 | 24,164 |
| `4DAE` | sprite decoder | 7.98% | 49 | 46,282 | 60,771 |
| `D69C` | clipped line | 0.99% | 130 | 2,171 | 2,781 |
| `BD68` | edge submission | 0.67% | 94 | 2,013 | 4,988 |
| `FDE0` | terrain polygons | 1.59% | 5 | 90,482 | 525,717 |
| `F290` | terrain/scenery selection | 1.10% | 5 | 62,641 | 102,471 |
| `BFD1` | rasterizer | 6.57% | 5 | 373,600 | 568,646 |
| `CE3C` | background fill | 0% | 0 | — | — |

Across the three captures, sprite share is 2.88–7.98% (9–49 calls), rasterizer
5.02–6.57% (4–5 calls); generated code 74.78–76.91%. Retain this trajectory
variation when pricing candidates. Per-run counts and costs: `tmp/native/A3/frames-*/`.
The rendering map consolidates these costs with source availability, admission
and adaptation prices. U0/U2/U3 approve the transform pilot with complete
byte-write history; U4 defers further routines.

## 10. Rejected and not built

(One line each: step, change, measured Δ, reason. Round 1 is in git
history at `781975e` and §5.)

- S1 shape "compare each present against a shadow copy to find changed
  rows": rejected by the user before building; every present would read
  the whole 64000-byte frame. Replaced by marks at the driver's stores
  (D9, translator-design Display).
- S5 "cell walk: mov cells four at a time under one bound check, opcode
  of each still compared": walk 14.1% → 12.0% of CPU, rejected only
  because frame times (trajectory noise) did not separate. Revisited as
  R7 under the meter.
- R1c "SI/DI mirrored like SP/BP": census −1.0% (SI/DI serve as data
  registers far more than as lone indexes); not built.
- R14h "mul with DX dead": DX is live after every hot `mul` (≤ 10K
  executions with DX possibly dead, ≈ 0.01%). Not built.
- R15 shape "per-vector `rt_lookup` cache on interrupt delivery": +≈ 10K
  model cycles (the timer handler's row is an overlay row, so the row search
  still runs per delivery); reverted.
- R19 flag-word packing: priced at 18,726–29,266 model cycles
  (0.0086–0.0135%) and ten code bytes on `25dd32c`; too small (D7).
- R23 loop-tail placement: model −0.1361%, changed-code target −11.3304%,
  code +12 bytes; six opening benches per arm give median +0.0042%, mean
  +0.0326% (overlapping ranges, five pairs slower). No-slowdown acceptance
  not established; placement reverted. Approved alias-boundary and timing-tool
  fixes plus oracle coverage retained; all seven gates passed. Evidence: `tmp/item31-r23/`.
- X1 REP STOSB long fill: not built; zero executions at all 17 emitted entries
  in A3’s three captures and the fresh 49-frame m4 census; zero priced saving
  in the acceptance window. Startup executes four sites (319,670 bytes); no
  startup timing or unreachability claim. Evidence: `tmp/native/X1/`.
