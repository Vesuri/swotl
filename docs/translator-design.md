# Translator design

The translator, runtime and test contract as built. Decisions D1–D16 are
settled where this file states them (D1 memory and calls, D2 overlays, D4
registers, D6 flags, D7 indirect transfers, D8 interrupts, D9 display, D11
strings, D15 memory, D16 self-modified code, D10 sound at the end); speed-plan
§8's decisions are cited as "speed-plan Dn". Speed forms are indexed in
[speed-plan.md](speed-plan.md) §7. Overview and guardrails:
[architecture.md](architecture.md).

## Fixed

### Components

| Module | Role |
|---|---|
| `translator/image.py` | proved root/overlay images (`tools/swotl_model.py`), annotations, run-time bytes of self-modified regions |
| `translator/decode.py` | own table-driven 8086 decoder; 186+/FPU opcodes raise (none in SWOTL) |
| `translator/cfg.py` | recursive descent from `annotations/` seeds; CS along flow; PLINK manager calls and parent chain; self-modified regions recorded, not decoded |
| `translator/ir.py`, `sem.py` | IR ops; lifting of every decoded instruction |
| `translator/interp.py` | host IR interpreter (the semantics under test) |
| `translator/gen.py` | `make gen`: `build/gen/<module>.ir` with hash header; coverage report (G6); sizes the R8 alignment pads by assembling the program (vasm) |
| `translator/check.py` | G1 header/digest/regeneration check, G2 lint |
| `translator/lower.py` | one decoded instruction -> 68020 text under the register contract (templates per op family; the IR stays the semantic reference) |
| `translator/flags.py` | flag demand: per-instruction store set and CCR fusion with the next reader, or one past plain instructions |
| `translator/region.py` | BP-stable components, their direct-access range and guards (speed-plan R6) |
| `translator/reuse.py`, `compact.py`, `reglive.py` | run-local rewrites: repeated index/base formations (R13), folded displacements (R14f), native BP (R25), push/pop runs (R31); word-mask compaction within an instruction (R4); DX liveness within a block (word MUL/DIV store DX only where live) |
| `translator/smc.py` | self-modified region as a run-time cell walk with cell cache (D16, below) |
| `translator/compute.py` | admission and emission of `kind=compute` HLE rows ([native-compute.md](native-compute.md)) |
| `translator/emit.py` | program mode: global flag liveness, per-function return sets, leaders, labels, transfers, `build/gen/<module>.s`, `program.s` (assembly root, dispatch table) |
| `translator/support.py` | state-block equates, flag/BCD helpers (`build/gen/support.s`) |
| `src/runtime/` | runtime (C + `rt_entry.s`): machine model of the reference (PSP, environment, MCBs, IVT values), EXEC of `SWOTL.EXE`, INT 21h/10h/16h/33h/67h services, `rt_*` entries, dispatch lookup with PLINK residency; platform interface `platform.h` |
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
| d0 d1 d2 d3 d4 d5 | AX CX DX BX SP BP | low word; upper word undefined (speed-plan R4); SP and BP mirrored: offset ^ 7FFFh |
| a4 a5 | SI DI | same (not mirrored); `movea.w` loads, dead-flag add/sub/inc/dec in place |
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

- Upper words (speed-plan R4): a lowering that reads a guest register's 32
  bits zero-extends it first (`read_zx`: segment loads, the cell walk's entry
  IP from an indirect call); the REP fast path converts SI/DI from their low
  words; the runtime masks what it takes.
- Segment loads in `annotations/seg-repeat.csv` (R30) compare the new value
  with `G_xS` first; only a change stores it, checks the cell caches and
  rebuilds the base, out of line (`lower.putseg_repeat`).
- Memory (D1, speed-plan R1): a little-endian word at linear L is the native
  word at TOP − L − 1 (68020 allows odd addresses), no byte swaps. The byte
  at offset o is `(7FFFh−o,aS)`, the word `(7FFEh−o,aS)`; a computed offset
  is mirrored into d7 (`move.w #7FFFh−disp` / `sub.w Rn`, or from a mirrored
  register `move.w Rn` / `sub.w #disp`) and indexes as `(0,aS,d7.w)` /
  `(−1,aS,d7.w)`, keeping the 16-bit wrap; SP/BP alone index directly. A word
  at offset FFFFh is two consecutive linear bytes. Push is `addq.w #2,d4` +
  `move.w v,(−1,a2,d4.w)`. A run of four or more pushes (pops) with no leader
  between steps SP once in its first instruction, `bvs` (only that step can
  overflow d4.w: the run wraps SS:0) to the exact lines out of line; the rest
  address from the final SP (`reuse.stack_runs`, R31; R29 for CALLF's long
  push). SP/BP as values convert with `eori.w #$7fff`
  (dead-flag add/sub/inc/dec, NOT and `or/and/test r,r` stay in place).
  Byte and word memory operands fold into the 68k op (source, read-modify-
  write destination, INC/DEC/NEG/NOT, CMP with an immediate) where AF and
  PF are dead.
