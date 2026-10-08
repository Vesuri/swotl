# Translator speed plan, round 2 (phase 7b)

Work order for making the generated code faster. An implementing agent
follows it literally, one step at a time. Round 1 (T1–T15) is in git
history at `781975e`; this file replaces it. [speed-plan.md](speed-plan.md)
§0 applies, except that §4 here replaces its per-step acceptance (§0.7–0.8).
Open-work item: 14b.

## 1. Target and state

- **Bar (user, 2026-10-07):** a 14 MHz 80286's frame rate on the 68020 +
  8 MB Fast model (`AMIGA_CPU` unset): frames 4–11 median ≤ 12 fields
  (240 ms); stretch ≤ 10.
- **HEAD `781975e`** (executable unchanged since `596b337`): run medians
  24.5, 24.5, 24.5 (round-1 final audit) and 28.5 (replan capture
  2026-10-08: intervals 29, 26, 36, 26, 31, 26, 32, 28). One executable;
  the spread is trajectory noise (§2.1).
- **Replan capture** (100 fields, 28,420,396 cycles): generated code
  85.97%, runtime/platform 9.29%; 1,668,895 guest instructions; 14.64
  cycles, 4.0 68k instructions and 9.87 execution-weighted static code
  bytes per guest instruction. Code payload 1,325,164 bytes.
- **Round 1:** kept T3 (block-local byte order), T4-local (carry in X),
  T6 (masks), T10, T11; rejected T2 (size), T4 cross-block, T7, T8,
  T12–T15; T5 not built. Cycles/guest 15.65 → 14.6–15.0, code payload
  1,364,372 → 1,325,164 bytes; frame medians 26–30 → 24.5–28.5.

## 2. Why round 1 stalled (do not repeat)

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
   image). That contract is where the cost is (§3): a 19.9% group yielded a
   1.19% candidate, and T10–T15 0.0007–0.07% each.
4. **The 1% threshold** deferred T3/T5 and drove the narrowing. Removed by
   the user (2026-10-08): every speed or size improvement is welcome.
5. **Wrong cost unit.** Steps were priced in 68k instructions; on this
   model the cost is code bytes and data accesses (§3).

## 3. Cost model and where the cycles are

Per-PC fit on the replan capture (13,608 non-branch PCs, 5.5M executions):
**cycles ≈ 1.09 × code bytes + 2.27 × data reads + 3.07 × data writes**
(R² 0.83). Outside the 256-byte i-cache a 2-byte register op costs ≈ 2
cycles, 4 bytes ≈ 4, `and.l #$ffff` (6 bytes) ≈ 6. Inside cached loops
(28.5% of time, the cell walk 12.8%) bytes are nearly free. Price and
accept in executed bytes, data accesses and taken branches, never in
instruction counts. FS-UAE is the user's instrument; a real 68020 may
weigh these differently.

| Cost (share of all CPU) | Share | Per 100 fields | Static |
|---|---:|---:|---:|
| Cell walk (D16), run-time matching | 13.20% | 1.30M 68k insns | — |
| Byte swaps `ror/rol.w #8` + store copies | 5.69% + 0.68% | 890K + 107K | 61,517 sites, 123 KB |
| 16-bit wrap arithmetic (copy + add before an indexed access) | 1.55% + 3.54% | 211K + 288K | — |
| Poll points (`tst.b G_IRQ`, `beq`) | 1.77% + 1.46% | 90K | 2,095 |
| Flag image (spill, reload, `ori #4,ccr` for adc/sbb ZF) | 1.60% + 0.55% + 0.93% | 64K spills | 2,446 spills |
| SI/DI address-register shuffles | 2.06% | 296K | 28 KB |
| Upper-word masks `and.l #$ffff` | 1.64% | 78K | 2,464 |
| Accesses at disp ≥ 8000h (8-byte `bd.l` form) | 1.68% | 44K | 10,924 |
| Return checks (`cmp`, 6-byte `bne.l`) | 1.28% | 72K | 11,324 |
| `jsr`/`bsr`/`rts` | 2.40% | — | — |
| Runtime: `rt_lookup` (646 cycles per delivery lookup), VRAM marks, interrupt path | 1.16%, 1.85%, ≈2.5% | 510 lookups | — |
| Guest data accesses themselves, indexed / d16 (inherent) | 12.62% / ≈8% | — | — |

