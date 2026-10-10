# Performance method

How to get a number you can trust on the A1200 and decide what to do with it.
Rules first; other projects' figures appear only as labelled examples (`ex:`).
Provenance: Slicks `docs/performance.md`, `frame-pacing.md`,
`development-verification.md`, git `docs/performance-{profiling,verification,distributions}.md`;
Pokeri `docs/performance.md`, `testing.md`; RoF `docs/perf-budget.md`, `AGENTS.md`;
Revs `docs/perf-method.md` (§ cited), `AGENTS.md`; Vette `docs/performance.md`,
`development.md`. Code-level cost facts: [m68k-optimisation.md](m68k-optimisation.md).
Emulator driving: [headless-fsuae.md](headless-fsuae.md). Process rules:
[method-lessons.md](method-lessons.md).

## 1. Order of work

1. **Measure the original first.** Run the reference under the PC loop and record
   its own frame time/rate, with a calibration line. Every port figure is quoted
   against it. (Revs §WHAT THE ORIGINAL HARDWARE ACHIEVES; ex: BBC 97.0 ms median.)
2. **Get an end-to-end translated skeleton running on the target model, then
   profile.** Do not pick optimisation work or promise a target before that.
   (Slicks `AGENTS.md`; RoF `docs/postmortem.md` §4.)
3. **User sets the bar** (frame rate, best-case vs worst-case workload). "We need
   50" is not evidence; "impossible" needs a hand-asm datapoint. (RoF `AGENTS.md`;
   Revs §The target.)
4. **Price the prize before building**: reachable share × removable fraction,
   compared with the noise floor. A skip/sparse scheme needs visits removed AND
   the cost of one visit in the new shape; compute the break-even. (Revs
   §AND THIS TABLE IS WHY THE PER-LINE SKIP WAS A NULL, ex: 39.5% of visits = 2.4% of frame.)
5. **Name the quantity the cost is proportional to** and check the change
   reduces it (stores vs source reads). (Revs `docs/method-lessons.md`.)
6. **Read what the worst case is made of before tightening its loop**; largest
   wins were work not done. (Revs `docs/m68k-optimisation.md` §MODE 7.)
7. **Lever order**: less work (skip unchanged, fewer items) → representation →
   generated/asm code shape last. (Revs `perf-method.md` L432; Slicks `docs/performance.md` §Cost model.)

## 2. Units and metrics

| Rule | Why | Source |
| --- | --- | --- |
| Quote ms/frame (or raster lines: 64 µs, 312/313 per PAL frame) | % of an unknown total is not a measurement | Slicks perf; Revs §The target machine |
| Displayed FPS is quantised to 50/N; size changes in ms | vblank padding absorbed 75% of a +7.9 ms burn; a −12.5 ms win read +1.5% FPS | Revs Rule 1a |
| Report work and cadence separately; mean, p50/p95/p99, max, count over budget | final-frame phase table ≠ max-work frame | Slicks git `performance-distributions.md`, `performance-verification.md` |
| Time in emulated fields/beam, never host wall time | warp/host load changes nothing emulated; wall windows gave 75 vs 144 emulated s | Vette `AGENTS.md`; Revs §PROBEFIELDS |
| Bound the window in emulated fields; fingerprint frozen counters | same 30 s wall window, different crash counts | Revs §PROBEFIELDS |
| An absolute figure is a property of (build × window × workload) | RoF same binary 24.88 vs 23.57 FPS on two windows | RoF `docs/perf-budget.md` |
| Don't add gains measured in different scenes or transfer them across CPU presets | — | Vette `docs/performance.md` |
| Time saving = 1 − new/old; FPS gain = old/new − 1; say which | — | Vette `docs/performance.md` |

## 3. Instruments

- **Whole-update work timer** in the normal build (raster-line stamps around
  step/HUD/audio/C2P, excluding sync wait), deterministic fixed-clock
  benchmark, reject a stale exe, print a final-state hash. (Slicks
  `amiga/bench_tracks.sh`, `docs/performance.md` §Measuring.)
