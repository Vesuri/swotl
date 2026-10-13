# Speed plan (phase 7)

Rules, measurement and work order for all speed work on the A1200 build.
An implementing agent follows it literally, one step at a time. Finished
work is in git history: S0–S6, and round 1 (T1–T15) at `781975e`. Method
background: [perf-method.md](perf-method.md). Open-work item: 14b.

## 1. Target and state

- **Bar (user, 2026-10-07):** a 14 MHz 80286's frame rate on the 68020 +
  8 MB Fast model (`AMIGA_CPU` unset): frames 4–11 median ≤ 12 fields
  (240 ms); stretch ≤ 10.
- **HEAD `781975e`** (executable unchanged since `596b337`): run medians
  24.5, 24.5, 24.5 (round-1 final audit) and 28.5 (replan capture
  2026-10-08: intervals 29, 26, 36, 26, 31, 26, 32, 28). One executable;
  the spread is trajectory noise (§5.1). Frames fixture (§4, 2026-10-10,
  3 runs each): medians 25, 25, 25 at `420d81b` (before R1), 24, 24, 24
  at `c6a7de1` (R1d); 2026-10-11: 23, 23, 23.5 at R5 (`714d61e`), 23,
  22.5, 23 at R6; 2026-10-12: 24, 21.5, 22 at R8; 2026-10-13: 20, 20,
  20 at R10 (`570ec2d`; sums 177–178) against 20.5, 20.5, 20.5 at R9
  (sums 179).
- **Bench** (§4): frames 4–11 mean 37.74 fields (5.36M cycles) at
  `b9b6374`, 37.56 at `63a99fe` (R1a), 34.41 (4.89M cycles) at R1b, 33.69
  at R1d, 33.37 at R3a, 33.27 (4.73M cycles) at R3b, 31.74 at R5, 29.67
  at R6, 74,336 → 74,373 lines at R7 (no walk in its window), 74,318 →
  74,096 lines at R8, 72,773 → 72,506 at R10 (R9 control; means of 3);
  window 2.20M guest
  instructions, SPAZ 0.22%.
- **Meter after R12** (m4, 49 frames; weights recalibrated at R11, §4):
  226,316,665 model cycles (generated 174.6M, cell walk 49.2M, runtime
  2.4M); 17,976,252 guest instructions, 12.45 model cycles each (generated
  + walk); R11 238,748,828, 240,644,109 under the R1 weights; R1 292,676,869 under them
  (275,119,407 under the first weights). Round 2 kept (first weights): T8 −0.242%, T7 −0.005%, R1a −0.0001%, R1b
  −1.916%, R1d −1.231%; (R1 weights) R2 −1.029%, R3a −0.991%, R3b −0.188%,
  R4 −2.646%, R5 −2.036%, R6 −1.213%, R7 −9.037%; R8 0 (layout only:
  bench −0.30%); R9 −1.615%; R10 −0.299%; (R11 weights) R12 −5.207%.
- **Replan capture** (100 fields, 28,420,396 cycles): generated code
  85.97%, runtime/platform 9.29%; 1,668,895 guest instructions; 14.64
  cycles, 4.0 68k instructions and 9.87 execution-weighted static code
  bytes per guest instruction. Code payload 1,325,164 bytes.
- **R11 capture** (frames fixture at R10, 100 fields): generated code
  90.58%, runtime/platform 6.04%, no PC 1.45%; 1,604,428 guest
  instructions, 16.05 cycles each (the window's mix: the cell walk of
  SWOTL.EXE+06A4D is 16.9%).