Guest register use (executions per 100 fields): SP 243K (92% implicit
push/pop/call/ret), BP 236K (65% base+disp), BX 242K (33% ALU destination,
32% base), SI 216K and DI 131K (34–41% base, 30–36% ALU).

## 4. Authority and acceptance

Hard rules; breaking one voids the step:

1. **No native replacement of any guest routine** (HLE, G3 entries,
   hand-written 68k or C doing a guest routine's work, pattern-matched
   intrinsics), however small, until the user authorizes that routine in
   the conversation. Nothing in this file, open-work, a profile or "the
   translator work is done" is an authorization.
2. **No exactness shortcuts:** every fast path is guarded by its exact
   condition with an exact fallback; no dropped return check, poll point,
   fail-loud stop, wrap handling or live flag; no "never seen" assumption;
   no annotation asserting what the translator must prove.
3. **The frame fixture is unchanged:** CPU model, Fast RAM, FS-UAE options,
   fixture, game data and settings, warp and speed.
4. **D16:** every cell is matched at run time against the writer forms
   from the guest RAM bytes, except through R7b's cache (D3), which is used
   only while its exact validity condition holds.
5. **No test edits that make a step pass.** R1's representation change
   (D1) may change how the harness maps memory and registers,
   never what is compared; every corpus case, reference and comparison
   stays. A plant is retired only with the template it targets, after an
   equivalent plant on the new template is in place and caught.
6. **No unmeasured claims.** Numbers in commits and docs come from runs in
   the same session.

**Acceptance (D0, user 2026-10-08: any speed or size improvement is
welcome):**

- Gates green: `make test`, `make test-sabotage`, `make test-host-all`,
  `make test-amiga`, `make smoke`.
- **Meter (M1) on the m4 window:** model cycles lower; or equal
  (|Δ| < 0.001%) with a smaller code payload. Report Δ model cycles,
  Δ executed code bytes, Δ data reads/writes, Δ code payload. No minimum gain.
- **Code growth** only with lower model cycles (D2). Stop and ask before
  the payload exceeds 1,325,164 bytes by more than 25% (open-work 19).
- **FS-UAE check** after every third kept step and after R1, R6, R7 and
  R7b: an M2 bench run per arm with a capture; the meter's Δ must have the
  sign of `ab_labels.py`'s mix-adjusted Δ over the changed labels. If they
  disagree, stop: fix the meter, never tune lowerings to FS-UAE noise.
  Report the bench's cycles per drawn frame (it includes layout effects).
- **Frame-rate claims:** M2 bench for build-to-build progress; the target
  itself is the frames fixture (three runs, with the interval lists),
  measured after R1, R6, R7b and R11. Neither is a per-step gate.

**Stop and ask the user** when: a gate fails for a reason that is not a
plain bug; a step needs any of 1–5 beyond what was approved; references
need re-recording or an interrupt delivery moves; two consecutive steps
are rejected by the meter; meter and FS-UAE disagree; a step is ambiguous.

**Per step:** price from M1 counts (write the price in §5 before coding);
coverage first (cases appended at the end of corpora, guard edges, a
deliberately broken version seen to fail, a new plant `make
test-sabotage` must catch, `m68k_blocks` cases for multi-block changes);
implement in `translator/` or `src/runtime/`, `make gen`; gates; meter;
keep or revert (revert keeps the passing new tests; one line in §8); one
commit with the numbers, §5 and open-work 14b updated; report in a few lines.

## 5. Steps (in order; prices are replan estimates, re-price with M1)

### M1. Deterministic cost meter (tooling)

- `tools/cost_meter.py MILESTONE`: host run (`tests/host_run.py`,
  reference interrupt replay) over the m4 window. Unicorn block hooks count
  executions per translated block and the taken transfers; expand to
  per-instruction counts from the disassembly of the image that ran.
  Features per instruction: encoded bytes, data reads, data writes, taken
  branch, inside an innermost loop of ≤ 256 bytes, mul/div. Output: guest
  instructions, executed 68k instructions, executed code bytes, reads,
  writes, taken branches, model cycles; per x86 form and per label; code
  payload (`make size`). Deterministic and layout-blind by design.
- `--calibrate CAPTURE ELF`: fit the coefficients on an FS-UAE capture of
  the same build (per-PC cycles); print R² and model vs measured
  generated-code total. Commit the coefficients (`tools/cost_model.json`)
  with the capture's commit.
