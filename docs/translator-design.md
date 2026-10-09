# Translator design

Skeleton for phase 5 on (phases 3–4 done: decoder, IR, 68020 backend; phase 5 done: runtime, host and A1200 runs to the logo frame). Fixed parts are decided; decision points D1–D16
list options, the evidence that settles them (from
[plan-reference-map.md](plan-reference-map.md)) and the default if evidence
does not object. Replace each decision with its outcome when settled.
Overview and guardrails: [architecture.md](architecture.md).

## Fixed

### Components

| Module | Role |
|---|---|
| `translator/image.py` | proved root/overlay images (`tools/swotl_model.py`), annotations, run-time bytes of self-modified regions |
| `translator/decode.py` | own table-driven 8086 decoder; 186+/FPU opcodes raise (none in SWOTL) |
| `translator/cfg.py` | recursive descent from `annotations/` seeds; CS along flow; PLINK manager calls and parent chain; self-modified regions recorded, not decoded |
| `translator/ir.py`, `sem.py` | IR ops; lifting of every decoded instruction |
| `translator/interp.py` | host IR interpreter (the semantics under test) |
| `translator/gen.py` | `make gen`: `build/gen/<module>.ir` with hash header; coverage report (G6) |
| `translator/check.py` | G1 header/digest/regeneration check, G2 lint |
| `translator/lower.py` | one decoded instruction -> 68020 text under the register contract (templates per op family; the IR stays the semantic reference) |
| `translator/flags.py` | flag demand: per-instruction store set and CCR fusion with the next reader |
| `translator/emit.py` | program mode: global flag liveness, per-function return sets, leaders, labels, transfers, `build/gen/<module>.s`, `program.s` (assembly root, dispatch table) |
| `translator/support.py` | state-block equates, flag/BCD helpers (`build/gen/support.s`) |
| `src/runtime/` | runtime (C + `rt_entry.s`): machine model of the reference (PSP, environment, MCBs, IVT values), EXEC of `SWOTL.EXE`, INT 21h/10h/67h services, `rt_*` entries, dispatch lookup with PLINK residency; platform interface `platform.h` |
| `src/platform/host/`, `src/platform/amiga/` | `platform.h` for Unicorn (harness-served stubs) and AmigaOS (dos.library, private native stack) |
| `tests/` | `host_run.py` (generated program + runtime on Unicorn 68020 to a milestone vs the reference; `--amiga` capture; `--sabotage`), `test_decode.py` (Capstone), `x86_diff.py` + `x86_sabotage.py` (Unicorn x86-16), `m68k_diff.py` (instructions/short blocks, test mode) + `m68k_blocks.py` (generated program, traced blocks) + `m68k_sabotage.py` (Unicorn 68020), `test_guards.py` (G1/G2 plants), `audit.csv` (audit expectations), `uc.py` (ctypes binding) |

Language: Python 3.11 (sibling tooling, Capstone binding present). Offline,
so translator speed is irrelevant.

### IR

Specification in `translator/ir.py`. Per instruction: an op list over
width-typed temporaries with local labels (REP loops, CL-count guards,
divide checks), explicit stack traffic, and one exit (`jump`, `call`,
`ret`, far forms, `int`, `fault`) or fall-through. Flags: `flags kind w a b
r` defines the status flags of `kind` and marks the undefined ones
(`FLAG_KINDS`; count-dependent for shifts/rotates); reading an undefined
flag is an error, never a value. Guest registers 16-bit with explicit
8-bit halves; segment registers separate; FLAGS bits 12–15 as `flagsx`.
Listings in `build/gen` carry `(module, offset, CS:IP)` per instruction.

### Generated code contract

Registers (D4, fixed program-wide; spill audit 0):

| 68k | Guest | Rule |
|---|---|---|
| d0 d1 d2 d3 d4 d5 | AX CX DX BX SP BP | 16-bit, upper word always 0; SP and BP mirrored: offset ^ 7FFFh |
| a4 a5 | SI DI | same (not mirrored); written via `movea.l` of a cleaned value |
| a1 a2 a3 | ES SS DS base | a6 − seg*16 − 7FFFh, recomputed on every segment write |
| a6 | guest RAM | TOP = linear 0, byte-exact and reversed (linear L at TOP − L); state block above |
| d6 d7 a0 | scratch | a0 also CS base (`lea (-cs*16-7FFFh,a6)`); CS is static per instruction |
| a7 | native stack | `jsr`/`rts` only |