- **Round 1:** kept T3 (block-local byte order), T4-local (carry in X),
  T6 (masks), T10, T11; rejected T2 (size), T4 cross-block, T7, T8,
  T12–T15; T5 not built. Cycles/guest 15.65 → 14.6–15.0, code payload
  1,364,372 → 1,325,164 bytes; frame medians 26–30 → 24.5–28.5.

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
4. **D16:** every cell is matched at run time against the writer forms
   from the guest RAM bytes (R7b's cache, D3, not built: §10).
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
10. **One step, one commit**, before/after numbers in the message, §7 and
    `docs/open-work.md` 14b updated in the same commit. Do not start the
    next step on an unproven one.

## 3. Acceptance (D0, user 2026-10-08: any speed or size improvement is welcome)

- Gates green (§2.5).
- **Meter (§4) on the m4 window:** model cycles lower; or equal
  (|Δ| < 0.001%) with a smaller code payload. Report Δ model cycles,
  Δ executed code bytes, Δ data reads/writes, Δ code payload. No minimum gain.
- **Code growth** only with lower model cycles (D2). Stop and ask before
  the payload exceeds 1,325,164 bytes by more than 25% (open-work 19).
- **FS-UAE check** after every third kept step and after R1, R6, R7 and
  R8: a bench run (§4) per arm with a capture; the meter's Δ must have the
  sign of `ab_labels.py`'s mix-adjusted Δ over the changed labels. If they
  disagree, stop: fix the meter, never tune lowerings to FS-UAE noise.
  Report the bench's frames 4–11 cycles (they include layout effects).
- **Frame-rate claims:** the bench (§4) for build-to-build progress; the
  target itself is the frames fixture (§4, with the interval lists),
  measured after R1, R6, R8 and R11. Neither is a per-step gate.

**Stop and ask the user** when: a gate fails for a reason that is not a
plain bug; a step needs any of §2 beyond what was approved; references
need re-recording or an interrupt delivery moves; two consecutive steps
are rejected by the meter; meter and FS-UAE disagree; a step is ambiguous.

**Per step:** price from meter counts (write the price in §7 before coding);
coverage first (§2.6; cases appended at the end of corpora, `m68k_blocks`
cases for multi-block changes); implement in `translator/` or
`src/runtime/`, `make gen`; gates; meter; keep or revert (revert keeps the
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
  1.1 GB: delete it after the report.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop. Per drawn
  frame (m4): `repe cmpsw` `VGA_03BE9` 19,290 words (the whole view vs the
  previous frame), `rep stosw` `R_0C1CA` 16,075 words, `rep movsw`
  `VGA_03C2D` 151 words to A0000h (median 6 rows).
- **Reference cadence** (DOSBox-X `cycles=fixed 12000`, m4): a drawn frame
  every 9 PIT ticks ≈ 36 ms, ≈ 408K x86 instructions per frame.
- **Meter** (`tools/cost_meter.py`, ≈ 40 s, deterministic): `--out
  tmp/meter/ARM.json` per arm, `--compare A B` for the §3 deltas. Weights
  `tools/cost_model.json`, fit at R11 on the bench's 100-field capture of
  `570ec2d`: per code byte 0.90 cycles (0.93 inside a loop of ≤ 256
  bytes), read 2.40, write 3.27, taken transfer 4.13 outside such a loop
  and 3.51 inside, mul/div 23.3 (R² 0.915, model −5.0% of measured; the
  other two captures of the arm give the same weights to ±0.06; the R1
  weights, fit on `c6a7de1`, give 0.904 and −1.4% there). It
  underrates removed instructions (bench vs meter: R1b −8.4% vs −1.9%,
  R1d −2.1% vs −1.2%; the per-instruction weight fits to 0). Recalibrate
  (`--calibrate CAPTURE ELF --write`, then `--plant-check`) at the next
  re-profile or when the FS-UAE check disagrees. Retro-check on round 1: T6 −0.39%, T4-local −6.05% (FS-UAE
  mix-adjusted −2.2%, −6.2%). `tools/ab_labels.py` serves the FS-UAE check.
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
(28.5% of time, the cell walk 12.8%) bytes are nearly free. Price and
accept in executed bytes, data accesses and taken branches, never in
instruction counts. FS-UAE is the user's instrument; a real 68020 may
weigh these differently.

Replan column: share of all CPU in the replan capture (`781975e`). R11
column: share of the meter's model cycles (m4, R11 weights, `570ec2d`),
by the 68k instruction's role (`tmp/` census over the meter's per-PC
counts; profile_report's role column still matches the old poll and state
block forms).

| Cost | Replan | R11 meter | R11 executions (m4) |
|---|---:|---:|---:|
| Cell walk (D16), run-time matching | 13.20% | 20.63% | — |
| Byte swaps `ror/rol.w #8` (+ store copies) | 5.69% + 0.68% | 0.47% | 609K |
| Index formation in d7 (`move.w #7FFFh−d,d7` + `sub.w Rn,d7`; mirrored + disp) | 1.55% + 3.54% | 4.04% | 1.96M `move.w #N,d7` |
| Poll points (`tst.b G_IRQ(a6)`, `bne`) | 1.77% + 1.46% | 3.52% | 980K |
| Flag image (CCR to and from G_FL, state block flags) | 1.60% + 0.55% + 0.93% | 2.28% | 583K spills |
| Stack accesses `(d,a2,d4.w)` + SP steps `addq/subq.w #2,d4` | — | 2.95% + 0.88% | 2.0M steps |
| SP/BP mirror conversions `eori.w #$7fff` | — | 0.53% | — |
| SI/DI address-register shuffles | 2.06% | (in index formation) | — |
| Upper-word masks `and.l #$ffff` | 1.64% | 0.00% | — |
| Accesses at disp ≥ 8000h (`bd.l`) | 1.68% | none (R1b: always d16) | — |
| Return checks (`cmp.w #ip,d7`, `bne` to the trampoline) | 1.28% | 0.72% | — |
| `jsr`/`bsr`/`rts`/`jmp` | 2.40% | 1.32% | — |
| Segment fields (DS/SS/ES in the state block) | — | 0.85% | — |
| mul/div | — | 4.71% | 399K `mulu.w`, 45K `divu.w` |
| `repe cmpsw` (the view vs the previous frame) / `rep stosw`; their loop bodies | — | 6.57% / 4.53%; 6.21% / 4.38% | 7,840 / 6,225 runs, 953K / 850K words |
| Runtime | 1.16%, 1.85%, ≈2.5% | 1.02% (capture: 6.04%) | — |
| Other memory ops / register ops / branches outside cached loops | 12.62% / ≈8% | 11.68% / 7.03% / 3.47% | — |
| Other code inside cached loops (loop bodies) | — | 23.19% | — |

The meter's runtime is the host run's (the reference's interrupts
replayed); the frames capture adds the CIA timer at its own rate (1,032
`rt_irq` per 100 fields: `rt_irq_c` 1.09%, `rt_lookup` 0.54%, `present`
0.37%).

Guest register use (executions per 100 fields): SP 243K (92% implicit
push/pop/call/ret), BP 236K (65% base+disp), BX 242K (33% ALU destination,
32% base), SI 216K and DI 131K (34–41% base, 30–36% ALU).

## 7. Steps (in order; prices are replan estimates, re-price with the meter)

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
  - R1a: runtime accessors only (generated code unchanged; gates). Price:
    meter Δ ≈ 0 (runtime code only), payload unchanged. Kept: −381 model
    cycles (−0.0001%), runtime +16 bytes.
  - R1b: reversed memory with biased bases and mirrored SP/BP. This is
    the switch itself and cannot be split further. Price (census of
    `63a99fe`): ≈ 4–5%: swaps 5.7 (`ror.w #8` 9.55M executions), `bd.l`
    ≈ 0.7, walk ≈ 1–2, minus native indexes without displacement ([bx],
    [si], [di]: 0.74M executions, +6 bytes) ≈ 1.4 and SP/BP as values
    (≈ 1M executions) ≈ 1.3. Kept: −1.92% (generated −5.75M: swaps
    −15.2M, native-index mirrors and SP/BP conversions back +; CMPS loop
    +1.6M, BP as a data register (`or bp,cx` chains) +1.7M, walk ±0: the
    model charges bytes, and its cells keep their size; runtime +0.34M,
    the present's row copy), static code −156 KB (−12%). FS-UAE check:
    bench frames 4–11 37.56 → 34.41 fields (−8.4%, equal RAM at frame
    12), `ab_labels.py` −10.6% on the 8,009 changed labels: same sign,
    but the meter underrates removed instructions (recalibrate after
    R1, §4). Display audit 40/40. Candidate:
    REPE CMPS comparing longs (half the reads), with exact first-mismatch
    and guards.
  - R1c: SI/DI mirrored, if the census prices it positive. Census of
    R1b (meter labels × byte deltas): −1.0% (direct [si]/[di]
    +2.3M, inc/dec and string updates +1.6M; SI/DI as data: mov, push/pop,
    xor/or/cmp/shl … −5.9M, [bp+si/di] −0.6M): skipped.
  - R1d: folded memory operands. Price (census of R1b): ≈ 1.2%: word
    sources of register ops (0.72M executions, −2 bytes), word
    read-modify-writes, INC/DEC/NEG/NOT and CMP with an immediate in place
    on memory (0.37M, −4–6 bytes); where AF and PF are dead, as for bytes.
    Kept: −1.231% (−3,428,504 model cycles, all generated code), static
    code −28,466 bytes (−2.5%). FS-UAE check: bench frames 4–11 34.41 →
    33.69 fields (−2.1%, equal RAM), `ab_labels.py` −2.75% (−21.8% on the
    759 changed labels).
  - R1 done. Frames fixture against `420d81b` (3 runs each): medians 25,
    25, 25 → 24, 24, 24 fields (500 → 480 ms per drawn frame), frames
    4–11 sums 184–185 → 178–179; ranges apart. Meter recalibrated (§4).
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
  addressed from their midpoint (AmigaXDev `docs/reference/m68k-optimisation.md` §2).
- R1b updates `translator-design.md` (register contract, D11) in the same
  commit.

### R2. Poll points: same points, cheaper form

The IRQ byte becomes reachable by a 2-byte `tst.b (An)`, and the branch is
inverted so the common case falls through: `bne` to an out-of-line stub at
the function or module tail, which calls `rt_irq` and returns to the poll
point. `poll-points.csv` stays identical. Price ≈ 1–1.3% (3.23% now; a
taken `beq.s` costs 4.6 cycles). Plant: the stub returns to the wrong point.
- Re-price (census of `58aae32`, m4: 979,570 executions of 276 poll points,
  2,094 in all): no free address register after R1 (a1–a3 bases, a4/a5
  SI/DI, a6 TOP), so the test stays `tst.b G_IRQ(a6)`; the stub sits after
  the end of its run (an unconditional transfer) and branches back to the
  poll. Meter: −0.5 to −1.8% with `bne.s` in reach (inside / outside
  ≤ 256-byte loops), +0.1 to −1.2% with `bne.w`; 68020: −2 cycles per poll
  with `bne.s` (taken `beq.s` 6, untaken `bne.s` 4), none with `bne.w`;
  18 bytes per poll point leave the loop body.
- Kept: −1.029% (−3,011,696 model cycles): taken transfers −467K, 12.6M
  executed bytes now inside ≤ 256-byte loops; static code +8,398 bytes
  (+0.8%). `bne.s` reaches its stub for 1,110 of 2,094 poll points, 71.9%
  of executions (all of the five hottest).

### R3. Flags

- R3a: adc/sbb skip `ori.b #4,ccr` when ZF is dead (64K executions).
  Kept: −0.991% (−2,869,993 model cycles: 728K presets in m4), static
  code −4,606 bytes; 6 presets left. Coverage: ADC/SBB boundary cases
  (1,320); plant: the preset dropped while ZF is live.
- R3b, N/Z provenance: the setter's flags reach a fusing reader in the
  CCR across plain instructions (`flags.py`). Lines that keep the CCR keep
  every flag. A move of the setter's result, at its width and unchanged
  since, leaves N and Z equal to SF and ZF. Anything else ends the chain.
  The setter stores only what is live after the reader.
  - Price ≈ 1–1.5% (spill 1.60, reload 0.55, ori 0.93). Re-price (census
    of `0aa7480`, m4: 652,585 spill executions): ≈ −0.19%, 18 sites.
  - Kept: −0.188% (−538,088 model cycles: 39,710 spills and 39,710
    reloads), static code −140 bytes. Coverage: setter, plain
    instructions, reader of ZF, SF, CF or SF^OF (9,648 boundary cases).
    The plain instructions are moves of the result and near misses.
    Plant: N/Z trusted after a move of another value.
  - FS-UAE check: bench frames 4–11 83,538 → 83,308 lines (33.37 → 33.27
    fields, equal RAM at frame 12), `ab_labels.py` −0.48% (−51.3% on the
    24 changed labels); same sign as the meter.
  - Candidates left: 329K spills sit right before a fused reader with flags
    still live after it. For about 210K of them the next reader is a second
    `jcc`, reached by fall-through. Another 150K keep CF for an `adc`/`sbb`
    (failed carry pairs, CF across moves).

### R4. Zero-extension only where consumed

After R1, addressing reads only low words. The translator tracks where a
guest register's 32 bits are consumed (`mulu`/`divu` operands, `.l`
operations, runtime entries) and cleans the register there. The remaining
`and.l #$ffff` masks and the `moveq #0` before loads go. Price ≈ 0.8–1.2%.

- Contract (user 2026-10-10): no guest register's upper word is defined. The
  68k and block differentials seed each one (0, FFFFh or random) at case
  entry and compare low words; their upper-word-0 checks go.
- Consumers of 32 bits: segment loads (`moveq #0` + `move.w`), the REP
  fast path's guards and pointers, the cell walk's entry IP (`call dx`).
  The runtime already masks what it takes.
- Re-price (census of `ea2cf7b`, m4: masks 959K executions, 1.94%;
  `moveq #0` 1.03M, 0.70%): ≈ −2.6% (7.8M executed bytes).
  - SI/DI loads and pops as `movea.w` (484K + 128K, −8 / −6 bytes).
  - Dead-flag add/sub/inc/dec and string updates on a4/a5 in place
    (614K, −4 to −6 bytes).
  - Segment reads straight into their word destination (95K, −4).
  - Segment loads cleaned by `moveq #0` (100K, −4).
  - Back: segment loads from data registers and `call dx` (+2 each).
  - Mul/div masks stay for R9, return pops for R5.
- Kept: −2.646% (−7,573,873 model cycles, all generated code: −6.14M
  executed bytes, reads and writes ±0), static code −28,758 bytes. A carry
  pair's setter keeps the X-producing op (`Ctx.keep_x`). Coverage: the
  harness's dirty upper words (71 mismatches before the change); SI/DI
  written, added to in place, feeding ADC/SBB, read by the REP fast path,
  LODSB and segment loads; segment loads and reads (2,322 boundary cases).
  Plants: a 32-bit consumer trusts a register's upper word; SI/DI in place
  with flags live; the REP fast path converts SI/DI as 32 bits. "SP not
  16-bit" and "RETF CS pop uses linear SP" (D1) moved from `.l` SP updates,
  exact under R4, to `.l` stack indexes.

### R5. Calls, returns, dispatch

- **Return check:** the 6-byte `bne.l rt_ret_mismatch` becomes
  `bne.s`/`bne.w` to a module-local trampoline.
- `jsr abs.l` becomes `bsr.w` where it reaches.
- ret drops its `moveq #0,d7` where the mismatch path doesn't need it.
- **`rt_lookup` on interrupt delivery:** cache the CS:IP → entry result per
  vector, invalidated on IVT writes and module loads (runtime surface).
- Price ≈ 1.5–2%.
- Re-price (meter of `f8da724`, m4): ≈ −0.4 to −0.7% (1.2–1.9M executed
  bytes).
  - Return checks: 319K `bne.l` (−2 bytes as `bne.w`, −4 as `bne.s`).
  - ret/retf/iret pops without `moveq #0` (≈ 293K, −2 bytes): every
    consumer reads the low word (`cmp.w`, the runtime masks).
  - `jsr` → `bsr.w`: vasm already relaxes local calls in reach (2,035
    sites); the 118K `jsr` left are runtime entries and calls out of
    reach.
  - `rt_lookup`: the binary search's result per CS:IP is cached (the
    table is constant, residency is still checked on every lookup), so
    nothing needs invalidating.
