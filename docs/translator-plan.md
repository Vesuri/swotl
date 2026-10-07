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
- **Now (commit 6646626):** median 26–27 fields (0.52 s). Guest code 88%:
  13.5 68020 cycles and 3.6 68k instructions per guest instruction (the
  80286: ≈ 5.4 clocks); cell walk 14%; runtime 8%.
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
   step priced under 1% of P is not built; it gets a line in §5.
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
6. **Keep or revert:** keep if the arms do not overlap (span or median) and
   the gain is at least half the priced prize; otherwise revert the code,
   keep any new tests that pass on the reverted code, and add one line to §5.
7. **Commit** one step per commit: before/after numbers in the message;
   §4 and open-work 14b updated in the same commit (speed-plan §0.8).
8. **Report** to the user after each step in a few lines: step, numbers,
   kept or reverted. Then the next step.

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
artifact requires the user's §0.9 approval; the measurement build stays fixed.

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

- **Data.** After T1: bytes per guest instruction by form. Known waste:
  `move.l #0,d6` (6 bytes) for `moveq`, `and.l #$ffff` where the upper
  word is known clear, `bne.l` where `bne.w` reaches, word-immediate
  pushes through `(a2,d4.l)`.
- **Shape.** Shortest exact encoding per lowering template; 68020 cycle
  costs of the alternatives measured on the A1200 model first (open-work
  15 microbenchmarks), not taken from tables.
- **Prize.** Price after T1 and the microbenchmarks.

### T7. Multiply and divide results only where live

- **Data.** `mul`/`imul`/`div`/`idiv` 4.8%, 45.7 cyc / 8.0 instructions
  (DX extraction, CF/OF from DX ≠ 0, AX masking) with `mulu.w` itself 22.
- **Shape.** DX and flag extraction only when live (register liveness from
  T3, flag liveness from D6).
- **Prize.** ≈ 1–1.5% of P.

### T8. 8-bit register and segment register forms

- **Data.** r8 forms 5.3%, 11.4 cyc (`sub r8,r8` 17.6 cyc / 8.0); segment
  forms (`mov`/`push`/`pop` sreg, `les`/`lds`) 2.0%, 24.8 cyc.
- **Shape.** Price per form; shorter AH/BH access sequences; segment base
  recomputation only when the base register is used before the next load.
- **Prize.** Price per form; build only forms ≥ 1% of P.

### T9. Re-profile

After T2–T8: fresh capture, re-price every group of §4 and any new
candidate ≥ 1% of P as a new step here (T10 …). Repeat until no candidate
of ≥ 1% of P remains.

## 5. Rejected and not built

(One line each: step, change, priced, measured, reason.)

- T2: guarded block duplication, priced 1.19% of P; executable +27.14%,
  generated text +21.65%; reverted for size before timing, boundary coverage retained.

## 6. When the translator work is done

When T9 finds no candidate ≥ 1% of P: write the final numbers into §1,
update open-work 14b, and report to the user with the remaining gap and
the profile's top routines (T1 attribution). Then **stop**. Native
replacement of hot routines (§2.1) is the user's decision, routine by
routine; the agent may list candidates with their shares, nothing more.
