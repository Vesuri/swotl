# Speed plan (phase 7)

Work order for making the A1200 build faster. Each step has a prize, a
shape, a gate and a stop rule; do them in order. Steps S0–S6 are done;
the work continues in [translator-plan.md](translator-plan.md), under §0
and §1 here. Method background:
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
   framebuffer. The display checks (host run: guest stores to A0000h vs the
   present's rectangles; `amiga/display_audit.gdb`: shown bitplanes vs guest
   A0000h) check the presentation, not the game; run the audit after any
   display change.
7. **Measure as §1 says** or the number does not count: emulated fields,
   never wall time; the 68020 model (`AMIGA_CPU` unset), never the 68030
   for a claim; no warp, no `cpu_speed=max`; control = the parent commit,
   built and run in the same session with the same fixture; three runs per
   arm; quote ms per drawn frame.
8. **One step, one commit**, before/after numbers in the message,
   `docs/open-work.md` 14b and §2 here updated in the same commit. A step
   that misses the acceptance criteria is reverted and gets one line in §4.
   The frame-time bar is half the priced prize; translator-plan §3.6 also
   allows measured efficiency/size wins under the user's amendment, with
   no slowdown: smaller code does not excuse a measured performance regression.
   Do not start the next step on an unproven one.
9. **Out of bounds**: presenting a frame before the game publishes it
   (D9: the outermost graphics driver call returns), reading the frame to
   find changes, or skipping published frames; changing the PIT or timer rate or the order of
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
  hard-drive folder completes I/O on host time). Claim a frame-rate gain only when
  the arms' ranges do not overlap. Efficiency/size acceptance follows the
  user amendment in translator-plan §3.6.
- **Shares.** The same fixture then captures 100 fields
  (`monitor profile` stops at 100) into `tmp/prof/frames.bin`;
  `tools/profile_report.py tmp/prof/frames.bin amiga/out/Swotl.elf
  --objdump m68k-amiga-elf-objdump --count rt_irq --count deliver --count
  plat_present`. A capture is 1.1 GB: delete it after the report.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop.
- **Stops are free (S0).** Fields from `rt_run_guest` to m1b-logo
  (`VGA_039AD`), 68020: 99–100 with no stop between (3 runs), 99–100 with
  110, 364 and 731 stops (5 runs). `amiga_io_frames` counts the fields
  inside I/O windows (host-timed disk I/O, 7–17 here); the total does not
  move because the guest waits on the PIT.

## 2. Baseline (commit c69b52b, 68020 + 8 MB Fast)

Reference (DOSBox-X, `cycles=fixed 12000`, m4): a drawn frame every 9 PIT
ticks ≈ 36 ms, ≈ 408K x86 instructions per frame. Whether that is CPU-bound
at 12000 cycles or paced is not measured.

**A1200 model: P ≈ 0.74 s per drawn frame** (display of changed rows of
published frames, D9; three runs, frame 4–11 intervals 33–44 fields,
median 37; demo flight starts at field ≈ 1290). Before it, with the whole
frame converted every 5th field: ≈ 4.2 s (median 210 fields). Machine
takeover (copper display, own VERTB/keyboard, DOS in I/O windows): same
period (medians 34, 35, 40 fields; demo flight from field ≈ 1280–1380);
Kickstart 2.8% → 1.0%, "no PC" 2.0%, runtime 16.3%.

**S2 (poll points skip `rt_irq` while IF = 0):** frames 4–11 in 252–253
fields vs 256–271 (control, same session; medians 36–37 vs 35–40), P ≈
0.73 s; `rt_irq` entries per 100 flight fields 6752–9343 → ≈ 1030 (474
deliveries both); `rt_irq_c`/`load_regs`/`save_regs`/`rt_irq` 8.6–11.7%
→ 1.9%; runtime 16.4–18.0% → 9.1%, guest code 86%. Demo flight starts at
field ≈ 855 instead of ≈ 1270 (SPAZ's OPL loading under CLI).

**S3 (REP fast paths, D11):** frames 4–11 in 196 fields vs 252–253
(three identical runs; median 26 vs 36–37), **P ≈ 0.52 s**; RTSVGA 8% →
3.7% (`repe cmpsw` `VGA_03BE9` 1.6%), `rep stosw` `R_0C1CA` 1.2%; guest
code 87.6%, runtime 7.9%; cell walk `SWOTL+06A4D` 14.1%.

Steady flight window (100 fields after frame 11):

| Class | Share | Note |
|---|---|---|
| generated guest code | 79.6% | SWOTL 46% (cell walk `SWOTL+06A4D` 11%), FLIGHT 19%, RTSVGA 8% (`repe cmpsw` 4.9%); 13–18 cycles per guest instruction |
| runtime / platform | 14.7% | `rt_irq` entered 6878×, 474 deliveries: ≈ 6400 entries deliver nothing |
| Kickstart | 2.8% | |
| c2p | 1.8% | 3 presents |
| IRQ transitions | 1.1% | |

Other windows: SPAZ loading OPL registers inside CLI (attract): `rt_irq`
12,895× for 502 deliveries, ≈ 17% of the CPU in `save_regs`, `rt_irq_c`,
`load_regs`. Menus: RTSVGA `repe cmpsw` 3.3% at 49 cycles per guest
instruction.

Per drawn frame (m4 host census): `repe cmpsw` `VGA_03BE9` 19,290 words
(the whole view vs the previous frame), `rep stosw` `R_0C1CA` 16,075 words
(63 × 255), `repne cmpsw` 150, `rep movsw` `VGA_03C2D` 151 words to A0000h
(≈ 300 bytes, median 6 rows). m5: A0000h also from `rep stosb`
(`VGA_03E7A` 38%, `VGA_04085` 20% of bytes) and `rep movsb`.

**Ceiling.** The frame is now almost all guest work: ≈ 650K guest
instructions per drawn frame at 13–18 cycles each. S4 prices what
is left (runtime 8%, the cell walk 14%); reaching the reference needs far fewer cycles
per guest instruction, and the user sets the bar (perf-method §1.3) before
work past S4.

## 3. Steps

Re-measure after each step and reprice the rest before starting the next.

### Priced, below 2% of P (not planned)

Interrupt delivery 3.6% for 474 deliveries per 100 fields (`rt_irq_c`
0.9, `load_regs`/`save_regs` 0.8 (any C call), `push_frame` 0.4,
`deliver` 0.4, `rt_flags_word` 0.4, `guest_vector` 0.35, glue 0.4): vector
bounds cached per IVT write and the flags word in asm would save ≈ 1–1.5%;
`rt_lookup` + dispatch 1.3% (a CS:IP cache); port output 0.8% (SPAZ OPL);
VRAM marks 0.85%. "No PC" 2.4% (outside the executable and ROM): find
it before pricing (SetPatch's RAM patches of Exec calls such as
`Disable`/`Enable`?).

### Beyond the plan

Continued in [translator-plan.md](translator-plan.md) (target, authority,
steps T1–T9). The cell walk cache is a D16 design change the user has not
approved.

## 4. Rejected

(One line per rejected arm: step, change, measured, reason.)

- S1 shape "compare each present against a shadow copy to find changed
  rows": rejected by the user before building; every present would read
  the whole 64000-byte frame. Replaced by marks at the driver's stores
  (D9, translator-design Display).
- S5 "cell walk: mov cells four at a time under one bound check, opcode
  of each still compared" (27% fewer 68k instructions per cell): walk
  14.1% → 12.0%, frames 4–11 191–201 fields vs 196 (P unchanged); priced
  5% of P. The cells' operand reads and stores, not the loop overhead,
  carry the walk's cost.
