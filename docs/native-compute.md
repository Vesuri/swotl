# Native compute contract

Enabled: the user-authorized (2026-10-21, native-plan U2)
transform from `xform20`, since 2026-10-24 (U10, F3b) the whole `B52D`
wrapper with `B54B`: pushes stored, SI/DI/BP restored, `retf` generated. The user-authorized
(2026-10-22, U4; whole routine 2026-10-24, U10) projection `B017` with its
divide `B4E2` is one poll-free row with four returns (speed-plan §7, F3a),
from `xproj20`/`xdiv20` and the original's 16-bit path; it folds the earlier
`B393` (R36) and `B4E2` (R37) rows. The divide handles the explicit
zero-denominator path; for nonzero denominators both original word quotients
fit (DX=0, then remainder<divisor).
The user-authorized (2026-10-22, U6) D5DA normalization loop from
`xpnorm20` resumes at D5F8 (R38); it writes no guest memory.
The scenery clear at 10A2F uses a continuation endpoint (R40); the sprite
packet loop at 4ECD (R42), D69C’s pixel loops at D92A and D95C (R44,
retaining generated clipping, shared callees and returns), BFD1's scanline
loop from C000 (F5, folds R48's ordering row: `end` C42C, its guest calls and
epilogue continuation exits, `hle.csv` `exits`) and SPAZ's OPL delay loops
`D03` and `D0F` (F9: every iteration and stack store kept) are loop rows.
Remaining candidates and user deferrals: open-work 14b. Admission, pricing
and S1–S9 remain required. Since [irq-plan](irq-plan.md) I9 every row is
poll-free (RC5, user 2026-10-24): U3 write histories, the U5 poll contract and
exact native polling are retired; nothing observes a row's intermediate state.

## Admission

`annotations/hle.csv` accepts an optional `kind`: absent/`hook` retains the sound
hooks' ABI; `compute` requires empty `args`, a reason and an oracle. `first` is
the entry, `last` the instruction immediately before the original RET/RETF.
The original return and its caller's return check stay generated.