State block (`G_*` equates at a6+1..a6+16): `G_FL` low byte = CCR image of
CF (C), OF (V), ZF (Z), SF (N), X not guest state; PF = even parity of
`G_PF`; AF = bit 4 of `G_AF`; `G_DF`/`G_IF`/`G_TF` bytes; `G_FX` = FLAGS
bits 12–15; `G_ES`/`G_SS`/`G_DS` segment values. Run-time CS =
`LOADSEG+link`, `LOADSEG` = 0822h (the reference load segment, so guest RAM
diffs directly); relocated words in instructions are emitted as
`LOADSEG+value`.

- Memory (D1, speed-plan R1): a little-endian word at linear L is the native
  word at TOP − L − 1 (68020 allows odd addresses), no byte swaps. The byte
  at offset o is `(7FFFh−o,aS)`, the word `(7FFEh−o,aS)`; a computed offset
  is mirrored into d7 (`move.w #7FFFh−disp` / `sub.w Rn`, or from a mirrored
  register `move.w Rn` / `sub.w #disp`) and indexes as `(0,aS,d7.w)` /
  `(−1,aS,d7.w)`, keeping the 16-bit wrap; SP/BP alone index directly. A word
  at offset FFFFh is two consecutive linear bytes. Push is `addq.w #2,d4` +
  `move.w v,(−1,a2,d4.w)`. SP/BP as values convert with `eori.w #$7fff`
  (dead-flag add/sub/inc/dec, NOT and `or/and/test r,r` stay in place).
  Byte and word memory operands fold into the 68k op (source, read-modify-
  write destination, INC/DEC/NEG/NOT, CMP with an immediate) where AF and
  PF are dead.
- Flags (D6): a setter stores the defined flags live after it (`flags.py`,
  global liveness in `emit.py`). The next instruction reads the CCR directly
  when it is not a leader, reads only flags the setter's 68k op holds with
  x86 meaning (`CCR_OK`), and the setter's tail leaves the CCR intact; else
  readers load `G_FL`. PF/AF are stored as result / `a^b^r` bytes only when
  live. adc/sbb/rcl/rcr derive X from `G_FL` and preset Z for `addx`/`subx`.
- Calls (D1): the guest stack stays byte-exact (return CS:IP pushed as the
  CPU does); a guest call is `jsr`, `ret`/`retf` pop into d7/d6 and `rts`;
  the return site checks d7 (and d6) against its own IP/CS and jumps to
  `rt_ret_mismatch` otherwise. A PLINK manager call's return site is 2 bytes
  later (the manager advances the return IP).
- Indirect transfers (D7): compare chain over the known targets
  (`annotations/indirect.csv`); a proved switch table falls back to
  `rt_stop_unknown`, other sites to `rt_dispatch_near`/`rt_dispatch_far`
  (target in d7, CS in d6). Table rows (`program.s`): the cfg seeds (MZ
  entry, PLINK thunks, `runtime.csv`, `indirect.csv` targets) as (CS, IP,
  overlay id, label); overlays sharing an area share CS:IP, so the row whose
  overlay is resident (PLINK record bit 15) wins; anything else stops.
- Runtime entries (`jsr`, contract in registers): `rt_int` (d7 next IP, d6
  CS << 16 | vector; the runtime writes the CPU's IRET frame below SS:SP;
  services read no guest flags and leave undefined-by-them flags in the
  state block; a vector pointing into the program's memory runs the guest
  handler on that frame), `rt_fault` (same d6/d7; returns to re-execute),
  `rt_in8/16`, `rt_out8/16` (d7 port, d6 value), `rt_halt`,
  `rt_stop_unknown` (prints and halts; never resumes).
- Returns: a `ret` continues at the return sites of the calls whose targets
  reach it without entering a call (the divide-error edge is not flow);
  calls through the dispatcher return from any `ret` a table row reaches.
- Generated files: `build/gen/<module>.s`, `support.s` and `program.s`
  (equates, runtime xrefs, includes, dispatch table, `load_segment`,
  `overlay_table`), header = SHA-256 of translator sources, annotations and
  input image (`make gen-check`). One assembly unit (`vasm -Felf`), linked
  with the runtime: `make host` (`build/host/swotl.elf`), `make amiga`.