- Kept: −2.036% (−5,674,160 model cycles), static code −22,240 bytes.
  - Generated −1.70M: −293,098 `moveq`, −1.57M executed bytes (bytes
    −3.06M, loop bytes +1.49M), reads and writes ±0.
  - Walk −3.80M: its ret cell lost 2 bytes, so the per-cell bound check
    (`bcs`, displacement 126) fits `bcs.s` (−3.95M loop bytes). Layout
    luck, but encoded; R7 reshapes the walk.
  - Runtime −174K (`rt_lookup`).
  - Return checks: 4,853 `bne.s` and 6,471 `bne.w` to 2,551 trampolines,
    none `bne.l`. vasm cannot relax them itself (it runs out of passes), so
    `emit.py` sizes each branch: `bne.s` within 96 estimated bytes (real
    0.69–1.18× the estimate; an out-of-range `bne.s` fails the build).
  - Coverage: the return protocol seeds random upper words in the popped
    IP/CS and adds a wrong-CS case for far calls.
  - Plants: a return check compares 32 bits; a trampoline that falls
    through.

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
- Re-price (census of `714d61e`, m4): only BP qualifies. A native SI/DI/BX
  cannot index reversed memory (it would add, not subtract). `[bp+d]`
  executes 1.19M times (−4 to −6 bytes each direct).
  - Exactness: d5.w sign-extends to 32767 − BP, so `(−d,aS,d5.w)` is
    exact while 0 ≤ BP + d ≤ FFFFh.
  - Guest code may change BP, so a call, `int` or poll inside a region
    needs the guard again (calls, `int`) or leaves the copy (poll stubs).
  - Components after a BP write, priced by the profile: ≈ −4.3M executed
    bytes net of guards (≈ −1.5%), ≈ 16K instructions copied.
