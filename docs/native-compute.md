# Native compute contract

Enabled: the user-authorized (2026-10-21, native-plan U2)
`SWOTL.EXE+B54B` transform pilot from `xform20`, retaining generated `B52D`
and return checks. U3 keeps complete byte-write history. The user-authorized
(2026-10-22, U4; whole routine 2026-10-24, U10) projection `B017` with its
divide `B4E2` is one poll-free row with four returns (speed-plan §7, F3a),
from `xproj20`/`xdiv20` and the original's 16-bit path; it folds the earlier
`B393` (R36) and `B4E2` (R37) rows. The divide handles the explicit
zero-denominator path; for nonzero denominators both original word quotients
fit (DX=0, then remainder<divisor).
The user-authorized (2026-10-22, U6) D5DA normalization loop from
`xpnorm20` resumes at D5F8 under U5 (R38); it writes no guest memory.
The scenery clear at 10A2F uses a continuation endpoint (R40); the sprite
packet loop at 4ECD preserves every original poll (R42). D69C’s pixel loops
at D92A and D95C use the same exact-poll contract (R44),
retaining generated clipping, shared callees and returns.
Remaining candidates and user deferrals: open-work 14b. Admission, pricing
and S1–S9 remain required.

## Admission

`annotations/hle.csv` accepts an optional `kind`: absent/`hook` retains the sound
hooks' ABI; `compute` requires empty `args`, a reason and an oracle. `first` is
the entry, `last` the instruction immediately before the original RET/RETF.
The original return and its caller's return check stay generated.

