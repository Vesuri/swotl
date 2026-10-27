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
Since irq-plan I10 (user 2026-10-26, go-ahead for each native) `D5A6` is one row up to
its projection call (D614, continuing at D618; folds R38's D5DA loop) and `BB70` one row
up to its RETF. The scenery clear at 10A2F uses a continuation endpoint (R40). Loop rows:
the sprite row `4E89` (`sprite_row`: packet loop, span setup and, since 2026-10-27, the
span walk loop 4FD3..5032 calling the cell walk; widens R42), D69C's
pixel loops at D92A and D95C (R44, retaining generated clipping, shared callees and
returns), SPAZ's OPL delay loops `D03` and `D0F` in O(1) (F9, speed-plan §2.9 exception).
Rows with guest calls as continuation exits (`hle.csv` `exits`) and
[re-entries](#re-entries-irq-plan-i10-user-2026-10-26): BFD1's scanline loop from C000
(F5, folds R48's ordering row: `end` C42C), `BD68` edge submission, `F290` tile
selection, `FDE0` terrain polygons (calls `B52D` and `BB70` directly) and `109D6`'s
vertex loops 10C08–10F5F. Measurements: speed-plan §7. Remaining candidates and user
deferrals: open-work 14b. Admission, pricing and S1–S9 remain required. Since
[irq-plan](irq-plan.md) I9 every row is poll-free (RC5, user 2026-10-24): U3 write
histories, the U5 poll contract and exact native polling are retired; nothing observes a
row's intermediate state.

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

Before enabling an authorized row: record original entry states with
`tools/native_entries.py` (DOSBox snapshots per fixture), add the routine-specific boundaries and
fallback cases, demonstrate its sabotage, and run the relevant checks under AGENTS.md
with that row active (native-plan S8). Keep each row's oracle command and evidence in its
`hle.csv` entry. Price, measure and accept under speed-plan §3–4.
Captures and byte-derived test material remain local; never re-record an
existing reference without approval.

## Loops and the sync set (RC5)

User 2026-10-24 (irq-plan RC5), implemented at I9. Production code has no poll
checks; tests and the reference deliver interrupts at sync points
(`build/gen/poll-points.csv`). A row is atomic to the interrupt: the loop heads
in its body, callees and re-entries included, leave the sync set (`emit.Program`), in
both arms and for flow from outside alike, and the references are recorded without them
(RC3: old/new `polls=` fingerprints in the commit). A row whose footprint meets
the handler's is rejected (I2; `irq.check_rows` takes a row with exits by its proved
body). No latency bound (RC6).

A native may also continue at a root loop head in generated code with exact
state there (the BFD1 wrap peeks). Entries: the hook at `first` and the `entries`
re-entry hooks (below).

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

### Re-entries (irq-plan I10, user 2026-10-26)

Optional `entries` on a row with `exits` lists module offsets where the row's
native resumes after a continuation exit's call returns (or anywhere in its
body). Each gets a hook to the same service with `moveq #1+k,d7` (the first
hook passes 0); the native dispatches on it after its guards and may decline
there before any mutation. A re-entry keeps its own liveness (it is a call's return
site; resume liveness would flow into the callee): the native defines every
flag live at a resume it reaches from a re-entry. Entries are walked as roots (their flow joins the
body, loop heads included), are leaders, and their liveness includes every
resume; an entry may not be an endpoint or another row's body. Rows: BFD1
(C2A8, C2B6, C2C0, C3EE), BD68 (BE1B, BEDB, BF97, BFB4), F290 (F414, F470, F5E8),
FDE0 (FF6A, 1006B, 1008B, 100B8, 1019E, 101E6, 101F6, 10211: after its eight calls),
109D6 (10CE4, 10F21: after the B52D/D5A6 calls and their 9C20h sync writes).
A re-entry may skip the first hook's admission when the native re-checks it
before relying on it: BFD1 re-admits at each scanline head (DF = 0, ES and SS
1000h apart) and, failing there inside, resumes at C000, whose hook declines.
The IRQ0 footprint check (`irq.check_rows`) takes a row with exits by its proved
body: the stretches from an exit to the next entry stay generated, sync accesses
included (plant `compute-exit-body`).
Checks: each row's differential from every entry (`t-rasterize`,
`t-edge-submit`, `t-terrain-select`, `t-terrain-polygons`, `t-ground-vertices`) and sabotage.

### Direct native calls (irq-plan I10, user 2026-10-27)

A native may call another row's native at that row's call site instead of
taking the exit: it stores the call's return address as the original call does
and enters the callee with the callee's hook state (d6 = CS, d7 per its
dispatch). The callee declines before any mutation, so a decline takes the exit
unchanged; a handled call continues in the caller. FDE0 calls the transform
(B52D) and classify (BB70) natives this way. The caller's differential runs each
case with the real callee natives and with declining callees (every exit taken).

### Code writes and the cell walk (user 2026-10-27)

User: "extend the native contract for the sprite decoder's walk loop". A native may
write code bytes inside a D16 cell cache (translator-design D16) only through the
bookkeeping the lowered CS stores use (`lower.code_store`): a RET planted at a covered
cell start sets `smc_walk_plant` when none is planted, the cell's first byte back
clears it, anything else calls `smc_walk_wb` (which drops the cache when needed).
Segment loads below `smc_seg_limit` call `smc_expose` as `lower.putseg` does. It may
call the generated cell walk (`smc_walk`, d7 = entry IP) at a root near call whose
only targets are the walk (`compute.validate` records it in `Region.walks`; a walk
call in a callee or a far call rejects), with the guest return pushed as the original
does; a return elsewhere goes to `rt_ret_mismatch` as the generated return check
does. A target outside the cells, or any state the native does not handle, resumes in
generated code before the call (a root loop head or endpoint). The generated program
exports the one cache's labels by surface name (`emit.WALK_ALIASES`). Oracle:
`compute_oracle.run(cells=…)` exempts writes into the cells (`cell_addresses`) from
the entry boundary rule (the walk executes the planted RET; the restore rewrites a
fetched byte); every other code write still fails, and the cells join `compare`'s
code set, so plant and restore addresses are compared. The cache bytes (`_cov`
through `_plant`) at the endpoint must equal the generated body's for the case (the
guest state cannot show a stale plant). Row: `sprite_row`'s walk loop
4FD3..5032 (`tests/test_sprite_packet.py`: native linked against the generated walk;
synthetic RET, MOV and reload cells, a sprite DS reaching the cells, DF set and span
starts outside the cells, captured entries; plants).