- Kept: −1.213% (−3,310,870 model cycles, all generated code).
  - Executed bytes −3.63M (bytes −5.55M, loop bytes +1.93M); reads and
    writes −23,038 each; taken +49,773 (each entry guard's branch into
    its copy).
  - Static code +128,030 bytes (1,051,540 → 1,179,570, +12.2%).
  - vasm runs out of passes relaxing the copies' guards and exits (the
    trampoline plant's image failed), so they are sized like the return
    checks: `.s` within 96 estimated bytes, else `.w`. That costs 64K
    against vasm's own choice (−1.236%).
- Shape: `translator/region.py`; 82 components (96 BP writes, 16,624
  instructions copied) from `annotations/bp-regions.csv`, which
  `tools/bp_regions.py` writes from a meter run (positive gain only).
  - Copies are placed after the next run that cannot fall through.
  - Entry guard `<S>_bpg` after the BP write; re-guard `<S>_bpr` after
    each call or `int`.
  - Poll stubs, BP writes, exits and divide-error retries continue in
    the exact code.
  - The host run and `ab_labels.py` count a copy's labels as its
    instruction's.
- Coverage:
  - Every 68k-differential case with a direct form also runs behind a
    region guard (10,877 cases, the T2 edges among them).
  - The block differential runs the 1,443 executed copy blocks with BP
    at both ends of the admitted range and inside it, plus 1,950 guard
    decisions just inside and outside that range.
