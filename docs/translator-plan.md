# Translator speed plan (phase 7b)

Work order for making the generated code itself faster. For an
implementing agent: follow it literally, one step at a time. Rules and
measurement from [speed-plan.md](speed-plan.md) §0 and §1 apply unchanged;
this file adds to them and never relaxes them. Open-work item: 14b.

## 1. Target

- **Bar (user, 2026-10-07):** the frame rate a 14 MHz 80286 PC reached,
  on a 68020 + Fast RAM A1200 (`AMIGA_CPU` unset, 8 MB Fast, `amiga/debug.sh`).
- **80286 estimate:** the measured flight instruction mix (≈ 444K guest
  instructions, 19K `cmpsw` and 17K `stosw` elements, ≈ 35K walk cells per
  drawn frame) at Intel 80286 real-mode timings: 2.7M clocks = 194 ms at 0
  wait states, 242 ms at 1 wait state (+25%), 271 ms with prefetch stalls.
  **Target: frames 4–11 median ≤ 12 fields (0.24 s); stretch ≤ 10 (0.20 s).**
- **Earlier baseline (commit 6646626):** median 26–27 fields (0.52 s). Guest code 88%:
  13.5 68020 cycles and 3.6 68k instructions per guest instruction (the
  80286: ≈ 5.4 clocks); cell walk 14%; runtime 8%.
- **After T11:** median 24.5 fields (490 ms), run medians 24.5–25;
  cycles/guest median 14.97 and 68k/guest 4.156193 (parent 15.45 / 4.304954).
  Code payload 1,325,164 bytes; stripped executable 1,367,420 bytes.
  Kept for lower measured cycles/instructions and smaller code; frame times
  overlap, with the same 24.5-field arm median. No frame-rate gain claimed.
- **Honest projection:** the steps below are priced at 18–25% of P in
  total, ≈ 0.38–0.42 s. The target needs ≈ 5.5 cycles per guest
  instruction. Translator work is to be completed first anyway (user
  decision); §6 says what happens when it is.

## 2. Authority (hard; breaking one voids the step)

Everything in speed-plan §0 holds. In addition:

1. **No native replacement of any guest routine** (HLE, G3 table entries,
   hand-written 68k or C doing a guest routine's work, "intrinsics" that
   pattern-match a guest routine), however small, until the user authorizes
   that specific routine in the conversation. An authorization is never
   inferred from this file, from open-work, from a profile, from an earlier
   authorization of another routine, or from "the translator work is done".
2. **No shortcut that weakens exactness**, in any form: no dropped guard,
   no "the census never saw it" assumption, no removed return check, poll
   point, fail-loud stop, wrap handling or flag definition that a live use
   needs; no annotation that asserts a property instead of the translator
   proving it (annotations name facts the tests check: entries, tables,
   forms, flag pairs).
3. **No change to what is measured or how:** CPU model, Fast RAM size or
   type, FS-UAE options, the fixture, the game's data, configuration or
   detail settings, warp or speed settings. If the measurement model looks
   unrepresentative, report it; do not change it.
4. **No change to the cell walk's matching (D16)**: a cell cache or
   decoded-cell reuse is a design change the user has not approved.
5. **No test edits that make a step pass**: no skipped corpus, no reduced
   sample size, no masked comparison, no re-recorded reference, no edited
   sabotage plant. New tests and plants only add coverage.
6. **No unmeasured claims.** Every number in a commit or doc comes from a
   run in the same session; "should be faster" is not a result.

**Stop and ask the user** (do not proceed, do not pick an alternative) when:
a gate fails and the fix is not a translator/runtime bug fix; a step needs
any of 1–5; a step needs references re-recorded; a step moves an interrupt
delivery (host run replay mismatch); two consecutive steps are rejected;
code size grows by more than 25% (open-work 19, Chip-only budget); the
plan's next step is ambiguous.

## 3. Step protocol (every step, in this order)

1. **Price** with data from this session: `tools/lowering_cost.py` on a
   fresh capture (speed-plan §1 Shares) and `tools/host_census.py` counts.
   Write the step's priced prize (% of P) into §4 before writing code. A
   step priced under 1% of P may be built when it is expected to reduce
   cycles, executed instruction count and code size (user amendment,
   2026-10-07). There is no minimum percentage for those candidates.
   Pricing still ranks work; acceptance still requires measured results (§3.6).
2. **Coverage first** (speed-plan §0.5): the new lowering's forms and its
   guard edges in the x86 corpora (`tests/x86_diff.py`, appended at the end
   of a corpus so earlier cases keep their random states), the change seen
   to fail against a deliberately broken version, and a sabotage plant in
   `tests/m68k_sabotage.py` (or `tests/host_run.py --sabotage`) that
   `make test-sabotage` must catch. Multi-block changes also need
   `tests/m68k_blocks.py` cases that enter the changed blocks from every
   kind of predecessor.
3. **Implement** in `translator/` (or `src/runtime/` for runtime glue), then
   `make gen`. Never edit `build/gen/`.
4. **Gates, all green:** `make test`, `make test-sabotage`,
   `make test-host-all`, `make test-amiga`, `make smoke`.
