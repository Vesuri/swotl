# Speed plan (phase 7)

Rules, measurement and work order for all speed work on the A1200 build.
An implementing agent follows it literally, one step at a time. Step
details (prices, coverage, plants, FS-UAE checks) are in the step's commit
message (`git log --grep '^R[0-9]'`); round 1 (T1–T15) at `781975e`.
Method background: [perf-method.md](perf-method.md). Open-work item: 14b.

## 1. Target and state

- **Bar (user, 2026-10-07):** a 14 MHz 80286's frame rate on the 68020 +
  8 MB Fast model (`AMIGA_CPU` unset): frames 4–11 median ≤ 12 fields
  (240 ms); stretch ≤ 10.
- **Status:** R16 alignment repair, R17 palette validity, R18 flag extraction kept; R20 cell
  cache, R21 string layout and R22 call layout kept. Item 14b's 240 ms target remains unmet; no native replacement is
  authorized. Next steps priced 2026-10-17: open-work 31.
- **Frames fixture** (R22, 2026-10-18): medians 390, 370 and
  380 ms; same-session parent 380, 390 and 380 ms. Full intervals and spans in §7.
- **Bench:** R22 opening 72,205 → 72,089 lines (−0.161%), identical guest RAM.
  R20 opening 71,523 → 72,197 lines (+0.9424%), identical guest
  RAM; approved tradeoff. Palette window 38,392–38,405 lines (R17),
  2.81–3.61% below its same-session parent.
- **Meter** (m4, R18 weights, R22): generated + walk + runtime 183,699,737
  model cycles (−0.0246% from parent); generated + walk 181,369,677 / 17,976,252 guest
  instructions = 10.089 cycles each. Host platform adds 2,171 cycles.
- **Capture** (R22, first frames run, 100 fields): generated code 80.18%
  (cell walk 2.72%), runtime/platform 14.66% (three main FM functions 7.89%, item 34),
  no PC 3.20%, Kickstart 1.04%, IRQ transition 0.93%. Profiler guest-entry count:
  2,290,967; 9.95 cycles and 2.329 68k instructions each (see open-work 36).

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
5. **Gates stay green and unchanged** at every commit: `make test`,
   `make test-sabotage`, `make test-host-all`, `make test-amiga`, `make
   smoke` (`make gates` runs all five). Never edit, skip, mask, loosen or re-record a test, reference or
   tolerance to make a step pass. R1's representation change (D1) may
   change how the harness maps memory and registers, never what is
   compared; every corpus case, reference and comparison stays. A plant is
   retired only with the template it targets, after an equivalent plant on
   the new template is in place and caught.
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
   are guest semantics); a double buffer or copper display (open-work 14a);
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
  lower fixed-work 68020 bench cycles, with identical final guest RAM, all
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
write the price in §7 before coding;
coverage first (§2.6; cases appended at the end of corpora, `m68k_blocks`
cases for multi-block changes); implement in `translator/` or
`src/runtime/` or `src/platform/amiga/`, `make gen`; gates; meter (D5: bench); keep or revert (revert keeps the
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
  1.1 GB: delete it after the report. Until open-work 36 is fixed, use
  `profile_report.py` guest-entry counts for ratios: `lowering_cost.py`
  includes helper entries. Historical ratios from that tool share this limitation.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop. Per drawn
  frame (m4): `repe cmpsw` `VGA_03BE9` 19,290 words (the whole view vs the
  previous frame), `rep stosw` `R_0C1CA` 16,075 words, `rep movsw`
  `VGA_03C2D` 151 words to A0000h (median 6 rows).
- **Reference cadence** (DOSBox-X `cycles=fixed 12000`, m4): a drawn frame
  every 9 PIT ticks ≈ 36 ms, ≈ 408K x86 instructions per frame.
- **Meter** (`tools/cost_meter.py`, ≈ 40 s, deterministic): `--out
  tmp/meter/ARM.json` per arm, `--compare A B` for the §3 deltas. Weights
  `tools/cost_model.json`, fit at R18 on the parent bench capture:
  per code byte 0.989 (0.914 inside a loop of ≤ 256 bytes), read 2.029,
  write 3.174, taken transfer 5.813 outside such a loop and 2.476 inside,
  mul/div 23.012 (R² 0.930, model −2.65% of measured). The doubling
  plant is caught (367,456 extra instructions, 734,912 extra bytes). It
  underrates removed instructions (bench vs meter: R1b −8.4% vs −1.9%,
  R1d −2.1% vs −1.2%; the per-instruction weight fits to 0). Recalibrate
  (`--calibrate CAPTURE ELF --write`, then `--plant-check`) at the next
  re-profile or when the FS-UAE check disagrees. `tools/ab_labels.py` serves the FS-UAE check.
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
  sum within 2 of 94,498 lines (single frames within 16), window guest
  instructions within 0.02%, start fields 1523 and 1508. Not comparable to P
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

## 6. Cost model and where the cycles are

Per-PC fit on the replan capture (13,608 non-branch PCs, 5.5M executions):
**cycles ≈ 1.09 × code bytes + 2.27 × data reads + 3.07 × data writes**
(R² 0.83). Outside the 256-byte i-cache a 2-byte register op costs ≈ 2
cycles, 4 bytes ≈ 4, `and.l #$ffff` (6 bytes) ≈ 6. Inside cached loops
bytes are nearly free. Price and accept in executed bytes, data accesses
and taken branches, never in instruction counts. FS-UAE is the user's
instrument; a real 68020 may weigh these differently.

Share of the meter's model cycles at `84d262d` (m4, R11 weights) by the 68k
instruction's role (`tmp/` census over the meter's per-PC counts;
`profile_report.py`'s role column still matches the old poll and state
block forms):

