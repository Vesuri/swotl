# Speed plan (phase 7)

Work order for making the A1200 build faster. Each step has a prize, a
shape, a gate and a stop rule; do them in order. Method background:
[perf-method.md](perf-method.md). Open-work item: 14b.

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
   framebuffer. The one permitted self-check is S1's display audit (shown
   bitplanes vs the guest's own A0000h at the same instant), which checks
   the platform's presentation, not the game.
7. **Measure as §1 says** or the number does not count: emulated fields,
   never wall time; the 68020 model (`AMIGA_CPU` unset), never the 68030
   for a claim; no warp, no `cpu_speed=max`; control = the parent commit,
   built and run in the same session with the same fixture; three runs per
   arm; quote ms per drawn frame.
8. **One step, one commit**, before/after numbers in the message,
   `docs/open-work.md` 14b and §2 here updated in the same commit. A step
   that delivers less than half its priced prize is reverted and gets one
   line in §4. Do not start the next step on an unproven one.
9. **Out of bounds**: presenting less often than every 5th field or
   skipping guest frames; changing the PIT or timer rate or the order of
   interrupt delivery; removing or thinning poll points or return checks;
   shortening the guest's own delay loops (SPAZ OPL waits are guest
   semantics); a double buffer or copper display (open-work 14a); symbol
   stripping (25); Chip-only memory (19). Ask the user first.

## 1. Measurement

- **Frame period (P).** `amiga/perf_frames.gdb` under `amiga/debug.sh`
  (68020, 8 MB Fast): field at each of the first 12 drawn frames of the
  attract demo flight (one gdb stop per frame at the frame loop `R_044E2`).
  P = median of the frame-4…11 intervals × 20 ms. Run it three times per
  arm: the start field varies run to run (4299, 4334, 5274 seen: the
  hard-drive folder completes I/O on host time). Claim a change only when
  the arms' ranges do not overlap.
- **Shares.** The same fixture then captures 100 fields
  (`monitor profile` stops at 100) into `tmp/prof/frames.bin`;
  `tools/profile_report.py tmp/prof/frames.bin amiga/out/Swotl.elf
  --objdump m68k-amiga-elf-objdump --count rt_irq --count deliver --count
  plat_present`. A capture is 1.1 GB: delete it after the report.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop.
- **S0, once, before S1:** prove a gdb stop costs no emulated time. Take
  the field delta from `rt_run_guest` to the m1b-logo label twice: with no
  stop between, and with a stop at a label hit ≥ 500 times in that span.
  The deltas must agree within 1 field. If they do not, P must come from a
  counter the program keeps and gdb reads once at the end; build that first.

## 2. Baseline (commit c69b52b, 68020 + 8 MB Fast)

Reference (DOSBox-X, `cycles=fixed 12000`, m4): a drawn frame every 9 PIT
ticks ≈ 36 ms, ≈ 408K x86 instructions per frame. Whether that is CPU-bound
at 12000 cycles or paced is not measured.

**A1200 model: P ≈ 5.3 s per drawn frame** (12 frames over fields
4319–7499; intervals 205–550 fields). Guest instructions per drawn frame
≈ 740K (≈ 2.5 `FLT_15E82` simulation steps per frame vs 1 on the
reference: the game catches up on elapsed time, so a slower frame also does
more work).

Steady flight window (100 fields after frame 11):

| Class | Share | Note |
|---|---|---|
| c2p | 61.4% | whole 320×200 every 5th field: ≈ 872K cycles ≈ 61 ms per present; the screen changes once per ≈ 5 s |
| generated guest code | 16.6% | 13–26 cycles per guest instruction; cell walk `SWOTL+06A4D` 2.8% |
| runtime / platform | 13.7% | `rt_irq` entered 4989×, 474 deliveries: ≈ 4500 entries deliver nothing |
| Kickstart | 7.0% | the same in every window |
| IRQ transitions | 1.3% | |

Other windows: SPAZ loading OPL registers inside CLI (attract): `rt_irq`
12,895× for 502 deliveries, ≈ 17% of the CPU in `save_regs`, `rt_irq_c`,
`load_regs`. Menus: RTSVGA `repe cmpsw` 3.3% at 49 cycles per guest
instruction.

Per drawn frame (m4 host census): `repe cmpsw` `VGA_03BE9` 19,290 words
(the whole view vs the previous frame), `rep stosw` `R_0C1CA` 16,075 words
(63 × 255), `repne cmpsw` 150, `rep movsw` `VGA_03C2D` 151 words to A0000h
(≈ 300 bytes, median 6 rows). m5: A0000h also from `rep stosb`
(`VGA_03E7A` 38%, `VGA_04085` 20% of bytes) and `rep movsb`.

