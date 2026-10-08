# Speed plan (phase 7)

Rules and measurement for all speed work on the A1200 build. Steps S0–S6
are done (history in git); the work order is
[translator-plan.md](translator-plan.md), whose §4 replaces the per-step
acceptance in §0.7–0.8. Method background: [perf-method.md](perf-method.md).
Open-work item: 14b.

## 0. Hard rules

Breaking any of these voids the step, whatever it measures.

1. **No guest code by hand.** No guest routine in C or asm, no edit of
   `build/gen/`, no runtime or platform code that tests a guest address,
   label, segment value or module offset (`if (ip == 0x3C0F)`, helpers named
   after `VGA_03C2D`, tables of guest addresses in `src/`). Guest code
   changes only through `translator/` lowerings or `annotations/`, then
   `make gen`.
2. **Where a change may live.** Translator lowerings, the runtime surface
   (`src/runtime/`, named by surface: interrupts, display, ports) and the
   platform layer (`src/platform/amiga/`). A native replacement of a guest
   routine is a G3 table entry ([translation-lessons.md](translation-lessons.md)
   G3) and needs the user's approval first; none is planned here.
3. **Semantics are not traded for speed.** Every fast path is guarded by the
   condition that makes it exact (DF, CX, no 16-bit offset wrap, no
   overlap) and falls back to the existing body otherwise. Flags live after
   the instruction keep their exact x86 values. No "usually true"
   assumption; no guard dropped because a census never saw it fail.
4. **Fidelity gates stay green and unchanged** at every commit: `make test`,
   `make test-sabotage`, `make test-host-all`, `make test-amiga`. Never edit,
   skip, mask, loosen or re-record a test, reference or tolerance to make a
   step pass. If a step needs references re-recorded (poll points moved,
   D8), stop and ask the user.
5. **New lowerings get differential coverage first.** Add the new form to
   the x86 corpora (`make test-m68k`, Unicorn x86-16 vs Unicorn 68020)
   with its guard edges (CX 0, 1, 0xFFFF; SI/DI near 0xFFFF; DF 1;
   mismatch at the first, a middle and the last element), see the test
   fail against a deliberately broken fast path, and add a sabotage plant
   so `make test-sabotage` fails if the guard is removed.
6. **Never compare the port with itself as correctness evidence.** Oracles:
   Unicorn x86, the host run against DOSBox references, the reference
   framebuffer. The display checks (host run: guest stores to A0000h vs the
   present's rectangles; `amiga/display_audit.gdb`: shown bitplanes vs guest
   A0000h) check the presentation, not the game; run the audit after any
   display change.
7. **Measure as §1 says** or the number does not count: emulated fields,
   never wall time; the 68020 model (`AMIGA_CPU` unset), never the 68030
   for a claim; no warp, no `cpu_speed=max`; control = the parent commit,
   built and run in the same session with the same fixture; three runs per
   arm; quote ms per drawn frame. This holds for frame-rate claims; per-step
   acceptance is translator-plan §4 (deterministic meter).
8. **One step, one commit**, before/after numbers in the message,
   `docs/open-work.md` 14b and translator-plan §5 updated in the same
   commit. A step that misses the acceptance criteria is reverted and gets
   one line in translator-plan §8.
   Acceptance: translator-plan §4. Do not start the next step on an
   unproven one.
9. **Out of bounds**: presenting a frame before the game publishes it
   (D9: the outermost graphics driver call returns), reading the frame to
   find changes, or skipping published frames; changing the PIT or timer rate or the order of
   interrupt delivery; removing or thinning poll points or return checks;
   shortening the guest's own delay loops (SPAZ OPL waits are guest
   semantics); a double buffer or copper display (open-work 14a);
   Chip-only memory (19). Ask the user first. Exception: the deterministic
   frame bench (translator-plan M2, user 2026-10-08) posts PIT ticks on a
   fixed schedule in its own runtime mode, as an instrument only.

## 1. Measurement

- **Frame period (P).** `amiga/perf_frames.gdb` under `amiga/debug.sh`
  (68020, 8 MB Fast): field at each of the first 12 drawn frames of the
  attract demo flight (one gdb stop per frame at the frame loop `R_044E2`).
  P = median of the frame-4…11 intervals × 20 ms. Run it three times per
  arm: the start field varies run to run (4299, 4334, 5274 seen: the
  hard-drive folder completes I/O on host time). Claim a frame-rate gain only when
  the arms' ranges do not overlap. Frame times fall into trajectory modes
  (translator-plan §2.1); per-step acceptance is translator-plan §4.
- **Shares.** The same fixture then captures 100 fields
  (`monitor profile` stops at 100) into `tmp/prof/frames.bin`;
  `tools/profile_report.py tmp/prof/frames.bin amiga/out/Swotl.elf
  --objdump m68k-amiga-elf-objdump --count rt_irq --count deliver --count
  plat_present`. A capture is 1.1 GB: delete it after the report.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop. Per drawn
  frame (m4): `repe cmpsw` `VGA_03BE9` 19,290 words (the whole view vs the
  previous frame), `rep stosw` `R_0C1CA` 16,075 words, `rep movsw`
  `VGA_03C2D` 151 words to A0000h (median 6 rows).
- **Reference cadence** (DOSBox-X `cycles=fixed 12000`, m4): a drawn frame
  every 9 PIT ticks ≈ 36 ms, ≈ 408K x86 instructions per frame.
- **Meter and bench:** translator-plan M1 (deterministic cost meter, the
  per-step acceptance) and M2 (deterministic frame bench).
- **Stops are free (S0).** Fields from `rt_run_guest` to m1b-logo
  (`VGA_039AD`), 68020: 99–100 with no stop between (3 runs), 99–100 with
  110, 364 and 731 stops (5 runs). `amiga_io_frames` counts the fields
  inside I/O windows (host-timed disk I/O, 7–17 here); the total does not
  move because the guest waits on the PIT.

## 2. Rejected

(One line per rejected arm: step, change, measured, reason.)

- S1 shape "compare each present against a shadow copy to find changed
  rows": rejected by the user before building; every present would read
  the whole 64000-byte frame. Replaced by marks at the driver's stores
  (D9, translator-design Display).
- S5 "cell walk: mov cells four at a time under one bound check, opcode
  of each still compared": walk 14.1% → 12.0% of CPU, rejected only
  because frame times (trajectory noise) did not separate. Revisited as
  translator-plan R7 under the meter.