5. **Measure:** control = the parent commit, built and run in the same
   session; three `amiga/perf_frames.gdb` runs per arm; report frames 4–11
   intervals, median and span, and the `lowering_cost.py` totals (cycles and
   68k instructions per guest instruction, the step's forms).
6. **Keep or revert:** keep a frame-time win if the arms do not overlap
   (span or median) and the gain is at least half the priced prize.
   **User amendment (2026-10-07):** also keep measured reductions in cycles
   per guest instruction, 68k instructions per guest instruction and code
   size when frame times overlap. **No slowdown** (user clarification):
   smaller code does not excuse increased cycles/instructions or a measured
   frame-time regression. Overlapping frame times alone establish neither a
   regression nor an improvement. Report accepted changes as efficiency/size gains;
   do not claim a frame-rate gain. Otherwise revert the code, retain passing
   new tests, and add one line to §5.
7. **Commit** one step per commit: before/after numbers in the message;
   §4 and open-work 14b updated in the same commit (speed-plan §0.8).
8. **Report** to the user after each step in a few lines: step, numbers,
   kept or reverted. Then the next step.

The user authorized revisiting candidates excluded by the former 1% cutoff.
Resume with fresh pricing of T3, then revisit T4 cross-block, T5 and T6 before
T7–T9. Earlier below-threshold entries are historical screening decisions,
not rejections under the amended rule. This authorization resumes work after
the T5/T6 stop; all correctness, size-growth and measurement rules remain.

## 4. Steps

Shares are of the whole CPU in steady flight (commit 6646626, 100 fields);
"cyc" is 68020 cycles per execution. Re-price each step before building:
earlier steps change later prices.

### T1. Tooling and baseline (no generated-code change)

- `tools/profile_report.py`: guest routine attribution (every routine is
  reported at module offset 0; the entry list from `build/gen` call
  targets does not match). Needed later to size anything routine-shaped.
- `tools/lowering_cost.py`: add static code bytes per executed guest
  instruction and per form (68020 without a data cache fetches every
  instruction word; code bytes are a cost of their own).
- Record the baseline table (§4 groups below, from `lowering_cost.py`) in
  this file.
- Gate: tools only; `make test`.
- T1 price (2026-10-07 session, parent `6e22e70`): tooling only,
  no generated-code saving claimed; the ≥1% build threshold applies to
  lowerings. Fresh 100-field capture: 28,420,398 cycles, guest share
  86.53%; m4 host census: 49 frames, 19,290 `cmpsw` and 16,075 `stosw`
  elements/frame. Root-directory attribution already finds call targets;
  the relative default silently loses them when invoked from `amiga/`.


#### T1 baseline (2026-10-07, unchanged `6e22e70` executable)

First fresh 100-field capture; grouped from `lowering_cost.py` form rows
(rounded). Groups overlap; shares are of all CPU cycles. Static instruction
counts and bytes are weighted by label executions; they include both arms
of a lowering and are not dynamic instruction-fetch traffic. The D16 walk
is counted at its generated entry, not as individual interpreted cells.

| Group | CPU share | Executions | Cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---:|---:|---:|---:|---:|
| T2 register-based memory | 19.88% | 313,369 | 18.07 | 5.16 | 15.79 |
| T3 swaps (role) | 6.08% | — | — | — | — |
| T3 `push r16` | 3.75% | 71,074 | 15.0 | 5.0 | 14.8 |
| T4 state-block traffic (role) | 8.99% | — | — | — | — |
| T4 carry readers | 5.86% | 100,041 | 16.61 | 5.08 | 14.37 |
| T5 calls/returns | 6.04% | 41,326 | 41.57 | 8.75 | 30.63 |
| T7 multiply/divide | 4.85% | 30,162 | 45.79 | 8.02 | 22.65 |
| T8 r8 forms | 5.85% | 141,895 | 11.68 | 3.87 | 10.52 |
| T8 segment forms | 2.06% | 22,908 | 25.64 | 6.09 | 20.79 |

Generated total: 86.53% of 28,420,398 cycles; 1,571,702 label executions,
6,688,419 executed 68k instructions; 15.65 cycles, 4.26 executed 68k
instructions and 10.99 execution-weighted static bytes per guest instruction.
Top call-target regions: SWOTL+06A4D 12.07%, SWOTL+0B54B 6.17%,
SWOTL+0BFD1 6.10%, FLIGHT+0A8D2 3.42%. These are nearest-call-target
self-time regions, not a proved source-level routine partition.

Repeated frame timing (interval ending at frame 4 through frame 11):

| Arm/run | Eight intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 30, 26, 36, 27, 30, 27, 34, 29 | 29.5 / 590 | 26–36 | 15.65 | 4.26 |
| parent-2 | 24, 31, 25, 33, 25, 30, 26, 27 | 26.5 / 530 | 24–33 | 16.19 | 4.43 |
| parent-3 | 30, 26, 36, 26, 31, 27, 33, 30 | 30 / 600 | 26–36 | 15.66 | 4.26 |
| tools-1 | 30, 26, 37, 27, 31, 26, 33, 30 | 30 / 600 | 26–37 | 15.64 | 4.25 |
| tools-2 | 30, 26, 37, 27, 32, 26, 33, 29 | 29.5 / 590 | 26–37 | 15.57 | 4.23 |
| tools-3 | 25, 31, 25, 33, 24, 31, 26, 26 | 26 / 520 | 24–33 | 16.16 | 4.42 |

Parent medians 26.5–30 fields (530–600 ms); tooling medians 26–30 fields
(520–600 ms). The arms overlap, as expected for T1: the executable is
unchanged (3,813,776 bytes). No speed gain claimed. `make test` and the
new tooling target pass; deliberately restoring the relative path or
dropping extension-word sizes is caught. Each capture was reported and
deleted. T1 kept as the explicitly tools-only step.

### T2. Register-based memory operands without per-access wrap arithmetic

- T2 price (2026-10-07 continuation, parent `2683c89`): fresh capture
  and host m4 census; 1.19% of P (single-register 1.12%, two-register
  0.06%, rounded). Measured untaken word-branch cost 4.13 cycles and
  immediate-register word/long comparisons 4.04/6.36 cycles; account for
  sum setup and address-register copies. This supersedes the preliminary
  price using mixed taken/untaken branches. Price assumes guard success;
  exact fallback remains mandatory. Acceptance requires ≥0.595% of P.
- User clarification: include two-register operands. Form the full unsigned
  sum once, check the displacement/width bounds, then keep it in scratch
  a0 only when lowering proves a0 unused through the last covered access.
  Both guest registers must retain their entry values through those uses.
  Other shapes and guard failures use today's exact lowering. No profile
  observation substitutes for either proof or guard.

- T2 rejected for size after the user's objection: executable 3,813,776 →
  4,848,664 bytes (+27.14%); generated `.text` 1,337,216 → 1,626,696 bytes
  (+21.65%). Prototype reverted; its 2,133 appended boundary cases are
  retained and pass with the original lowering. No optimized-arm timing
  or speed gain claimed. Local recovery patch stays under `tmp/`.

#### Executable size audit (2026-10-07)

`tools/hunk_size.py` accounts for every byte without modifying the file.
All nine in-scope original modules total 426,672 bytes; the Amiga executable
contains their generated code together. SWOTL.EXE and FLIGHT.OVL alone
are 100,112 and 103,472 bytes. BSS allocation is not file payload.

| File component | Parent | Rejected T2 |
|---|---:|---:|
| Code payload | 1,364,372 | 1,653,852 |
| Data payload | 4,044 | 4,044 |
| Embedded symbols | 2,407,116 | 3,149,564 |
| Relocations | 38,128 | 41,088 |
| Headers | 116 | 116 |
| Total | 3,813,776 | 4,848,664 |

Restored output: 3,813,776 bytes. Every non-symbol/debug record matches the
measured parent exactly; eight symbol-name padding bytes differ on rebuild.
`make test`, `make test-sabotage`, `make test-host-all`, `make test-amiga`
and `make smoke` all pass after the revert.
Static label-span code attribution: SWOTL 293,854 bytes, FLIGHT 349,570
bytes. `make size` exposes the full file breakdown for subsequent steps.

Keep code bytes and file bytes visible separately. Symbol removal addresses
file overhead; it does not compact generated instructions. A separate release
artifact was authorized by the user under §0.9. `make amiga-release` now
produces 1,406,660 bytes (2,407,116 fewer, 63.12% smaller than the debug file),
with zero symbols/debug records. Code/data/relocation/allocation records are
identical; the debug executable and ELF hashes are unchanged. No speed gain
claimed. Code payload remains 1,364,372 bytes including runtime/platform;
stripping does not address that expansion. Release smoke passes on the
68020 A1200 model with the existing fixture. `make test`,
`make test-sabotage`, `make test-host-all`, `make test-amiga` and `make smoke`
also pass for this tooling-only change.

- **Data.** `[bp/bx/si/di(+si/di)+disp]` operands: 19.2%, 307K executions,
  17.7 cyc, 5.1 68k instructions (`[bp]` alone 9.0%, 18.6 cyc). Each access
  forms the 16-bit offset in d7 (`move.l d5,d7` / `add.w #d,d7`) for the
  64 KiB wrap, then indexes `(seg,d7.l)`.
- **Shape.** Per block, for each base register the block does not write
  before its last use: the minimum and maximum displacement over its
  accesses (width included). One guard at block entry
  (`cmp.w #lo,dN`/`bcs`, `cmp.w #hi,dN`/`bhi`) proves no access in the block
  wraps; then accesses use `d16(seg,dN.l)` directly. Guard failure runs an
  exact copy of the block (today's lowering). Only blocks where the guard
  costs less than it saves (count it).
- **Exactness.** The guard is the exact no-wrap condition for every access
  it covers; a register written inside the block ends coverage at that
  write.
- **Tests.** Corpora: bases at 0, 1, 7FFFh, 8000h, FFFEh, FFFFh and at the
  guard's bounds ±1, displacements ±1, ±7Fh, ±8000h; word accesses at offset
  FFFFh. Blocks: `m68k_blocks` must execute both arms (count them). Plant:
  guard bound off by one.
- **Prize.** ≈ 2 instructions per covered access: ≈ 4–6% of P.

### T3. Byte order kept lazily in registers

- T3 revisit price (parent `48af2d7`, fresh capture and m4 census):
  **0.933% of P**, 265,087 estimated cycles of 28,420,398. Narrow to
  consecutive word moves/pushes/pops in AX/BX/CX/DX/BP inside one block;
  restore before address use, other instructions and block exits. Exclude
  graphics-driver stores that enter runtime. Static proof only; no annotations.
  3,582 profitable runs, 358 executed; net 64,991 swaps and 70,242 copies
  removed in the pricing model. Measured costs: 1.853 cycles/swap and
  2.060 cycles/data-register copy. Model counts every restoration. No gain
  claimed before A/B measurements; all gates and no-slowdown rule apply.
  Coverage first: 880 appended cases pass parent; deliberate wrong byte
  order gives 528 mismatches. Scratch reports: `tmp/t3-revisit/`.

#### T3 revisit result (kept)

All five gates pass, including all host milestones and c6. Added 880 boundary
cases and 36 leader-boundary cases pass; the permanent missing-native-store-
swap fault gives 553 mismatches. Implementation further requires no net added
swaps in any selected run. Every block entry/exit retains native register
order; there are no runtime, poll-point, guest-code or reference changes.

Three runs per arm, unchanged 68020 fixture; captures reported and deleted:

| Arm/run | Frames 4–11 intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 26, 31, 26, 38, 26, 31, 28, 32 | 29.5 / 590 | 26–38 | 15.18 | 4.159 |
| parent-2 | 24, 29, 24, 31, 24, 29, 24, 25 | 24.5 / 490 | 24–31 | 15.74 | 4.388 |
| parent-3 | 24, 29, 24, 31, 24, 29, 24, 25 | 24.5 / 490 | 24–31 | 15.39 | 4.280 |
| candidate-1 | 29, 24, 35, 25, 25, 26, 29, 26 | 26 / 520 | 24–35 | 15.18 | 4.144 |
| candidate-2 | 28, 25, 35, 25, 25, 26, 29, 26 | 26 / 520 | 25–35 | 15.19 | 4.146 |
| candidate-3 | 28, 25, 35, 25, 25, 26, 29, 26 | 26 / 520 | 25–35 | 15.19 | 4.145 |

Median cycles/guest 15.39 → 15.19; median 68k/guest 4.280 → 4.145.
Code payload 1,354,532 → 1,335,628 bytes (−18,904); release executable
1,396,816 → 1,377,892 (−18,924); debug executable 3,803,932 → 3,785,008.
Frame run medians 24.5–29.5 → 26 overlap. Median of the 24 frame intervals
is 26 fields in each arm; median of the three run medians is 24.5 → 26.
These timings establish neither a frame-rate gain nor a regression under
§3.6. Kept for reduced cycles/instructions and smaller code under the user
amendment; no frame-rate gain claimed. Next: revisit T4 cross-block.

Selected forms across the three runs (ranges; counts/bytes are weighted
static template sizes):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `push r16` | 14.8–14.9 → 13.9 | 5.0–5.1 → 4.5 | 14.7–15.2 → 14.0 |
| `pop r16` | 13.3–13.6 → 12.9–13.0 | 4.5–4.6 → 4.3–4.4 | 12.1–12.2 → 11.8 |
| `mov r16,m16[disp]` | 11.5–11.6 → 10.8 | 2.5 → 2.3 | 8.4–8.6 → 8.2 |
| `mov m16[disp],r16` | 12.4–12.5 → 11.6 | 3.0 → 2.7 | 8.9–9.0 → 8.3 |

#### Earlier T3 screening (superseded by the revisit)

- T3 price (2026-10-07 continuation, parent `0710c7d`): **0.958% of P**;
  below the 1% build threshold, not built. Fresh 100-field capture:
  28,420,394 cycles, 1,535,271 guest instructions, 6,798,002 68k instructions;
  16.18 cycles/guest, 4.43 68k/guest, 11.06 weighted static bytes/guest.
  Frames 4–11: 25, 30, 26, 32, 25, 31, 26, 26 fields; median 26 (520 ms),
  span 25–32. One pricing capture only; no optimized arm or speed claim.
- Pricing follows block-local memory loads/pops, word-register copies,
  stores/pushes and unconditional overwrites. Native order is restored for
  address/partial-register/arithmetic uses, runtime/transfer boundaries and
  block exits. Count both removed swaps and store copies; measured averages
  1.795 cycles/swap and 2.003 cycles/data-register copy. Address-register
  restores need two additional moves; address-register dead stores save no
  copy. Exclude in-place rotations that would change the store's own address.
  Include the graphics driver and choose the better positive block price
  with or without address-register propagation: 272,347 priced cycles.
  This is a candidate estimate, not a measured speedup or an exhaustive
  bound on other designs. Fresh host m4 census: 49 frames, 19,290 `cmpsw`
  and 16,075 `stosw` elements/frame. Reports and pricing scripts remain local
  under `tmp/t3-session/`; the raw capture was reported and deleted.
- T2 and T3 are consecutive unsuccessful translator steps. Stop under §2
  and ask the user before proceeding to T4. No lowering or test changed.

- **Data.** Byte swaps 5.9% (893K `ror.w #8` per 100 fields) plus the
  `move.l dN,d6` copies stores make to swap without destroying the
  register (`mov m16,r16` 12.6 cyc / 3 instructions; `push r16`
  15.1 cyc / 5.1).
- **Shape.** A per-block register analysis: a value loaded from guest
  memory and only moved, stored or pushed stays in memory byte order (no
  swap on load or store); a register whose next use overwrites it is
  swapped in place without a copy (register liveness within the block).
  At block exit every register is in native order.
- **Tests.** Corpora: load/store/push chains, partial-register (AL/AH) use
  of a swapped value, flags from a swapped value. Plant: one store skips its
  swap.
- **Prize.** ≈ 3–4% of P.

### T4. Flags across block boundaries

- T4 implementation price (parent `a8d1591`, fresh capture and m4 census):
  **0.03189% of P**, 9,062 of 28,420,386 cycles. Narrow to conditional
  branch entries whose every predecessor already establishes all four CCR
  bits. Keep every flag store and the original memory-flag liveness. Exclude
  runtime/indirect entries, calls, returns and polls. 52 static candidates,
  five active sites. Coverage before code: 192 predecessor graph cases pass;
  dropping a predecessor's flag store produces 183 mismatches. Appended
  branch corpus covers all 16 conditions, 32 flag combinations and signed
  displacement edges. Authorized harness change only initializes proved
  entry bits; all comparisons remain. Local reports: `tmp/t4-cross/`.

#### T4 cross-block result (reverted)

All five candidate gates passed. Added 1,536 branch cases and 192 predecessor
graph cases; the missing-predecessor-store plant gives 183 mismatches. The
candidate removed 52 full CCR reloads, retaining every memory flag definition.
Three runs per arm, unchanged 68020 fixture; raw captures reported and deleted:

| Arm/run | Frames 4–11 intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 29, 24, 35, 25, 25, 26, 29, 26 | 26 / 520 | 24–35 | 15.18 | 4.144 |
| parent-2 | 29, 25, 35, 25, 25, 25, 30, 25 | 25 / 500 | 25–35 | 15.18 | 4.142 |
| parent-3 | 29, 24, 36, 25, 25, 25, 30, 25 | 25 / 500 | 24–36 | 15.17 | 4.142 |
| candidate-1 | 24, 29, 23, 31, 24, 28, 24, 25 | 24.5 / 490 | 23–31 | 15.64 | 4.331 |
| candidate-2 | 26, 30, 27, 37, 26, 32, 27, 32 | 28.5 / 570 | 26–37 | 14.96 | 4.067 |
| candidate-3 | 24, 29, 23, 31, 24, 28, 24, 25 | 24.5 / 490 | 23–31 | 15.72 | 4.346 |

Selected branch forms across the three runs (ranges; instruction and byte
columns are execution-weighted static template sizes):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `jne near` | 6.9 → 6.3–6.8 | 1.2 → 1.1–1.2 | 3.2 → 2.8–3.1 |
| `je near` | 5.0 → 4.9–5.1 | 1.1 → 1.1 | 3.0 → 2.9–3.0 |
| `jg near` | 7.3–7.4 → 5.8–7.9 | 1.6 → 1.3 | 4.9 → 3.9–4.1 |

Median cycles/guest 15.18 → 15.64 and 68k/guest 4.142 → 4.331 do not
support an efficiency win. Frame arms overlap; no frame-rate gain established.
Code payload 1,335,628 → 1,335,420 bytes; release 1,377,892 → 1,377,684;
debug executable 3,785,008 → 3,784,800. Revert the optimization and its
entry-state harness setup under the no-slowdown rule; retain the added
branch/predecessor corpus and permanent sabotage plant. Local reports and
recovery patch: `tmp/t4-cross/`. All five gates also pass after the revert;
restored code payload 1,335,628 bytes and release 1,377,892 bytes verified.
Next: fresh T5 pricing.

- T4 revisit (parent `8f963c1`): fresh capture prices cross-block flag reuse
  at **0.03196% of P**, 9,082 of 28,420,397 cycles; 62 static eligible
  readers, six sites with captured savings. Eligible under amended §3.1;
  initial pricing only. Host m4 census: 49 frames, 19,290 `cmpsw`
  and 16,075 `stosw` elements/frame. Capture: 1,612,795 guest instructions,
  6,683,102 68k instructions; 15.18 cycles/guest, 4.144 68k/guest,
  10.37 weighted static bytes/guest. Frames 4–11: 29, 24, 35, 25, 25,
  26, 29, 26; median 26 fields (520 ms), span 24–35. Pricing run only.
  Reports: `tmp/t4-revisit/`; raw capture reported and deleted.
- **Authorized harness change (user, 2026-10-07):** T4's Tests paragraph requires
  CCR-aware block-entry setup, but §2.5/user instructions prohibit edits to
  existing tests to make a step pass. `tests/m68k_diff.py` currently clears
  SR before every run; `tests/m68k_blocks.py` uses that for every entry.
  Proposed narrow change: initialize only proved entry CCR bits from the
  oracle input flags, preserve all existing comparisons, samples and references,
  and add every-predecessor cases plus the missing-store sabotage fault.
  The user authorized this input-setup change. Preserve every existing
  comparison and reference. Resume T4; T3 remains kept.

- T4 price (2026-10-07 continuation, parent `4d94654`): **0.0273% of P**
  (7,760 captured cycles); cross-block candidate not built below the 1% bar.
  Fresh capture: 28,420,396 cycles, 1,567,672 guest instructions, 6,690,952
  68k instructions; 15.68 cycles/guest, 4.27 68k/guest, 10.99 weighted static
  bytes/guest. Frames 4–11: 30, 26, 36, 26, 31, 27, 33, 30 fields;
  median 30 (600 ms), span 26–36. Pricing capture only; no speed claim.
- Analysis intersects predecessor flag availability; excludes actual runtime
  dispatch entries, call targets, return sites, interrupt entries and poll
  points. CFG branch-target seeds are not all runtime entries. Check emitted
  CCR effects, direct jumps (near/far), preserving address-register moves,
  and X preservation before carry consumption. Retain state stores demanded
  by another successor. Candidate: 62 static cross-boundary readers, six
  sites with captured savings. Fresh host m4 census: 49 frames, 19,290
  `cmpsw` and 16,075 `stosw` elements/frame.
- The same analysis including **within-block** carry reuse estimates 4.903%
  (1,393,557 captured cycles). This is preliminary pricing, not a measured
  speedup or a proved exhaustive bound; implementation may narrow eligibility.
  The user subsequently authorized the within-block extension (below).
  Local reports: `tmp/t4-session/`; raw capture reported and deleted.

- User authorized the within-block extension. T4-local price (parent
  `8f41976`, fresh 2026-10-07 capture and m4 census): **4.191% of P**
  (1,191,109 of 28,420,399 cycles; 970 static eligible readers, 606 sites
  with captured savings). Narrow to adjacent producers/readers inside a
  block: hardware X must equal guest CF and survive reader operand setup.
  Reuse for `adc`/`sbb`/`rcl`/`rcr`; retire a producer's CF store only when
  the next reader definitely replaces CF or the old CF is dead afterward.
  Preserve every block entry's memory-flags contract and all poll points.
  Original frame-time bar: at least 2.096% of P and non-overlapping arms;
  the user's later §3.6 amendment also accepts efficiency/size gains.
  Baseline code payload 1,364,372 bytes; stripped executable 1,406,660 bytes.
- Coverage before implementation: 1,901 appended carry cases pass on the
  parent; deliberately clearing X gives 1,055 mismatches. Candidate passes
  all 1,901; bypassing its EA preservation check gives 468 mismatches.
  Another 32 cases poison X at a block entry: all pass; deliberately ignoring
  the entry boundary gives 12 mismatches. Both faults are permanent sabotage
  checks. The 1,901 carry cases and 32 entry cases remain. No block's entry
  convention changes.

#### T4-local result (kept under revised acceptance)

All five gates passed on the candidate. Three runs per arm, same session and
unchanged 68020 fixture; each capture reported and deleted:

| Arm/run | Frames 4–11 intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 30, 26, 36, 27, 30, 27, 34, 29 | 29.5 / 590 | 26–36 | 15.65 | 4.26 |
| parent-2 | 29, 26, 36, 27, 31, 26, 34, 29 | 29 / 580 | 26–36 | 15.63 | 4.25 |
| parent-3 | 25, 30, 25, 33, 25, 30, 26, 27 | 26.5 / 530 | 25–33 | 16.18 | 4.43 |
| candidate-1 | 30, 26, 38, 26, 31, 27, 33, 28 | 29 / 580 | 26–38 | 14.73 | 4.01 |
| candidate-2 | 29, 25, 35, 25, 26, 25, 30, 26 | 26 / 520 | 25–35 | 15.28 | 4.22 |
| candidate-3 | 31, 26, 37, 27, 31, 27, 33, 28 | 29.5 / 590 | 26–37 | 14.75 | 4.02 |

Parent medians 26.5–29.5 fields; candidate 26–29.5: frame times overlap,
so no frame-rate gain is established. Cycles/guest fall from 15.63–16.18 to
14.73–15.28; 68k instructions/guest from 4.25–4.43 to 4.01–4.22. Code payload
1,364,372 → 1,354,532 bytes; stripped executable 1,406,660 → 1,396,816 bytes;
debug executable 3,813,776 → 3,803,932 bytes. Kept by the user's revised §3.6
rule: fewer cycles/instructions and smaller code count as a win even without
an observed frame-rate increase. The kept rebuild's loadable records match
exactly the executable used for the successful gates and measurements.
Reports in `tmp/t4-local/`. Next: T5.

Selected carry forms across the three runs (ranges; static counts/bytes are
execution-weighted, not dynamic fetch traffic):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `adc r16,r16` | 15.2 → 5.4–5.5 | 4.1 → 2.0 | 12.4 → 6.0 |
| `rcl r16,imm` | 11.9–12.0 → 4.8–5.1 | 3.5 → 1.4 | 10.0–10.1 → 3.4–3.6 |
| `rcr r16,imm` | 8.7–8.8 → 3.2 | 3.4 → 1.4 | 8.9–9.0 → 2.8–2.9 |

- **Data.** State-block traffic 8.9% (`move.w ccr,G_FL(a6)` and reloads);
  CF readers `adc`/`sbb`/`rcl`/`rcr` 5.9%, 16.6 cyc / 5.0 instructions
  (CF reloaded from `G_FL` through `lsr.b`/`ori #4,ccr`).
- **Shape.** Flag location analysis on top of the global liveness
  (`emit.py`): a block whose every predecessor is a direct jump or fall
  through from code that leaves the needed flags in the CCR with x86
  meaning (`CCR_OK`) reads the CCR, and the predecessors skip the store
  when no other successor needs the state block. Blocks entered from the
  runtime (dispatch, return sites, interrupt returns, SMC) keep the state
  block.
- **Tests.** `m68k_blocks` cases entering such blocks from each kind of
  predecessor; the harness sets the CCR as well as the state block for
  CCR-entry blocks. Plant: a predecessor skips a store another successor
  needs.
- **Prize.** ≈ 4–6% of P.

### T5. Far and near calls and returns

- T5 revisit (2026-10-08, parent `2a070b5`): fresh capture and m4 census
  price the specified packing at an optimistic **0.913% of P**, 259,423
  estimated cycles of 28,420,397. 10,497 far-call pushes and 11,447 far
  returns; measured compare costs 3.996 word / 6.547 long cycles and 1.309
  cycles for an untaken short branch (220,166 samples). As in the earlier
  screen, charge long accesses only word-access cost, assume guard success,
  omit fallback joins and return-format conversions. This is not a speedup.
- The specified inline form adds SP guards and exact fallback paths;
  packing the return check removes less code than those paths add. No
  smaller exact implementation has been established. It therefore does not
  qualify for the sub-1% efficiency/size exception. No prototype or test
  change built; do not infer an exhaustive bound on alternative designs.
- Capture: 1,612,857 guest instructions, 6,683,316 68k instructions;
  15.18 cycles/guest, 4.144 68k/guest, 10.37 static bytes/guest. Frames 4–11:
  29, 24, 35, 25, 25, 26, 29, 26; median 26 fields (520 ms), span 24–35.
  Host census: 49 frames, 19,290 `cmpsw` and 16,075 `stosw` elements/frame.
  Reports: `tmp/t5-revisit/`; raw capture reported and deleted. Code payload
  remains 1,335,628 bytes; release executable 1,377,892 bytes.
- T4 rejected and T5 not built are two consecutive unsuccessful steps.
  User authorized leaving T5 unbuilt and continuing autonomously through
  T6–T9 (2026-10-08). Other hard stops remain.
  No authority to change return comparisons, references or guest semantics.


- T5 price (parent `f7dad4b`, fresh capture and m4 census): **0.926% of P**
  (263,296 estimated cycles of 28,420,398); the specified guarded far-call/
  return packing is not built below 1%. This is an optimistic common-path
  screen, not a measured speedup: charge long memory operations only the
  measured word-access cost, omit cold-arm joins and return-format conversion,
  and assume every guard succeeds. Near calls/returns are unchanged by this
  four-byte packing shape. No wrap case is removed or assumed impossible.
- The capture contains 10,571 far-call pushes and 11,553 far returns.
  Measured immediate compare costs: word 3.994, long 6.599 cycles;
  short untaken branches 1.399 cycles (220,514 samples, checked against the
  next executed PC). Estimated savings: pushes 55,700, pops 126,126,
  exact two-word check replaced by long check 81,470 cycles. Additional
  implementation costs can only reduce this estimate under this cost model.
- Capture: 1,593,422 guest instructions, 6,745,673 executed 68k instructions;
  15.32 cycles/guest, 4.23 68k/guest, 10.50 weighted static bytes/guest.
  Frames 4–11: 29, 24, 36, 25, 25, 26, 30, 27 fields; median 26.5
  (530 ms), span 24–36. One pricing run; no candidate or speed claim.
  Host census: 49 frames, 19,290 `cmpsw` and 16,075 `stosw` elements/frame.
  Reports and pricing script: `tmp/t5-session/`; raw capture deleted after
  reporting. No code/test change; code payload remains 1,354,532 bytes.

- **Data.** `callf`/`retf`/`call`/`ret` 5.6%, 41.7 cyc / 8.8 instructions:
  two separate word pushes, then the callee pops IP and CS into d7/d6 with
  swaps and the caller compares both (return check).
- **Shape.** Under an SP guard (no wrap for 4 bytes), CS:IP pushed as one
  long of a constant already in memory byte order; `retf` leaves the raw
  long and the caller compares it with the constant in one `cmp.l`. The
  check stays exact: the same bytes are compared. Otherwise today's form.
- **Tests.** SP at 0, 2, 4, FFFEh; return address edited by the callee
  (mismatch must stop). Plant: compare one word only.
- **Prize.** ≈ 2–3% of P.

### T6. Code bytes and addressing modes

- T6 revisit price (2026-10-08, parent `3561bd5`): fresh 100-field capture
  and m4 census; **0.443% of P**, 125,954 estimated cycles of 28,420,399.
  Local upper-word proof screens 2,052 masks: 753 with CCR overwritten
  before use (11,910 executions), 1,299 requiring an exact `tst.l`
  replacement (14,259 executions). Model includes replacement costs;
  implementation may narrow eligibility. No guest values/flags, guards,
  wrapping, poll points or entry conventions change.
- Isolated synthetic microbenchmarks on the default 68020 + 8 MB Fast model:
  `and.l #$ffff,d0` 6.125 cycles / 6 bytes (444,764 executions), `tst.l d0`
  2.125 cycles / 2 bytes (1,233,964 executions). These are instruction-cost
  probes, not game speed measurements; the game fixture is unchanged.
  Static screen estimates 9,714 fewer code bytes. Unknown native effects,
  labels and control transfers invalidate facts; removing a mask additionally
  requires proof that a later instruction overwrites all its CCR results
  before any read. Otherwise keep those flags through `tst.l`.
- Fresh m4 census: 49 frames, 19,290 `cmpsw` and 16,075 `stosw` elements/frame.
  Local captures/reports/pricing: `tmp/t6-revisit/`; three parent runs complete,
  raw game and microbenchmark captures reported and deleted. Coverage first,
  sabotage and all five gates required before candidate timing.


#### T6 revisit result (kept)

All five gates pass. Initial coverage: 222 cases pass the parent, six fail
with a deliberately blind mask-to-TST replacement. Expanded coverage: 276
cases pass the candidate; the permanent fault is caught in 45 cases of the
full boundary corpus. Proof tests include dirty scratch, arithmetic, labels,
control flow, CCR readers, address auto-update, unsized MOVE and MOVEQ sign
extension. Final guard refinements leave every allocated ELF section exactly
identical to the candidate used for host/Amiga/smoke validation.

The generated code removes 798 masks and replaces 1,299 with `tst.l`.
Three runs per arm, unchanged fixture/model; captures reported and deleted:

| Arm/run | Frames 4–11 intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 29, 24, 35, 25, 25, 26, 29, 26 | 26 / 520 | 24–35 | 15.18 | 4.144538 |
| parent-2 | 28, 25, 35, 25, 25, 25, 30, 26 | 25.5 / 510 | 25–35 | 15.19 | 4.145716 |
| parent-3 | 29, 25, 35, 25, 25, 25, 29, 26 | 25.5 / 510 | 25–35 | 15.20 | 4.146322 |
| candidate-1 | 28, 24, 34, 24, 24, 24, 29, 25 | 24.5 / 490 | 24–34 | 14.94 | 4.145894 |
| candidate-2 | 28, 24, 33, 24, 25, 24, 29, 25 | 25 / 500 | 24–33 | 14.94 | 4.144618 |
| candidate-3 | 28, 25, 34, 25, 24, 24, 30, 25 | 25 / 500 | 24–34 | 14.97 | 4.158969 |

Kept under §3.6's non-overlapping **run-median** timing criterion: 25.5–26
→ 24.5–25 fields; median of run medians 25.5 → 25 (1.96% reduction), above
half the 0.443% price. Individual interval spans overlap; no span separation
claimed. Median cycles/guest 15.19 → 14.94, with non-overlapping ranges.
Median 68k/guest rises slightly, 4.145716 → 4.145894 (0.0043%); no instruction-
ratio improvement claimed, and the three-metric efficiency exception is not
the acceptance basis. Measured frame time and cycles improve; smaller code
is not being used to excuse slower execution.

Code payload 1,335,628 → 1,325,612 (−10,016 bytes); release executable
1,377,892 → 1,367,868 (−10,024); debug 3,785,008 → 3,774,984.
Selected forms across the runs (static instruction/byte counts are weighted):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `mov sreg,r16` | 21.9 → 14.8 | 5.0 → 4.0 | 18.0 → 12.0 |
| `pop r16` | 12.9–13.2 → 11.9 | 4.3–4.4 → 4.3 | 11.8–11.9 → 10.7 |
| `mov r16,m16[bp]` | 15.5 → 15.1–15.2 | 4.3 → 4.2 | 13.0 → 12.6–12.7 |

Next: T7, fresh pricing of live multiply/divide results.

#### Earlier T6 screening

- T6 screening (parent `47379e9`, fresh capture and m4 census): the listed
  encoding candidates total at most **0.593% of P** in the local analysis
  (168,532 of 28,420,384 cycles), even charging replacements zero cycles.
  Not built under the current 1% rule. This is a candidate screen, not an
  exhaustive bound on all possible code-size work or a measured saving.
- Assembled-code audit: no remaining small `move.l` immediates that fit
  `moveq`, or word branches that fit byte displacements. 223 long branches
  fit word displacements but have zero executions in this capture. Local
  upper-word tracking finds 2,052 mask sites (27,464 executions); their
  complete captured cost is 168,532 cycles. Actual removal also requires
  preserving CCR effects, so the screen intentionally overstates the prize.
  Guest-register zero-extension is the existing translator contract; scratch
  values are tracked conservatively and invalidated at control transfers.
  Constant word pushes already use immediate stores. No alternative built
  or microbenchmark result claimed; replacement-cost measurements are deferred
  because even a zero-cost replacement falls below the current screen.
- Capture: 1,651,478 guest instructions, 6,655,788 executed 68k instructions;
  14.78 cycles/guest, 4.03 68k/guest, 10.12 weighted static bytes/guest.
  Frames 4–11: 31, 26, 37, 26, 32, 27, 32, 29 fields; median 30
  (600 ms), span 26–37. One pricing run; no speed claim. Host census:
  49 frames, 19,290 `cmpsw` and 16,075 `stosw` elements/frame. Local reports:
  `tmp/t6-session/`; raw capture reported and deleted. No code/test change.
  T5 and T6 are consecutive not-built steps: pause before T7 under §2.

- **Data.** After T1: bytes per guest instruction by form. Known waste:
  `move.l #0,d6` (6 bytes) for `moveq`, `and.l #$ffff` where the upper
  word is known clear, `bne.l` where `bne.w` reaches, word-immediate
  pushes through `(a2,d4.l)`.
- **Shape.** Shortest exact encoding per lowering template; 68020 cycle
  costs of the alternatives measured on the A1200 model first (open-work
  15 microbenchmarks), not taken from tables.
- **Prize.** Price after T1 and the microbenchmarks.

### T7. Multiply and divide results only where live

- T7 price (2026-10-08, parent `fd8ed6e`): fresh capture and m4 census;
  **0.00546% of P**, 1,553 captured cycles of 28,420,398. Narrow to word
  multiply/divide DX results proven dead before a full overwrite within the
  same block. 89 static sites: 56 `mul`, 14 `imul`, 14 `div`, five `idiv`;
  603 executed instructions and 496 static code bytes removable in the
  pricing model. Fourteen sites active in this capture. This is eligible
  under the user's removed floor for smaller efficiency/size candidates.
- Keep unsigned multiply's DX extraction when CF/OF computation needs it.
  Keep all AX masks, divide guards and fault paths. Unknown instructions,
  runtime boundaries, branches, block exits and leaders make DX live.
  Prove full writes and all explicit/implicit DX reads, including DH/DL;
  multiplication's implicit overwrite is safe, division remains a barrier
  on input because its fault handler can observe the old registers.
- Baseline capture: 14.99 cycles/guest, 1,680,697 guest instructions and
  6,991,027 68k instructions; fresh census 49 frames, 19,290 `cmpsw` and
  16,075 `stosw` elements/frame. Reports: `tmp/t7-session/`. No gain claimed
  before coverage, all gates and the three-run measurements.


#### T7 result (reverted)

All five candidate gates passed. Retain 2,458 appended oracle cases: register
and every word-memory addressing form, wrap edges, normal/fault division,
DX/DH/DL reads, partial/full overwrites, implicit multiply writes and defined
CF/OF readers. Parent and candidate both pass; blindly dropping DX gives 330
mismatches in these cases and 412 in the full boundary sabotage gate.

Three runs per arm, unchanged 68020 fixture; captures reported and deleted:

| Arm/run | Frames 4–11 intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 28, 24, 34, 25, 25, 24, 29, 25 | 25 / 500 | 24–34 | 14.99 | 4.159600 |
| parent-2 | 28, 24, 34, 23, 25, 24, 29, 25 | 25 / 500 | 23–34 | 14.94 | 4.145103 |
| parent-3 | 28, 24, 34, 23, 25, 24, 29, 25 | 25 / 500 | 23–34 | 14.94 | 4.144098 |
| candidate-1 | 29, 24, 35, 25, 25, 24, 30, 24 | 25 / 500 | 24–35 | 15.06 | 4.164762 |
| candidate-2 | 23, 29, 23, 31, 23, 29, 23, 26 | 24.5 / 490 | 23–31 | 15.00 | 4.159346 |
| candidate-3 | 23, 29, 23, 30, 24, 28, 24, 25 | 24.5 / 490 | 23–30 | 15.01 | 4.161331 |

Selected forms across the runs (static counts/bytes are execution-weighted):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `mul r16` | 37.0 → 36.8 | 6.0 → 5.9 | 16.0 → 15.9 |
| `div r16` | 68.8 → 68.5 | 16.0 → 15.9 | 44.0 → 43.9 |
| `mul m16[disp]` | 42.9 → 42.8–42.9 | 7.0 → 7.0 | 20.0 → 20.0 |
| `div m16[disp]` | 72.0 → 72.0 | 17.0 → 17.0 | 48.1 → 48.1 |

Median cycles/guest 14.94 → 15.01 and 68k/guest 4.145103 → 4.161331.
Frame run-median ranges overlap at 25 fields; interval spans overlap too.
Candidate code payload 1,325,612 → 1,325,112 bytes, release 1,367,868 →
1,367,368, debug 3,774,984 → 3,774,484. The 500-byte saving does not excuse
these results under §3.6. Revert the implementation; retain the appended
oracle corpus and permanent live-DX fault. Recovery patch and reports:
`tmp/t7-session/`. All five restored-build gates pass; the live-DX plant
still gives 412 mismatches. Restored code/release/debug sizes are
1,325,612 / 1,367,868 / 3,774,984 bytes. Next: T8.

- **Data.** `mul`/`imul`/`div`/`idiv` 4.8%, 45.7 cyc / 8.0 instructions
  (DX extraction, CF/OF from DX ≠ 0, AX masking) with `mulu.w` itself 22.
- **Shape.** DX and flag extraction only when live (register liveness from
  T3, flag liveness from D6).
- **Prize.** ≈ 1–1.5% of P.

### T8. 8-bit register and segment register forms

- T8 price (2026-10-08, parent `2acc1be`): fresh capture and m4 census;
  **0.278745% of P**, 79,220 estimated cycles of 28,420,398. Replace only
  high-byte register writes with `bfins src,dN{16:8}`: 2,396 static sites,
  38,007 executions, 76,014 fewer executed instructions and 4,792 fewer
  static bytes in the pricing model. All AH/CH/DH/BH sources and addressing
  forms remain supported. Preserve X, all guest flags and register bits.
- Isolated unchanged-model probes: three-instruction rotate/move/rotate
  write 6.375 cycles / 6 bytes; BFINS 4.125 cycles / 4 bytes. High-byte reads
  price separately at 0.039392% with no byte saving; leave them unchanged.
  Conservative block-local segment-base overwrite screen finds zero sites;
  unknown instructions/runtime/control boundaries keep every base live.
- Fresh baseline: 14.94 cycles/guest, 1,686,348 guest instructions and
  6,991,489 68k instructions. Census: 49 frames, 19,290 `cmpsw` and 16,075
  `stosw` elements/frame. Reports/pricing/probes: `tmp/t8-session/`.
  No gain claimed before coverage, gates and three-run candidate measurements.
- Coverage: 5,740 new comparisons pass both parent and candidate; the
  deliberately wrong byte offset gives 5,680 mismatches. Include CF-only
  consumers for logical/shift forms whose undefined flags make PUSHF an
  unsuitable full-flag oracle. All existing comparisons remain unchanged.
  The candidate preserves all 1,560 exercised carry-reuse pairs. Preliminary
  built sizes: code 1,320,788 bytes; release 1,363,044 bytes (−4,824 each).

#### T8 result (reverted)

All five candidate gates pass. Retain 5,740 appended comparisons and the
permanent wrong-byte-insertion fault, caught in 6,379 full-corpus cases.
Three runs per arm, unchanged 68020 fixture; captures reported and deleted:

| Arm/run | Frames 4–11 intervals (fields) | Median (fields/ms) | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 28, 24, 34, 24, 24, 24, 29, 25 | 24.5 / 490 | 24–34 | 14.94 | 4.145935 |
| parent-2 | 28, 24, 34, 24, 24, 24, 29, 25 | 24.5 / 490 | 24–34 | 14.94 | 4.145665 |
| parent-3 | 29, 24, 34, 25, 25, 24, 29, 25 | 25 / 500 | 24–34 | 14.98 | 4.160922 |
| candidate-1 | 23, 29, 23, 30, 24, 28, 24, 24 | 24 / 480 | 23–30 | 15.44 | 4.261203 |
| candidate-2 | 24, 28, 23, 31, 23, 29, 23, 25 | 24.5 / 490 | 23–31 | 15.43 | 4.258929 |
| candidate-3 | 25, 31, 26, 36, 26, 31, 28, 31 | 29.5 / 590 | 25–36 | 14.82 | 4.019370 |

Selected forms across the three runs (execution-weighted static counts/bytes):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `sub r8,r8` | 17.6 → 15.7–16.1 | 8.0 → 6.1–6.2 | 16.8 → 15.1–15.6 |
| `mov r8,r8` | 6.8 → 5.9–6.3 | 3.2 → 2.4 | 6.5 → 5.6–5.8 |
| `mov r8,imm` | 4.2 → 3.9–4.0 | 1.3 → 1.1 | 4.2 → 4.0 |

Median cycles/guest 14.94 → 15.43; 68k/guest 4.145935 → 4.258929.
Frame medians and spans overlap; candidate run-median range 24–29.5 fields
is wider than the parent's 24.5–25. Neither acceptance route passes.
Code payload 1,325,612 → 1,320,788, release 1,367,868 → 1,363,044,
debug 3,774,984 → 3,770,160: 4,824 bytes saved in each, insufficient under
the no-slowdown rule. Implementation reverted; local recovery patch/reports
in `tmp/t8-session/`. All five restored-build gates pass; the new fault
still gives 6,379 mismatches. Restored code/release/debug sizes are
1,325,612 / 1,367,868 / 3,774,984 bytes.

T7 and T8 are consecutive rejections. Stop under §2 before T9 and request
user authorization to continue; the earlier authorization resumed after
T4/T5 and did not remove this hard stop. User authorized resuming T9
(2026-10-08); all other hard stops remain.

- **Data.** r8 forms 5.3%, 11.4 cyc (`sub r8,r8` 17.6 cyc / 8.0); segment
  forms (`mov`/`push`/`pop` sreg, `les`/`lds`) 2.0%, 24.8 cyc.
- **Shape.** Price per form; shorter AH/BH access sequences; segment base
  recomputation only when the base register is used before the next load.
- **Prize.** Price per form; apply the amended eligibility rule in §3.1.

### T9. Re-profile

After T2–T8: fresh capture, re-price every group of §4 and any new
candidate eligible under §3.1 as a new step here (T10 …). Repeat until no
remaining candidate qualifies, including smaller efficiency/size candidates.

#### T9 first pass (2026-10-08, parent `9446e5e`)

Fresh three-run baseline, unchanged 68020 fixture; captures reported and
deleted. Code/release sizes remain 1,325,612 / 1,367,868 bytes.

| Run | Frames 4–11 intervals | Median fields/ms | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| 1 | 28, 25, 34, 25, 24, 24, 30, 25 | 25 / 500 | 24–34 | 14.97 | 4.159059 |
| 2 | 28, 24, 35, 24, 25, 24, 30, 25 | 25 / 500 | 24–35 | 14.97 | 4.157952 |
| 3 | 29, 24, 34, 25, 25, 24, 29, 25 | 25 / 500 | 24–34 | 14.98 | 4.161243 |

First capture: 28,420,399 cycles. Fresh m4 census: 49 frames, 19,290
`cmpsw` and 16,075 `stosw` elements/frame. Group shares overlap; sums of
rounded form rows, not savings:

| Group | CPU share | Remaining screen |
|---|---:|---|
| T2 register-based memory | 19.62% | Guarded duplication re-priced 1.26351%; remains rejected for size |
| T3 byte swaps / register push-pop | 5.94% / 5.53% | Existing eligible data-register runs already transformed; broader propagation still to screen |
| T4 state traffic / carry readers | 5.09% / 4.14% | Rejected cross-block candidate re-priced 0.037269% |
| T5 calls/returns | 5.86% | Optimistic guarded packing 0.910342%; code growth still excludes sub-1% exception |
| T6 listed encodings/masks | — | No remaining known-clear masks, MOVEQ or short-branch candidates; 223 word-reachable long branches have zero executions |
| T7 multiply/divide | 5.86% | Rejected dead-DX candidate re-priced 0.005556% |
| T8 byte registers / segments | 5.60% / 1.98% | Rejected BFINS writes 0.280673%; BFEXTU reads 0.038754% with no size reduction; zero conservative dead-base sites |

Nearest-call-target self-time regions: SWOTL+06A4D 16.20%, SWOTL+0B54B
6.69%, SWOTL+0BFD1 6.09%, SWOTL+04DAE 4.84%, FLIGHT+0A8D2 4.31%.
These are not proved source-routine boundaries or native-replacement approval.
Reports/scripts: `tmp/t9-session/`. This is not the final no-candidate audit:
T10 qualifies; continue re-profiling after it and screen broader T3 variants.

### T10. Byte register copies without redundant scratch work

- Fresh T9 capture price: **0.023223% of P**, 6,600 estimated cycles.
  Low-to-low copies: 45 sites, 3,054 executions, 90 static bytes and 3,054
  dynamic instructions removable. High-to-high copies: six sites, 270
  executions, 24 static bytes and 540 dynamic instructions removable.
- Low copies become one byte move. High copies save the destination's low
  byte in scratch, copy the source word, then restore the saved low byte.
  Keep all surrounding register bits, X and guest flags. Mixed byte positions
  and memory operands keep their existing exact lowering. No block contract,
  poll, wrap path, runtime or annotation changes.
- Model uses fresh measured register-copy costs: byte 2.186734 cycles,
  word 2.221192. Expected total reduction: 114 bytes / 3,594 instructions
  per capture. Coverage, deliberate fault, five gates and three-run A/B
  measurements still required. T9's three baseline runs may serve as the
  parent arm because this documentation-only commit changes no executable.
- Coverage before implementation: 1,544 appended comparisons pass parent;
  deliberate wrong-source copy gives 480 mismatches. Candidate passes all
  1,544 and catches the same fault. Includes every byte-register pair,
  aliases, surrounding-byte preservation, live flags/CF, memory and word
  operand guard cases. Built code/release sizes 1,325,496 / 1,367,752 bytes,
  both 116 bytes smaller. Reports: `tmp/t10-session/`; all five gates pass.

#### T10 result (kept for measured frame time)

All five gates pass. New wrong-source sabotage gives 588 mismatches in the
full boundary corpus. Three runs per arm, unchanged model and fixture;
raw captures reported and deleted:

| Arm/run | Frames 4–11 intervals | Median fields/ms | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 28, 25, 34, 25, 24, 24, 30, 25 | 25 / 500 | 24–34 | 14.97 | 4.159059 |
| parent-2 | 28, 24, 35, 24, 25, 24, 30, 25 | 25 / 500 | 24–35 | 14.97 | 4.157952 |
| parent-3 | 29, 24, 34, 25, 25, 24, 29, 25 | 25 / 500 | 24–34 | 14.98 | 4.161243 |
| candidate-1 | 23, 29, 23, 30, 24, 28, 24, 25 | 24.5 / 490 | 23–30 | 15.45 | 4.304450 |
| candidate-2 | 23, 29, 23, 31, 23, 28, 24, 25 | 24.5 / 490 | 23–31 | 15.45 | 4.304991 |
| candidate-3 | 24, 28, 23, 31, 24, 28, 24, 24 | 24 / 480 | 23–31 | 15.46 | 4.306707 |

Kept under §3.6's frame-time route: run medians 25 → 24–24.5 fields,
median 25 → 24.5 (2% reduction), above half the 0.023223% price.
Individual interval spans overlap. Median cycles/guest rise 14.97 → 15.45
and 68k/guest 4.159059 → 4.304991; no whole-profile efficiency gain claimed.
Acceptance rests on measured faster frame time, not on using smaller code
to excuse slower frame time or claiming the three-metric efficiency exception.

Code payload 1,325,612 → 1,325,496, release 1,367,868 → 1,367,752,
debug 3,774,984 → 3,774,868 bytes. The `mov r8,r8` form's cycles/exec
6.8 → 6.2, weighted static instructions 3.2 → 3.0 and bytes 6.5 → 5.9.
No poll, guard, guest-state contract, runtime, fixture or reference changes.
Next: continue T9 with a fresh profile and broader byte-order screening.


### T11. Byte order across unrelated arithmetic inside a block

- Fresh post-T10 capture and m4 census, parent `f2bf24e`: **0.004728% of P**,
  1,344 estimated cycles. 73 static groups, five active; pricing predicts
  334 fewer code bytes and 761 fewer executed instructions. Fresh swap/copy
  costs 1.747250 / 1.928342 cycles. Reports: `tmp/t9-after-t10/`.
- Extend T3 only across a closed set of arithmetic/flag instructions whose
  explicit operands describe all guest-register accesses. Restore any raw
  register mentioned by an operand, including partial registers and memory
  address components. Unknown/implicit-register instructions, runtime and
  leader boundaries remain barriers. Keep every group entry/exit native.
- Trim each group to end on an eligible move/push/pop, so restoration never
  invalidates arithmetic CCR exported to a following reader. Accept a group
  only when it removes at least one swap/copy relative to T3 and adds neither
  kind. Keep the old in-place-store proof limited to consecutive word moves.
  No control-flow, poll, wrap, annotation, runtime or entry-contract changes.
- Fresh census: 49 frames, 19,290 `cmpsw` and 16,075 `stosw` elements/frame.
  Coverage, planted fault, five gates and three-run measurements required.
- Coverage: 1,529 new comparisons pass parent and candidate, plus 36 new
  leader-entry cases (72 total). Deliberately omitted native restoration
  gives 475 mismatches in the candidate's new cases and 571 in the full
  corpus. Includes simultaneous raw values exposed by partial registers,
  CL shift counts and each memory-address form. All five candidate gates pass.
  Built code/release sizes 1,325,164 / 1,367,420 bytes (−332 each).


#### T11 result (kept for efficiency/size)

All five gates pass. Three runs per arm, unchanged model/fixture; captures
reported and deleted. The new fault is caught in 571 full-corpus comparisons.

| Arm/run | Frames 4–11 intervals | Median fields/ms | Span | Cycles/guest | 68k/guest |
|---|---|---:|---|---:|---:|
| parent-1 | 23, 29, 23, 31, 23, 28, 24, 25 | 24.5 / 490 | 23–31 | 15.45 | 4.305057 |
| parent-2 | 23, 29, 23, 30, 24, 28, 24, 25 | 24.5 / 490 | 23–30 | 15.45 | 4.304764 |
| parent-3 | 23, 29, 23, 30, 24, 28, 24, 25 | 24.5 / 490 | 23–30 | 15.44 | 4.304954 |
| candidate-1 | 23, 29, 23, 30, 24, 28, 24, 25 | 24.5 / 490 | 23–30 | 14.97 | 4.156193 |
| candidate-2 | 23, 29, 23, 30, 24, 28, 24, 25 | 24.5 / 490 | 23–30 | 14.98 | 4.158873 |
| candidate-3 | 23, 29, 24, 30, 23, 29, 23, 26 | 25 / 500 | 23–30 | 14.96 | 4.153929 |

Kept by the efficiency/size exception: median cycles/guest 15.45 → 14.97,
68k/guest 4.304954 → 4.156193, code payload 1,325,496 → 1,325,164.
Frame timings overlap; both arm medians are 24.5 fields. No frame-rate gain
claimed. Release 1,367,752 → 1,367,420, debug 3,774,868 → 3,774,536 bytes.
The whole-window instruction mix differs; these ratios are the specified
capture measurements, not an attribution of every saved cycle to T11.

Selected forms (execution-weighted static counts/bytes):

| Form | Parent → candidate cycles/exec | Static 68k/exec | Static bytes/exec |
|---|---|---|---|
| `push r16` | 13.8 → 13.8 | 4.5 → 4.5 | 13.9–14.0 → 13.8–13.9 |
| `pop r16` | 11.9–12.0 → 11.9 | 4.3–4.4 → 4.4 | 10.7 → 10.7–10.8 |
| `mov r16,m16[disp]` | 10.7 → 10.7 | 2.3 → 2.3 | 8.2 → 8.1 |

No block entry, runtime, poll, reference or guest-state contract changed.
Next: T9 re-profile and screen remaining addressing/register forms.


## 5. Rejected and not built

(One line each: step, change, priced, measured, reason.)

- T2: guarded block duplication, priced 1.19% of P; executable +27.14%,
  generated text +21.65%; reverted for size before timing, boundary coverage retained.

- T3: block-local lazy byte order, priced 0.958% of P from a fresh capture;
  not built (below 1%); no generated-code or executable-size change.

- T4 cross-block candidate: priced 0.0273% of P; not built below 1%.

- T5: guarded far-call/return packing, optimistic price 0.926% of P; not
  built below 1%; no code or executable-size change.

- T6: listed encoding/local mask candidates screened at at most 0.593%
  of P with zero-cost replacements; not built below 1%; code unchanged.

- T4 cross-block revisit: priced 0.03189% of P; code −208 bytes, median
  cycles/guest 15.18 → 15.64 and 68k/guest 4.142 → 4.331, timing arms overlap;
  reverted under the no-slowdown rule, new coverage retained.

- T5 revisit: optimistic fresh price 0.913% of P; specified inline guards/
  fallbacks grow code, so not eligible for the sub-1% size exception; not built.

- T7: dead word DX results, priced 0.00546% of P; code −500 bytes, median
  cycles/guest 14.94 → 15.01 and 68k/guest 4.145103 → 4.161331; timing arms
  overlap. Reverted; oracle cases and live-DX sabotage retained.

- T8: high-byte BFINS writes, priced 0.278745% of P; code −4,824 bytes,
  median cycles/guest 14.94 → 15.43 and 68k/guest 4.145935 → 4.258929;
  timings overlap. Reverted, coverage retained; stop after two rejections.

## 6. When the translator work is done

When T9 finds no remaining candidate eligible under §3.1: write the final numbers into §1,
update open-work 14b, and report to the user with the remaining gap and
the profile's top routines (T1 attribution). Then **stop**. Native
replacement of hot routines (§2.1) is the user's decision, routine by
routine; the agent may list candidates with their shares, nothing more.
