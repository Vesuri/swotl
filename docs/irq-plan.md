# Interrupt plan (open-work 43)

Goal: no guest interrupt polling in generated code. SPAZ's INT 08h handler runs from the
CIA-B timer interrupt, asynchronously as on the PC; keyboard and mouse are read at the
vertical blank and reach the guest at its service calls. Lockstep with DOSBox stays: tests
deliver interrupts deterministically at sync points, which the reference follows. Approved
with its rule changes by the user 2026-10-24. Speed-plan §2–4 apply except as changed
here; one step, one commit, checks stated before running (AGENTS.md validation scope).
Evidence: `tmp/irq/<step>/`.

Why: poll tests are 5.15% of the m4 meter's model cycles and 3.73% of the flyby (I1,
Facts). Exact native state at every
poll and U3 write histories hold native rows near the generated code (F5: `BFD1` −2.1% per
call; its estimate was −45–60% of the replaceable ~300K cycles per call).

## Facts (2026-10-24)

- Interrupts reaching guest state: IRQ0 only. Guest handler SPAZ `+07CC`
  (`annotations/entries.csv`), 236.7 Hz. IRQ1 runs the runtime's BIOS handler (`input.c`
  `rt_keyboard_irq`: BDA flags and buffer, no guest code; Print Screen stops); the guest
  reads keys only through INT 16h AH=02h and DOS AH=0Bh/08h. IRQ12 (DOSBox-X
  `F000:D020`) is skipped by host runs, which still match, and is not posted on the
  Amiga; the mouse is JOY0DAT at the vertical blank, read through INT 33h.
- Handler footprint (static reading of the IR): pushes AX–ES on SS:SP; DS = 188Ah,
  re-entry byte `[3E0]`, BIOS countdown `[3E1]`; ES = `[188A:0162]` (game DS): increments
  `813C`, `9BCA`, `9C44+2·[9C20]`, dword `9D32`; reads `639F` (sound), `6316` (pause),
  song table `613C+di`/`613E+di` and song data through it; OPL ports 388h/389h, EOI
  `out 20h`; every 13th tick `jmp far cs:[0]` to the BIOS tick (`0040:006C`, `0070`).
  SPAZ has no string instructions. Stop-all `+0666`, called by the handler when `639F`
  changes, runs `cli`…`sti`; `[3E0]` guards re-entry. Effects start through `+048C`
  (`sfx_start` hook), also from the gun-delay tick (sound-plan.md).
- Main-code readers of handler-written bytes: `813C` only (literal search of the IR).
  FLIGHT `+0122A..01245` spins until it is nonzero, takes it as the frame's tick count
  (`[88F8]`, `0xEC/ticks` → `[88B0]`) and clears it; SWOTL `+0180..01A6` (timeout wait),
  `+3682` (200-tick wait), `+3F94`. Main writes `9C20`, `639F` (`xor`), `6316`.
- SPAZ's main-thread entries: init `+028E`, shutdown `+03A5`, play `+0516..05AD` and
  stop-all `+066D..06C9` run under `cli`; stop `+05AF` and engine stop/query/pitch
  (`+06D8`, `+06F9`, `+0713`: eight OPL writes per pitch, once per flight frame) do not.
  Other static `cli`/`sti`: SWOTL `+4469` (joystick timing), `+136AE`, `+164F2`, `+16574`.
- Polls: 2,096 points at loop heads (`build/gen/poll-points.csv`), 2,453 emitted tests
  with guarded copies. They also carry the platform's field work: the first poll after a
  vertical blank runs `plat_service` (key script, `fm_field`) and the due present
  (`video.c` `rt_video_refresh`).
- Generated code keeps no guest memory value across instructions (`reuse.py` tracks
  register formations only). Pop runs (R31, `reuse.py` `stack_runs`) step SP before their
  loads, so popped words sit below SP; `bp_native` and native rows may hold guest registers
  in other forms mid-run. A handler cannot push on the interrupted stack.
- The reference takes hardware interrupts only before a poll point
  (`dosbox-x-swotl-trace.patch`: `SWOTL_IrqPoint`, `PIC_runIRQs` gate); its PIC holds one
  pending IRQ0. Poll visits also time key releases (`release-visits` patch, `host_run.py`
  triggers), REP slices (`rep-chunks`), the bench spin rule (`RT_BENCH_POLLS` 8,956,
  `RT_BENCH_SPIN`), host IRQ groups and diagnostic replays (`amiga_replay`).
