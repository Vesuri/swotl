# Interrupt plan (open-work 43)

Goal: no guest interrupt polling in generated code. SPAZ's INT 08h handler runs from the
CIA-B timer interrupt, asynchronously as on the PC; keyboard and mouse are read at the
vertical blank and reach the guest at its service calls. Lockstep with DOSBox stays: tests
deliver interrupts deterministically at sync points, which the reference follows. Approved
with its rule changes by the user 2026-10-24. Speed-plan §2–4 apply except as changed
here; one step, one commit, checks stated before running (AGENTS.md validation scope).
Evidence: `tmp/irq/<step>/`.

Why: at least 745,740 poll visits in the m4 meter window (`zf3arm-f4` arm), about 4–5% of
model cycles at ~10 cycles each (estimate; I1 measures it). Exact native state at every
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
  old/new `polls=` fingerprints in the commit. Fixtures and tolerances stay.
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
- **Sync points** (`poll-points.csv` keeps its name and format) are addresses, not code:
  main-code instructions that may access the handler footprint (I2) and software `int`
  sites, minus accesses that only run with guest IF = 0 (they can never deliver), plus
  IF 0→1. Between two sync points a tick commutes with all main code, so tests deliver
  at the next one. Delivered by: the host run (Unicorn code hooks at the addresses), the
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
  points (tests). ICR is read-to-clear and shared
  with `ciaa.resource`: sample SP through the resource or keep a minimal SP read, decided
  on FS-UAE in I7. Keys pressed during I/O windows (Exec's VERTB) must arrive.
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
  handler write outside the footprint. Records the sites found, song buffer location and
  EMS use.
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
  overlap rejects (I2). Retired tests and plants get poll-free equivalents. Checks:
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
- Keyboard ICR sharing with `ciaa.resource` (I7).
- The D16 cell walk and SMC lie outside the handler footprint (I2 confirms).