| Cost | R14 meter | Executions (m4, R11) |
|---|---:|---:|
| Cell walk (D16), run-time matching | 21.84% | — |
| Other code inside cached loops (loop bodies) | 24.98% | — |
| Other memory ops / register ops / branches outside cached loops | 12.02% / 7.38% / 3.67% | — |
| mul/div | 4.99% | 399K `mulu.w`, 45K `divu.w` |
| Index formation in d7 (`move.w #7FFFh−d,d7` + `sub.w Rn,d7`; mirrored + disp) | 4.10% | 1.96M `move.w #N,d7` |
| Poll points (`tst.b G_IRQ(a6)`, `bne`) | 3.73% | 980K |
| `repe cmpsw` / `rep stosw`; their loop bodies | 3.74% / 2.51%; 3.28% / 2.30% | 7,840 / 6,225 runs |
| Stack accesses `(d,a2,d4.w)` + SP steps `addq/subq.w #2,d4` | 3.09% + 0.92% | 2.0M steps |
| Flag image (CCR to and from G_FL, state block flags) | 2.42% | 583K spills |
| `jsr`/`bsr`/`rts`/`jmp` | 1.37% | — |
| Runtime (capture: 6.13%) | 1.08% | — |
| Segment fields (DS/SS/ES in the state block) | 0.90% | — |
| Return checks (`cmp.w #ip,d7`, `bne` to the trampoline) | 0.76% | — |
| SP/BP mirror conversions `eori.w #$7fff` | 0.54% | — |
| Byte swaps `ror/rol.w #8` (+ store copies) | 0.49% | 609K |

The meter's runtime is the host run's (the reference's interrupts
replayed); the frames capture adds the CIA timer at its own rate.

Guest register use (executions per 100 fields): SP 243K (92% implicit
push/pop/call/ret), BP 236K (65% base+disp), BX 242K (33% ALU destination,
32% base), SI 216K and DI 131K (34–41% base, 30–36% ALU).

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
| R20 | cell cache: cells matched once, runs of destinations stored by longs, exact invalidation (D3) | `smc.py`, `lower.py`, runtime | −15.3114% |
| R21 | backward string bodies outlined; forward path falls through | `lower.py` | −0.1080% |
| R22 | first matched walk call returns into its check; fallback outlined | `lower.py` | −0.0246% |

Priced candidates (2026-10-17, `5ecdf79` meter): open-work 31 (each ≤ 2.8%). No form
left (§2): poll points
(`(a6)` is guest byte 0; no thinning), `mulu`/`divu` themselves. The translator helpers
`__set_flags` (POPF/IRET) and `__flags_word` are the largest runtime-side
items left.

