# Native compute contract

Enabled: the user-authorized (2026-10-21, native-plan U2)
`SWOTL.EXE+B54B` transform pilot from `xform20`, retaining generated `B52D`
and return checks. U3 keeps complete byte-write history. Further routines
remain deferred and need individual authorization (speed-plan §2.2).

## Admission

`annotations/hle.csv` accepts an optional `kind`: absent/`hook` retains the sound
hooks' ABI; `compute` requires empty `args`, a reason and an oracle. `first` is
the entry, `last` the instruction immediately before the original RET/RETF.
The original return and its caller's return check stay generated.

`translator/compute.py` proves reachable flow, including callees, from the CFG.
The initial contract requires one root return, no cycles, no unresolved flow,
no poll points, no nested HLE hooks and no runtime/device effects. REP, interrupt
control and diagnostic replay hooks are rejected too. Internal entry points
remain generated and valid. A rejected row is a generation error, not fallback
authorization. Arithmetic faults must use an exact, unchanged-state fallback;
an exceptional CFG edge that violates admission rejects the row.

**Poll policy:** until C3 implements the [U5 poll contract](#poll-contract-u5),
reject routines whose reachable body or callees contain polls. U5 changes the
poll set only for an authorized row (U6); interrupt order and PIT rate stay.

## ABI

The callback uses the generated-code ABI directly, not the C ABI:

| State | Representation |
|---|---|
| AX/CX/DX/BX | d0/d1/d2/d3 low words |
| SP/BP | d4/d5 low words, guest offset XOR 7FFFh |
| SI/DI | a4/a5 low words |
| ES/SS/DS | state words and a1/a2/a3 segment bases, both kept coherent |
| Guest RAM | a6 = TOP; byte L at TOP−L; word at TOP−L−1 |
| Guest flags | G_FL, G_PF, G_AF, G_DF, G_IF, G_TF, G_FX, as translator-design |
| CS input | d6.l, zero-extended guest CS at entry |
| Scratch/result | d6, d7, a0; d7.l = 0 declines, nonzero handles |
| Native stack | a7 balanced across callback; a6 preserved |

Upper register words are undefined; consumers of long operands must extend
explicitly. No guest register is an argument or result scratch register.
The callback must reproduce every guest register and segment value. Status
flags are exact where translator liveness requires them at the resume; undefined
flags use the existing IR definition. Control flags and IRQ state are preserved.
Only flags in the translator's `live_in[first]` are guaranteed on entry;
callbacks must not depend on dead/undefined flags.
No annotation may declare a register, flag or scratch store dead.

Decline before changing any guest register, flag, RAM or runtime state. The
emitter tests d7 and either resumes at the original return or runs the original
body. Hook and resume are leaders; entry with live CCR-only flags is rejected.
The handled path branches to the exact resume, leaving any BP-specialized copy.

Every guest store, including scratch and stack stores, must retain its address
and value. Effective-address arithmetic wraps at 16 bits as the original does;
wide accesses retain the original boundary semantics. Stores must preserve the
generated memory path's SMC invalidation and display bookkeeping. Native code
must not bypass those paths; use generated store sequences or decline before
mutation. Internal guest calls retain their stack effects and return checks.
Native routines cannot call an OS service or deliver an interrupt.

## Oracle and acceptance

`tools/compute_oracle.py` reads a DOSBox snapshot (`ram.bin`, `regs.txt`) or a
synthetic test record (`ram.bin`, `regs.json`). Original x86 runs under Unicorn
to the specified pre-return CS:IP. Unicorn supplies flow, registers and writes;
the IR supplies only undefined-flag metadata. Missing input, zero executed
instructions, a limit, an unexpected service or a fault fails loudly.
User-approved entry boundary (2026-10-21): the oracle rejects writes to an
instruction already fetched, or later fetching an instruction byte previously
written during the call, including the retained return instruction. It reports
failure, never a skipped/passing comparison.
The transform declines unchanged unless DS is at least CS+1000h (computed
without 16-bit wrap) and DS ≤ F000h; its data cannot overlap the CS window.
The original generated fallback remains responsible for declined entries;
arbitrary self-modifying code outside D16 is not admitted by this contract.

The recorded RAM extent is retained separately from mapped padding. Both x86
and native validation reject reads or writes outside that extent; x86 instruction
fetches must also lie within it.

Compare every register, live defined flags, control flags, written-address sets,
each byte's write-value history and all RAM. No memory ignore list. Merged stores
may reorder distinct bytes, but cannot omit or change a byte's writes.
`--generated MODULE+offset` establishes the
harness against the current translator on an original entry; it is not evidence
for a future native implementation. The native differential must use the same
inputs without seeing the x86 results. Recorded game states supplement, never
replace, arithmetic boundaries and guard-edge cases from the rendering map.

Tests: `make t-compute-contract t-sab-compute-contract`,
`t-point-transform t-sab-point-transform`, and
`t-compute-code-writes t-sab-compute-code-writes`; the predecessor cases
also run in `tests/m68k_blocks.py`. Generated synthetic callback bodies exercise
both arms against x86 without hand-porting guest code. Admission, wrong-arm,
register, missing/duplicate store, live-flag and uncaptured-memory plants must
be caught.

Before enabling an authorized row: record original entry states with the
existing DOSBox snapshot mechanism, add the routine-specific boundaries and
fallback cases, demonstrate its sabotage, and run the unchanged full gates
with that row active. Keep each row's oracle command and evidence in its
`hle.csv` entry. Price, measure and accept under speed-plan §3–4.
Captures and byte-derived test material remain local; never re-record an
existing reference without approval.

## Poll contract (U5)

Approved by the user 2026-10-21 (native-plan U5); replaces the C1 exact-handoff
design (`f4a7c68`). Not implemented: C3 builds it; each routine still needs U6
and S1–S9. Exceptional flow, multiple root returns, REP, device or
interrupt-control effects and nested HLE remain outside this contract.

The native routine is written by us, so its polls are chosen, not copied. Each
chosen poll stands for an original x86 point (address, visit) at which the native
state equals the original's. The reference takes interrupts only at poll points
(`build/gen/poll-points.csv`, pc-reference-loop.md `--polls`), so the poll set is
a translator decision that the reference follows.

### Poll set of a row

- **Removed:** every poll reachable only through the row's body. Both arms
  (native and the declined generated body) omit them.
- **Kept:** a poll also reachable from outside the row (shared callee, internal
  entry) stays in the set; the native routine treats each of its visits as a
  sync poll, or the row is rejected.
- **Return poll:** a poll at the retained original return instruction, emitted in
  generated code before it, so both arms visit it once per call.
- **Sync polls (optional):** x86 sites inside the body, listed in the row. At each
  visit the native state equals the original's at that site and visit: all
  registers, segments, live/control flags, RAM and each byte's write history (U3);
  no store moves across it. Visit order and counts at sync sites match the
  original. With G_IRQ set the callback returns POLL_EXIT (translator-assigned
  exit ID) to a generated trampoline that restores the site's ABI and enters its
  existing IRQ stub; generated code completes the routine and its return checks.
  The native loop is never resumed. Choose sites where this state is cheap
  (outer-loop heads after a pass).
- Every poll reads G_IRQ fresh and does not test IF (G_IRQ also carries bench and
  presentation requests); the runtime owns IF and the pending queue.

### Admission

- **No waiting:** every loop whose poll is removed must terminate without
  interrupt or device effects (proved bound or entry-derived trip count). A loop
  that can wait on timer, key, mouse or other interrupt-written state keeps its
  poll as a sync poll, or the row is rejected.
- **Latency (user, 2026-10-21):** a posted guest interrupt may wait up to one PIT
  period inside a native routine. The longest stretch without a poll visit
  (entry to first sync, between syncs, last sync to the return poll), in A1200
  cycles on all S3 inputs and boundary cases, is at most one period at the
  game's rate (236.7 Hz: about 59,900 cycles at 14.19 MHz). Over the bound: add
  sync polls or reject. Ticks queue in the 32-entry `rt_irq_ring` and are
  delivered in order at the next poll; the bound keeps a routine from delaying
  more than one tick.
- Poll-free rows (the `B54B` transform) are unchanged: no return poll is added.

### References (user, 2026-10-21)

A row that changes the poll set re-records every affected DOSBox reference with
the new `poll-points.csv` in the same commit, then runs full gates against them.
Record the old and new poll-set fingerprints (`summary.txt` `polls=`) and the
re-recorded references in the commit message. This is the only approved
reference change: no PIT rate, interrupt order, fixture or tolerance changes.

### Validation and plants

- Rows without sync polls: the existing compute oracle, entry to retained return.
- Sync polls: the x86 oracle stops before the n-th arrival at each sync site and
  records the original state/write-history prefix; the native exit is compared
  against it, then the generated continuation through the return. Native tests
  get the same inputs and forced-pending schedule, never the x86 results.
- Diagnostic replay and bench observe the same visits in both arms, with native
  execution enabled in diagnostic builds. No event is delivered inside a callback.
- Coverage: zero/one/many passes; first, middle and terminating sync visits;
  G_IRQ clear, pending on entry and between visits; IF clear/set; queued ticks
  across a long routine; decline and complete arms.
- Plants, each caught: a removed poll still emitted in one arm, a missing return
  poll, a removed poll on a waiting loop, stale register/flag or missing store at
  a sync exit, a store before its sync poll, skipped/duplicate sync visit, wrong
  exit site, cached G_IRQ or IF gating, resumed native loop, latency over bound.

C3 is complete when admission, emitter (poll removal, return poll, exit
trampolines), oracle, controls and plants pass, followed by full gates.