- Before use: two meter runs identical; model total within 3% of the
  capture; retro-check on round 1: meter Δ for T6 (`fd8ed6e`) and
  T4-local (`f7dad4b`) against their parents has the sign and order of
  the mix-adjusted FS-UAE results (−2.2%, −6.2%); a flag-neutral doubling
  plant (each `ror.w #8` → three) moves the model by its predicted amount.
- `tools/ab_labels.py`: FS-UAE mix-adjusted A/B (per-label cycles per
  execution, weighted by the meter's counts) for the §4 checks and R8.
- Gate: `make test` with unit tests for both tools.

### M2. Deterministic frame bench (D4)

- **What it is:** a bench mode of the Amiga runtime, selected at startup
  and never active in release or fixture runs. PIT ticks are posted on a
  fixed schedule tied to guest progress, not to the CIA timer, so every
  build does the same guest work. Ticks are still delivered at poll points
  as today.
- **Schedule:** follow the reference cadence (m4: a drawn frame every 9 PIT
  ticks at the guest's programmed rate). Disk I/O must not leak host time
  into the window.
- **Output:**
  - Emulated cycles (fields and beam position) for drawn frames 4–11 and
    for a 100-field capture window.
  - A guest-RAM hash at the end. Equal hashes prove both arms did the same
    work (perf-method §4).
- **Checks:**
  - Two runs give identical numbers.
  - The bench is independent of the start field.
  - The guest never waits for a tick that cannot come. If it would, stop
    and report the schedule problem; never patch the guest.
- Guest semantics are unchanged; only the timing of interrupts moves
  (speed-plan §0.9 exception).

### Q. Round-1 candidates under the meter

T8 (BFINS high-byte writes; patch `tmp/t8-session/rejected-lowering.patch`)
and T7 (dead DX; `tmp/t7-session/`): re-apply, gates, meter. Their coverage
and plants are already in the tree. T12–T15 are superseded by R1 and R6.

### R1. Memory model v2 (D1)

Exact by construction:

- **Reversed guest memory:** guest byte at linear L lives at host TOP − L.
  A little-endian guest word or dword is a native big-endian word/long at
  TOP − L − 1 / TOP − L − 3. No byte swaps anywhere; unaligned is legal.
- **Biased segment bases:** aS = TOP − 16·seg − 7FFFh. `[disp]` is
  `(7FFFh − disp, aS)` for bytes and `(7FFEh − disp, aS)` for words:
  always d16, no `bd.l`.
- **Mirrored index registers with `.w` indexing:** an index holds
  off XOR 7FFFh (= 7FFFh − off mod 2^16) in its low word; `(d8,aS,Xn.w)`
  reads only the low word, so no register needs a zero upper word for
  addressing.
- **Which registers are mirrored:** SP and BP always; SI and DI by the R1c
  census; BX native.
  - Push is `addq.w #2,d4` then `move.w v,(-1,a2,d4.w)`; pop is the mirror.
  - `[bp]`, `[si]` and `[di]` are direct.
  - add/sub/inc/dec on a mirrored register with dead flags is one
    instruction on the low word. That includes address registers:
    `subq.w #1,a4` is `inc si`.
  - Where the native value is needed (live flags, moves to native
    registers, pushing the register itself), the lowering copies it and
    applies `eori.w #$7fff`.
- **Displaced and native indexes:** mirrored + disp is `move.w Rn,d7`
  then `sub(q).w #d,d7`, which keeps the exact 16-bit wrap (R6 removes it
  under guards). A native register as index is `move.w #(7FFFh−d),d7`
  then `sub.w Rn,d7`.
- **Today's semantics at every offset,** including word accesses at FFFFh,
  segment wrap and the HMA.
- **Strings (D11):**
  - Forward operations descend in host memory: `move.w -(Ay),-(Ax)` and
    `move.w d,-(Ax)`.
  - Forward CMPS/SCAS have no CMPM form, so they use a compare loop with
    an exact first mismatch and exact flags.
  - The guards are the same as today.
- **Folded memory operands** where flags allow: `add.w mem,dN`,
  `cmp.w #i,mem`, `subq.w #1,mem`.
- **Runtime:** every guest memory access goes through one accessor set
  (byte, word, dword, block copy, fill). That covers DOS file I/O,
  PSP/MCB/environment, the IVT, EMS page copies, interrupt frames, the
  VGA present (rows reversed on read) and the D16 walk.
- **Harness (D1):**
  - `m68k_diff`, `m68k_blocks`, `host_run` and `host_census` map guest
    memory reversed and convert mirrored registers at case entry and exit.
  - DOSBox reference comparisons read through the same conversion.
  - No comparison is weakened.
- **Sub-steps, each kept on its own meter result:**
  - R1a: runtime accessors only (generated code unchanged; gates).
  - R1b: reversed memory with biased bases and mirrored SP/BP. This is
    the switch itself and cannot be split further.
  - R1c: SI/DI mirrored, if the census prices it positive.
  - R1d: folded memory operands.
- **Coverage:**
  - Every addressing form at offsets 0, 1, 7FFEh, 7FFFh, 8000h, FFFEh and
    FFFFh, with disp ±1, ±7Fh and ±8000h.
  - Push/pop at SP 0, 2 and FFFEh.
  - Mirrored arithmetic with live and dead flags at 0, 7FFFh, 8000h and
    FFFFh.
  - New plants: TOP off by one, wrong mirror constant, missing native
    conversion before a flag-live op, unbiased segment base.
- **Price:** ≈ 9–11% of CPU (swaps 5.7, copies 0.7, SI/DI shuffles ≈ 1.5,
  masks ≈ 0.8, `bd.l` ≈ 0.7, folding ≈ 0.8, spills ≈ 0.4, minus
  conversions ≈ 1). Static code shrinks by ≈ 10–15%.
- Precedent for the biased base and `.w` index: Vette's C2P tables
  addressed from their midpoint ([m68k-optimisation.md](m68k-optimisation.md) §2).
- R1b updates `translator-design.md` (register contract, D11) in the same
  commit.

### R2. Poll points: same points, cheaper form

The IRQ byte becomes reachable by a 2-byte `tst.b (An)`, and the branch is
inverted so the common case falls through: `bne` to an out-of-line stub at
the function or module tail, which calls `rt_irq` and returns to the poll
point. `poll-points.csv` stays identical. Price ≈ 1–1.3% (3.23% now; a
taken `beq.s` costs 4.6 cycles). Plant: the stub returns to the wrong point.

### R3. Flags

- adc/sbb skip `ori.b #4,ccr` when ZF is dead (64K executions).
- **N/Z provenance:** a later move of the last flag result (a plain store
  after R1) leaves N and Z equal to SF and ZF.
  - SF/ZF-only readers use the CCR.
  - The producer drops its `G_FL` spill when no reader needs the image.
  - CF/OF/PF/AF readers still get the image.
- Price ≈ 1–1.5% (spill 1.60, reload 0.55, ori 0.93).

### R4. Zero-extension only where consumed

After R1, addressing reads only low words. The translator tracks where a
guest register's 32 bits are consumed (`mulu`/`divu` operands, `.l`
operations, runtime entries) and cleans the register there. The remaining
`and.l #$ffff` masks and the `moveq #0` before loads go. Price ≈ 0.8–1.2%.

### R5. Calls, returns, dispatch

- **Return check:** the 6-byte `bne.l rt_ret_mismatch` becomes
  `bne.s`/`bne.w` to a module-local trampoline.
- `jsr abs.l` becomes `bsr.w` where it reaches.
- ret drops its `moveq #0,d7` where the mismatch path doesn't need it.
- **`rt_lookup` on interrupt delivery:** cache the CS:IP → entry result per
  vector, invalidated on IVT writes and module loads (runtime surface).
- Price ≈ 1.5–2%.

### R6. Wrap-free register-relative accesses under region guards (D2)

- **Region:** a function body after `mov bp,sp` for BP, or a loop for
  SI/DI/BX, over which the register is unchanged.
- One exact guard at region entry covers the region's displacement range.
  Accesses then use `(d8,aS,Rn.w)` directly. A failed guard runs the exact
  region (today's code).
- The profile chooses which regions get a guarded copy, within the size
  budget. The choice never affects correctness.
- **Coverage:** the 2,133 retained T2 boundary cases, region entries from
  every kind of predecessor, guard edges. Plant: guard off by one.
- Price ≈ 2.5–3.5% (wrap arithmetic 5.09% now).

### R7. Cell walk, run-time matching kept

- The matching is unchanged: forms are read from guest RAM at execution
  time.
- The shape gets cheaper:
  - One bound check per entry and per kind change (whole cells left to
    the region end) instead of one per cell.
  - One long read per form-0 cell yields opcode and operand (native after
    R1).
- This is S5's direction, now judged by the meter. Price ≈ 3–4% (13.2%
  now, ≈ 32 cycles per cell).

### R7b. Cell cache (D3)

- **What is cached:** each decoded cell (kind and operand) at its walk
  position. Walks reuse it while no write can have reached the walk region
  since decoding. A dirty or bypassed cache runs R7's matching walk, which
  decodes again.
- **Exact invalidation covers every write path:**
  - generated stores through DS, ES and SS, including string ops and
    interrupt frames;
  - runtime writes (DOS reads, EMS copies, all R1a accessors);
  - the walk's own DS reload cells.
- **Candidate mechanism, segment-window gating:**
  - Loading a writable segment register whose 64 KiB window overlaps the
    region marks the cache dirty.
  - The cache is bypassed while any writable segment register overlaps it.
  - Runtime accessors mark writes that overlap the region.
  - A segment load proven not to overlap (a constant, or a copy of a
    checked register) skips the check.
  - Any other mechanism must cover the same paths.
- **Price:** walk ≈ 9–10% of CPU after R7 → ≈ 3%, minus the gating cost
  on segment loads (≈ 45K per 100 fields): ≈ 5–7% net. Re-price with M1,
  gating included.
- **Coverage:**
  - Walk snapshots (`make test-blocks`) hitting the cache.
  - Writes into the region between walks, through each segment register
    and through the runtime.
  - DS reload cells whose window overlaps the region.
  - Plants: the gating check skipped on one segment load; an accessor
    that doesn't mark.
- Update `translator-design.md` D16 in the same commit.

### R8. Branch-target alignment

Price it from a capture's PC sequence: taken branches by target alignment
and their cost difference. If that is positive, align the hot targets
(`cnop 0,4`), chosen by profile within the size budget. The meter is
layout-blind, so this step alone is accepted by `ab_labels.py`, with three
captures per arm.

### R9. Multiply/divide

DX extraction without `clr.w` and masks once R4 allows dirty upper words.
Price ≈ 0.5%.

### R10. Runtime surface

- VRAM marks (`vram_span`, `rt_vram_mark`: 1.85%).
- The interrupt path (`rt_irq_c`, `push_frame`, `deliver`, `guest_vector`,
  flags words ≈ 2.5%): vector bounds cached per IVT write, the flags word
  in asm.
- Port output (SPAZ OPL ≈ 0.75%).
- "No PC" (2.72%, outside the executable and ROM): identify it before
  pricing.
- Price ≈ 1–2%.

### R11. Re-profile

Fresh capture and recalibration, then re-price every row of §3. Repeat
from the top while the meter finds a gain.

## 6. User decisions (approved 2026-10-08)

- **D0.** Per-step acceptance by the meter (§4), instead of FS-UAE frame A/B.
- **D1.** R1's memory model, with the harness converting memory and
  registers. Plants whose templates R1/R4 remove are replaced first, then
  retired: "word loads not byte-swapped", "ror for ror.w on memory dest",
  "native word store skips byte swap", "native byte-order restoration
  omitted", "address word not restored", "stack pointer not restored",
  "address restoration copies stale scratch", "SP not 16-bit", "RETF CS
  pop uses linear SP", "mask trusts dirty upper word".
- **D2.** R6 may grow the code beyond +5% when each guarded copy lowers
  model cycles; the +25% stop in §4 remains.
- **D3.** Cell cache (R7b) with exact invalidation.
- **D4.** Deterministic frame bench (M2).
- Native replacement is not part of this plan (§4.1).

## 7. Projection

R1–R10 with R7b ≈ 28–34% of CPU: from 24.5 fields to ≈ 16–18
(320–360 ms). The 12-field target needs ≈ 50% less time than today.
Translation alone is not expected to get there: the remaining generated
code would still cost ≈ 10 cycles per guest instruction (≈ 6–7 code bytes
and ≈ 1.3 data accesses each), against the 80286's ≈ 6 clocks. At R11,
report the gap and the top routines. Native replacement stays the user's
decision, routine by routine.

## 8. Rejected and not built

(One line each: step, change, meter Δ, reason. Round 1 is in git history
at `781975e` and §2.)