- I1 (2026-10-24, `b666a22`, evidence `tmp/irq/I1/`). Meter m4 (`cost_meter.py`):
  poll tests (`tst.b G_IRQ(a6)` + `bne`) 925,939 visits, 7,937,528 of 154,046,871 model
  cycles (5.15%): generated 549,772 visits, 3.09%; native rows 376,167, 2.06% (mostly
  F9's OPL delay loops); 441 taken. Flyby (`irq_profile.py`, five 100-field captures,
  500 fields, 142,101,993 cycle units ≈ 68020 cycles): poll tests 3.73% (generated
  433,612 visits 2.57%, native 219,130 visits 1.16%). Per call, cycle units mean / p50 /
  p99 / max, native stack below the entry A7:
  - SPAZ tick (`deliver_guest`, BIOS chain included; net of nested deliveries):
    2,367 calls (236.7 Hz), 2,221 / 920 / 20,921 / 93,046; 3.89% of the flyby; stack
    68 bytes (524 with a nested delivery's field work). The long ticks are OPL write
    bursts: 70% of them in the `D03`/`D0F` delay loops and `rt_out8`.
  - Field work at the first poll after a vertical blank (`rt_video_refresh`): 485 calls,
    25,106 / 19,299 / 83,396 / 99,294; 8.57%; `plat_service` 24,987 mean, of it
    `fm_field` 24,276 (8.29%); stack 432.
  - `present` (tail-called): 29 calls, 284,619 / 200,683 / 781,584 max; 5.81%; of it
    `plat_present` 233,614 mean; stack 196.
  - `rt_irq` (one poll's deliveries and field work): 2,435 calls, 9,109 mean, 111,587
    max; 15.61%; stack 536.
- I2 (2026-10-24, evidence `tmp/irq/I2/`). Handler: 1,158 instructions, 70 bytes of
  stack, transparent; writes G `6564..658A` (effect counts), `813C`, `9BCA`,
  `9C44..9CA9` (`[9C20]` ≤ 32h: `irq-bounds.csv`, main writes checked), `9D32..9D35`;
  `188A` up to the module end `059F` (SPAZ data; voice-indexed accesses clamped to it,
  `irq-bounds.csv` extent), BDA `6C..70` through the chain; reads the song table and
  song segments (S, located at run time); ports 20h, 388h, 389h; IF changes only in
  play and stop-all; a divide at `+1229` could fault. Main code (DS per entry and
  entry DS/SS; G = `43CDh`): 205 sync accesses (handler-written reads: `813C` and the
  effect bytes, FLIGHT `+3F0F`/`+3F2A` `[6570]`; SPAZ `+064E`/`+065E` inc/dec of them;
  the 9C20 writers; song-table setup; SPAZ's main-thread OPL writes), each one 68k
  memory access; disjoint 16,432, masked 22, monitored 26,284, not reached 1,085.
  `irq-ds.csv`: `__heap_search` and the cell walk driver `+EA74` return the caller's
  DS unseen. Generated bodies unchanged; `make gen` +13 s.
- I3 (2026-10-24, evidence `tmp/irq/I3/`, records `tmp/test/irq-monitor-*.json`).
  `test-host-all` (102 runs, 802,362 ticks): handler accesses all inside the footprint
  (handler entry `1F92:058C`, G `43CDh`); main accesses meeting it from 117 sync sites
  (with `+0455C` below), 41 IF-clear SPAZ sites, and services: DOS reads (SPAZ's image `1770`/`188A` at load,
  BDA time) and the BIOS tick. One monitored site met it: SWOTL `+0455C`, the string
  routine `042B:02A0` reached by the fall-through of the tick wait `042B:0290` (no
  return; FRONTEND `+06891`), whose stacked C8h and the word above it point at
  `188A:00C8` (handler slot arrays) → `irq-sync.csv`, sync 206. Songs 0–37 (21 seen),
  none in the EMS frame; FRONTEND `+0EBE5` reuses a stopped song's buffer (writes after
  its last read). Host run time +28% (m3 12.0 → 15.4 s).
- I4 (2026-10-24, evidence `tmp/irq/I4/`). IRQ0 with a guest handler runs through
  `rt_irq_async` (sync mode, from `rt_irq`): private stack `B000:8000` down, sentinel
  CS:IP `B000:8000`, 68k registers, state block and `rt_r` restored; other vectors keep
  `deliver`. References unchanged; host runs match with the reference's frames in the
  masked dead stack; the private stack (`host_run.py` `IRQ_STACK`, 200h below
  `B8000h`) is no machine memory (the reference reads FFh there). Meter m4 +239,209
  model cycles (+0.1553%), runtime only (saves around each tick); generated +0.
  In service: no posted interrupt is taken from `rt_irq0_enter` to `rt_irq0_leave`
  (the PIC holds IRQ0 and IRQ1 until the EOI). SPAZ's handler reaches an STI
  (SPAZ+05AD, via SPAZ+0DA7) before its EOI (SPAZ+0A80); on FS-UAE a tick posted meanwhile
  re-entered `rt_irq_async`, overwrote `rt_irq_saved` and resumed main code with SS
  `B000` (`test-amiga-restore`, display audits). Check `t-irq-in-service`.
- I5 (2026-10-25, evidence `tmp/irq/I5b/`). The vertical blank requests SOFTINT; our
  level-1 vector (owned like VERTB, both triples in the restore check and the I/O
  windows) runs `rt_video_refresh`: `plat_service`, then the present unless a driver
  call runs or `busy` (`rt_video_publish`, `rt_int10`). Amiga polls no longer call it
  (`rt_present_due` stays below 1). `Audio::service` copies `rt_opl`, key-on counts and
  the effect slots under `Disable` and synthesises from the copy. Key scripts skip
  unknown names at the interrupt (logged at startup). D5 bench (3 runs per arm, base
  `115d6f0`): median 68,431 → 68,395 (−0.053%), RAM hash equal; display audits 40
  captures, 0 late (68030, 68040).
- I6 (2026-10-25, evidence `tmp/irq/I6/`). The CIA-B tick runs SPAZ's handler through
  `rt_irq_interrupt` when `rt_irq0_ready`: IF set, none running, `rt_irq_mask` clear
  (taken by services, faults, polls, ports, dispatch), `rt_opl_pair` clear (a main OPL
  index without its data write), nothing posted, not `BENCH`; EXTER acknowledged and SR
  lowered to 2, so the vertical blank preempts a long tick and a tick during the
  handler posts. Else it posts as before. A stop at interrupt level returns through
  `rt_irq_abort` and is raised at the next poll. Display audits: 40 captures, 0 late;
  ticks posted = handler runs + BIOS ticks: 68030 27,585 = 27,551 + 34 (93.9% at the
  interrupt), 68040 24,988 = 24,955 + 33 (93.8%). Host stress (`tests/irq_stress.py`,
  `make test-irq-stress`): a recorded lone IRQ0 is injected through `rt_irq_interrupt`
  1–400 68k instructions after its visit, or before the next sync access, CLI/POPF,
  runtime entry, script step or recorded interrupt; seeds 1 and 2 match the reference
  on m2, m4, c13, c27 (seed 1: 3,220 / 3,115 / 18,084 / 11,253 ticks; 2,731 / 1,856 /
  15,535 / 8,845 at the drawn instruction). Ticks the reference took inside a main OPL
  pair (4 / 4 / 46 / 64) post (production holds them to the data write, a legal PC
  timing). Plant `irq-async-state` (no state block saved) fails stress, passes sync.
  Unicorn 2 loses the lazy CCR on a PC write in a hook or an SR read through the API: the
  harness stops in the hook and restarts at a stub that saves CCR itself. Frames A/B
  (3 runs, base `dc28e3d`): median 320 ms (310–320) → 300 ms (300–300). Flyby (500
  fields): tick latency (`cia_tick` to its `deliver_guest`) mean 26,262 → 2,614 units,
  p99 552,934 → 21,491; handler mean 2,184 → 2,280; 2,339 of 2,370 ticks at the
  interrupt, `rt_irq_interrupt` mean 3,845 with entry and exit, supervisor stack 280
  bytes; ms/frame equal (454.5). Meter m4 +43,558 model cycles (+0.0282%), runtime only.
- I7 (2026-10-25, evidence `tmp/irq/I7/`). No keyboard interrupt: `Input::begin` disables
  CIA-A SP with `AbleICR` (keyboard.device's vector stays registered, never runs) and
  clears a stale byte; each vertical blank samples SP with `SetICR(0)`, clears it, reads
  SDR and handshakes; `Input::end` restores the enable. I/O windows read it from a VERTB
  server on Exec's chain. WHDLoad's QuitKey needs no keyboard interrupt (whdload.doc
  `ws_keyexit`: checked on every interrupt with a moved VBR); untested, as before.
  `make test-amiga-keyboard` (FS-UAE `monitor key`): 2 edges read
  by the window server (40 toggles, field 59), held 61 fields → 8 makes then the break;
  plants (server on COPER, SP left enabled) fail. D5 bench (3 runs, base I6): median
  68,366 → 68,446 (+0.117%, ranges 68,361–68,383 / 68,427–68,448), RAM hash equal;
  layout is not the cause (a 100-byte pad arm: 68,363); one CIA access per field
  (`Input::keyboard` 0.04% of the profile). An unchanged-SDR prefilter before
  `SetICR` gave no gain (68,450) and was dropped. Bench cost accepted by the user
  (2026-10-25). Display audits 40 captures, 0 late
  (68030, 68040).
- I8 (2026-10-26, evidence `tmp/irq/I8/`). Sync set (`poll-points.csv`, 2,410 rows):
  206 `access`, 104 `int`, 11 `clear`, 12 `if`, 2,077 `loop`. Production tests only at
  `if` points (image 4,930,208 → 4,785,764 bytes); a tick posted while IRQ0 could not run
  goes at the next CIA tick (`rt_irq0_take`); keys drain at service entry. Sync builds
  (`SWOTL_SYNC`: host, replays, bench) post IRQ1 and test everywhere, so host runs deliver
  through those checks, not Unicorn hooks; loop-head stubs set `d6` bit 0, the only
  visits the bench's spin rule counts (SPAZ's calibration loop now also holds an `if`
  point; its count is unchanged, `RT_BENCH_POLLS` stays). Alignment pads fit production,
  not the sync image. IRQ12 unchanged (host skips it, the Amiga posts none). Reference
  patch: an IRQ0 pending while deliverable (IF set, unmasked, not in service) whose next
  edge the gate would merge is kept and raised at once at a later opening; merges the
  ungated machine makes stay. Without loop heads (333 points) gated runs left the
  ungated original's trajectory (m4 VRAM from frame 20, a tick merged in a ~90k-instruction
  handler run shifted by deferral; c7's demo returned at 2.05G instructions, ungated
  349M; c7, c81, c84 failed); with them m4 VRAM equals ungated, c7 349,303,972 vs
  349,303,949. Hybrid chosen by the user (2026-10-26, RC3). c81 and c84 failed ungated
  too (their damage came from the old gate's merges): re-scripted by the user's decision,
  c81 last `my-60` at `#60` (was `#50`), c84 `4` at `#2` (was `#1`); ungated they reach
  their endpoints at 418,940,505 / 392,713,482. 94 references re-recorded, `polls=`
  `c1aa4a7564f96486` → `76bd1cb483ad50d3`; m2, m4, c7, c81, c84 repeat exactly. The run
  name's length reaches the guest (`pc_run.py` name; m4 differs by 211 instructions):
  references keep their `ref-` names. Old/new: m2, m4 service streams equal, c12/c13
  diverge after ~10,300 services; ticks per frame (between `+44E0` calls) differ in m4
  0/200, m2 9/901 (all by one), c12 763/4,253 (635 by one), c13 576/4,331 (553 by one).
  Meter m4 (base on the old reference, same name): 154,344,769 → 160,124,683 model
  cycles (+3.7448%, sync ELF): the rows with polls run generated (guest instructions
  10,322,775 → 14,233,376); without the sync-only tests (8.407 cycles a visit, 1,893
  `if` visits kept) about 151.66M (−1.74%). Bench (sync image, 3 runs, base I7): median
  68,444 → 68,852 lines (+0.60%, ranges 68,427–68,448 / 68,827–68,852), new RAM hash
  `4dcd4d43…`. Frames (production, 3 runs): median 330 ms (310–340) → 310 ms (300–320).
  I3's song-buffer rule now holds per byte (`song_races`): with the new timing song 35's
  reads span ticks 141–10037 while FRONTEND `+0EBE5` reloads `630CC`–`630D4` at 9835, last
  read at 3220 (c62, c63); the per-song window flagged it. Chosen by the user. Stress
  windows also end at a sync point's continuation (`_np`, `_bp_np`, `_native_np`): a tick
  recorded at an `access` poll ran past its write of `9C20` (m2 seed 1, ticks 113/114).
- I9: one poll-free proof (`compute.validate`: loops, callees, several returns,
  continuation exits; resumes are the returns/endpoints, then the root loop heads); the
  eight rows return. Their 19 body loop heads leave the sync set (2,391 points: 206
  access, 104 int, 11 clear, 12 if, 2,058 loop); `polls=` `76bd1cb483ad50d3` →
  `a8595a6631599363`, 94 references re-recorded (m2, m4, c7, c81, c84 repeat exactly).
  c7's attract demo no longer took the HIGH view call (`+EC5B`) before 6.15G gated
  instructions (349M before): re-scripted by the user's decision to c32's keys, ungated
  205,330,776 / gated 205,330,758 instructions to `+EC60`, VRAM equal. BFD1's C1E2/C3DF
  wrap resumes are not reached from a C000 entry (were via poll re-entry): untested
  until its I10 rebuild. Meter m4: 160,124,683 → 150,903,197 model cycles (−5.76%; guest
  instructions 14,233,376 → 11,026,510; generated in the row bodies before → after: BFD1
  16.8M → 4.8M, OPL 5.4M → 0.03M, sprite 3.6M → 0.17M, normalise 3.0M → 0.22M, line
  1.6M → 0.02M, scenery 0.6M → 0.06M). Bench (sync image, 3 runs, base I8): median
  68,850 → 68,875 lines (+0.036%, ranges 68,848–68,850 / 68,859–68,878; RAM hash
  unchanged). Frames (production, 3 runs): median 320 ms (310–340) → 300 ms (290–300).
- I10: one batch (user 2026-10-26: all natives first, one verification). Rows: `D5A6`
  to the `B017` call, `BB70` whole, `F290`, `FDE0`, `109D6` vertex loops, `BD68`, `BFD1`
  re-entries (C1E2/C3DF wraps now tested), F9 O(1), `D69C`, `4DAE` span setup.
  Contract: `hle.csv` `entries` (re-entry hooks after an exit's call; a re-entry keeps
  its own liveness, else resume liveness flows into the callee: CF went live in
  B52D/B017/D5A6/BB70), direct native calls (FDE0 → B52D, BB70), `irq.check_rows`
  takes a row with exits by its proved body. 34 loop heads leave the sync set (2,357
  points: 206 access, 104 int, 11 clear, 12 if, 2,024 loop); `polls=`
  `a8595a6631599363` → `9243d3a514f7c09d`, 94 references re-recorded (m2, m4, c7, c81,
  c84 repeat exactly; c20/c22/c23 not resident as before). First meter −0.66%: the new
  natives cost 2–3× their estimates (FDE0 native 5.19M against 3.03M generated saved);
  after one optimization pass every row is below its generated cost. Meter m4:
  150,903,197 → 143,485,059 model cycles (−4.9158%; guest instructions 11,026,510 →
  7,761,478; per row: speed-plan §7 I10). Bench (sync image, 3 runs, base I9): median
  68,872 → 68,539 lines (−0.48%, ranges 68,859–68,878 / 68,520–68,543; RAM hash
  unchanged). Frames (production, 3 runs): median 300 ms (280–310) → 280 ms (260–300). Not built: `EA74`; the `4DAE` walk
  loop needs a contract extension (open-work 14b).
- Guest memory backs 1 MiB + HMA (`RT_GUEST_BYTES`); host runs compare RAM from the
  environment MCB to A0000h with dead stack masked (open-work 24).

## Rule changes (user, 2026-10-24)

- **RC1** L18 exception: SPAZ's IRQ0 handler runs in Amiga interrupt context, admitted by
  I2's proof and I3's monitor. Other guest handlers (faults) stay in the main thread;
  unknown vectors still stop.
- **RC2** Production generated code has no poll checks (I8); sync points are delivery
  addresses for the test harness, the reference and diagnostic builds. Delivery timing
  changes (production asynchronous, tests at sync points); the PIT rate does not. Only IRQ0
  remains a guest interrupt. Supersedes speed-plan §2.3/§2.9's poll and delivery-order
  limits for these steps.
- **RC3** References are re-recorded with the sync set (I8) and whenever it changes, with
  old/new `polls=` fingerprints in the commit. Fixtures and tolerances stay. The set keeps
  the loop heads outside native rows (user 2026-10-26), so a native row that removes
  loop heads (I9, I10) re-records.
- **RC4** Keyboard and mouse are read at the vertical blank; no keyboard interrupt. The
  BIOS keyboard state is updated at service entry in production and at sync points in
  tests (services are sync points).
- **RC5** U3 write histories, the U5 poll contract (sync sites, latency bound) and exact
  native polling retire at I9: nothing can observe a native row's intermediate state.
  Rows compare registers, live and control flags and all RAM at entry, exits and returns,
  plus written-address sets for code (SMC) and VRAM. A row whose footprint meets the
  handler's is rejected (I2).
- **RC6** No poll-latency bound: production delivers ticks at 236.7 Hz from the CIA; tests
  deliver at sync points.

## Target

- **No checks in production code.** Async delivery needs none: the CIA interrupt
  delivers every tick; ticks deferred by guest IF = 0 are delivered by the runtime's
  IF 0→1 paths (`sti` after its one-instruction shadow, POPF and IRET through
  `__set_flags`, `rt_set_flags_word`); wait loops on `813C` see the interrupt's store.
- **Sync points** (`poll-points.csv` keeps its name, plus a `kind` column) are addresses,
  not code: main-code instructions that may access the handler footprint (I2) and
  software `int` sites, minus accesses that only run with guest IF = 0 (they can never
  deliver), CLI/POPF/IRET with IF possibly set, plus IF 0→1. Between two sync points a
  tick commutes with all main code, so tests could deliver at the next one; the
  reference and sync builds also deliver at loop heads outside native rows (user
  2026-10-26, I8 Facts): deferring ticks to the 333 sync points alone moves the
  original's trajectory. Delivered by: the host run (Unicorn code hooks at the addresses), the
  reference (gate opens there), diagnostic builds (a check emitted only in those builds,
  next to the existing replay hooks; or gdb breakpoints) and the bench (a diagnostic-style
  build, or ticks at services plus a runtime spin detector; chosen in I8 by bench
  stability).
- **Modes** (runtime): *sync* (host runs, replays, bench, diagnostic builds) delivers
  posted interrupts at the next sync point, as the reference does; *async* (production)
  runs the handler from the CIA-B interrupt when guest IF is set and none is running,
  else counts it pending for IF 0→1. Production runs the generated code the tests ran,
  minus the diagnostic hooks; its async path is exercised by I6's stress mode, not by
  lockstep.
- **Handler entry** `rt_irq_async`: save the 68k registers, state block, `rt_r` and the
  runtime scratch on the handler path; a6 = TOP; SS:SP on a private guest stack
  (candidate `B000:8000` down: backed, outside compared RAM; confirm the reference never
  writes it); a frame with a sentinel CS:IP to which SPAZ's IRET or the BIOS chain
  returns; dispatch through IVT 08h (BIOS vector: `bios_tick`); restore. A stop raised at
  interrupt level unwinds to the main exit path.
- **Shared runtime state:** the OPL register copy and key-on counts (`rt_out8`, read by
  `fm_field`), `sfx_start`/TFH routing (`Audio.cpp`), the BIOS tick dword (DOS time, INT
  1Ah), the pending count and IRQ flags are interrupt-safe. Runtime services that write
  handler-visible memory non-atomically (DOS reads; EMS map copies if song data can sit
  in the page frame) mask the tick. Main-thread OPL writes without `cli` (engine calls)
  mask it across each index/data pair, a legal PC timing.
- **Field task:** a level-1 software interrupt caused by the vertical blank runs
  `plat_service` and the due present when no driver call runs; the present also stays at
  the outermost driver return (`rt_video_publish`). VBI order stays L17.
- **Keyboard:** the vertical blank reads CIA-A SDR, handshakes (~85 µs SPMODE output),
  maps through `Input.cpp`'s table, repeats as now and fills `rt_key_ring`;
  `rt_keyboard_irq` drains it with IF set at service entry (production) or at sync
  points (tests). ICR is read-to-clear and shared with `ciaa.resource`: SP is disabled
  with `AbleICR` and sampled with `SetICR` (I7). Keys pressed during I/O windows (Exec's
  VERTB) arrive through a VERTB server.
- **Mouse:** unchanged. IRQ12: the reference stops delivering it, or the port keeps
  skipping it (I8, by the re-recorded RAM).

## Steps

- **I1 Measure** (tooling). `cost_meter.py` counts poll tests (labels × the model cost of
  `tst.b d16(a6)`/`bne.w`) as a share of m4; flyby capture (`perf_flyby.gdb`,
  `profile_tree.py`): poll share, SPAZ handler cycles per tick (mean, max),
  `plat_service` and present cycles per call, native stack depth on the handler path.
  Numbers into Facts. Checks: cost-tool tests and their sabotage.
- **I2 Footprint proof** (translator, gen time, output unchanged). From IVT 08h's guest
  handler over the CFG with callees: segment constants (DS 188Ah; ES = `[188A:0162]`,
  class G; song segments, class S), offset intervals for indexed accesses
  (`9C44+2·[9C20]` from the values main stores to `9C20`, else the whole index range),
  ports, IF changes, runtime calls and hooks → `build/gen/irq-footprint.csv`. Proves
  register transparency (no interrupted register read except to save it, every written
  one restored, no DF use). Classifies every main-code access: disjoint, sync (may meet
  the footprint) or monitored (segment unknown). A sync access to a handler-written byte
  lowers to one 68k instruction, else `make gen` fails; compute rows meeting the
  footprint reject. Checks: `t-irq-footprint`, `t-sab-irq-footprint` (plants: handler
  touches a main variable, split read-modify-write on a shared byte, unsaved register,
  undeclared port, compute row writing `813C`); generated output unchanged.
- **I3 Footprint monitor** (host runs). `host_run.py` checks every guest access: inside a
  delivered handler, within the footprint; in main code, a footprint address (fixed
  ranges, song buffers from SPAZ's table, the EMS frame if they sit there) only from a
  sync access or a runtime service that masks the tick. Fails loudly. Runs in
  `test-host-all` and the coverage scenarios; plants: undeclared main read of `9BCA`,
  handler write outside the footprint; a generated write of a song byte between the
  handler's first and last read of that byte fails. Records the sites found, song buffer
  location and EMS use.
- **I4 Private-stack entry** (runtime). IRQ0 delivery at today's polls goes through
  `rt_irq_async` in sync mode (private stack, sentinel return); faults keep `deliver`.
  References unchanged; host runs match with dead stack masked. Checks: `make test` (the
  block differential posts interrupts), `test-sabotage`, `test-host-all`, `test-amiga`,
  `test-amiga-replay`, `t-compute-*` (native poll handoffs), interrupt-frame and vector
  tests; plants: sentinel return check, state block not restored, handler on the
  interrupted stack. Meter Δ reported (expected ≈ 0).
- **I5 Field task** (platform, runtime). `plat_service` and due presents leave the poll
  path for the level-1 software interrupt (`INTF_SOFTINT` in the takeover mask); a busy
  flag separates it from `rt_video_publish`'s present; `fm_field` reads an OPL snapshot
  taken with the tick masked. Checks: `test_display_queue.py` (new races),
  `amiga/display_audit.sh` (zero late handoffs, also `AMIGA_CPU=68040`), `make
  gates-audio`, `make smoke`, `test-amiga`, `test-amiga-replay`, `test-whdload`; bench
  (D5) no slowdown.
- **I6 Asynchronous IRQ0** (platform, runtime). The CIA-B handler calls `rt_irq_async`
  (IF set and none running; else pending); IF 0→1 delivers pending ticks; interrupt-safe
  state and tick masks as in Target. Level from I1's handler times: level 6, or
  acknowledge and lower the mask to 2 so the vertical blank preempts it, re-entry
  counted; required: zero late handoffs,
  posted ticks = handled ticks. Host stress mode: each recorded IRQ0 injected at a random
  instruction boundary between the I2 sync events around its recorded visit, through
  `rt_irq_async`; must match the reference at every service and milestone (seeds
  recorded). Loop-head polls remain, inert in production. Checks: stress mode on m2
  (music), m4, c13, c27; `test-host-all`, `test-amiga`, display audit (68020, 68040),
  `gates-audio`, `test-whdload`, smoke; frames fixture A/B with flyby capture (tick
  latency from post to run, handler time).
- **I7 Keyboard at the vertical blank** (platform). The VBI read replaces the CIA-A SP
  vector (Target); delivery through `rt_key_ring` unchanged until I8. Checks:
  `test_amiga_input.py`, key and keyboard-prefix tests, c9 and c85 replays, FS-UAE
  `monitor key` press/release (also during an I/O window), typematic repeat,
  `test-amiga-replay`.
- **I8 Sync points** (translator, reference, tools; references re-recorded).
  - Translator: no poll checks in production builds (loop heads and stubs go); diagnostic
    builds emit a check at each sync point; IF 0→1 delivers at once; `poll-points.csv`
    holds the sync set; key events drain as in Target (IRQ1 is no longer a port
    interrupt).
  - Host run: delivers recorded interrupts through Unicorn code hooks at sync addresses
    (visit counts as today's poll visits); bench delivery as in Target.
  - Reference patch: gate open before sync points and after IF 0→1; IRQ0 edges counted
    while it is closed and delivered in order at the next opening; IRQ1 at sync points;
    IRQ12 decided.
  - Tools rebased on sync visits: key triggers and releases (`release-visits`,
    `host_run.py`, `fixture_inputs.py`), REP slices (`rep-chunks`: REPs at sync points
    only), host IRQ groups, `amiga_replay`, census, the bench spin rule (spins read `813C`
    or SPAZ's calibration byte; re-derive `RT_BENCH_POLLS` from the new reference).
  - Native rows with polls (`polls` U5/exact) are disabled in the same commit (generated
    fallback) and return poll-free in I9; poll-free rows stay.
  - Re-record every reference (`make reference`, sound references); old/new `polls=` in
    the commit; diagnostic diff of old/new service logs and per-frame tick counts at
    FLIGHT `+0123B` (divergence reported: a tick posted just before a read may move one
    frame).
  - Measure: meter (also Δ guest instructions; if the trajectory moved, cycles per guest
    instruction), bench (new RAM hash baseline: dead stack moves), frames fixture
    checkpoint.
  - Checks: `make gates` (translator, references, host, replay and sabotage all change).
- **I9 Native rows poll-free** (RC5). `compute.py` drops U5/exact-poll admission and
  emission (polls, sync sites, aliases, `native_polls.i`); `compute_oracle.py` compares at
  entry, exits and returns without histories, written-address sets for code and VRAM;
  rows re-enabled with their natives' G_IRQ tests and trampolines removed; footprint
  overlap rejects (I2). Loop heads in a re-enabled row's body leave the sync set
  (`emit.Program`; references re-recorded, RC3). Retired tests and plants get poll-free
  equivalents. Checks:
  `t-compute-*` with sabotage, each row's native differential, `test-host-all`, replays;
  meter and bench per row group.
- **I10 Re-open native rows** (user 2026-10-24: do them as soon as I9 allows), each by
  native-plan S1–S9, priced without polls or histories, in price order:
  - Deferred for the poll contract itself: F3's `D5A6` prefix (poll-set change and
    re-recording), `BB70` (R39: seven kept sync sites); F9 in O(1) (poll visits and
    re-recording; speed-plan §2.9 delay-loop exception approved by the user 2026-10-24).
  - Deferred for no positive price under exact polls and address reuse (exits and
    handoffs remain, so re-price first): `FDE0` cache loops (R45), `BD68` edge loops
    (R43), `F290` tile selection (R41), `109D6` vertex loops.
  - Exact-poll rows rebuilt poll-free: `BFD1` (F5, with R46/R47 inside it), `4DAE`
    packet loop (R42), `D69C` pixel loops (R44), SPAZ delay loops (F9).
  - Not affected: `B8A1` (no calls in the workload).
- **I11 Close.** Docs: translator-design D8, amiga-arch interrupts and L18, native-compute
  poll sections, pc-reference-loop `--polls`, speed-plan §1/§7, native-plan F re-priced
  under RC5; open-work 43 removed; frames checkpoint.

Order: I2 and I3 before any behaviour change. I5 and I6 before I8: production must not
depend on sync points for ticks, audio or presents (in flight one may come only once a
frame). I8 and I9 adjacent, then I10. I7 is independent (platform only). Acceptance: speed-plan §3
for I4, I8 and I9; D5 bench for I5 and I7; I6 by frames fixture and flyby A/B (the bench
stays in sync mode); fidelity tradeoffs go to the user.

## Risks

- A guest read of uninitialized stack sees different dead-stack bytes once frames move;
  lockstep shows it.
- FLIGHT `+0123B` reads `813C` and clears it four instructions later; an async tick in
  between is lost, as on the PC. Tests deliver before the read.
- The handler path's native stack at interrupt level (I1 depth; switch stacks if needed).
- Ticks during I/O windows run translated SPAZ while the OS is active; the path makes no
  OS calls.
- Song data in the EMS page frame would need tick-masked map copies (I3 decides).
- The D16 cell walk and SMC lie outside the handler footprint (I2 confirms).