- Plants: the guard admits one past its range (193 of 60,131); direct
  `[bp+d]` one byte off (618 of 60,131).
- FS-UAE check (bench, 68020): frames 4–11 79,473 and 79,467 → 74,276
  lines (31.74 → 29.67 fields, −6.5%), guest RAM at frame 12 equal.
  `ab_labels.py`: −4.70% on all labels, −10.1% on the 7,987 changed ones.
  Same sign as the meter.
- Frames fixture against R5 (3 runs each, frames 4–11):
  - Sums 185, 184, 203 → 182, 181, 182: ranges apart.
  - Medians 23, 23, 23.5 → 23, 22.5, 23: they overlap, so no
    frame-time claim (≈ 460 ms per drawn frame).

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
- Re-price (meter of `4daf37b`, m4): walk 73.6M model cycles, 32,799
  entries, ≈ 1.94M mov cells (28 loop bytes, 2 reads, 1 taken each),
  ≈ 5K reload cells.
  - Mov run: the cells left to the bound counted once (dbra), four cells
    per loop pass; each cell one `move.l -(a0)` (opcode word low, operand
    high), opcode compared with a register, address `(7FFFh − BX) − w`
    from a register: 17 loop bytes, 1 read, ¼ taken per cell.
  - Two guest registers saved around each run (≈ 38K runs).
  - ≈ −14 cycles per cell, net ≈ −24M (≈ −9%).