`translator/compute.py` `validate` proves reachable flow, including callees,
from the CFG: no unresolved flow, no recursion, no nested HLE hooks, no
runtime/device or interrupt-control effects, no diagnostic replay hook or REP
slice, and no sync point other than a loop head (I2: a sync access meets the
IRQ0 handler's footprint; `irq.Proof.check_rows` also rejects one in the range
or body). Loops are admitted ([below](#loops-and-the-sync-set-rc5));
[U8](#contract-extensions-u8) admits REP, divide faults (exact decline) and
multiple returns. Internal entry points remain generated and valid. A rejected
row is a generation error, not fallback authorization. Interrupt order and PIT
rate stay.

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
it takes the exact resume. The native entry’s guard is never inherited.

At the resume all RAM equals the original's; written-address sets match for
code (SMC) and VRAM (RC5). Effective-address arithmetic wraps at 16 bits as the original does;
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

Compare (`compute_oracle.compare`) every register, live defined flags, control
flags and all RAM at the resume reached, plus the written-address sets for code
(`code_addresses`) and VRAM (A0000–BFFFFh). No memory ignore list. Write order,
count and intermediate values are not compared (RC5).
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

## Loops and the sync set (RC5)

User 2026-10-24 (irq-plan RC5), implemented at I9. Production code has no poll
checks; tests and the reference deliver interrupts at sync points
(`build/gen/poll-points.csv`). A row is atomic to the interrupt: the loop heads
in its body, callees included, leave the sync set (`emit.Program`), in both arms
and for flow from outside alike, and the references are recorded without them
(RC3: old/new `polls=` fingerprints in the commit). A row whose footprint meets
the handler's is rejected (I2). No latency bound (RC6).

A native may also continue at a root loop head in generated code with exact
state there (the BFD1 wrap peeks); one hook at `first` is the only entry.

## Contract extensions (U8)

Approved by the user 2026-10-21 (native-plan U8); implemented by C4
(`compute.successors`, `Region.returns`, `hle.csv` `end`).

- **REP:** a REP string instruction in the body is admitted, unless a
  diagnostic REP slice hook sits there. The reference resumes a sliced REP only
  at sync points, and a row's body holds none, so in a row a REP is
  uninterruptible, as the x86 oracle runs it.
- **Divide fault:** the `div`/`idiv`/`aam` edge to the INT 00h handler is a
  decline edge, not body. The native checks the fault condition (divisor 0,
  quotient out of range) and declines before any mutation in its current segment
  (at entry), so the generated code takes the
  exact fault. `compute_oracle.run` raises `DivideFault` with the original's
  state at the faulting instruction, where the declined arm enters `rt_fault`;
  flags compare as live at the INT 00h handler (open-work 24).
- **Multiple returns:** every root return in the range is a resume. The hook
  is `tst.l d7; bne` to the resume, or with several resumes to
  `compute.resume_dispatch`: d7.l out = 1..R selects return r (ascending
  offset), R + k root loop head k; any other value stops loudly
  (`rt_stop_unknown` with the hook's IP). Each hook may resume at any of them,
  so its liveness includes theirs. `compute_oracle.run(returns=...)` stops
  before any of them.
- **Flow out of range, unresolved flow:** no contract change. `hle.csv` `end`
  (hex, exclusive) widens the root range past the declared return, for compiled
  C's loop bodies after the epilogue; resolve unresolved targets in
  `annotations/` as for any translated code; otherwise the row is rejected.

`make t-compute-u8 t-sab-compute-u8` (`tests/test_compute_u8.py`): emission on
in-memory rows at `SWOTL.EXE` `DCE9` (two returns), `DB9D` (three returns, a
loop, `div bx` fault), `1446A` (REPNE SCASB in the loop) and `15416` (`end`):
body loop heads leave the sync set, resumes are returns then loop heads; a
handoff differential with an x86-driven double on each, both arms, every return
and the fault reached, no interrupt inside a row. Plants caught: REP as effect,
fault edge as flow, returns dropped, loop head not a resume, body loop head kept
in the sync set, mutate then decline, no decline at a fault, wrong return.
Admission, sync-set and dispatch controls: `t-compute-contract`, `t-compute-loops`.

## Continuation endpoints (user, 2026-10-22)

Approved for the D5A6 normalization loop: an explicit `hle.csv`
`resume=continue` admits a non-return endpoint on a compute row.
`last` still names the instruction immediately before that endpoint.
The endpoint is outside the replaced body and remains generated; it gets
resume id 1. Root returns before it, an unreachable endpoint,
escaping flow and range extensions reject; user 2026-10-24 (F5): `end` may widen
a continuation row past its endpoints, for a loop body after them. Calls retain all existing admission
checks, including nested-hook rejection. The live-state and reference rules
apply unchanged. Empty `resume` retains the return-only contract.

Checks: `tests/test_compute_endpoint.py` (admission, emission, sabotage),
plus the row's native differential and the U8 protocol checks.

### Multiple continuation endpoints (user, 2026-10-22)

Approved for 109D6’s scenery vertex loops; user also approved F290’s
F31A → F339/F35F/F3B4 tile-selection scope on 2026-10-23. Optional `exits` on a
`resume=continue` row lists additional module offsets. The primary endpoint
still follows `last`; every endpoint must be a distinct, reachable non-return
instruction in the root module, outside the replaced body. An endpoint may be
a call: admission stops before it, leaving the call and return check generated.
Callee endpoints, undeclared escapes, unreachable endpoints, nested hooks and
recursion reject. Existing range rules remain.

All endpoints become leaders and resumes; d7 resumes 1..R select them in
ascending offset order, followed by the root loop heads. Liveness includes every
endpoint.
Checks: `t-compute-multi-endpoint`, `t-sab-compute-multi-endpoint`, existing
endpoint/U8/contract checks; the routine still needs S1–S9.
