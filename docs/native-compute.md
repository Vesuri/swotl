# Native compute contract

No guest routine is enabled. User authorization (2026-10-21, native-plan U2):
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

Tests: `make t-compute-contract t-sab-compute-contract`; the predecessor cases
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