### R22 near-call fallback layout (2026-10-18; kept)

Parent `a9c2e69`. Fresh m4 meter: 183,744,876 cycles. First matched
cell-walk call falls through to the existing return check; remaining
range tests/targets and runtime fallback go out of line. Keep both bounds,
zero-extension, stack effects and return validation unchanged.
Price: −30,299 cycles (−0.0165%), conservatively allowing two extra bytes
on each range branch and a four-byte return branch on every fallback.
Three exercised sites, 32,799 walk calls, zero observed fallbacks; absence
is not a correctness assumption. Test both bounds and all fallback paths.
Evidence: `tmp/item31-r22/{meter.json,meter_raw.pkl,census.log,price.log}`.

Candidate: 183,699,737 model cycles (−45,139, −0.0246%); instructions
−32,799, executed bytes +113,194, data reads/writes unchanged. Amiga code
+52 bytes to 1,258,240; allocated hunks 1,576,576. Target comparison:
3,974,716 → 3,774,795 weighted cycles (−5.0298%) across four changed labels;
all required PCs mapped and sampled. Bench 72,205 → 72,089 lines, identical
RAM SHA-256 `bb1607f7815ef1c79c754b1eabbb4a134cf625a76eeb2f7efe046061ff8aafd3`.
Coverage before implementation: 144 operand cases and 24,052 block cases
pass; deliberately rejecting the lower endpoint gives 13 failures.
Candidate targeted cases pass; its endpoint plant again catches 13 failures.
Full test passed in 499 s: 13,663 executed blocks, 52,587 cases, zero
mismatches. All gates passed: test 499 s, sabotage 3,186 s, host-all 3,316 s,
Amiga 70 s, smoke 191 s, restoration 352 s, five replays 2,503 s.
Source hashes and measured ELF match after validation. Evidence: `tmp/item31-r22/`.
First captures: 10.36 → 9.95 cycles/guest, 2.424 → 2.329
68k instructions/guest, using the profiler guest-entry counts (open-work 36);
guest mixes differ. No frame-rate gain is claimed.

| Arm/run | Frames 4–11 intervals (fields) | Median | Span |
|---|---|---:|---:|
| Parent 1 | 23,22,17,21,18,20,16,17 | 380 ms | 16–23 |
| Parent 2 | 22,22,19,20,18,25,19,19 | 390 ms | 18–25 |
| Parent 3 | 22,22,18,21,17,20,17,16 | 380 ms | 16–22 |
| R22 1 | 23,21,19,20,18,26,19,19 | 390 ms | 18–26 |
| R22 2 | 22,22,17,22,17,20,16,17 | 370 ms | 16–22 |
| R22 3 | 22,21,18,21,17,20,16,17 | 380 ms | 16–22 |

### R21 string direction layout (2026-10-18; kept)

Parent `5619afe`. Fresh m4 price before coding: −233,585 cycles (−0.127%)
for outlining the backward string bodies; free-placement layout ceiling
−5,983,232 cycles. Direction tests, both bodies, wraps, flags and diagnostic
REP checkpoints are retained; the forward path falls through.

Meter: 183,943,624 → 183,744,876 cycles (−198,749, −0.1080%);
executed instructions −50,360, bytes +45,300, data reads/writes unchanged.
Amiga code 1,257,444 → 1,258,188 bytes (+744); allocated hunks
1,575,780 → 1,576,524. Opening bench: parent 72,238 / 72,178 lines,
candidate 72,204; identical RAM, candidate within unchanged-parent spread.
The bench capture executes no changed labels; normal captures cover them.

Entry-weighted target A/B initially disagreed (+0.947%); the approved
investigation found varying REP lengths (40.44 → 45.75 pairs per call).
Exact host-instruction weighting fixes that confound: changed-label target
cycles −4.563%, repeated −4.579%, all required PCs mapped and sampled.
`ab_labels.py --meter-b` fails on missing samples or mismatched code;
controls and sabotage retain actual slowdowns and removed work.
No model weights, fixtures or references changed.

