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
  (240 ms); stretch ≤ 10. A guide, not an absolute target (user 2026-10-28): the ReadMe
  recommends a 68030 or better.
- **Status:** R16 alignment repair, R17 palette validity, R18 flag extraction kept; R20 cell
  cache, R21 string layout, R22 call layout, R24 REP STOSW fill, R25 BP as data, R26 REPE CMPSW, R27 cold
  branch sides, R28 carry in X, R29 far push, R30 repeated segment loads,
  R31 push/pop runs, R32 conditional-over-jump fusion and R33 packed far returns
  kept; R34 FM continuity accepted as a quality tradeoff. Item 14b's 240 ms target
  remains unmet. R35 enables the authorized N1 transform pilot. R36 enables
  B017’s authorized B393 projection long path; R37 enables the authorized
  B4E2 perspective divide; R38 enables D5A6’s normalization loop.
  R40 enables the guarded scenery clears with proved BP-region re-entry.
  R42 enables the guarded sprite packet loop, R44 the guarded line pixel loops, R48
  guarded edge ordering and merging (all with exact original polls until irq-plan I9).
  F3a replaces `B017` with its divide `B4E2` whole (folding R36 and R37);
  F3b replaces `B52D` with `B54B` whole; F5 `BFD1`'s scanline loop (folds R48); F9
  SPAZ's OPL delay loops. [irq-plan](irq-plan.md) I8–I10 (user 2026-10-24): no poll
  checks in production, rows poll-free (RC5), and the deferred rows re-opened (§7 I10).
  Paused under U7, resumed under U9 (2026-10-23): [native-plan.md](native-plan.md#f-flyby-plan).
- **Frames fixture** (Z1, `9afe0b8`, 2026-10-23): medians 340, 340 and
  350 ms; run-median span 340–350 ms. Frames 4–11 intervals (fields):
  `[21,19,15,17,17,23,17,16]`, `[24,15,25,17,17,17,19,16]`,
  `[21,18,17,20,17,20,17,16]`; interval spans 15–23, 15–25 and 16–21.
  Same-session parent `6855468`: medians 350, 360 and 340 ms (340–360 span),
  intervals `[21,19,15,17,17,23,18,16]`, `[21,18,15,17,18,23,18,16]`,
  `[20,19,16,17,17,24,17,16]`; spans 15–23, 15–23 and 16–24.
  Three unchanged 68020/8 MB Fast runs per arm, each followed by 100-field
  profiling; frozen executables and tool versions match R48 validation.
  Ranges overlap: no frame-rate gain established. Target remains unmet;
  340 ms needs 100 ms (29.4%) less to reach 240 ms. Evidence:
  `tmp/native/N4-raster-remaining/z1-summary.json`; raw captures deleted.
- **Frames checkpoint after F3/F4** (ZF3, `130bd18`, 2026-10-24, arm64):
  medians 330, 300 and 300 ms; run range 300–330 ms. Intervals (fields)
  `[20,17,14,18,16,18,15,15]`, `[19,18,14,15,14,23,15,15]`,
  `[20,18,14,15,14,23,15,15]`. Same session: pre-F3 arm (`f0b93f8`) 360,
  350, 360 ms (`[24,15,25,18,17,18,19,16]`, `[24,15,25,18,17,17,19,16]`,
  `[23,16,25,18,17,18,19,16]`); F3 arm 350, 340, 330 ms
  (`[20,18,15,20,16,19,17,15]`, `[20,17,15,21,15,19,17,15]`,
  `[20,18,14,16,16,23,17,16]`). F3+F4 against pre-F3: ranges 300–330 and
  350–360 do not overlap, a frame-rate gain (−60 ms median, −16.7%). F3
  alone and F4 alone overlap their parents. 300 ms needs 60 ms (20%) less
  to reach 240 ms. `tools/ab_runs.py frames`, three runs per arm,
  interleaved. Evidence: `tmp/speed/zf3/`.
- **Frames checkpoint after irq-plan** (ZI, irq-plan I11, 2026-10-27, arm64, production
  images): head `c21d035` medians 300, 290, 300 ms (`[19,17,13,14,15,21,15,14]`,
  `[19,17,14,13,14,22,14,15]`, `[19,16,13,16,14,17,14,13]`) against pre-irq-plan
  `5d82dad` (F5, F9 kept) 330, 330, 320 ms (`[20,17,14,18,16,18,15,15]`,
  `[20,18,13,19,15,18,15,15]`, `[24,15,17,16,20,14,16,14]`). Ranges 290–300 and 320–330
  do not overlap: a frame-rate gain (−30 ms median, −9.1%). 300 ms needs 60 ms (20%)
  less to reach 240 ms. `tools/ab_runs.py frames`, three interleaved runs per arm.
  Evidence: `tmp/irq/I11/`.
- **F1 measurements** (2026-10-23): EMS map copy. Meter m4 unchanged
  (161,346,464; no maps in its window). Meter c12 (B-17 bombing, 715 frames,
  10.3 maps/frame): 10,719,598,079 → 7,748,395,558 (−27.72%), runtime
  4,469,615,307 → 1,498,412,785. Flyby target cost per map: base 242,524 and
  242,459 cycles (12, 15 maps); F1 622 (36 maps, all identical remaps) and
  12,138 (108 maps, copies and skips). Runtime +316 bytes, executable +392.
  Evidence: `tmp/speed/f1/`.
- **arm64 baseline** (2026-10-24, `f0b93f8`, `$FSUAE_ARM`): every FS-UAE
  number before this entry is from the x86_64 build and does not compare
  with later ones (§4). Bench frames 4–11: 68,366 lines median (68,345–68,374;
  RAM hash `951adbe5…6c63` in all three). Frames fixture 370, 370, 380 ms
  (an earlier same-build session 370, 360, 350). Flyby: 22 and 20 drawn
  frames in 500 fields (455, 500 ms/frame); `3B9A` 4.19% inclusive.
  Evidence: `tmp/speed/arm64-base/`.
- **F2 measurements** (2026-10-23): REP MOVSW by longs (translator). The
  flyby profile puts `3B9A`'s cost in its REP instructions (`repe cmpsw`
  `03BE9`, `repne cmpsw` `03C0F`, `rep movsw` `03C2D`), not its glue
  (≈0.3%), so a lowering replaces the native. Censuses (`--strops`) per
  frame: `03C2D` m4 151 words (5.8/run), c12 177 (4.1/run), c13 110; the long
  spans are the outside-view flyby's. Meter m4 161,346,464 → 161,335,708
  (−0.0067%; `rep movsw` −11,809); generated code +1,446 bytes. Flyby pairs
  (two runs per arm): `03C2D` cycles per `03C0F` cycle (same words) 0.866,
  0.842 → 0.625, 0.583 (−29%); `03C2D` 0.88–1.17% → 0.77% of the clip.
  Evidence: `tmp/speed/f2/`.