- Overlays (D2 = a): every translated module resident in native code; the
  guest's own PLINK manager runs translated and loads the overlay bytes into
  guest RAM (data, CS-relative reads, RAM equal to the reference).
- Memory (D15 = b): Fast RAM required (1.44 MB code + 1.06 MiB guest RAM);
  the A1200 model runs with 8 MiB Fast; development runs set `--cpu=68030`
  (`AMIGA_CPU`, ~3× the 68020: logo at 80 vs 252 frames); timing runs
  leave it unset (68020).

### Annotations (`annotations/`, CSV)

`entries.csv`, `indirect.csv` (site -> targets; written by `make map`),
`tables.csv` (cs: word tables sized by evidence other than an MS C bounds
check, read by the sweep), `data.csv` (ranges),
`hle.csv` (guest range, service, reason, oracle; starts empty), `names.csv`
(name, evidence class).

### Tests

- Instruction differential (`make test-m68k`): the x86 corpora (forms,
  space, boundary, blocks) lowered in test mode (every exit through a stub,
  all flags live at the end), Unicorn x86-16 vs Unicorn 68020 on the same
  guest-memory layout; registers, segments, CS:IP, defined flags, FLAGS
  12–14, memory, OUT sequence, interrupt/fault.
- Block differential (`make test-blocks`): the generated program as emitted,
  run from executed leaders to the first transfer with random states; flags
  compared where live at the successor reached; calls also run the return
  protocol (right IP reaches the return site, wrong IP `rt_ret_mismatch`).
- Host run (`make test-host`, gate 5): `build/host/swotl.elf` on Unicorn
  68020 from the MZ entry to milestones m1–m3 (`make test-host-all`: m1–m7
  and c6-flight-keys, whose film recorder writes files, kept in memory;
  ~6 min); every software
  INT's registers at entry and return vs the tracer's service log; registers
  and RAM (environment MCB to A0000h) vs the snapshot, dead stack masked
  (below SS:SP at a service, and the FLAGS image of an `annotations/flags.csv`
  PUSHF, until the guest rewrites it); at m1b-logo the A0000h window and the
  DAC; machine bytes the guest read hold reference values. `make
  test-amiga`: the same at m1b-logo on the A1200 model (FS-UAE,
  `amiga/milestone.gdb.in`), plus the shown screen (bitplanes, colour
  table) decoded against the reference framebuffer and DAC.