| Arm/run | Frames 4–11 intervals (fields) | Median | Span |
|---|---|---:|---:|
| Parent 1 | 22,23,19,19,18,26,19,19 | 380 ms | 18–26 |
| Parent 2 | 23,22,20,19,18,25,19,20 | 400 ms | 18–25 |
| Parent 3 | 24,21,20,19,18,25,19,19 | 390 ms | 18–25 |
| R21 1 | 22,22,17,22,17,20,16,17 | 370 ms | 16–22 |
| R21 2 | 23,22,17,21,17,20,17,16 | 370 ms | 16–23 |
| R21 3 | 22,22,17,22,17,20,16,17 | 370 ms | 16–22 |

Intervals overlap: no frame-rate gain claimed. First paired captures:
9.88 → 10.20 cycles/guest and 2.307 → 2.385 68k instructions/guest;
these reflect different guest mixes, not fixed-work cost.
Coverage first: 310 string cases; DF plant caught before implementation.
The new full-corpus plant catches 2,314 cases. The approved diagnostic
wrapper correction places cold code after its terminating jump: all 168
oracle cases / 120 resumptions pass, unchanged SI-corruption plant caught.
All gates passed: test 424 s, sabotage 3,351 s, host-all 3,299 s,
Amiga 61 s, smoke 193 s, restoration 345 s, five replays 2,565 s.
Source inputs and measured ELF match after validation.
Evidence: `tmp/item31/` (frozen arms, reports, `gate-logs-2`).

### R16 audit and alignment repair (2026-10-14; kept under D5)

Parent `858d8ab`. Fresh m4 census: 1,261,759 uncached taken transfers;
496 candidate chunks, preferred-vs-other residue difference 833,704
transfers (416,852 expected switches from a random layout). Padding runs
zero instructions; branch relaxation can change encoded sizes. This price
was recorded before implementation; no frame-rate saving was assumed.

The old 0/2-byte solver oscillates across a short-branch boundary. Monotone
two-byte growth converges and verifies its final object; nonconvergence
fails generation. Fresh candidates satisfy 496/496 residues in host and
Amiga ELFs (parent 234/510). Regression fails on the old solver; the
oscillation and stale profiler poll-offset plants are caught.

Profiler repair is tooling only: current state offsets, disassembler
syntax, out-of-line IRQ stubs and return-check trampolines. No guest
instruction, guard, return check, poll point or interrupt order changes.

| Arm/run | Frames 4–11 intervals (fields) | Median | Min–max |
|---|---|---:|---:|
| Parent 1 | 28,24,20,23,20,24,21,24 | 23.5 / 470 ms | 20–28 |
| Parent 2 | 28,24,20,23,20,24,20,24 | 23.5 / 470 ms | 20–28 |
| Parent 3 | 28,23,20,24,19,25,20,24 | 23.5 / 470 ms | 19–28 |
| Candidate 1 | 27,24,20,23,19,25,20,24 | 23.5 / 470 ms | 19–27 |
| Candidate 2 | 28,23,20,23,20,24,20,24 | 23 / 460 ms | 20–28 |
| Candidate 3 | 27,24,20,23,20,24,20,24 | 23.5 / 470 ms | 20–27 |

Arms overlap: no frame-rate gain claimed. Fixed-work bench: 69,631 →
68,806 lines (−1.18%; 63,224,948 → 62,475,848 profiler cycles at 908/line);
final guest RAM SHA-256 identical. Mix-adjusted all-label cost −1.047%
(19.9% of weight covered). The older "changed labels" subset included
unchanged guarded copies; R18 corrects that selection. R16 acceptance rests
on the fixed-work bench, not that subset.

Meter: identical executed instructions/bytes, reads/writes and modeled
cycles. Static decoded generated bytes +10, runtime +2; actual HUNK code
payload unchanged at 1,198,668 bytes, executable unchanged at 4,298,924
bytes (3,043,796 are symbols). First frames capture: 11.38 → 11.33 cycles
and 2.849 → 2.849 68k instructions per guest instruction; the instruction
mix differs, so these ratios do not establish a gain.

