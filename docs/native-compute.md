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

**Poll policy (user, 2026-10-20):** reject routines whose reachable body or
callees contain polls. Supporting them requires a separately approved contract.
Do not alter the poll set, interrupt order or PIT rate.

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

## Proposed poll contract (C1; awaiting U5)

Design only. C2/U5 decision requested 2026-10-21; awaiting the user’s approval.
The enabled ABI and poll-free admission above remain unchanged.
U5 approves this contract before C3 implementation; U6 separately authorizes
each routine. No new poll site, PIT rate, interrupt order or reference is
approved here. C3 must retain the poll-set fingerprint and existing references.

### Admission and visit semantics

The translator proves the complete reachable CFG and enumerates every existing
poll, including callees. Cycles are allowed only with proved control flow and
an exact mapping from native execution to the original ordered poll visits.
No profile-derived bounds or annotation assertions substitute for that proof.
Unresolved transfers, exceptional flow, multiple root returns, REP, device or
interrupt-control effects and nested HLE remain outside the existing contract;
C does not independently admit them. A callee that fails admission rejects the
whole row. Internal entries retain their generated implementation.

A visit is arrival at a poll before its guest instruction, including entry by
fall-through or a forward edge; it is not just a taken backward branch. For each
entry state, native execution must preserve the ordered sequence of site identities
and visit counts, not just totals. At every visit it performs a fresh byte read of
G_IRQ. It must not gate that read or handoff on IF: G_IRQ also requests bench and
presentation work, and the runtime owns pending-IRQ/IF handling.

An algorithm with fewer arithmetic passes still performs every original poll
visit in order. For example, xpnorm20 may calculate a shift count once, but must
visit D5DA once for each original arrival, including the terminating visit, and
reconstruct each visit's intermediate values and flags. It may not do final guest
stores before their original visit interval, replay all checks at the end, or
replace repeated G_IRQ reads with one read plus a count. Computing private
intermediates early is allowed only if it cannot fault or expose future state.
If the exact visit sequence or intermediate state cannot be proved, keep the
original loop. Price the retained checks, state reconstruction and stores.

### State and generated handoff

At a requested exit, materialize the exact pre-instruction guest state: all
registers and segments, coherent segment bases and SP/BP mirrors, live defined
status flags and all control flags. Liveness includes the generated IRQ path
and its pushed FLAGS, not merely the normal successor. Retain all RAM and each
byte's complete write history up to that visit (U3), with existing SMC/display
bookkeeping. Store reordering across a poll boundary is forbidden. Uncaptured
memory and self-modification retain the rejection/guard rules above.

Extend the callback result explicitly, without reinterpreting existing compute
rows: DECLINE (unchanged), COMPLETE (original generated return), or POLL_EXIT
(translator-assigned exit ID). Invalid IDs fail loudly. Only the emitter maps
IDs to guest sites; runtime helpers do not test guest addresses. The callback
balances its native stack and returns to a generated exit trampoline, which
restores the site's generated ABI and enters its existing IRQ stub. It must not
retest G_IRQ, re-enter the HLE hook, or count the same visit twice. The stub alone
calls rt_irq with the original CS:IP and continues at the exact generated
post-poll label; it leaves any BP-specialized copy. All normal guards and return
checks remain. Handler changes to registers, segments or RAM take effect: there
is no return to a stale native loop continuation. Even if IF is clear or no
vector is delivered, execution stays generated after handoff.

Callee exits also require the original guest call/stack writes and generated
return-check continuations. Admission must prove that the emitter can rebuild
that continuation chain without replaying guest writes or leaving native stack
frames behind. If it cannot, reject the row; jumping into a callee with only its
guest stack reconstructed is insufficient. Guards that can decline run before
any mutation; a late unsupported case cannot restart the original entry.

Diagnostic replay and host validation must observe the same logical visits as
the generated path, even when G_IRQ was initially clear. A due diagnostic event
requires materializing state and leaving the callback before the generated
diagnostic hook delivers it. Use a distinct generated entry before that hook,
without running the HLE hook again; this differs from the production pending-IRQ
exit directly to the IRQ stub. Preserve visit/service counts and same-visit IRQ
groups: each observer runs once, and the handoff must not repeat its accounting. Bench mode uses
the same G_IRQ handoff and rt_irq_c accounting, never a native approximation.
C3 must validate these paths with native execution enabled, not silently disable
it in diagnostic builds. No event is delivered inside a native callback.

### Oracle, controls and C3 completion

Extend the x86 oracle to stop before the instruction at the n-th arrival at each
poll. Record the ordered visit trace and state/write-history prefix from the
original; never derive expected visits from native results. Establish the
extended harness against generated code first. Native tests receive the same
entry state and forced-pending schedule, without the x86 outputs.

For every exercised site and visit, compare the native exit against that x86
prefix: registers, defined live/control flags, full RAM, written-address set and
per-byte history. Then run the generated continuation and compare against the
original through the retained return. IRQ cases compare the original handler,
interrupt frame, ordering, modified state and subsequent execution too. Existing
DOSBox fixtures remain the service/IRQ oracle; synthetic x86 cases supply
boundary coverage. Missing sites, visits, input or an execution limit fail loudly.

C3 coverage must include:

- Zero/one/many loop passes, first/middle/last and terminating visits, every
  proved predecessor kind, multiple sites and nested calls; generated-only
  internal entries, decline and complete arms.
- Clear G_IRQ throughout; pending on entry and between successive visits;
  IF clear/set, BIOS and guest handlers, multiple queued vectors at one visit,
  handler changes to BP/segments/RAM, and existing re-arm behaviour.
- Prefix writes, wrap/alias and guard boundaries, IRQ-visible flags, diagnostic
  event scheduling and bench visits; original return checks after every exit.
- Plants for stale registers/flags, missing prefix stores, a future store before
  its poll, skipped/duplicate visits, wrong site/count, cached G_IRQ or IF gating,
  lost callee continuation and stale native resumption. Every plant must be caught.

C3 is complete only when admission, generated exit leaders/trampolines, oracle,
positive controls and sabotage pass, followed by full gates (the change spans
control flow, flags, interrupts and validation). This does not enable a routine:
N4 still needs U6 and S1–S9, a viable price including exit overhead, and unchanged
references. Exceptional-flow/multiple-return contracts remain separate work.