- **F3a measurements** (2026-10-24, `$FSUAE_ARM`): `B017` whole with `B4E2`.
  Price (m4 meter, F2 arm): `B017`+`B4E2` generated 4.31% of the meter
  (9,539 calls: 441 16-bit path, 9,098 32-bit; flyby mostly 16-bit). Meter
  161,335,708 → 158,939,203 (−1.4854%; generated −6,145,705, runtime
  +3,749,200). Bench 68,395 (68,365–68,434) → 68,332 (68,280–68,359), RAM hash
  `951adbe5…6c63` in all six runs. Flyby, exact cycles per `B017` call (both
  arms' captures): inclusive 1,083 → 837 (−22.7%); `D5A6` inclusive 1,522 →
  1,249. Runtime +938 bytes. Evidence: `tmp/speed/f3/`.
- **F3b measurements** (2026-10-24, `$FSUAE_ARM`): `B52D` whole with `B54B`.
  Price (m4 meter, F3a arm): wrapper and hook 1.84% of the meter (14,455 calls).
  Meter 158,939,203 → 156,420,369 (−1.5848%; generated −2,262,443, runtime
  −256,391). Bench, 8 interleaved runs per arm: medians 68,333 → 68,350
  (+0.025%), spans 68,275–68,371 and 68,307–68,389, RAM hash `951adbe5…6c63`
  in all 16; user 2026-10-24: "16 lines is noise. Accepted." Flyby, exact
  cycles per `B52D` call: 820 → 629 (−23.3%).
  Evidence: `tmp/speed/f3/`.
- **F4 measurements** (2026-10-24, `$FSUAE_ARM`): FM loop cache and render
  loop, same slots, pages and samples (`t-fm-cache`, `t-fm-render`). Flyby,
  exact cycles per call: `fm_field` inclusive 31,380 → 23,719 (−24.4%; 10.75%
  → 8.11% of the clip), `render` 23,194 → 13,546, `loop_for` 9,667 → 5,224.
  Bench, 5 interleaved runs per arm: medians 68,307 → 68,445 (+0.20%), spans
  68,290–68,354 and 68,397–68,482, RAM hash `951adbe5…6c63` in all. Frames
  4–11 render no loops: there only FM code placement counts (`eg_advance`
  unchanged, +4–9% per call) and frame 3 comes ~3 fields earlier; generated
  code moves 0x434 bytes; with it padded back to the base mod 256 the bench is
  still +0.12%. After frame 12 the guest executes +0.9% instructions per 100
  fields. User 2026-10-24: bench accepted as noise. Evidence: `tmp/speed/f4/`.
- **F9 measurements** (2026-10-24, `$FSUAE_ARM`, clean worktree arms at
  `184414d`): SPAZ OPL delay loops `D03..D05` and `D0F..D15` as exact-poll
  rows: every iteration, poll visit and stack-slot store kept (loop count
  unchanged, no §2.9 shortening); the PUSH/POP reloads and SP updates go.
  Meter m4 156,392,185 → 154,046,871 (−1.4996%; generated −5,117,342,
  runtime +2,772,028; code +150 generated, +76 runtime bytes); 568,080 fewer
  guest instructions. Bench, 5 interleaved runs per arm: medians 68,387 →
  68,425 (+0.056%, D8 noise: meter −1.5%), spans 68,339–68,431 and
  68,341–68,451, RAM hash `951adbe5…6c63` in all 10. Flyby: `0CEE`
  inclusive 1,840 → 1,171 cycles/call (−36.4%; 2.83% → 1.82% of the clip),
  callers `07CC` 2,762 → 2,160, `0A8B` 21,118 → 13,737. O(1) loops (§2.9
  exception) follow irq-plan I9, at I10.
  Evidence: `tmp/speed/f9/`, `tmp/native/F9/`.
- **F5 measurements** (2026-10-24, `$FSUAE_ARM`, clean worktree arms at
  `4d4272d`): `BFD1` scanline loop `C000..C42C` one exact-poll row, guest
  calls as continuation exits; folds R48. Meter m4 156,420,369 → 156,394,228
  (−0.0167%; generated −11,656,496, runtime +11,630,355; code +1,612
  generated, +1,260 runtime bytes); 1,509,262 fewer guest instructions.
  Bench, 5 interleaved runs per arm: medians 68,421 → 68,391 (−0.044%), spans
  68,365–68,461 and 68,351–68,449, RAM hash `951adbe5…6c63` in all 10. Flyby
  (23 frames each): `BFD1` inclusive 632,281 → 618,740 cycles/call (−2.1%);
  without `CD99` 6.63% → 6.58% of the clip. The S2 estimate (−45–60% of
  ~300K/call) missed: exact polls and byte histories leave the native close
  to the generated code, and 6,264 m4 entries pay guards, hooks and the
  generated segments between an exit and the next poll. Two fixes found
  here: native dispatch onto a poll's execution alias (`*_native_np`)
  double-counted host visits (lost IRQ at `C3A4` in the meter; entries now
  start below the alias; probably R46's c13/c27 failure at `C32D`); hooks
  with five or more resume ids dispatch through a PC-relative table (the
  chain cost 375K m4 cycles). Evidence: `tmp/speed/f5/`, `tmp/native/F5/`.
- **Flyby profile** (F0, frozen R48 build `8b46b6a5…`, 2026-10-23): attract
  demo, fields 1144–1648 after drawn frame 12, five consecutive 100-field
  captures; 142,101,991 cycles, 18 drawn frames (555 ms/frame). Drawn frames
  per 100 fields 5, 5, 3 (distant fighters, terrain), 3, 2 (close B-17s).
  Inclusive shares, clip (w0–w2 / w3–w4): EMS map `rt_int67` 10.30%
  (0–0.9 / 25.6, 24.8; 61 maps, 240K cycles each, two byte-wise 16 KB copies),
  FM `fm_field` 10.97%, `BFD1` 9.16%, `109D6` 9.20%, `FDE0` 6.92%, sprites
  `4D7D` 4.57% (0.8–1.4 / 7.6, 12.0), present+C2P 5.22%, SPAZ timer driver
  4.55%, `RTSVGA+3B9A` 4.11%, simulation `FLIGHT+012E6` 15.66%. The frames
  fixture's 100-field window misses the EMS-bound section. Second run
  (`4838add` rebuilt, start field 1126, 20 frames, 500 ms/frame) caught close
  fighters and smoke instead: sprites `4D7D` 15.46%, EMS 1.83% (9 maps,
  288K cycles each), `BFD1` 7.85%, `109D6` 7.64%, `FDE0` 5.89%, FM 10.89%,
  `3B9A` 4.53%, present 3.88%. The window's content follows the start field:
  rank on several runs. Plan:
  [native-plan.md](native-plan.md#f-flyby-plan). Evidence: `tmp/flyby/`.
- **Bench** (A3, `6bf8aef`, 2026-10-21): opening frames 4–11 sums 68,525,
  68,536 and 68,493 lines; median 68,525, span 43 lines (0.063%). Corresponding
  profiler cycles: 62,220,700; 62,230,688; 62,191,644 (908/line).
  All three final guest RAM hashes match the established bench endpoint
  (`951adbe5…39b6c63`). This spread exceeds the introduction's two-line observation
  (§4); no build-to-build claim. Palette window 38,392–38,405 lines (R17).
- **Meter** (R48, m4, A4 weights): generated + walk + runtime
  161,344,429 model cycles, down 0.100064% from the parent’s 161,506,038; unchanged host
  platform adds 2,035. Three identical runs per arm. Native callbacks bypass
  body labels, so label-derived guest counts are not semantic work counts.
- **N1 measurements** (2026-10-21): transform 1,182.182 → 634.432 target
  cycles/call (−46.334%). Opening-bench medians 68,526 → 68,540 lines
  (+0.0204%; user accepted), spans 68,495–68,553 → 68,502–68,540; all six
  final RAM hashes match. Single frames captures: `[25,16,21,19,21,19,19,16]`
  → `[21,19,16,17,18,26,17,17]`, medians 380 → 350 ms, spans 16–25 →
  16–26 fields. These per-call captures do not establish a frame-rate gain;
  Z1 reports the current three-run checkpoint above. Payload +446 bytes; full gates green.
- **R36 measurements** (2026-10-22): B393 long path
  809.612 → 596.125 target cycles/call (−26.3690%). Opening-bench medians
  68,538 → 68,567 lines (+0.0423%), spans 68,527–68,558 → 68,551–68,621;
  all six final RAM hashes match. User accepts the initial +0.0598% layout
  difference as noise; no general no-slowdown exemption. Payload +432 bytes.
  Single S7 profiles do not establish a frame-rate gain; Z1 is the latest
  three-run frames checkpoint. Evidence: `tmp/native/N2-projection/`.
- **R37 measurements** (2026-10-22): divide 251.151 → 153.673 target
  cycles/call (−38.8126%). Bench medians 68,580 → 68,565 lines (−0.0219%),
  spans 68,577–68,609 → 68,565–68,598; all six RAM hashes match.
  Host payload +110 bytes; Amiga executable +152 bytes. Single frames
  captures both have 350 ms medians; no frame-rate gain claimed.
  Evidence: `tmp/native/N2-divide/`.
- **R38 measurements** (2026-10-22): normalization loop plus poll
  427.549 → 138.246 target cycles/call (−67.6654%). Bench medians
  68,584 → 68,581 lines (−0.0044%), spans 68,537–68,584 → 68,557–68,590;
  all six RAM hashes match. Host payload +102 bytes; Amiga executable +188.
  Single frames captures have 340 → 350 ms medians; no frame-rate gain claimed.
  Evidence: `tmp/native/N4-normalise/`.
- **R40 measurements** (2026-10-23): scenery clear plus endpoint poll
  606.930 → 405.636 target cycles/call (−33.1659%). Bench medians
  68,385 → 68,406 lines (+0.030708%, user accepts this specific difference
  as noise); spans 68,380–68,408 → 68,394–68,411, all six RAM hashes match.
  Host payload +346 bytes; Amiga executable +656 bytes. Single frames captures:
  `[24,16,26,16,17,17,18,16]` → `[25,15,20,17,20,16,17,16]`; both
  medians 340 ms, spans 16–26 → 15–25 fields. No frame-rate gain claimed.
  Both arms use checked matching tool versions; earlier mixed-version target
  comparisons are excluded. Evidence: `tmp/native/N4-scenery/`.
- **R42 measurements** (2026-10-23): sprite packet work
  815.176 → 782.000 target cycles/packet (535 packets / 2,908 iterations
  in each capture); exact host-instruction weighting −5.261052%.
  Bench medians 68,385 → 68,380 lines (−0.007312%), spans
  68,351–68,386 → 68,379–68,383; all six RAM hashes match.
  Host payload +240 bytes; Amiga executable +580 bytes. Single frames
  captures `[21,18,15,17,16,24,19,16]` → `[21,18,16,21,17,21,16,16]`:
  both medians 350 ms, spans 15–24 → 16–21 fields. No frame-rate gain
  claimed. Evidence: `tmp/native/N4-sprite/`; investigation in the R42 commit.
- **R44 measurements** (2026-10-23): line pixels
  2,821.121 → 2,709.515 target cycles/entry (66 entries each, 4,662/4,747
  pixels); exact host-instruction weighting −5.866799%. Meter
  161,572,185 → 161,506,038 (−0.040939%), three identical runs per arm.
  Bench medians 68,395 → 68,384 lines (−0.016083%), spans
  68,352–68,408 → 68,328–68,393; all six RAM hashes match.
  Host payload +420 bytes; Amiga executable +1,344 bytes. Single frames
  captures `[21,18,17,20,17,20,17,15]` → `[20,19,16,16,17,24,17,17]`:
  medians 350 → 340 ms, spans 15–21 → 16–24 fields. No frame-rate gain
  claimed. Evidence: `tmp/native/N4-line/`.
- **R48 measurements** (2026-10-23): edge ordering/merging target cost
  1,106.530 → 857.514 cycles/entry (381 entries in each initial capture);
  exact host-instruction weighting −10.780077%, including rare IRQ handoffs
  from user-approved targeted captures. Bench medians 68,383 → 68,384 lines
  (+0.001462%, user accepts this specific difference as noise), spans
  68,361–68,393 → 68,372–68,400; all six RAM hashes match.
  Host payload +1,162 bytes; Amiga executable +3,300 bytes. Initial frames
  captures `[21,19,15,17,17,23,18,16]` → `[21,19,15,17,17,23,17,16]`,
  medians 350 → 340 ms; both spans 15–23 fields. No frame-rate gain claimed.
  Evidence: `tmp/native/N4-raster-remaining/`.
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
   sync point (except as [irq-plan](irq-plan.md) allows; native-plan U5 retired at its I9), fail-loud stop or wrap
   handling; no "usually true" or "never seen" assumption; no annotation
   asserting what the translator must prove.
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
   or the order of interrupt delivery; removing or thinning sync points or
   return checks (exceptions: [irq-plan](irq-plan.md)'s sync points, loop heads in
   native rows and asynchronous IRQ0, user 2026-10-24, RC2/RC3/RC5; native-plan U5
   retired at its I9); shortening the guest's own delay loops
   (SPAZ OPL waits are guest semantics; exception, user 2026-10-24: F9's
   delay loops in O(1) with an exact final state once irq-plan I9 has landed);
   a double buffer or copper display;
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
- **Bench noise (D8):** a bench median at most +0.25% above the base
  (layout-scale; F4's code move gave +0.20%) is noise, not a slowdown,
  when the step is generally faster (meter lower, or the flyby lowers the
  changed work per call) and final guest RAM is identical. Report it; ask
  only above +0.25% or when nothing general improves.
- **Code growth** only with lower model cycles (D2), or lower bench cycles
  for work covered by D5. Stop and ask before
  the payload exceeds 1,325,164 bytes by more than 25% (slave ExpMem margin, [whdload.md](whdload.md) Memory).
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
need re-recording or an interrupt delivery moves (beyond a U5 row's approved
re-recording); two consecutive steps
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

- **Emulator.** `$FSUAE` (`amiga/env.sh`: the shared arm64 `$FSUAE_ARM`
  since 2026-10-24; x86_64 before). Compare FS-UAE numbers from one binary
  only; `ab_runs.py` fingerprints it. Its captures hold absolute PCs
  (`profile_report.hunk_relative`).
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
  per arm, `--compare A B` for the §3 deltas; also poll tests per class (irq-plan I1); the JSON's `runtime` holds model cycles per runtime symbol (natives against the generated cycles they replace). Weights `tools/cost_model.json`,
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
- **Bench** (`SWOTL_ARGS=BENCH ./debug.sh "" bench_frames.gdb`, same model, on the
  sync image `make amiga-sync` since irq-plan I8: production has no poll checks and
  refuses `BENCH`; `ab_runs.py` freezes and runs it; runtime.h `rt_bench`): no CIA timer; 9 PIT ticks per 4 runtime services
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
- **Flyby** (F0, user 2026-10-23): `amiga/perf_flyby.gdb`, five consecutive
  100-field captures from drawn frame 12 of the attract demo (fighters to close
  B-17s); `tools/profile_tree.py` over all five. Supplements the frames fixture
  and bench; runs: `tools/ab_runs.py flyby`.
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
| R35 / N1 | guarded native point transform from authorized xform20; complete byte-write history | runtime, compute oracle | −4.6800% (bench +0.0204%, user-approved tradeoff) |
| N3 | post-transform frames checkpoint: 370, 350, 340 ms; target unmet | docs | measurement only |
| R36 / N2 | guarded projection long path from authorized xproj20; complete byte-write history | runtime, compute tests | −0.2838% (bench +0.0423%; user accepts initial +0.0598% as noise) |
| R37 / N2 | perspective divide from authorized xdiv20; exact intermediate BP and all register results | runtime, compute tests | −0.6499% (bench −0.0219%) |
| R38 / N4 | counted normalization from authorized xpnorm20; proved continuation endpoint and U5 poll | runtime, compute contract/tests | −1.3373% (bench −0.0044%) |
| R40 / N4 | guarded scenery clears from clr_scenery; proved BP continuation guard and U5 endpoint poll | runtime, translator, compute tests | −0.150466% (bench +0.030708%, user accepts as noise) |
| R42 / N4 | guarded sprite packet loop; exact original polls and handler-state re-entry | runtime, translator, compute/replay tests | −0.131085% (bench −0.007312%) |
| R44 / N4 | guarded line pixel loops; exact original polls and handler-state re-entry | runtime, compute tests | −0.040939% (bench −0.016083%) |
| R46 / N4 | priority searches deferred; generated oracle coverage and optional short poll macro retained | tests, translator tooling | No shipped speed change |
| R48 / N4 | guarded edge ordering/merging; wrapping index reuse and exact original polls | runtime, compute tests | −0.100064% (bench +0.001462%, user accepts as noise) |
| Z1 | post-N4 frames checkpoint: 340, 340, 350 ms; target unmet; user paused speed work (U7) | docs | measurement only |
| F1 | EMS map: long-word page copy, exact identical-remap skip | runtime, EMS oracle | c12 meter −27.72% (m4 unchanged) |
| F2 | REP MOVSW by longs; element order kept for CX < 4 and DI 1–3 bytes above SI | `lower.py` | −0.0067% (flyby `rep movsw` −29%) |
| F3a | projection `B017` whole with divide `B4E2`, four returns; folds R36/R37 rows; merged long stores | runtime, compute tests | −1.4854% (bench −0.0921%) |
| F3b | transform `B52D` whole with `B54B`; wrapper pushes stored, SI/DI/BP restored | runtime, compute tests | −1.5848% (bench +0.025%, user accepts as noise) |
| F4 | FM loop cache: split key/stamp arrays, first-free hint, freed-range refit; render loop per feedback/connection | Amiga platform, FM tests | outside meter (flyby `fm_field` −24.4%/call; bench +0.20%, user accepts as noise) |
| ZF3 | post-F3/F4 frames checkpoint: 330, 300, 300 ms against pre-F3 360, 350, 360 (no overlap); target unmet | docs | measurement only |
| F5 | `BFD1` whole, exact polls, guest calls as exits; folds R48. Price (S2, flyby `130bd18`): 575,524 inclusive cycles/call, self 260,523 + ordering 86,293; clear 0.80% of the clip stays (long stores, U3); replaceable ~300K/call; estimate −45–60% of it, 1.5–2.5% of the clip | runtime, translator, compute tests | −0.0167% (bench −0.044%, flyby `BFD1` −2.1%/call) |
| F9 | SPAZ OPL delay loops as exact-poll rows, every iteration, poll and store kept | runtime, annotations, `test_opl_delay` | −1.4996% (bench +0.056%, D8; flyby `0CEE` −36.4%/call) |
| I10 | native rows re-opened poll-free (irq-plan I10), one batch, references re-recorded once; per row below: generated cycles saved and native cost on the same m4 run (`cost_meter.py` `runtime` per symbol) | runtime, translator, compute tests | −4.9158% (bench −0.48%) |
| I10 / BB70 | polygon classify whole up to its RETF, R39's admission guard | runtime, compute tests | generated −3.13M, native 1.47M: −1.66M |
| I10 / BFD1 | rasterizer re-entered after each guest call (`hle.csv` entries); guards once per scanline | runtime, translator, compute tests | −1.18M against the I9 arm (native 9.79M → 13.11M, generated 5.74M → 1.25M) |
| I10 / F290 | tile and scenery selection whole; object calls as exits with re-entries; far-ring sprite objects skipped by their type byte | runtime, compute tests | generated −2.90M, native 2.06M: −0.84M |
| I10 / 109D6 | ground-object vertex loops 10C08–10F5F; B52D/D5A6 calls and their 9C20h sync writes as exits | runtime, translator (`irq.check_rows`), compute tests | generated −3.46M, native 2.80M: −0.66M |
| I10 / FDE0 | terrain polygons whole; transform and classify natives called directly (exit only on decline), other calls as exits | runtime, compute tests | generated −3.96M, native 3.37M: −0.59M |
| I10 / BD68 | edge submission; C962/CD00 calls as exits with re-entries; hook and dispatch overhead leaves little | runtime, compute tests | generated −1.11M, native 1.05M: −0.06M |
| F8 | sprite walk loop 4FD3..5032 in `sprite_row` (user 2026-10-27: code writes through the cell cache's bookkeeping, the generated cell walk called directly); sync set −1 (4FD3), references re-recorded; generated −10.70M, native +8.97M | runtime, translator, compute tests | −1.2038% (bench +0.025%, user accepts as noise) |
| ZI | post-irq-plan frames checkpoint (irq-plan I11): 300, 290, 300 ms against pre-irq-plan 330, 330, 320 (no overlap); target unmet | docs | measurement only |
| I10 / rest | D5A6 prefix and suffix to the projection call; F9 delay loops O(1) (§2.9 exception); D69C BP once; 4DAE packet loop widened to the span setup (`sprite_row`) | runtime, compute tests | −2.43M together (no per-row I9 runtime baseline) |

No priced translator candidate remains. Unchanged (§2): sync points outside native rows
(`(a6)` is guest byte 0; no thinning; no poll checks in production since irq-plan I8), `mulu`/`divu` themselves. The translator helpers
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
- **D8 (2026-10-24).** The bench stays frames 4–11 (static opening view).
  Tiny bench regressions count as noise when general performance improves (§3).
- Native replacement: [native-plan.md](native-plan.md); each routine needs the user's
  authorization (§2.2).

## 9. Gap

ZI's frames-fixture medians (arm64, irq-plan I11) are 300, 290 and 300 ms: 60 ms (20%)
more to cut to reach 240 ms; the run range needs 50–60 ms less. Against the same-session
pre-irq-plan arm (320–330 ms) the ranges do not overlap, as F3+F4 did against pre-F3
(ZF3). The user
resumed speed work under U9 on 2026-10-23: plan F in native-plan.
No priced translator candidate remains (§7). N1, N2’s B393 projection and B4E2 divide,
and N4’s scenery clear and line pixel loops are kept; F5's whole `BFD1` scanline loop replaces R48's ordering row; irq-plan I10's rows are in §7. Rows are poll-free since irq-plan I9
([native-compute.md](native-compute.md#loops-and-the-sync-set-rc5); U5 retired), with the U8
extensions (C4). Active candidates and user deferrals: open-work 14b and
[native-plan.md](native-plan.md).

Historical candidate costs, A3 run 2 (`6bf8aef`, 100 fields, 28,420,399 profiler cycle
units). Own cost groups generated instructions by call-target boundary; inclusive
cost follows completed A7 call scopes, excluding hardware and guest interrupt
delivery (`tools/profile_tree.py` method). All listed observed calls finish inside
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
byte-write history; U4 authorizes B017’s B393 long path and B4E2, U6 the
remaining N4 routines under S1–S9. Current decisions: native-plan U4/U6.

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

- R39 / BB70: deferred by user 2026-10-22; whole-body prototype skipped kept syncs. Repair budget 4,363,049 versus 3,198,000 generated model cycles; no positive price. Generated differential and skipped-sync sabotage retained; evidence `tmp/native/N4-classify/`.

- R41 / F290: user deferred 2026-10-23; narrow tile-selection design estimated at 1,633,529 versus 1,147,792 generated model cycles (JSR/RTS model accesses corrected after 7744ce5). No implementation built; guards and frequent handoffs outweigh the priced arithmetic folds. Evidence: `tmp/native/N4-terrain/`.

- R43 / BD68: user deferred 2026-10-23; approved exact-poll edge scopes budget 843,635 versus 667,905 generated model cycles even with optimistic credits. Frequent external-call handoffs outweigh address reuse; no implementation built. Evidence: `tmp/native/N4-edges/`.

- R45 / FDE0: user deferred 2026-10-23; approved cache-loop design budgets 476,194 versus 434,107 generated model cycles, even with optimistic credits. Frequent cache-miss exits outweigh address reuse; no implementation built. Evidence: `tmp/native/N4-polygons/`.

- R46 / BFD1 priority searches: user deferred 2026-10-23; meter −0.087648%, target mix −3.777903%, but four bench pairs give median +0.049732% with overlapping ranges. No-slowdown acceptance unproved; native hooks removed, generated coverage retained. Evidence: `tmp/native/N4-raster/`.

- R47 / BFD1 expiry and advance: user deferred 2026-10-23; address-reuse budgets 1,304,535 versus 1,048,049 and 1,769,291 versus 1,676,612 model cycles. No implementation built; evidence `tmp/native/N4-raster-remaining/`.