Accepted under D5: the layout-blind meter is unchanged and the bench
improves without payload growth. `make gates` passed,
including sabotage and all three diagnostic replays.
Evidence: `tmp/item14b-agent/` (local logs, frozen binaries and reports).

### R17 palette validity (2026-10-14; kept under D5/D6)

Parent `dbb6e43`, executable hash unchanged from accepted R16. Fresh normal
capture: five `buildPalette` / `finishDisplayUpdate` calls, zero
`plat_palette` calls; palette construction 0.70%, copper setup 0.75%,
`Palette24Bit::update` 0.39% (1.84% removable ceiling in this window).
Fresh m4 census: 49 frames, 43 presentations, zero palette calls.
Proposed replacement: one validity check per publication and two buffer
invalidations per palette update; palette changes still perform the full
conversion for each physical buffer before its next publication. Guest
rendering, c2p, queue publication and VBI order are untouched.

Fresh parent frame intervals 4–11: [27,23,19,22,18,22,18,22],
[27,22,19,22,18,22,19,22], [27,22,19,22,17,23,18,22]; all medians
22 fields / 440 ms, spans 18–27, 18–27, 17–27. The executable is identical
to R16: these are trajectory variation, not an optimization gain.
Bench: 68,826 lines; final RAM hash matches R16. Its profile records zero
palette rebuilds and zero display publications: it cannot establish a
palette saving. D6 approves a separate frames-60–67 BENCH window,
with matching final guest RAM, exercised palette calls and no slowdown;
the existing bench and frames fixture remain mandatory and unchanged.
The new later bench profile exercises palette construction (0.70%), copper
setup (0.75%) and palette update (0.39%): 1.84% removable ceiling before
validity-check overhead. Coverage first: production methods pass 6,000
queue/palette histories against independently expanded DAC colours; a
plant retaining stale colours fails.
Candidate: both buffers invalidated on each DAC update; only a rebuilt
buffer is marked valid. Additional omission plants for either invalidation
are caught. Code payload 1,198,668 → 1,198,752 bytes (+84); executable
4,298,924 → 4,299,020 (+96). Host meter does not represent this platform work.

| Bench | Parent lines | Candidate lines | Parent cycles | Candidate cycles |
|---|---:|---:|---:|---:|
| Opening, intervals 4–11 | 68,826 | 68,774 | 62,494,008 | 62,446,792 |
| Palette, intervals 60–67 | 39,829 | 38,392 | 36,164,732 | 34,859,936 |

Cycle-unit correction: the fresh 100-field profile accounts for 28,420,397
cycles over 31,300 PAL lines (908/line, within three boundary cycles).
The inherited 454/line conversion was wrong; R16's absolute totals above
are corrected, with its percentage and line measurements unchanged.

Repeated later bench: 39,514 → 38,405 lines (2.81% saving), zero I/O fields
inside either measured window, nine → seven display handoffs under the
unchanged publication rules. Across both runs, parent 39,514–39,829 and
candidate 38,392–38,405 do not overlap. All four final guest RAM hashes match.

Both final guest RAM hashes match their parent. Palette-window saving
3.61%; opening window −0.076%. Later profile: five palette rebuilds → zero,
with five display publications in both arms and zero palette changes.

| Candidate run | Frames 4–11 intervals (fields) | Median | Min–max |
|---|---|---:|---:|
| 1 | 27,19,27,20,19,20,23,20 | 20 / 400 ms | 19–27 |
| 2 | 26,18,26,18,18,18,21,19 | 18.5 / 370 ms | 18–26 |
| 3 | 24,23,19,24,19,23,20,20 | 21.5 / 430 ms | 19–24 |

Frame interval ranges overlap the parent; the fixed-work bench establishes
the saving, not the differing normal-flight trajectory. First capture:
11.80 → 11.26 cycles/guest, 2.988 → 2.823 68k instructions/guest; these
ratios reflect different guest mixes, not a lowering change.
All `make gates` checks passed, including all three DOSBox diagnostic
replays. Display audits passed 40 captures each on 68020 and 68040. The
first 68040 audit was invalidated by a debugger-port collision; its unchanged
rerun used a dedicated strict port. No reference, tolerance or IRQ order changed.
Evidence: `tmp/item14b-agent/palette-{parent,candidate}/`,
`palette-census.txt`, `palette-measurements.json`.