**Ceiling.** At ≈ 15 cycles per guest instruction, 740K guest instructions
are ≈ 0.8 s of a 14 MHz 68020 with nothing else running. S1–S3 attack the
overhead around the guest; reaching the reference needs far fewer cycles
per guest instruction, and the user sets the bar (perf-method §1.3) before
work past S4.

## 3. Steps

Re-measure after each step and reprice the rest before starting the next.

### S1. Present only changed rows (platform)

- **Prize.** Up to ≈ 61% of the CPU: between drawn frames the screen does
  not change, and a drawn frame changes a few rows.
- **Shape.** `plat_present` keeps the last presented frame (64000 bytes,
  Fast RAM, allocated when the screen opens). Per present: compare row by
  row (longwords, early exit per row), merge changed rows into runs, call
  `c2p1x1_8_c5_bm` per run (`d1` rows, `d3` first row, `a0` frame + first
  row × 320), copy those rows to the shadow. Palette changes still go
  through `LoadRGB32` every time. Screen open and mode set convert the whole
  frame and refill the shadow. `plat_present(frame, dac)` keeps its
  signature; nothing about the guest enters the platform.
- **Not allowed here:** tracking writes in generated code, reading the
  guest's back buffer, changing the cadence.
- **Price first.** Build an arm that compares but still converts the whole
  frame: its extra cost is the compare. Expected ≈ 150K cycles per present;
  if above 250K, report before continuing.
- **Gate.** §0.4, plus a display audit fixture (commit it): at `shot`
  marks on the title, the U.S. menu and in flight (`KEYS=` as in
  [translator-design.md](translator-design.md) Interrupts), decode the 8
  bitplanes and compare every pixel with guest A0000h; any difference
  fails. Include marks where a present lands while RTSVGA is mid-update.

### S2. Poll points skip `rt_irq` while IF = 0 (runtime + translator)

- **Prize.** ≈ 4500 empty `rt_irq` entries per 100 fields in flight
  (≈ 6% of the CPU now, a larger share after S1); ≈ 17% while SPAZ writes
  OPL registers under CLI.
- **Cause.** `rt_irq_c` delivers nothing while `G_IF` = 0 but leaves
  `G_IRQ` set, so every poll point (each pass of SPAZ's `loop` delay loops)
  saves registers, calls C and reloads them.
- **Shape.** Keep "something is pending" separately from `G_IRQ` (a state
  byte the platform sets with `G_IRQ`; the ring is unchanged). `rt_irq_c`
  with `G_IF` = 0 runs a due present, then clears `G_IRQ`. Every path that
  can set IF re-arms it: the `sti` lowering, `__set_flags` (POPF, IRET),
  and every runtime path that writes IF (`rt_set_flags_word`, delivery and
  service returns). Re-arming copies the pending byte into `G_IRQ` in one
  `move.b` (atomic with respect to the platform's interrupts). Delivery
  points do not move: with IF = 0 nothing was delivered before either.
- **Gate.** §0.4 (`test-host-all` replays interrupts at the reference's
  poll-point visits and must still match); a sabotage plant that drops one
  re-arm path must fail. If the change moves a delivery, stop and report.

### S3. String-op fast paths (translator, D11)

- **Prize.** Per drawn frame: 19K `repe cmpsw` words (≈ 17 68k
  instructions each now), 16K `rep stosw` words, plus `rep stosb` and
  `rep movs` in menus. Price each from the census × the cycles at its label
  in a capture; skip any form under 2% of P.
- **Shape.** DF = 0, CX ≠ 0, and the SI/DI ranges cannot wrap 16 bits
  (`offset + size × CX ≤ 0x10000`); `movs` also needs no harmful overlap.
  Then: 32-bit pointers formed once from segment base + offset; `cmpm.w`
  with `dbne`/`dbeq` (big-endian word equality is byte-order independent),
  `move.l`/`move.w` stores for `stos`, `move` for `movs`, with `dbf`'s 16-bit
  counter split for CX > 0x8000; SI, DI and CX written back. For
  `cmps`, recompute the flags of the last compared pair exactly as the
  existing lowering does (byte-swapped loads, `cmp`). Otherwise the
  existing per-element body.
- **Gate.** §0.5, then §0.4.

### S4. Re-profile and price (no code)

Price each in §2 before building; each becomes its own step here:
interrupt delivery per real interrupt (`save_regs`/`load_regs`,
`push_frame`, `rt_flags_word`, `guest_vector`); `rt_lookup` (binary search
per indirect transfer: a direct-mapped cache keyed by CS:IP, flushed at
overlay load); the cell walk (open-work 14, D16 specialisation); the
constant Kickstart 7% (find the ROM code: input.device, timer or vblank
servers, the Intuition screen); generated-code shape (the role table's
"other" split finer: flag materialisation, segment arithmetic, byte
swaps).

## 4. Rejected

(One line per rejected arm: step, change, measured, reason.)