- **Sampling profiler for shares only**: CIA-B timer interrupt with jittered
  period recording PC/SR from the exception frame; ~12% uniform overhead.
  **Never sample via GDB interrupts** — FS-UAE services them only at vsync
  (doubled C2P's share, hid physics). (Slicks `docs/performance.md`.)
- **FS-UAE built-in instruction profiler** (Barto format) for whole-field
  self-time by address; needs code in the first hunk; no breakpoints in the window.
  Not inclusive timings; moving code changes attribution, so whole-frame timing
  is the performance measure. (Vette `docs/development.md` §Original-code gameplay profile.)
- **SWOTL**: `tools/profile_report.py CAPTURE ELF [--count LABEL]` decodes a
  `monitor profile N "" FILE` capture (gdb fixture, no breakpoints in the
  window) to class, module, guest routine/instruction (generated labels) and
  runtime shares; records without a PC are code outside the first hunk and
  ROM (today the Kalms c2p in hunk `code`).
- **SWOTL lowering cost**: `tools/lowering_cost.py CAPTURE ELF` groups the
  same capture by x86 form (executions, cycles and 68k instructions per
  execution) and the generated code by 68k mnemonic and role.
- **SWOTL counts**: `tools/host_census.py MILESTONE [--labels L…] [--strops]
  [--vram]` (host run between milestone snapshots: label executions, string-op
  elements, A0000h writers and rows per frame); `amiga/perf_frames.gdb` (frame
  period and a capture, [speed-plan.md](speed-plan.md) §4).
- **Phase brackets** (beam stamps) for shares; mandatory sanity lines printed
  each run: accounted ≈100%, body ticks/field ≈1. Use a monotonic epoch, not
  `beam − beam` (wrap drops the longest phases). (Revs `perf-method.md` L68–114, §Lessons — measurement.)
- **FPS/throughput counters sampled by the program**, read by gdb only at the end;
  conditional-breakpoint scripts biased FPS by 10× either way. (Revs Rule 1; RoF `AGENTS.md`.)
- **Calibrate every new bracket with a known burn**; fit a slope over N, not one
  row. **Empty-bracket control** at the same call rate gives the probe floor.
  (Revs §The four view probes; L339.)
- **In-process differential** for a replacement routine: new and reference
  run on identical state in one run, compared and timed per side; quote the ratio,
  run baselines ≥2×. Brackets include nested callees. (RoF `docs/perf-budget.md`
  §Measuring an asm twin; Revs Rule 2.)
- **Doubling / removal arms** price a sub-step without a bracket (run an
  idempotent pass twice; delete it for a ceiling only). (Revs `perf-method.md` L1724, L1827–1893.)
- **Static objdump cycle model** (addressing-mode-weighted, floor/ceiling)
  closed to ~1% on one walk but over-read ~6× at the 2–7-instruction grain.
  Use objdump to *find* a defect, never to *size* one. (Revs Rule 1b.)
- **Host build as a free census** (call/line counts matched the target exactly);
  never for timing. (Revs §THE SWEEP'S CENSUS.)
- **Single-step trace** gives instructions per call by label. (Revs §VIEW_PAINT_LINES SINGLE-STEPPED.)
- **Normal-code read-only probes for acceptance**; ledger/trace observers add
  6–7% and inflated cold start ~45%. Never compare instrumented with shipping
  totals. (Pokeri `docs/performance.md`; Vette `docs/development.md`.)
- **Diagnostic flags default off, never released**; clean/force rebuild when
  toggling; audit the release for diagnostic markers. (Slicks `docs/performance.md`;
  Pokeri `docs/testing.md`.)

## 4. A/B discipline

- **Control = exact parent build, same session, same window/workload.** Never
  diff against a ledger row or another session. (Slicks `docs/performance.md`;
  RoF `AGENTS.md`.)
- **Behaviour-preserving change must reproduce the final-state hash exactly**;
  fixed-clock mode makes final state depend only on inputs. Real-time-clock runs
  cannot gate fidelity. (Slicks `docs/frame-pacing.md` §Fixed-clock.)
- **Pin randomness** (fixed RNG seed) on every perf run; render speed otherwise
  changes the trajectory, even the level. Never judge gameplay from a pinned build.
  (RoF `docs/perf-budget.md`.)
- **Cross-build per-phase deltas carry trajectory noise (~±10%)**; use them for
  shares, the whole-frame A/B for progress. (RoF `docs/perf-budget.md`; Revs Rule 2.)
- **If a change needs an enabling restructure, measure three builds**: old code,
  new code with feature off, new code. Only the old code is the baseline.
  (Revs `docs/method-lessons.md`, ex: +34% vs real +10.7%.)
- **Built-in controls must not move** (phases the change cannot touch; fixed
  phase identical across runs). (Revs `perf-method.md` L1462, L2485.)
- **Noise floor**: RoF/Revs end-to-end <~3% is agreement, not evidence; a paired,
  field-bounded phase A/B resolved 0.015%. Know yours before claiming.
  (RoF `AGENTS.md`; Revs §PROBEFIELDS.)
- **Prove flags reached the build**: zsh does not word-split `$VAR`; command-line
  `VAR+=` replaces the Makefile's list; assert a symbol-count fingerprint per arm.
  (Revs §PROVE THE FLAGS REACHED THE BUILD.)
- **Layout matters**: unrelated globals/sections moving changes alignment and beam
  phase. (Pokeri `docs/performance.md` §Alignment; Slicks git `performance-distributions.md`.)

## 5. Fail-cheap experiment loop

1. Build + quick correctness smoke (routine oracle).
2. Time against the parent. Clear regression → reject now, record one line.
3. Promising → full fidelity gates (shadow/dual-execution, whole-frame
   comparisons, display audits).
4. Final timing confirmation; commit.

Never pay for full validation of a candidate already rejected on performance.
(Slicks `AGENTS.md`, `docs/development-verification.md`.)

A null counts only if the change **ran** (positive-control counter), was
**emitted** (objdump), and was **faithful**; it proves "this shape is dead",
not the hypothesis false. (Revs `perf-method.md` L1098–1121.)

Keep/reject: validated but slower → revert (Revs ex: packed state, 0 mismatch,
+0.2 ms). Record each disposition in one line with its reason; write "do not
retry" at the code. (Slicks `docs/performance.md` §Rejected; Pokeri experiment register.)

## 6. Measurements that lied

| Trap | Fix | Source |
| --- | --- | --- |
| Compiler deleted a busy-delay loop; every baseline lacked it | diff objdump of both arms | Revs §A BUSY-DELAY LOOP |
| Beam delta wrapped; longest phases lost most; zeros read as "trivial" | monotonic epoch; accounting line | Revs §Lessons — measurement, `method-lessons.md` |
| GDB-interrupt sampling vsync-locked | timer-interrupt sampler | Slicks perf |
| gc-sections dropped a counter; gdb read code bytes | link roots + probe audit | Revs Rule 1; Vette `AGENTS.md` |
| Stale object reproduced the previous number to the digit | clean on flag change | Revs `perf-method.md` L87, L341, L3136 |
| Frozen numerator over live denominator | snapshot at window edge | Revs §THE PARTIAL-FREEZE TRAP |
| Wrong denominator (per line vs per span vs per walk) | count calls first | Revs §PHASE 18 IS PER-WALK; `m68k-optimisation.md` |
| Fitted model collinear; gave negative cost | direct bracket | Revs §HISTORICAL FIT |
| Probe/census code inside the bracket (5–15%) | ratios from instrumented, absolutes from plain | Revs `perf-method.md` L565–573, L1994; RoF §Instrumentation (probe build ~35% slower) |
| Bracket held reset/crash time or a second call population | single-step; `calls > frames` tell | Revs `perf-method.md` L2996–3015, L2940 |
| Instruction count/size moved opposite to time | measure time | Revs `perf-method.md` L629, L1386, L1884, L2356 |
| Spill count read as cost | measure | Revs `perf-method.md` L1689, L2584 |
| Pixel/RAM compare across builds of different speed | in-process oracle | RoF `perf-budget.md`; Revs `validation-harness.md` |
| Parked/static scene flattered a census; mode excluded code | measure the representative workload | Revs `perf-method.md` L2111–2146, L1561 |
| Restore label included unrelated work; intrusive sub-probes don't add | separate brackets; don't sum independent probes | Slicks git `performance-distributions.md` |
| Residual attributed to an unmeasured component | measure both removed work and replacement cost | Revs `AGENTS.md`; Revs `perf-method.md` L884–903, L2148–2177 |
| Isolated routine win not visible whole-frame (ex: Pokeri compact dispatch −5.48 µs, no card gain) | whole-workload A/B decides | Pokeri `docs/performance.md` |
| PC sampler bucket "Kickstart ROM 8%" was the first instruction of the L3 autovector stub (FS-UAE gdb stub breaks after dispatch) | timer sampler, not gdb | RoF `flight-perf-log.md` §4.1 |
| Phase bracket credited ISR time at ISR exit, straddling bracket ends (+15% on combat) | calibrate with a fixed load; beam-locked windows | RoF `flight-perf-log.md` §8.3 |
| In-process differential's timing column sign-wrong below ~500 cycles/call | correctness only at that size; size from disassembly | RoF `asm-migration-plan.md` §Phase 8, §Phase 11 |
| Oracle reading ISR-written state raced (1 bad of 284) | snapshot before the change; run oracle on both sides, discard disagreeing calls | RoF `flight-perf-log.md` §12.4, §13.2 |
| Run stopped doing work while the vblank counter ran (crash/death cinematic in window) | short windows; discard rows not in the measured state | RoF `perf-budget.md` |
| Estimates over-read (1/3 to 6× high) | estimate is an upper bound | Revs `perf-method.md` L913, L1290, Rule 1b; Pokeri register ("estimated … not met") |
| Same executable, run medians 24.5 and 28.5 fields: frame times fall into trajectory modes; cycles per guest instruction follow the window's mix | per-step decisions on a deterministic fixed-workload meter; frame bench with a fixed tick schedule | SWOTL `speed-plan.md` §5 |
| Layout shift moved untouched forms by up to ±0.7%; keep/revert on that noise selected lucky layouts | layout-blind meter for lowering steps; layout changes judged by mix-adjusted per-label A/B | SWOTL `speed-plan.md` §5 |
| Priced in instructions; the 68020 model charged ≈ 1.1 cycles per code byte plus data accesses | price in executed bytes, data accesses and taken branches | SWOTL `speed-plan.md` §6 |

### Pricing rules

- **Three numbers**: what the change deletes, what one unit of the new shape
  costs, what it cannot touch. Two ports lost a built, proven optimisation to the
  missing third. (Vette git `56032f5^:docs/perf-method.md` §Lessons — implementation.)
- **Deferring is not removing**: price flush − record. (RoF `flight-perf-log.md` §17.)
- **Work inside a blitter/DMA shadow** only pays for the part that exceeded the
  shadow. (RoF `flight-perf-log.md` §12.5.)
- **Controlled vs supporting evidence**: only the in-process ratio is controlled;
  per-call cost over advancing-state windows is supporting, never a cross-run speed
  claim. (Vette git `56032f5^:docs/perf-method.md` §Vette measurements.)
- **Divide by the right denominator**; count how often the loop runs before pricing
  it per iteration. (Revs `m68k-optimisation.md` §SIBLING CASE.)
- **Compare with the original only on a matched workload**, including the
  original platform's system/display services; a port-only stage (C2P) is not a
  slowdown "versus the original". (Vette `docs/development.md` §Original-code gameplay profile.)

## 7. Budgets

- **Frame budget**: 20 ms (one PAL frame, 312 lines of work) at 50 Hz. Decide
  with the user whether mean, p95 or max must meet it. (Slicks `docs/performance.md`.)
- **ISR budget is separate**: a fixed wall-clock tax; copper/pointer work first,
  bounded work after; it hides inside the phase it interrupted.
  (Revs Rule 5, `AGENTS.md`; RoF `docs/perf-budget.md`.)
- **Memory budget** measured, not reserved: report Chip vs other and check before
  adding tables. (RoF `docs/perf-budget.md`; Pokeri `docs/architecture.md`.)
- **Game speed vs frame rate**: decouple when the original's speed depends on
  its frame rate (variable ticks per update, capped batch) and publish late
  updates immediately rather than snap to 40 ms; then worst-case frame time stops
  being a ship blocker. (Slicks `docs/frame-pacing.md`, ex: 33–48 → 46–50 updates/s.)

## 8. When to stop

- Bar met → stop; do not reopen for margin. (RoF `AGENTS.md`.)
- Flat profile (ex: Slicks no routine >7%) and experiments moving totals
  0.03–1% → stop micro work; change the structure or declare scope.
  (Slicks `docs/frame-pacing.md` §Alternatives not taken.)
- Stop sizing at the 2–7-instruction grain: measure one arm or move to a coarser
  lever. (Revs Rule 1b.)
- "At its floor" covers only the named operations; re-check the surrounding
  call/counter shape before closing. (Revs `perf-method.md` L2867–2879.)