- Kept: −9.037% (−24,372,098 model cycles, all in the walk: loop bytes
  −19.1M, reads −1.82M, writes +79,812 for the saved registers); static
  walk +116 bytes.
  - The run's exit falls into the next form: a `bra` to the next line
    made vasm run out of passes on the trampoline plant's image.
- Coverage: per region image, 8 entries with mov cells to the bound and
  two past it (stop at the bound), a RET in the last cell before it, and
  an unknown cell (`90`; `88 86` and `2E 8B 1F`, which match a form's
  first bytes only) at the first, a middle and the last position: 210
  cases (434 walks in all). A case whose stores overwrite its own cells is skipped, as is
  one where the x86 then raises an exception.
- Plants: the run counts one cell past the bound (47 of 9,865); the
  opcode compare always matches (407 of 9,865).
- FS-UAE check:
  - Bench: frames 4–11 74,336 → 74,373 lines, guest RAM at frame 12
    equal. Its window has no walk; the +37 is layout.
  - Frames fixture capture per arm (100 fields after frame 11): walk
    31.28 → 23.57 cycle units per mov cell (−24.6%), 19.64% → 16.35% of
    the window (178,442 and 197,157 cells).
  - `ab_labels.py` there: −8.87% on the changed labels, −3.87% on all.
    Same sign as the meter.

### R7b. Cell cache (D3)

Not built (user, 2026-10-12): re-priced in §10.

### R8. Branch-target alignment

Price it from a capture's PC sequence: taken branches by target alignment
and their cost difference. If that is positive, align the hot targets
(`cnop 0,4`), chosen by profile within the size budget. The meter is
layout-blind, so this step alone is accepted by `ab_labels.py`, with three
captures per arm.

- Price (bench capture of `83296eb`): a taken transfer from outside a
  cached loop to a target at an address = 2 mod 4 costs ≈ 3.4 more units
  (2-byte target instruction ≈ 2.5), mostly on the branch itself. Matched
  over (branch, target instruction, size): 1.37% of the window
  (196,278 such transfers), loops 0.08%.
- Shape: a chunk is the code from a label that only transfers reach (the
  instruction before it is `bra`, `jmp`, `rts` or `rte`) to the next such
  instruction. A pad before the chunk never runs, so it costs no cycles,
  and it moves every target in the chunk.
  - The meter now reports taken transfers per target (`targets`, from
    outside a cached loop). `tools/align_targets.py` sets, per chunk, the
    residue mod 4 of the chunk's first label that aligns the most of them
    and writes `annotations/align.csv` when the counts differ by ≥ 64:
    510 of 1,120 chunks.
  - `emit.align` places a pad mark only after an unconditional transfer.
    `gen.pad` sizes each mark to 0 or 2 bytes by assembling the program
    and reading the label addresses, repeating until the labels sit on
    their residues (510 of 510, host and Amiga ELF). vasm's `cnop` never
    converges here: one `cnop` anywhere after the start of the program
    hits its pass limit, while a fixed `ds.b 2` at the same spot
    assembles.
- Kept:
  - Meter unchanged (245,326,091; layout-blind). Payload +502 bytes (251
    pads).
  - Bench frames 4–11: control 74,390, 74,264, 74,300 lines; R8 74,048,
    74,084, 74,155 (−0.30%, ranges apart). Guest RAM equal in all six
    runs.
  - `ab_labels.py` per pair: all labels −0.68%, −0.89%, −0.81%; changed
    labels −0.29%, −0.75%, −0.57%. Far transfers to = 2 mod 4 targets
    196K → 104K per window (matched extra 1.37% → 0.57%).
  - Frames fixture (3 runs): medians 24, 21.5, 22 fields (R7 21.5 in one
    run; trajectory noise, §5.1).
- Coverage: the pads change no executed instruction. `tests/test_align.py`
  covers the guard (a pad only after `bra`/`jmp`/`rts`/`rte`, past
  label-only and comment lines). Its plant, a guard that accepts any
  instruction, fails 7 of 16 cases (`make test-sabotage`).
- `make gen` assembles the program up to 5 times (+15–20 s).

### R9. Multiply/divide

DX extraction without `clr.w` and masks once R4 allows dirty upper words.
Price ≈ 0.5%.

- Re-price (meter of `0a64eea`, m4): word `mul` 365K executions (329K
  memory sources), word `div` 40K; byte forms 5K.
  - `mul`: DX as `move.l d0,d2` + `swap d2` (no `clr.w`), no `and.l
    #$ffff,d0` (−8 bytes; −6 with DX dead).
  - Source straight into `mulu.w`/`muls.w` (memory, AX–BX): −2 bytes.
  - `div`: DX:AX built in d2 (`swap d2`, `move.w d0,d2`), quotient and
    remainder read from it (−4 bytes); the fault path swaps d2 back (a
    `divu`/`divs` overflow leaves its destination unchanged). Source DX
    still goes through d6.
  - ≈ −3.8M executed bytes, ≈ −1.5%.