- Display (D9 slice): only the graphics driver (`emit.GRAPHICS_DRIVER`,
  RTSVGA) writes video memory. Before each of its memory stores the
  lowering checks the segment for A000h and calls `rt_vram_mark` (offset,
  bytes; `rep stos/movs` once for the whole run), which widens per-row
  changed columns; a store with no driver call in progress stops. The `jmp
  far` of each PLINK thunk into the driver is a `jsr` counted in
  `rt_vdrv_depth`; the outermost return publishes the frame
  (`rt_vdrv_return`). A published frame's changed rows go to `plat_present`
  as 32-pixel-aligned rectangles at the first vertical blank after it
  (`rt_present_due`) while no driver call runs; mode set marks the whole
  frame; DAC block sets go to `plat_palette` at once. No frame is read to
  find changes. Amiga (machine taken over, `Swotl.cpp`): an 8-plane copper
  display (framework `CopperList`/`Bitmap`), Kalms `c2p1x1_8_c5_bm` per
  rectangle (one call per full-width band, per row otherwise) into the
  shown bitmap (`amiga_bitmap`), the copper's 24-bit palette MOVEs
  rewritten per DAC change (`amiga_colours` keeps the LoadRGB32-layout
  table). Checked by the host run (every byte the guest stores
  to A0000h lies in the next present's rectangles; sabotage `vram`) and
  `amiga/display_audit.gdb` + `tests/display_audit.py` (after a present the
  shown bitplanes equal guest A0000h).
- Interrupts (D8): poll points at loop heads (targets of backward branches,
  all block leaders, so live flags are in the state block): `tst.b G_IRQ(a6)`
  then `rt_irq` (d6 = CS << 16, d7 = IP). The platform raises `G_IRQ` and
  `rt_irq_pending` together (`RT_RAISE_IRQ`); with IF clear `rt_irq` clears
  `G_IRQ` only, and `sti`, `__set_flags` (POPF, IRET) and
  `rt_set_flags_word` re-arm it from `rt_irq_pending` when they set IF
  (checked in the 68020 differential and `host_run.py rearm_problems`;
  sabotage plants). With guest IF set posted interrupts run in order: a guest handler (`annotations/entries.csv`) on a pushed
  frame, else the BIOS one (INT 08h ticks; INT 09h takes the next
  `rt_key_ring` event, a set 1 scan code with break bit and E0 flag, as
  DOSBox-X's IRQ1 handler does: its scan-code table, shift and lock flags,
  words like `48E0`/`xxF0` in the buffer, which DOS AH=08h converts as its
  CON device over INT 16h AH=10h);
  a guest handler's `jmp far` to F000:FEA5 is the BIOS tick plus IRET
  (`rt_bios_int08`). INT 33h is DOSBox-X's driver with the mouse captured
  (8/16 mickeys per 8 pixels, 640x200, mode 13h X even) over `plat_mouse`
  counts, the Amiga's JOY0DAT deltas taken at each vertical blank. The platform posts vectors to `rt_irq_ring` (08h tick,
  09h/89h key make/break): Amiga a CIA-B timer per PIT period
  (`plat_timer_rate`) and the CIA-A keyboard interrupt (`Input.cpp`: raw
  key -> scan code, PC typematic repeat from the vertical blank; diagnostic
  argument `KEYS=when:key,...` feeds keys, `lmb`/`rmb` and `mx±N`/`my±N`
  into the same paths at a frame or `pN`, N
  guest mouse reads after the previous step (host load moves frame
  timings), and `shot`/`quit` call `amiga_script_mark` for a gdb fixture;
  `SWOTL_ARGS` in `amiga/debug.sh`); host run the reference's `irq` events, replayed at the
  same visit of the same poll point after the same service event, one of a
  same-visit group per return of the guest handler to that poll point (the
  reference takes interrupts only at poll points, `build/gen/poll-points.csv`;
  references are re-recorded when poll points change).
- Self-modified code (D16, `translator/smc.py`): the root block
  `+6A4D..+89FD` is one generated cell walk. The setup (+E50E) writes opcodes
  as well as operands, and the shape (cell counts [2587]/[2591], reload position) varies,
  so cells are matched at run time against the forms the writers produce
  (`annotations/self-modifying.csv` kind `form`: `mov [bx+w],al`, the
  `bx`/`ds` reload, the planted `ret`), each checked against the decoder,
  operand words read from guest RAM; anything else stops. `call dx` sites
  range-check into the walk. The EGA/Tandy and/or variant ([2581]=0) is out
  of scope. Checked by `make test-blocks` (walks over every snapshot image
  vs x86).
- Audits (`make gen`): spills, full-flag materializations, PF/AF stores,
  dispatcher exits, `stop_unknown` sites against `tests/audit.csv` (above
  expected fails), plus flag stores/merges/loads and return checks; HLE count.

## Decision points

| # | Decision | Options | Evidence | Default |
|---|---|---|---|---|
| D8 | Interrupt delivery | (a) runtime runs translated guest ISRs at safe points (loop back-edges, calls); (b) HLE of the game's ISRs | [external-surface.md](external-surface.md): guest installs INT 00h/05h/08h (SPAZ tick)/23h/24h; INT 09h/1Ch stay BIOS | (a) |
| D9 | Graphics drivers | (a) HLE at RTSVGA's call table on the dA JoRMaS layer; (b) translate driver + emulate VGA ports/memory | chained mode 13h via INT 10h, no VGA ports, no page flip; entries = PLINK thunks with id 3 | (a), with RTSVGA itself as oracle |
| D10 | Sound | SPAZ HLE at its table; AdLib music method open (OPL -> Paula) | 2.5; open-work AdLib item | HLE |
| D11 | String ops | per-element loops, one body per DF; REP with DF = 0, CX ≠ 0 and SI/DI + size × CX < 10000h: host pointers descending (base + 8000h − offset), `move -(a4),-(a5)` / `move d,-(a5)` / `move -(a4),d6` + `cmp -(a5),d6` / `cmp -(a5),d` with `db<cc>`, last pair's flags recomputed (done) | boundary corpus (guard and stop edges, overlap), sabotage | done |