`translator/compute.py` proves reachable flow, including callees, from the CFG.
The initial contract requires one root return, no cycles, no unresolved flow,
no poll points, no nested HLE hooks and no runtime/device effects. Interrupt
control and diagnostic replay hooks are rejected too. Internal entry points
remain generated and valid. A rejected row is a generation error, not fallback
authorization. [U5](#poll-contract-u5) admits polls and loops;
[U8](#contract-extensions-u8) admits REP, divide faults (exact decline) and
multiple returns. U5 changes the poll set only for an authorized row (U6);
interrupt order and PIT rate stay.

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
The handled path rechecks the current BP against the proved component range
when a specialized resume exists. It enters that copy only on success; otherwise
it takes the exact resume. Both destinations retain their poll, and interrupt
return still leaves the copy. The native entry’s guard is never inherited.

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
The transform and projection decline unchanged unless DS is at least CS+1000h (computed
without 16-bit wrap) and DS ≤ F000h; their data cannot overlap the CS window.
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
`t-point-transform t-sab-point-transform`,
`t-point-projection t-sab-point-projection`,
`t-point-normalise t-sab-point-normalise`, and
`t-compute-code-writes t-sab-compute-code-writes`; the predecessor cases
also run in `tests/m68k_blocks.py`. Generated synthetic callback bodies exercise
both arms against x86 without hand-porting guest code. Admission, wrong-arm,
register, missing/duplicate store, live-flag and uncaptured-memory plants must
be caught.

Before enabling an authorized row: record original entry states with the
existing DOSBox snapshot mechanism, add the routine-specific boundaries and
fallback cases, demonstrate its sabotage, and run the relevant checks under AGENTS.md
with that row active (native-plan S8). Keep each row's oracle command and evidence in its
`hle.csv` entry. Price, measure and accept under speed-plan §3–4.
Captures and byte-derived test material remain local; never re-record an
existing reference without approval.

## Poll contract (U5)

Approved by the user 2026-10-21 (native-plan U5); replaces the C1 exact-handoff
design (`f4a7c68`). Implemented by C3; R38 uses it for normalization. Each routine needs
U6 and S1–S9. Divide faults, multiple root returns and REP: [U8](#contract-extensions-u8).
Device or interrupt-control effects and nested HLE remain outside every contract.

The native routine is written by us, so its polls are chosen, not copied. Each
chosen poll stands for an original x86 point at which the native state equals
the original's. The reference takes interrupts only at poll points
(`build/gen/poll-points.csv`, pc-reference-loop.md `--polls`), so the poll set is
a translator decision that the reference follows.

### Row and poll set

`hle.csv` `polls` on a `compute` row: empty keeps the poll-free contract;
`return` [sync offsets...] selects U5. `translator/compute.py` `validate_polled`:

- **Removed:** every poll in the body (callees included). Both arms omit them:
  the declined generated body has no poll there either.
- **Kept:** a poll that flow from outside reaches without passing a hook entry
  (internal entry, shared callee) must be a sync site, or the row is rejected.
  Sync sites in callees and recursion are rejected.
- **Return poll:** at the retained original return, in generated code, so every
  call visits it once.
- **Sync sites:** root-body instructions listed in the row; each becomes a poll,
  a resume and a hook entry. Its generated code polls first (the visit), then
  calls the callback again. The callback never reads G_IRQ: it runs one segment
  and resumes at the return or at the next sync site with exact state there (all
  registers, segments, live/control flags, RAM and each byte's write history,
  U3; no store moves across a site). Every visit, interrupt delivery, diagnostic
  replay hook and bench service stays in generated code; nothing is delivered
  inside a callback and no native loop is resumed.

ABI on U5 rows (`compute.polled_hook`): d7 in = entry (0 the row's first
instruction, k sync site k); d7.l out = 0 declines (generated code continues
at that entry), 1 resumes at the return, 1 + k at sync site k; any other value
stops loudly (`rt_stop_unknown` with the hook's IP). Each hook may resume at any
of them, so its liveness includes theirs.

### Admission

- **No pure wait:** a removed poll's loop needs an exit whose branch condition
  or target can change inside the loop (`compute.wait`). Proved invariant:
  registers and flags the loop never writes or writes only with invariant
  values, and loads from invariant addresses when the loop stores nothing. This
  rejects loops only an interrupt can end; it is not a termination proof, so
  termination on every S3 input and the latency bound are its evidence.
  A backward jump that closes no cycle is not a loop.
- **Latency (user, 2026-10-21):** a posted guest interrupt may wait up to one PIT
  period inside a native routine: the longest stretch between poll visits
  (entry, sync sites, return), on all S3 inputs and boundary cases, is at most
  `compute_oracle.PIT_PERIOD_CYCLES` = 59,900 model cycles (236.7 Hz at
  14.19 MHz, rounded down). `compute_oracle.PollGaps` measures it on the host
  68k core: cost-model weights without the i-cache discount, gaps between G_IRQ
  reads. Over the bound: add sync sites or reject. Ticks queue in the 32-entry
  `rt_irq_ring` and are delivered in order at the next poll.
- Poll-free rows (the `B54B` transform) are unchanged: no return poll is added.

### References (user, 2026-10-21)

A row that changes the poll set re-records every affected DOSBox reference with
the new `poll-points.csv` in the same commit, then runs the affected host/replay
checks and compute-contract gates (AGENTS.md validation scope).
Record the old and new poll-set fingerprints (`summary.txt` `polls=`) and the
re-recorded references in the commit message. This is the only approved
reference change: no PIT rate, interrupt order, fixture or tolerance changes.

### Validation and plants

- The x86 oracle (`compute_oracle.run` with `stops`) stops before each arrival at
  a sync site, so a chain of runs gives the original state and write-history
  prefix at every visit; interrupts' writes are applied at their visits.
  Natives are compared at every visit and at the return, against those prefixes,
  with the same inputs and interrupt schedule and without the x86 results (S6).
- `make t-compute-polls t-sab-compute-polls` (`tests/test_compute_polls.py`):
  admission controls on synthetic graphs; emission on an in-memory row at
  `SWOTL.EXE+135E0` (removed polls absent in both arms, return poll, poll
  before hook at sync sites, dispatch); and a generated-handoff differential on
  the assembled program, with a test double driven by the x86 standing in for
  the callback (protocol only, not native evidence). It covers decline, handle and
  alternating arms, zero/one/many passes, interrupts between visits that change
  the loop bound, the return-poll interrupt and the latency monitor.
- Plants, each caught: pure-wait and shared-poll admission, a kept removed
  poll, a missing return poll, hook before the sync poll, stale register,
  missing store, store before its sync site, skipped and duplicate visits,
  wrong resume site, stale native continuation, latency over the bound; an
  invalid resume id stops loudly.

## Contract extensions (U8)

Approved by the user 2026-10-21 (native-plan U8); implemented by C4
(`compute.successors`, `Region`/`Polled.returns`, `hle.csv` `end`). They apply
to poll-free and U5 rows alike; everything else in the contract is unchanged.

- **REP:** a REP string instruction in the body is admitted when its address is
  not a poll in the row's resulting poll set. The reference delivers interrupts
  only at polls (`SWOTL_IrqPoint`, trace patch) and resumes a sliced REP at its
  own address, so elsewhere a REP is uninterruptible, as the x86 oracle runs it.
  A REP at a removed poll is removed like any poll (U5, references re-recorded);
  a REP at a kept poll still rejects the row.
- **Divide fault:** the `div`/`idiv`/`aam` edge to the INT 00h handler is a
  decline edge, not body. The native checks the fault condition (divisor 0,
  quotient out of range) and declines before any mutation in its current segment
  (at entry or at the sync site that began it), so the generated code takes the
  exact fault. `compute_oracle.run` raises `DivideFault` with the original's
  state at the faulting instruction, where the declined arm enters `rt_fault`;
  flags compare as live at the INT 00h handler (open-work 24).
- **Multiple returns:** every root return in the range is a resume. d7.l out =
  1..R selects return r (ascending offset), R + k sync site k; U5 rows poll at
  each return. Poll-free rows with several returns use the U5 hook and dispatch
  (d7 in = 0) without polls; with one return they keep `tst.l d7; bne resume`.
  `compute_oracle.run(returns=...)` stops before any of them.
- **Flow out of range, unresolved flow:** no contract change. `hle.csv` `end`
  (hex, exclusive) widens the root range past the declared return, for compiled
  C's loop bodies after the epilogue; resolve unresolved targets in
  `annotations/` as for any translated code; otherwise the row is rejected.

`make t-compute-u8 t-sab-compute-u8` (`tests/test_compute_u8.py`): emission on
in-memory rows at `SWOTL.EXE` `DCE9` (poll-free, two returns), `DB9D` (U5,
three returns, removed loop, `div bx` fault), `1446A` (U5, REPNE SCASB in the
removed loop) and `15416` (U5, `end`); a handoff differential with an x86-driven
double on each, both arms, every return and the fault reached, an interrupt at
every return poll. Plants caught: REP as effect, fault edge as flow, returns
dropped (poll-free, U5), early return without poll, mutate then decline, no
decline at a fault, wrong return. Admission controls: `t-compute-contract`,
`t-compute-polls`.

## Continuation endpoints (user, 2026-10-22)

Approved for the D5A6 normalization loop: an explicit `hle.csv`
`resume=continue` admits a non-return endpoint on a U5 compute row.
`last` still names the instruction immediately before that endpoint.
The endpoint is outside the replaced body and remains generated; it gets
the U5 poll and resume id 1. Root returns before it, an unreachable endpoint,
escaping flow and range extensions reject. Calls retain all existing admission
checks, including nested-hook rejection. The existing sync, shared-poll,
live-state, latency and reference rules apply unchanged. Empty `resume`
retains the return-only contract.

Checks: `tests/test_compute_endpoint.py` (admission, emission, poll sabotage),
plus the row's native differential and the existing U5/U8 protocol checks.

### Multiple continuation endpoints (user, 2026-10-22)

Approved for 109D6’s scenery vertex loops; user also approved F290’s
F31A → F339/F35F/F3B4 tile-selection scope on 2026-10-23. Optional `exits` on a
`resume=continue` row lists additional module offsets. The primary endpoint
still follows `last`; every endpoint must be a distinct, reachable non-return
instruction in the root module, outside the replaced body. An endpoint may be
a call: admission stops before it, leaving the call and return check generated.
Callee endpoints, undeclared escapes, unreachable endpoints, nested hooks and
shared removed polls reject. Existing range and latency rules remain.

All endpoints become leaders and U5 polls; d7 resumes 1..R select them in
ascending offset order, followed by the sync sites. Liveness includes every
endpoint. This adds no production row or poll change by itself.
Checks: `t-compute-multi-endpoint`, `t-sab-compute-multi-endpoint`, existing
endpoint/U5/U8/contract checks; the routine still needs S1–S9.

## Exact native polling (user, 2026-10-23)

User authorized implementation and validation for 4DAE on 2026-10-23.
The opt-in `polls=exact` contract is used by the 4DAE packet loop.
U5 above remains unchanged:

- Keep the original poll set in both arms; add no endpoint poll. Declined
  generated code keeps its existing polls. No reference re-recording is needed
  solely for this mode if the poll fingerprint stays identical.
- At every original poll, native registers, segments, live flags, RAM and
  per-byte write history equal the original. A7 holds only the callback's
  return address: no private stack frame or saved guest values remain.
- The ordinary native path tests G_IRQ at an exported canonical visit alias.
  No pending work continues at a distinct execution alias. Pending work
  tail-jumps to a translator-generated trampoline: original CS:IP, existing
  rt_irq path, then RTS to the callback's caller with an explicit after-poll
  resume result. Dispatch resumes after the original poll, never its entry.
  Guest state changed by a handler is neither restored nor reused from a
  native cache; any new callback invocation rechecks its guards.
- Diagnostic builds tail-hand off every native poll to a generated trampoline
  using the existing replay hook and poll order. After-poll dispatch avoids
  replaying a visit. Other diagnostic interior points require explicit support
  or admission rejection, never silently missing a hook.
- Generated metadata binds native visit/execution aliases to original points.
  Host IRQ groups retain their actual A7 key: the tail jump adds no call frame
  before rt_irq. Key/snapshot/release triggers and census consumers need the
  same aliases. All original polls must be accounted for, including first entry.
- Bench watching can hold G_IRQ set without a queued guest IRQ; it still takes
  the trampoline once per visit. Preserve display refresh, IF handling, queue
  order and checked guest-handler returns through rt_irq.

Local protocol evidence: `tmp/native/N4-sprite/poll-tail-protocol.log` exercises
Host.run's hooks (two queued IRQs, no event, stack ownership, exact-once visits).
`tail-asm.json` / `tail-asm.log` exercise a synthetic 68020 callback with an IRQ
stub, handler register changes and persistent bench watch. Missing polls,
duplicate visits and bad native stack depth are caught. These probes are not
production IRQ/replay integration or guest-routine correctness evidence.

Checks: `t-compute-exact-polls`, `t-sab-compute-exact-polls`,
`t-sprite-packet`, `t-sab-sprite-packet`; unchanged m4/c13/c27 host and
diagnostic replays. Current acceptance status: open-work 14b.