- Kept: −1.615% (−3,960,722 model cycles, all generated code: −3.77M
  executed bytes, −1.26M instructions, reads and writes ±0), static code
  −9,714 bytes. Per form: word `mul` −22 to −23%, `div` −7 to −11%.
  - vasm does not widen `mulu`/`muls`/`divu`'s (d16,An) to a 32-bit
    displacement as it does `move`'s: absolute offsets FFFEh and FFFFh go
    through d6 (FFFEh: under the plants' one-byte displacement shifts).
  - A `bra`/`jmp` to the next line is dropped (`emit.drop_next_branches`,
    5 sites, none executed in m4): the trampoline plant's image ran out of
    vasm passes again (R7).
- Coverage: word mul/imul/div/idiv with DX live from every register (DIV DX
  always faults) and from `[disp]`, `[bx+si]`, `[bp+d8]`, edge values: 1,848
  boundary cases. `tests/test_next_branch.py` covers the branch drop.
- Plants (of 62,147): "DX result dropped while live" moved to the new
  templates (1,558); a divide fault leaves DX:AX swapped (1,612); a divide
  reads DX from the dividend being built (30); the branch drop skips
  instructions (20 of 64).

### R10. Runtime surface

- VRAM marks (`vram_span`, `rt_vram_mark`: 1.85%).
- The interrupt path (`rt_irq_c`, `push_frame`, `deliver`, `guest_vector`,
  flags words ≈ 2.5%): vector bounds cached per IVT write, the flags word
  in asm.
- Port output (SPAZ OPL ≈ 0.75%).
- "No PC" (2.72%, outside the executable and ROM): identify it before
  pricing.
- Price ≈ 1–2%.
- Re-price (meter of `e73421f`, m4): runtime 3.24M model cycles (1.34%).
  Flag helpers (`__set_flags`, `__set_flags_lo`, `__flags_word`,
  `__getpf`; popf/iret/pushf) 0.37%, 190–230 cycles per call; interrupt
  path 0.49% (`rt_irq_c`, `push_frame`, `rt_flags_word`, `guest_vector`,
  `load_regs`/`save_regs` 243 per pair); VRAM marks 0.13% (two `divu` per
  span); port output 0.08% (three calls deep per OPL write); `rt_lookup`
  0.06%. Bench capture (FS-UAE): runtime/platform 1.50%, no PC 0.02%
  (2.72% was the frames fixture's).
  - Flag helpers inline with tables (parity, CCR nibble): ≈ −0.25%.
  - Guest words in one `move.w`, flags word by table, registers by
    `movem`/no dead zero-extension: ≈ −0.2%.
  - `divu #320` by table; OPL writes answered in `rt_out8`: ≈ −0.14%.
  - ≈ −0.6% in all.
- Kept: −0.299% (−721,260 model cycles, all runtime: −374K executed bytes,
  −22.5K reads, −27.6K writes, −22.4K taken), runtime static +100 bytes.
  Flag helpers −37% (`__set_flags` 231 → 155 cycles per call with
  `__set_flags_lo` inlined, `__flags_word` 194 → 112), interrupt path −18%
  (`rd16`/`wr16`/`rd32`/`wr32` one `move` at any alignment; `load_regs`/
  `save_regs` by `movem.w`), port output −47% (`rt_out8` answers AdLib
  writes and the PIC EOI), VRAM marks −6% (the model prices `divu` at 23
  cycles; the 68020 takes ≈ 44). Not taken: the guest-vector bounds cache
  (IVT writes are not seen), `present` (its reads and writes are the copy).
- Coverage: PF from every byte (`add al,0`, then PUSHF, LAHF, JP, JNP);
  PUSHF/LAHF from every CF PF AF ZF SF OF IF DF combination; SAHF from every
  AH; POPF from every combination of its 8 flag bits with bits 12-15: 2,816
  boundary cases.
- Plants: each helper table read one entry off (parity, CCR → FLAGS,
  FLAGS → CCR).
- FS-UAE check (at R11, against `e73421f`, 3 bench runs each, interleaved):
  frames 4–11 72,722–72,816 → 72,448–72,596 lines (−0.37%, ranges
  apart), guest RAM at frame 12 equal in all six; runtime/platform 1.50% →
  1.15% of the capture; `ab_labels.py` all labels −1.03%, −1.11%, −1.21%,
  changed generated labels +0.19%, −0.01%, −0.25%. Same sign as the meter.

### R11. Re-profile

Fresh capture and recalibration, then re-price every row of §6. Repeat
from the top while the meter finds a gain.

- Done 2026-10-13 at `570ec2d` (R10): FS-UAE check of R10 (§7 R10), meter
  recalibrated (§4; plant check ok: 609,493 `ror.w #8` tripled, +1,218,986
  instructions and +2,437,972 bytes as wanted), §6 re-priced, R11 capture
  (§1).
- Frames fixture (3 runs each, interleaved with R9 `e73421f`): medians 20,
  20, 20 fields (intervals 28, 20, 27, 20, 20, 20, 23, 20), sums 177–178;
  R9 20.5, 20.5, 20.5, sums 179. 400 ms per drawn frame; R8 gave 21.5–24.
- Next by the re-price (round 3, one step each, priced here before coding):
  - R12 (below).
  - Index formation in d7 (4.04%: `move.w #7FFFh−d,d7`, `sub.w Rn,d7`
    before `(d,aS,d7.w)`): reuse of a formed index within a block while
    Rn and the segment are unchanged; price by census first.
  - Poll points (3.52%) and stack accesses (3.8%) have no exact cheaper
    form under §2 (`(a6)` is guest byte 0; no thinning).

### R12. String loops by longs

- Price (meter of `eefb416`, m4): REPE CMPSW, REP STOSW and REP MOVSW two
  words per iteration (`move.l -(a4),d6` / `cmp.l -(a5),d6`; the stored
  word doubled in a long). Exact first mismatch: in a mismatching long the
  guest-first word is the low (higher host) word, compared first; an odd
  count ends with one word; the same DF, CX and wrap guards; flags from the
  final word pair as now. Loop bodies 6.21% + 4.38% + 0.12%: ≈ −5% (the
  meter counts a long access as one; a long at an address ≡ 2 mod 4 costs
  two bus cycles on the 68020, so FS-UAE may show less).
  - Not taken: REP MOVSW (0.12%; a distance of 1–3 bytes between ES:DI and
    DS:SI breaks pair order: needs an overlap guard), REPNE CMPSW (a long
    compare cannot find the first equal word).
- Kept: −5.207% (−12,432,163 model cycles, all generated code: `repe
  cmpsw` −7.27M, `rep stosw` −5.16M; −2.18M instructions, −942K reads,
  −423K writes, loop bytes −6.34M, other bytes +183K, taken +16K), static
  code +346 bytes (19 sites: 5 CMPSW, 14 STOSW).
- Coverage: REPE CMPSW and REP STOSW with CX 1–9, CMPSW stopping at every
  element or none, the stop word differing in its low or high byte, above
  or below; SI/DI at every offset mod 4; ranges ending at FFFFh and one
  past it: 324 boundary cases (1,068 boundary cases lower to a pair loop).
- Plants (of 65,287): the low-word decision dropped (blames the second
  element, 82), the odd element skipped (290), AX stored in one word of
  each long (197), CX without the odd mask (162).
- FS-UAE check (against `eefb416`, interleaved): the bench window runs
  neither site (frames 4–11 72,487–72,561 → 72,549–72,613 lines, +0.08%,
  layout; equal RAM). Frames fixture captures (2 per arm): `repe cmpsw`
  (RTSVGA+03BE9) 880 → 525 cycles per run, `rep stosw` (+0C1CA) 1,671 →
  891; `ab_labels.py` changed labels −7.94%, −7.93%, all labels without
  the walk −2.49%, −2.48% (with it +17.9%: the walk label's cycles per
  execution follow the cells each call runs, 1,461 → 2,852 in these
  windows). Frames 4–11 sums 176, 176 → 178, 178 (trajectory, §5.1).

## 8. User decisions (approved 2026-10-08)

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
- **D3.** Cell cache (R7b) with exact invalidation (not built, §10).
- **D4.** Deterministic frame bench (§4).
- Native replacement is not part of this plan (§2.2).

## 9. Projection

R1–R10 with R7b ≈ 28–34% of CPU: from 24.5 fields to ≈ 16–18
(320–360 ms); R7b (priced 5–7%) is not built. The 12-field target needs ≈ 50% less time than today.
Translation alone is not expected to get there: the remaining generated
code would still cost ≈ 10 cycles per guest instruction (≈ 6–7 code bytes
and ≈ 1.3 data accesses each), against the 80286's ≈ 6 clocks. At R11,
report the gap and the top routines. Native replacement stays the user's
decision, routine by routine.

At R11 (2026-10-13): 20 fields (400 ms) against the 12-field bar: frame time
must fall by 40%. Top guest routines in the R11 capture (self time):
SWOTL.EXE+06A4D 16.9% (the cell walk), +0BFD1 8.3%, +04DAE 6.5%, +0B54B
6.2%, RTSVGA.OVL+03B9A 4.1% (its `repe cmpsw` at 03BE9: 2.8%), SWOTL.EXE
+0B017 3.0%, +109D6 2.7%, +0D5A6 2.6%, SPAZ.OVL+00CEE 2.4%.

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
- R7b "cell cache (D3)": re-priced on the R7 meter at about −1.7% at best;
  not built (user, 2026-10-12). After R7, matching is 6 of the 17 loop
  bytes per mov cell (at most −11.1M). Every walk plants a RET in the
  region and restores it (65.6K CS stores per window), so the restored
  cells decode again. The other costs are a check on 110K segment loads,
  invalidation at the CS stores and the run setup.