- BP regions (speed-plan D2 and R6, `region.py`): a BP-stable component (the
  code after a BP write up to the next, calls continuing at their return
  site) chosen in `annotations/bp-regions.csv` (`tools/bp_regions.py`, from
  a meter run) gets a guarded copy (`<label>_bp`) in which `[bp+d]` and far
  pointers at `[bp+d]` are `(−d,aS,d5.w)` / `(−d−1,aS,d5.w)`: d5.w
  sign-extends to 32767 − BP, so this is exact while 0 ≤ BP + d ≤ FFFFh.
  One range check on d5.w covers every displacement of the component: at
  its entry after the BP write (`<S>_bpg`) and after each call or software
  interrupt in it (`<S>_bpr`); a failure continues in the exact code, as do
  exits, BP writes, poll stubs and divide-error retries. Entries, those
  return points and where a copy run falls into the exact code are leaders (a
  guard clobbers the CCR; the run passes start afresh there). Tools that hook an
  instruction's label (host run) hook its copy too.
- Flags (D6): a setter stores the defined flags live after it (`flags.py`,
  global liveness in `emit.py`). The next instruction reads the CCR directly
  when it is not a leader, reads only flags the setter's 68k op holds with
  x86 meaning (`CCR_OK`), and the setter's tail leaves the CCR intact; else
  readers load `G_FL`. Plain instructions (no flags, no transfer) may stand
  between the two (speed-plan R3b). Their 68k lines keep the CCR, or the
  last one that changes it moves the setter's result register at its width
  (unchanged since), which leaves N and Z equal to SF and ZF. PF/AF are
  stored as result / `a^b^r` bytes only when live. adc/sbb/rcl/rcr take CF
  from X when the instruction before (not across a leader: add, sub, adc,
  sbb, neg, shifts) leaves X = CF, else from `G_FL`; an adc/sbb operand
  setup that changes X keeps it in d6 (`subx.b d6,d6` first, `add.b d6,d6`
  before the setup's load into d6, R28). Z is preset for `addx`/`subx`.
- Strings (D11): per-element loops, one body per DF; the backward body is
  out of line and rejoins the forward body's continuation (R21). REP with DF = 0,
  CX ≠ 0 and SI/DI + size × CX < 10000h takes a fast path with host pointers
  descending: `move -(a4),-(a5)`, `move d,-(a5)`, `move -(a4),d6` + `cmp
  -(a5),d6` or `cmp -(a5),d` with `db<cc>`, the last pair's flags
  recomputed. REP STOSW and REPE CMPSW move or compare two words per
  `move.l`/`cmp.l` (speed-plan R12: an odd element alone, a mismatching
  long's guest-first word first), eight longs per pass (R24: STOSW stores
  a first word to long-align; R26). Checked by the boundary corpus (guard and
  stop edges, overlap) and sabotage plants.
- Calls (D1): the guest stack stays byte-exact; a guest call is `jsr` and
  returns with `rts`. Near returns carry IP in d7.w; RETF and IRET carry
  CS:IP in d7.l (R33). RETF pops one long after a word SP step guarded by
  overflow; a wrap pops the two words out of line, wrapping SP between
  them. IRET pops flags and words separately, then packs the pair.
  Return sites compare the near word or far long and branch to a module-local
  `<tag>_rm<n>` trampoline after a run that cannot fall through. Far failure
  normalizes CS into d6 before the fail-loud diagnostic. A PLINK
  manager call's return site is 2 bytes later (the manager advances the IP).
- Indirect transfers (D7): compare chain over the known targets
  (`annotations/indirect.csv`); a proved switch table falls back to
  `rt_stop_unknown`, other sites to `rt_dispatch_near`/`rt_dispatch_far`
  (target in d7, CS in d6). The first walk call falls through to its return
  check; its remaining targets and fallback are out of line, with both walk
  range checks retained (R22). Table rows (`program.s`): the cfg seeds (MZ
  entry, PLINK thunks, `runtime.csv`, `indirect.csv` targets) as (CS, IP,
  overlay id, far, label); overlays sharing an area share CS:IP, so the row whose
  overlay is resident (PLINK record bit 15) wins; anything else stops.
  `far` = 0 for a row seeded only as a target of indirect near `jmp`/`call`
  sites: `rt_dispatch_far` (and interrupt delivery, the guest entry) stops
  there (R14e).
- Layout: runs in offset order, stubs (poll, cold paths) after a run that
  cannot fall through. A forward jcc listed in `annotations/outline.csv`
  (R27) branches, inverted, to its fall-through range, which goes first among
  the stubs after the next closing transfer and ends with `bra` to the target
  unless it ends in a transfer; every instruction keeps its lowering.
  `build/gen/outline-sites.csv` lists every eligible site and where its range
  would go.
- Runtime entries (`jsr`, contract in registers): `rt_int` (d7 next IP, d6
  CS << 16 | vector; the runtime writes the CPU's IRET frame below SS:SP;
  services read no guest flags and leave undefined-by-them flags in the
  state block; a vector pointing into the program's memory runs the guest
  handler on that frame), `rt_fault` (same d6/d7; returns to re-execute),
  `rt_in8/16`, `rt_out8/16` (d7 port, d6 value), `rt_halt`,
  `rt_stop_unknown` (prints and halts; never resumes).
- Returns: a `ret` continues at the return sites of the calls whose targets
  reach it without entering a call (the divide-error edge is not flow);
  calls through the dispatcher return from any `ret` a table row reaches
  (far calls: a far row, R14e).
- Generated files: `build/gen/<module>.s`, `support.s` and `program.s`
  (equates, runtime xrefs, includes, dispatch table, `load_segment`,
  `overlay_table`), header = SHA-256 of translator sources, annotations and
  input image (`make gen-check`). One assembly unit (`vasm -Felf`), linked
  with the runtime: `make host` (`build/host/swotl.elf`), `make amiga`.
- Overlays (D2 = a): every translated module resident in native code; the
  guest's own PLINK manager runs translated and loads the overlay bytes into
  guest RAM (data, CS-relative reads, RAM equal to the reference).
- Memory (D15 = b): Fast RAM required (1.36 MB code at R34 + 1.06 MiB guest RAM);
  the A1200 model runs with 8 MiB Fast; development runs set `--cpu=68030`
  (`AMIGA_CPU`, ~3× the 68020: logo at 80 vs 252 frames); timing runs
  leave it unset (68020).

### Annotations (`annotations/`, CSV)

`entries.csv`, `indirect.csv` (site -> targets; written by `make map`),
`tables.csv` (cs: word tables sized by evidence other than an MS C bounds
check, read by the sweep), `runtime.csv` (MS C runtime entries: name,
class, evidence), `self-modifying.csv` (D16 regions and cell forms),
`flags.csv` (PUSHF/POPF pairs that only save and restore FLAGS),
`hle.csv` (guest range, service, reason, oracle; below), `align.csv`
(R8 pads; `tools/align_targets.py`), `bp-regions.csv` (BP writes whose
component gets a guarded copy; a profile choice, `tools/bp_regions.py`),
`outline.csv` (forward jcc whose fall-through range goes out of line, R27;
a profile choice, `tools/outline_sites.py` from `build/gen/outline-sites.csv`),
`seg-repeat.csv` (segment loads that compare first, R30; a profile choice,
`tools/seg_repeat.py`), `irq-bounds.csv` (value bounds of variables that index
the IRQ0 handler's accesses, and class extents, I2), `irq-ds.csv` (entries that return the
caller's DS where the I2 analysis cannot see it; host runs check, I3) and `irq-sync.csv`
(monitored accesses the I3 monitor found meeting the footprint: sync for the declared span).

### Tests

- Instruction differential (`make test-m68k`): the x86 corpora (forms,
  space, boundary, blocks) lowered in test mode (every exit through a stub,
  all flags live at the end), Unicorn x86-16 vs Unicorn 68020 on the same
  guest-memory layout; registers, segments, CS:IP, defined flags, FLAGS
  12–14, memory, OUT sequence, interrupt/fault. A case with a direct
  `[bp+d]` form also runs behind a region guard (copy, exact fallback).
- Block differential (`make test-blocks`): the generated program as emitted,
  run from executed leaders to the first transfer with random states. Every
  branch to an instruction's label targets a leader (copy exits, divide-error
  retries: `lower.exit_fault` re-executes the instruction), except exact code
  branching to its own fall-through (R27). Guest CFG
  exits remain stopping boundaries when a zero-code jump aliases its target;
  direct zero-code entries stop without executing the target. Each outlined
  jcc (R27) runs from the leader that falls into it, and its fall-through
  range as paths from there (registers and the words a path loads at edge
  values or its immediates; cases taking a jump on the way are skipped). Flags
  compared where live at the successor reached (at a cell walk: live at the
  transfer; the walk reads no flags); calls also run the return protocol
  (right IP/CS reaches the return site, wrong IP or CS reaches the mismatch
  handler; near IP’s upper word random, far CS:IP packed). Register calls and jumps that
  can enter a self-modified region also run with the target in each region.
  Every executed block of a guarded copy runs with BP at both ends of the
  range its guard admits and inside it; every guard runs just inside and
  outside that range. Every `annotations/tables.csv` row also runs from
  its call site to the target read from the original table, then every
  reachable block runs against x86, including untraced targets.
- File dates (`tests/test_file_dates.py`): live DOSBox-X find-first/next
  over synthetic files verifies Amiga DateStamp conversion and runtime
  DTA time/date, including leap centuries, pre-1980 wrapping and odd seconds.
- Host run (`make test-host`, gate 5): `build/host/swotl.elf` on Unicorn
  68020 from the MZ entry to milestones m1–m3 (`make test-host-all`: m1–m7,
  the Makefile's `HOST_COVERAGE` scenarios and `t-hle-music-skip`; files the
  guest writes are kept in memory); every software
  INT's registers at entry and return vs the tracer's service log; registers
  and RAM (environment MCB to A0000h) vs the snapshot, dead stack masked
  (below SS:SP at a service, and the FLAGS image of an `annotations/flags.csv`
  PUSHF, until the guest rewrites it); at m1b-logo the A0000h window and the
  DAC; machine bytes the guest read hold reference values; every guest
  access against the IRQ0 footprint (`tests/irq_monitor.py`, irq-plan I3:
  handler accesses inside it, main accesses meeting it only from sync
  instructions, IF clear or services; record `tmp/test/irq-monitor-<run>.json`).
  `make test-amiga`: the same at m1b-logo on the A1200 model (FS-UAE,
  `amiga/milestone.gdb.in`), plus the shown screen (bitplanes, colour
  table) decoded against the reference framebuffer and DAC.
- Amiga replay (`make test-amiga-replay`, also in `make gates`): separate
  diagnostic images for m2-choose-side, m5-player-flight, c9-mouse-menu,
  c66-flight-calibration and c85-joystick-calibration.
  Translator hooks preserve native registers/CCR and split diagnostic
  entries at block boundaries; the normal generated bodies are unchanged.
  `tests/amiga_replay.*` replays DOSBox input and interrupt groups at their
  recorded poll visits/service counts through the production IRQ glue.
  Every service prefix checks registers, segments, vector, IF and DF;
  final counts, guest state, DAC and shown bitplanes must match the original.
  The final guest state is held while its queued frame reaches the VBI.
  Only diagnostic builds disable physical input and the CIA timer; normal
  hardware, smoke and restoration gates remain mandatory. No reference,
  poll point, normal interrupt order or PIT rate changes.
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
  inactive bitmap. Both bitmaps retain dirty rows since their own last
  conversion. A pending frame is withdrawn before reuse; updates can
  coalesce without waiting before a guest poll. Each bitmap has a complete
  copper list and palette. VERTB switches lists before input, only at beam
  lines below 8; a late VBI defers the handoff. `amiga_bitmap` and
  `amiga_colours` describe the handed-off frame. Checked by the host run
  (every guest A0000h store lies in the next present's rectangles; sabotage
  `vram`), `tests/test_display_queue.py` (inheritance and queue races), and
  `amiga/display_audit.sh` (40 handoffs against published guest snapshots
  and DAC, no conversion into the shown bitmap, zero late handoffs).
- Interrupts (D8; [irq-plan](irq-plan.md) removes poll checks from production code:
  asynchronous IRQ0, sync points delivered by the test harness): poll points at loop heads (targets of backward branches,
  all block leaders, so live flags are in the state block): `tst.b G_IRQ(a6)`
  and `bne` to the poll's stub `X_irq`, placed after the next run that cannot
  fall through: d6 = CS << 16, d7 = IP, `jsr rt_irq`, back past the test to
  `X_np` (the tools fold `X_np` into `X`; the block differential also runs
  every poll block with an interrupt posted). The platform raises `G_IRQ` and
  `rt_irq_pending` together (`RT_RAISE_IRQ`); with IF clear `rt_irq` clears
  `G_IRQ` only, and `sti`, `__set_flags` (POPF, IRET) and
  `rt_set_flags_word` re-arm it from `rt_irq_pending` when they set IF
  (checked in the 68020 differential and `host_run.py rearm_problems`;
  sabotage plants). With guest IF set posted interrupts run in order: IRQ0's guest
  handler (`annotations/entries.csv`) through `rt_irq_async` on the private guest
  stack `B000:8000` down (frame with the sentinel CS:IP `B000:8000` its IRET must pop;
  68k registers, state block and `rt_r` restored after it; nothing posted is taken
  until it returns, the PIC's in-service IRQ0, irq-plan I4), another
  guest handler on a pushed frame, else the BIOS one (INT 08h ticks; INT 09h takes the next
  `rt_key_ring` event, a set 1 scan code with break bit and E0 flag, as
  DOSBox-X's IRQ1 handler does: its scan-code table, shift and lock flags,
  words like `48E0`/`xxF0` in the buffer, which DOS AH=08h converts as its
  CON device over INT 16h AH=10h);
  a guest handler's `jmp far` to F000:FEA5 is the BIOS tick plus IRET
  (`rt_bios_int08`). INT 33h is DOSBox-X's driver with the mouse captured
  (8/16 mickeys per 8 pixels, 640x200, mode 13h X even) over `plat_mouse`
  counts, the Amiga's JOY0DAT deltas taken at each vertical blank. Recorded
  IRQ12 (74h) at the exact DOSBox-X external vector F000:D020 drains no
  guest callback: the supported INT 33h surface installs none and never
  shows the DOS driver cursor. Guest-installed vectors still dispatch;
  other external targets stop. `c9-mouse-menu` checks motion, buttons and
  these recorded interrupts; `test_mouse_irq.py` checks the IVT/IF edges.
  The platform posts vectors to `rt_irq_ring` (08h tick,
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
- IRQ0 footprint (irq-plan I2, `translator/irq.py`, run by `make gen`): the guest
  handler's memory, ports, IF changes, hooks and runtime calls, register
  transparency proved over the lifted IR; every main-code access classified
  masked, disjoint, sync (may meet the footprint) or monitored, with segment
  registers per (entry, DS, SS) context. A sync access to a handler-written
  byte lowers to one memory-touching 68k instruction, no compute row holds a
  sync access, bounded G variables keep their bound, else generation fails.
  Output `build/gen/irq-footprint.csv`; `t-irq-footprint` and its sabotage.
- HLE (`annotations/hle.csv`, G3): at a range's first instruction
  `jsr rt_hle_<service>`; NE skips to the instruction after `last`, EQ runs
  the guest code. `args`: up to two guest word registers (not SP, BP), in d7
  and d6. Both ends are leaders, the first's live-in includes the
  resume's, and a hook where the CCR holds live flags fails `make gen`. The
  block differential runs the guest path. Entries: `sfx_start` (observe
  only: SPAZ's effect start, BX = slot·6, DI = id·4 → `rt_sfx_id`,
  `rt_sfx_starts`; oracle `check_sfx` in every host run: each report equals
  the guest's store of DI after the hook; sabotage `sfx_start` on c6);
  `music_skip` (SPAZ song
  start, [sound-plan.md](sound-plan.md)): `rt_music_skip`, 0 by default
  (music enabled, user 2026-10-15; 1 skips) and 0 with the argument
  `MUSIC`; `amiga/debug.sh` passes `MUSIC` and host runs
  clear it, since the references hold the music. Oracle `make
  t-hle-music-skip` (in `test-host-all`): m2 with the skip on; the interrupt
  the reference took in the song code is posted at the next poll point;
  services and interrupts equal the reference, RAM too outside SPAZ's state
  (its data segment, its effect counts at DS:6564, dead stack below SP).
  Optional `kind=compute` uses the complete generated register ABI and a d7.l
  handled result; admission proves poll-free reachable flow, including callees.
  It leaves the guest return and check generated. With `polls` (U5) the row's
  body loses its polls in both arms, its return and listed sync sites become
  polls, and each sync site is a resume and a hook entry. U8: REP off the poll
  set, the divide-fault edge as a decline edge, every root return a resume
  (d7 dispatch), `end` for code past the return. Contract and oracle:
  [native-compute.md](native-compute.md). Enabled: the poll-free `B54B` transform.
- Self-modified code (D16, `translator/smc.py`): the root block
  `+6A4D..+8E2C` is one generated cell walk (the whole template block: the
  [2581]=0 variant fills it at 190 cells per run). The setup (+E50E) writes opcodes
  as well as operands, and the shape (cell counts [2587]/[2591], reload position) varies,
  so cells are matched at run time against the forms the writers produce
  (`annotations/self-modifying.csv` kind `form`: `mov [bx+w],al`, the
  `bx`/`ds` reload, the planted `ret`), each checked against the decoder,
  operand words read from guest RAM; anything else stops. Mov cells run
  counted (R7): the cells that fit before the bound are counted once, each
  still matched when it runs (one long read: opcode and operand). That
  exact walk (`_walk_x`) serves a cell cache (speed-plan D3, R20): a cell is
  matched once, when a walk first reaches it, and its bytes are covered; a
  mov cell records its operand and the end of its run of consecutive
  destinations, which the walk stores AL to a long at a time (under 8 bytes
  one by one, offsets wrapping at 16 bits one by one). Every store that may
  change a covered byte is seen: a CS store that may reach a region calls its
  hook after storing (`lower.code_store`; byte `mov`s plant or restore inline):
  a RET at a covered cell start is the walk's stop (one at a time), its first
  byte back ends it, anything else drops the cache. A DS, ES or SS value whose
  window reaches a region drops every cache where it is loaded
  (`lower.putseg`, the reload cells, the runtime's `load_regs`; reloading the
  value a segment holds changes nothing, R30), and so does a
  runtime store into a region (`rt_wrote`; bounds and segment limit from the
  program). A dropped cache is cleared at the next walk with no segment
  reaching a region; until then walks are exact, and so is the rest of a walk
  whose reload loads such a DS. Bytes not covered are read when reached: a
  RET returns, other cells are decoded or walked exactly. Unresolved
  near indirect transfers range-check every walk in their module and CS,
  regardless of traced targets; proved tables retain their closed target set.
  The graph includes the walk edge. If every decoded cell instruction preserves
  arithmetic flags, a call propagates its return site's live flags through the
  walk; otherwise all flags are live. Return checks remain in place. The EGA/Tandy and/or variant ([2581]=0) is out
  of scope. Checked by `make test-blocks` (walks over every snapshot image
  vs x86, through a dropped cache and exactly; per entry, mov cells to the
  bound and past it, a RET at the bound, unknown cells; warm walks between
  RET plants, restores and operand patches made by the hooks or by the
  lowered stores, and cells rewritten after a lowered segment load or
  `smc_expose`; RETs inside and at the ends of runs, 16-bit wraps, a DS
  reaching the region at the entry and from a reload, entries inside a cached
  cell) and `make t-cell-cache` (the runtime's notifications).
- Trap flag: the game never sets TF (its four POPF/IRET sites pop PUSHF or
  interrupt-frame images; no INT 1 and no TF in any reference). A popped
  image with TF set stops (IR exit `trap`, `rt_trap`; `rt_set_flags_word`
  likewise); no single-step delivery. Checked by the TF cases of
  `flag_extract_cases` (x86, 68k) and `flag_helper_entries` (POPF, IRET).
- Audits (`make gen`): spills, full-flag materializations, PF/AF stores,
  dispatcher exits, `stop_unknown` sites against `tests/audit.csv` (above
  expected fails), plus flag stores/merges/loads and return checks; HLE count.

## Sound (D10)

SPAZ runs translated; its OPL2 writes reach `rt_out8` (register file in
`src/runtime/ports.c`). The FM re-hoster produces Paula voices for music,
which stays enabled in both FM and TFH modes; see
[sound-plan.md](sound-plan.md).