### R18 flag extraction (2026-10-14; kept)

Parent `75a4a5e`. Fresh m4 census: `__set_flags` 2,300 calls,
`__flags_word` 1,893; meter 222,109,822 cycles. Replacing each TF/IF/DF
`btst; sne; neg.b` with register `bfextu` removes four encoded bytes and
two instructions per flag: 27,600 executed bytes, 13,800 instructions,
about 27,008 model cycles (0.0122%) and 12 static bytes. Reads, writes,
IF re-arm condition, guest polls and delivery order must remain identical.
Pre-implementation coverage requirement: POPF flag combinations and
subsequent carry consumers. Generic helper costs also require explicit
coverage in the label A/B report, which previously selected guest labels only.
The original meter misread BFEXTU/BFEXTS/BFFFO's offset as a memory
operand. New tests fail on that bug; the corrected parser and explicit
runtime-helper A/B attribution have sabotage plants. The A/B report also
incorrectly included every guarded copy in its changed-label subset; that
selection is fixed and its plant caught. Comparing actual instruction
bodies now identifies exactly one changed label: `__set_flags`. Both host arms were
rebuilt with identical corrected weights, fitted on the frozen parent.
Fit: R² 0.9302; generated measured 27,804,962, modeled 27,068,987 (−2.65%).
The doubling plant detects 367,456 extra instructions and 734,912 bytes
(+711,919 modeled cycles, within its 671,736–727,003 bounds).

Measured m4: 217,138,886 → 217,111,583 cycles excluding host platform
(−27,303, −0.0126%); executed bytes −27,600, instructions −13,800,
reads/writes/taken transfers unchanged. Code payload and executable −12
bytes (1,198,740 / 4,299,008 bytes). Target helper: 349 calls per arm,
152.092 → 139.421 cycles/call (−8.331%, −29,142 census-weighted cycles).
Opening bench 68,778 → 68,787 lines, identical final guest RAM; nine lines
are below observed bench phase variation, so no whole-frame gain is claimed.

Coverage first: 144 added POPF cases, independent TF/IF/DF/CF and following
carry consumers; the old-helper wrong-bit plant fails 72. Candidate passes
all 144, and its focused wrong-bit plant also fails 72. The full sabotage
corpus catches 759 mismatches from that plant. Block differential adds 32
POPF/IRET entries, covering both IF-dependent predecessors. No flags, polls,
IRQ re-arm condition or interrupt order changed.
All gates passed: test 346 s, Amiga 395 s, host-all 511 s, smoke 129 s,
restoration 213 s, sabotage 1,093 s, diagnostic replays 713 s. Final
measurement-tool checks pass all ten tests and three plants. The rebuilt
loadable payload matches the measured candidate.
Evidence: `tmp/item14b-agent/flags-*` (frozen arms, count/cost reports).


### R20 cell cache (measured 2026-10-17; kept 2026-10-18)

Parent `96e5ac2` (the `5ecdf79` code). Price before coding (open-work 32, D3):
−37.4M model cycles (−17.2%), the walk −79%. Census (host run, whole c8/m5 runs):
segment loads reaching the region only at start-up and in the setup (two
invalidations per run), at most one RET planted at a time, 63 operand-patch walks in
c8.

Built (translator-design D16): cells matched once, when a walk first reaches them;
a mov cell's record holds its operand and its run's end; runs of 8 or more
destinations stored by aligned longs, shorter ones and 16-bit wraps byte by byte.
CS stores that may reach the region (40 sites, all in its segment) call its hook
after storing; byte movs plant or restore the RET inline. DS/ES/SS loads reaching it
(segment limit 1106h), the runtime's register reload and runtime stores drop the
cache; a dropped cache is cleared at the next walk with no segment reaching the
region and walks exactly until then. The R7 walk remains as the exact walk.

Coverage: exact and cached random walks, RET plants/restores, operand patches,
segment exposure, entries inside cells, run bounds and 16-bit wrap. Runtime
stores and segment reloads have separate coverage. Immediate post-restore x86
comparisons catch both inherited RET-restore plants. A new boundary case exposed
an invalid-cache revival: a zero byte stored immediately before the region had
index zero, equal to the invalid tag. The inline restore now rejects that index;
four outside-region controls pass, and removing its guard fails the x86 comparison.
All fourteen cache/lowering plants and two runtime plants are caught. The final
block differential covers all 13,663 executed blocks, 51,653 cases including
6,004 walks, with zero mismatches.

Meter m4 (generated + walk + runtime): 217,200,040 → 183,943,624 cycles
(−33.26M, −15.3114%); walk 47.32M → 9.90M. Generated code +4.10M,
runtime +0.055M. Executed code bytes −26,514,112; data reads −1,842,821,
writes −1,322,456; 68k instructions −11,931,146. Static decoded bytes:
generated +28,914, runtime +6,236, walk +810. Code hunk 1,221,568 →
1,257,444 bytes; allocated payload 1,489,316 → 1,575,780 (cache data 50,586).

FS-UAE: 68020, 8 MB Fast, same session, unchanged frames fixture:

| Arm/run | Frames 4–11 intervals (fields) | Median | Span |
|---|---|---:|---:|
| Parent 1 | 28,22,25,21,25,21,25,21 | 470 ms | 21–28 |
| Parent 2 | 24,25,20,23,19,23,19,19 | 430 ms | 19–25 |
| Parent 3 | 29,21,29,20,20,19,24,20 | 410 ms | 19–29 |
| R20 1 | 22,22,17,22,17,20,16,17 | 370 ms | 16–22 |
| R20 2 | 22,22,17,21,19,20,16,16 | 390 ms | 16–22 |
| R20 3 | 22,22,18,21,17,20,17,16 | 380 ms | 16–22 |

Individual interval ranges overlap, so no frame-rate gain is claimed (§4).
First captures: 11.37 → 10.26 cycles/guest, 2.851 → 2.394 68k instructions/guest;
the guest mixes differ. Mix-adjusted all labels −23.065%; changed nonwalk
labels +62.492%, consistent with the meter's nonwalk overhead. The changed walk
spans different labels, so its label-pair ratio is not a per-cell comparison.
Opening bench: 71,523 → 72,197 lines, 64,942,884 → 65,554,876 cycle
units (+0.9424%); final guest RAM SHA-256 identical. Separate unchanged-fixture
captures measure walk cost 22.29 → 4.72 cycles per executed MOV cell (−78.84%),
agreeing with the meter. Byte stores count one cell, long stores four; register
replication instructions do not count as cells.
The user accepted the measured ~1.1% opening-bench regression for ~15.36%
model-cycle savings, conditional on correctness gates. The corrected build is kept under that approval. All gates passed: test 525 s,
Amiga 65 s, smoke 207 s, restoration 355 s, diagnostic replay 2,572 s (five
scenarios), host-all 3,329 s, sabotage 3,338 s. Frozen source hashes and the
measured executable match after validation; no reference or comparison changed.
Evidence: `tmp/item32/` (pricing), `tmp/item32-review/` (review, regression,
frozen arms, meters, captures' reports and gates).

## 8. User decisions (D0–D4 approved 2026-10-08)

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
- Native replacement is not part of this plan (§2.2).

## 9. Gap

R22's run medians are 390, 370 and 380 ms. Reaching 240 ms requires about
37% less frame time from their 380 ms median; parent and candidate intervals overlap.
Normal trajectories vary; acceptance uses the fixed-work meter and §3 checks.
Top guest routines (first R22 capture, self time): SWOTL.EXE+0B54B 8.30%,
+0BFD1 7.67%, +109D6 4.46%, +0D5A6 3.98%, +0B017 3.92%,
RTSVGA.OVL+03B9A 3.81%, SWOTL.EXE+06A4D 2.72% (walk), +0B4E2 2.44%.
Generated guest code is 80.18%; three main FM functions are 7.89%.
Flag-word packing is rejected (§10); native replacement needs per-routine
authorization (§2.2).

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
