# Their Finest Hour: what to adapt and how

Evidence for speeding up SWOTL's rendering with what Their Finest Hour's Amiga
version (TFH, same engine family) and its WHDLoad slave show. Static research
2026-10-16; candidate consolidation 2026-10-21 (B1–B3). Open work: [open-work.md](open-work.md) 14b; the plan:
[native-plan.md](native-plan.md). Rules: [speed-plan.md](speed-plan.md) §2. The full
research notes are kept locally in `tmp/tfh-xref/swotl-tfh-rendering-map.2026-10-16.md`.

## Rules

- No original TFH game code or data enters the port ([tfh-cross-reference.md](tfh-cross-reference.md)).
  U0 (2026-10-21) permits adapting the user's improved slave source for individually
  authorized routines; original TFH code remains reference material only.
- Translator work first. Native code for a guest routine only after the user
  authorizes that routine (speed-plan §2.2), as an `hle.csv` row with reason and oracle.
- SWOTL's original x86 is the oracle (Unicorn, DOSBox references); TFH and the slave's
  checks are not. Keep SWOTL's constants, rounding, branch order, scratch writes and
  tables; never take TFH's.

## Inputs

| Input | Where |
|---|---|
| TFH `bob` v1.1, 254,400 bytes, SHA-256 `4b5931c8…22443877` ([tfh-cross-reference.md](tfh-cross-reference.md)) | `../Their Finest Hour/tmp/game/TheirFinestHour/data/bob`; listing `tmp/tfh-xref/BOB.txt` |
| TFH addresses | code-hunk offsets; `jsr d16(a4)` enters a data-hunk `jmp` thunk (A4 = data + 7FFE): resolve it first |
| The slave (the user's): register and 68020 versions of TFH's transform, projection, divide, normalisation and scenery loops; models of the originals | in `../Their Finest Hour/`: `whdload/transform.s`, `whdload/render.s`, `tools/xform_check.py`, `docs/internals.md` |
| SWOTL costs | A3 on `6bf8aef`, 2026-10-21: three 100-field captures (`tmp/native/A3/frames-*/`); run 2 has 28,420,399 cycles and P = 390 ms. Own costs use call-target boundaries; inclusive costs use completed A7 scopes, excluding interrupt delivery. |

## What the slave measured (68020)

- System changes gave most of TFH's gain: caches on, data hunk and chunky buffers
  from Chip to Fast, tear-free pacing. 68020 + Fast 18.8 fps (detail 1) → 23.5
  (detail 0); 68030/50 15.6 → 50; A1200 Chip only 10.6 → 12.5.
- SWOTL has those already: guest RAM and code `MEMF_ANY` (Fast), Chip only for
  bitmaps, copper lists and audio; two display buffers; changed-row C2P; game time
  from the PIT. To carry over: `CACHECHIP` in SWOTL's slave ([whdload.md](whdload.md)).
- Routine rewrites (TFH's originals are hand-written 68000), shares before patching:
  transform 11% of the frame (~83 calls), projection 32-bit path 5.1%, divide 3.8%,
  projection entry 5.4%. Projection entry with callees 1,360 → 1,082 cycles per call,
  scenery object `1142C` 17,481 → 14,863; 22.4 → 23.5 fps.

## Plan

Order, procedure and user decisions: [native-plan.md](native-plan.md).
B4 consolidates the source inventory (B1), admission (B2) and prices (B3).
N1 enables `B54B`, retaining generated `B52D` and return checks. Next: N2
authorization/contracts; U5 polls are implemented, other N4 blockers remain (native-plan C). Current N3 checkpoint and
remaining gap: speed-plan §1/§9. U1 retains executed backward branches.

## Candidates

A3 run 2 costs, with B1–B3 source/admission results. Ceilings are **own cost
removed at zero replacement cost**, in ms/frame; they are not native savings.
The transform saving assumes all calls pass its guard and applies under either
U3 write rule. It is analytical, not a measured speedup. Detailed inclusive
costs, adaptation inventory and eligibility sensitivity: [B3](#b3-candidate-prices).

| SWOTL | Function | Own share | Calls/100 fields | Own ceiling (ms) | Improved slave source | Admission / blocker | Priced saving (ms/frame) |
|---|---|---:|---:|---:|---|---|---|
| `B52D` | transform wrapper | 1.02% | 1,483 | 3.99 | `xform20` with the wrapper | Enabled with `B54B` (F3b) | Measured per-call cost below |
| `B54B` | point transform | 6.17% | 1,483 | 24.06 | `xform20` | Enabled (N1; inside `B52D` since F3b) | 11.48–12.04 priced; measured per-call ratio below |
| `B4E2` | perspective divide | 1.82% | 2,072 | 7.09 | `xdiv20` | Enabled inside `B017` (F3a) | Measured with `B017` below |
| `B017` | projection | 2.99% | 1,036 | 11.65 | `xproj20`; 16-bit path from the original | Whole routine with `B4E2` enabled (F3a) | Measured per-call cost below; no frame-rate claim |
| `D5A6` | normalise/project | 2.07% | 836 | 8.07 | `xpnorm20` | D5DA loop enabled (R38) | Measured per-call cost below; no frame-rate claim |
| `B8A1` | face-facing test | 0% | 0 | 0.00 | None | Admitted; no captured calls | 0 in A3; native cost unpriced |
| `BB70` | polygon bounds/classify | 1.33% | 177 | 5.20 | None | Admitted (U5) | Unpriced |
| `109D6` | ground objects | 2.64% | 109 | 10.31 | `scen_verts`, `clr_scenery`, partial | DOS call in callee | Unpriced |
| `4DAE` | sprite decoder | 7.98% | 49 | 31.12 | None | Packet loop enabled (R42); dispatch remains generated | Measured packet cost below; no frame-rate claim |
| `D69C` | clipped line | 0.99% | 130 | 3.87 | None | Shared callee poll | Unpriced |
| `BD68` | edge submission | 0.67% | 94 | 2.60 | None | Overlay call | Unpriced |
| `FDE0` | terrain polygons | 1.59% | 5 | 6.21 | None | Overlay call | Unpriced |
| `F290` | terrain/scenery selection | 1.10% | 5 | 4.30 | `tile_scenery` | Overlay call | Unpriced |
| `BFD1` | rasterizer | 6.57% | 5 | 25.63 | None | Unresolved callee flow | Unpriced |

Admission after C4: see the [inventory](#compute-admission-inventory). No source/contract means
unpriced, as approved for B3. `B8A1`'s zero calls do not prove unreachability.
TFH counterparts and exact source boundaries remain in the inventory below.

The transform pair is one pilot: keep `B52D` generated, replace only the
`B54B` body. Its estimate takes 390 ms to 377.96–378.52 ms, leaving
137.96–138.52 ms to 240 ms. Across A3's three trajectories, estimated savings
are 10.74–11.27, 11.48–12.04 and 15.12–15.86 ms. No savings are asserted for
unpriced rows. Current measured baseline and variation: speed-plan §1, §9.

User decisions, 2026-10-21: U0 permits adapting the improved slave source;
U1 retains executed backward branches; U2 authorizes only the `B54B` transform
pilot with generated `B52D` and return checks; U3 keeps complete byte-write
history and all bookkeeping/state checks; U4 defers further routines pending
viable prices/contracts and individual authorization. `B8A1` has no captured
A3 work or improved source. Only the authorized transform is enabled.

Not candidates: the cell walk (already optimized by R20), RTSVGA `+3B9A`
(changed-row copy; TFH `283A0` converts 4-bit chunky to planar), RTSVGA `+3DCD`
packed images (`27D40`; SWOTL's FB/FC tokens), TFH image payloads and terrain
map, TFH projectile dispatch, TFH's two-chain rasterizer in place of `BFD1`.

## Native contract

Range, ABI, stores, poll policy (user) and oracle: [native-compute.md](native-compute.md);
poll points stay (speed-plan §2.9); only the U2 transform pilot is authorized. Facts for
adapting the slave:

- Layout: a guest word at L is the 68k word at TOP−L−1, a dword the 68k long at
  TOP−L−3; no byte swaps. 16-bit offset wrap keeps its x86 meaning.
- Scratch: the slave keeps TFH's scratch in registers because it proved every other
  user writes first; the contract keeps every SWOTL store (comparison rule: native-plan U3).
  `B54B` writes scratch DS:`22C6..22D6` besides its outputs.

## Slave source inventory

Source reviewed for B1 at TFH commit `315dbd2c344579ead8edc61bb8c3bec7825ca591`;
paths below are relative to `../Their Finest Hour/whdload/`. These two files match
that commit. SHA-256: `transform.s`
`0aa83493d199ed0ca72cf41bda66258529558ce5079c1670e67e843476492985`;
`render.s` `7eb06de148240ddfd463685cb3d1b0edfdbc381c33a8cba7a0d3c978cdd9985e`.
Line ranges include macros: the one-line entry alone is not the implementation.

| SWOTL | Slave entry and implementation lines | Replacement boundary in TFH |
|---|---|---|
| `B52D` / `B54B` | `transform.s:143` `xform20`; 77–84, 105–117, 120–138 | `2F4AE` body only; `2F48C` wrapper remains original |
| `B4E2` | `transform.s:299–323` `xdiv20` | `2F374` through return |
| `B017` | `transform.s:223` `xproj20`; 161–171, 176–183, 187–218 | only `2F28A..2F372`; entry `2F160`, divides, short path and rejects remain original |
| `D5A6` | `transform.s:291` `xpnorm20`; 227–257, 281–286; target 294 initialized at 46–54 | `3041C..30484`, calls original `2F160` entry |
| `109D6` | `render.s:155–166` `clr_scenery`; 320–492 `scen_verts`; exit base initialized at 130–132 | clear `11454..1148E`; vertex loops `11604..11B34`, not all of `1142C` |
| `F290` | `render.s:175–300` `tile_scenery`; call target 302 initialized at 127–129 | `11138..11338`, calls original `1133A` |
| `B8A1`, `BB70`, `BD68`, `D69C`, `4DAE`, `FDE0` | no improved slave implementation | original reference only: respectively `2F822`, `2FA12`, `2FBB2`, `30486`, `2BACE`, `104B6..10830` |
| `BFD1` | none | no TFH equivalent |

### Source preconditions

All slave routines assume TFH's native big-endian globals at A4 = data hunk +
7FFEh, its native stack, valid TFH tables and caller ABI. `xform20`, `xdiv20`,
`xproj20`, `xpnorm20` require 68020; the scenery routines have no separate 020
variant. The patch lists are `transform.s:68–73` and `render.s:146–148`.
None uses SWOTL's generated ABI. Adaptation must retain x86 registers, flags,
stack stores, segment wrapping and generated write bookkeeping under
[native-compute.md](native-compute.md); caller liveness in TFH is not a SWOTL proof.

- **Transform:** D0/D1/D2 are full point longs; camera 4154/4158/4162(A4),
  matrix magnitudes 4114–4128, signs 4130–4144. Saves D3–D7/A0; trashes D0–D2,
  writes outputs 4236/4228/4232. Source comments (lines 5–17) claim every other
  user overwrites scratch 4246–4262 before reading, so differences, signs and
  partial sums stay in registers. This TFH proof does not permit omitting SWOTL's
  DS:22C6..22D4 or other writes. Preserve the per-term sign tests and bits 16–47,
  including 32-bit wrap; do not replace sign/magnitude arithmetic with signed MUL.
- **Divide:** D0.w is signed numerator; divisor is unsigned word 4244(A4),
  scale word 4264. D1.w retains the numerator, D0 returns signed result, D2 its
  magnitude; D3 is saved. Zero divisor skips division, retaining the shifted
  magnitude. The long-divide bound follows the word numerator/divisor domain,
  not observed calls. No dead-global proof is supplied here; SWOTL's original
  two-divide fault/overflow and zero paths still determine fallback.
- **Projection:** 4282/4286(A4) supply magnitudes, 4316/4318 signs; rotation
  words 4146/4148 and signs 4150/4152; viewport offsets −7802/−7788 and long
  correction 4312. Writes 4268/4272; D0 ends with the input X high word and
  zero low word, D1–D7 are working registers. Source lines 20–27 rely on callers
  `2F134`, `30246`, `30478` consuming only D0 then restoring D1–A3/A6.
  Products/partial sums are register-held; no SWOTL scratch-store exemption
  follows. Carry the rounding add into the high product. This source covers
  only the long path, so its cost cannot stand for all of `B017`.
- **Normalise:** three long stack arguments (36(A7) after the save); saves
  D1–D7/A0, records A5 at −10352(A4), and x/y signs via longs 8860/8856.
  Shifts x/y magnitudes and raw z; highest-set-bit count is clamped by branching
  around the shifts when already below 8000h, including zero. Writes words
  4240/4242/4244 and calls the initialized `xp_2f160`. The smaller save set
  relies on TFH's callee clobbers; intermediate one-bit-pass state is omitted.
  SWOTL's D5DA poll visits and their visible state cannot be replaced by one
  shift under the current contract.
- **Scenery clear:** A5 is the original frame; three even 20-byte arrays at
  −498, −478 and −298, first two adjacent. D0/A0 are dead until reloaded at
  `1148E`; −24 becomes 20. The helper adjusts its native return address past
  the original byte loop. Long clears omit intermediate counter writes and
  reorder distinct bytes; U3 and SWOTL's actual frame layout must govern adaptation.
- **Scenery vertices:** A5 is the original frame; −8 points to six-byte vertices,
  −26 is the polygon count, 26372(A4) points to byte indices. Frame arrays and
  origins are specified in source lines 304–319. Saves D3/D6–D7/A2–A3/A6;
  transform/projection callees must preserve D1–A3/A6. D4/D5 and frame scratch
  −30..−38, −504/−506 are claimed written before reuse and omitted. Exits are
  `11C70` (all behind), `11B34` (clip), `11B2A` (draw); all depend on the original
  surrounding function. Preserve signed midpoint truncation: `(a+b)/2` for
  world points versus `a/2+b/2` for projected parents, with the latter allowed
  only when both parents are projected and z > 20000. TFH's checked flights
  did not exercise all-behind, midpoint or shared-projection paths
  (`docs/internals.md:134–141`); SWOTL needs explicit oracle cases for them.
  SWOTL differs: its world midpoint shifts the wrapped sum with SAR/RCR
  (no negative rounding adjustment); its projected midpoint adds first,
  then uses SAR on the high word and SHR on the low word, without carry
  between them. Its depth guard tests the signed high word against 2.
  R40's original-x86 cases cover these paths; do not import TFH's arithmetic.
- **Terrain rings:** saves D4–D7/A2–A3, uses a new four-byte A5 frame and
  register-held loop variables. Inputs: plane 11668/11672(A4), heading 11680,
  map/offset/object pointers 12132/12136/12140, tables −21726..−21670 and
  −23016. The original `1133A` callee must preserve the loop registers;
  receives detail in the high word of a long stack argument and globals
  26360/26364/26372/26376/26377. Runs at TFH ground detail 0. Replacing the C
  frame omits local-store histories; no individual dead-local proof is supplied.
  Preserve byte/word index wrap, signed offsets, detail and bounds ordering.

### SWOTL adaptation boundaries

The following **Facts per candidate** sections are the full mapped differences
for every row above: transform globals and wrapper; divide zero/overflow;
projection constants and short path; normalise signs and poll; object header,
face mask and call graph; terrain dimensions and data. The no-slave rows retain
48-bit facing sums, classification ties, SWOTL edge records, line source swaps
and endpoint order, sprite byte packets/selector transparency/scale tables, and
terrain caches/visitation/clipping respectively. `BFD1` retains its own merge,
priority, lifetime and emission semantics. Their detailed addresses and oracle
cases below remain binding; none inherits a TFH register or dead-store contract.
These are source facts and adaptation requirements, not equivalence or admission
proofs. Admission and B3 prices are recorded below. Only the U2 transform is enabled; no further routine is authorized.

## Compute admission inventory

B2 on `d4f2b75` (2026-10-21), unchanged translator and annotations. All offsets
below are in `SWOTL.EXE`. Each trial adds one in-memory `kind=compute` row to
`image.rows`, then constructs `emit.Program` through its normal
`compute.validate` path; no row is installed and no assembly is emitted.
`Program.reach` supplies the root returns; every return choice is tried.
The row's `last` is the decoded instruction immediately before that return.
Local reproduction and results: `tmp/native/B2/admission.py`, `admission.json`.

| Entry | Trial last → resume | Admission / first rejecting rule |
|---|---|---|
| `B52D` | `B549 → B54A` | Admitted: 168 reachable instructions, including `B54B`. |
| `B54B` | `B704 → B708` | Admitted: 153 reachable instructions. |
| `B4E2` | `B529 → B52C` | Rejected: divide-error edge to `13735` leaves the declared range (INT 0 handler; also a poll). |
| `B017` | `B15D → B15F`, `B160 → B163`, `B38F → B392`, `B4DF → B4E1` | Rejected for every return choice: callee reaches poll `13735` (divide-error handler). Four root returns also violate the single-return contract. |
| `D5A6` | `D61D → D61E` | Rejected: poll `D5DA`. |
| `B8A1` | `BA2C → BA2D` | Admitted: 147 reachable instructions; no improved slave source. |
| `BB70` | `BD66 → BD67` | Rejected: poll `BBAC`. |
| `109D6` | `10A27 → 10A28`, `1121E → 1121F` | Rejected: with `10A28`, flow at `10A29` leaves the range; with `1121F`, REP STOS at `10A3D`. Two root returns. |
| `4DAE` | `51A1 → 51A4` | Rejected: callee poll `9174`. |
| `D69C` | `DAD1 → DAD2` | Rejected: callee poll `D4FA`. |
| `BD68` | `BF07 → BF08` | Rejected: poll `BDA5`. |
| `FDE0` | `FEAA → FEAB` | Rejected: REP STOS at `FE0F`. |
| `F290` | `F318 → F319` | Rejected: poll `F2BD`. |
| `BFD1` | `C049 → C04A` | Rejected: poll `C000`. |

C4 rerun (U5 + U8, `tmp/c4/admit.py`, `admit2.py`): admitted `B4E2`, `B017`
(four returns), `B8A1` poll-free; `D5A6` (`D5DA` removed) and `BB70` (7 polls
removed) under U5. With `end` past the epilogue, `F290` (`F5E4`), `BD68`
(`BF95`) and `FDE0` (`1022E`) reach PLINK manager calls (another overlay);
`109D6` reaches `int 21h` at `144B7`; `4DAE` has `call dx` (`4F7B`, `4FF7`,
`50A5`, `5139`); `BFD1` reaches unresolved flow in a callee; `D69C`'s callee
poll `D4FA` is reachable from outside.

B2 result (initial contract): three entries admitted, eleven rejected (18 trial rows). Rejections are the
checker's first failure, not an exhaustive list of blockers. In particular,
zero polls in a routine's own body does not prove transitive admission:
`B4E2`/`B017` retain their divide-error edges; U8 (C4) admits them as decline
edges. `B8A1` has no calls in A3, so admission alone gives no
priced saving. Admission is not native correctness or replacement authorization;
S3–S6 still apply. Existing admission controls: 19 pass; removing the effect/poll
guard is caught (`poll admitted`).

## B3 candidate prices

Recomputed 2026-10-21 from retained A3 run 2, not new frame measurements.
Conversion: `390 ms × cycles / 28,420,399`; this assumes the captured work mix
scales with frame time. Values below are **zero-cost removal ceilings**, not
native saving estimates. Own costs are disjoint; inclusive costs overlap and
must not be added. B2's admission blockers remain binding.

| Entry | Own ceiling (ms/frame) | Inclusive ceiling (ms/frame) |
|---|---:|---:|
| `B52D` | 3.99 | 28.05 |
| `B54B` | 24.06 | 24.06 |
| `B4E2` | 7.09 | 7.09 |
| `B017` | 11.65 | 18.74 |
| `D5A6` | 8.07 | 23.50 |
| `B8A1` | 0.00 | 0.00 |
| `BB70` | 5.20 | 5.20 |
| `109D6` | 10.31 | 36.14 |
| `4DAE` | 31.12 | 40.86 |
| `D69C` | 3.87 | 4.96 |
| `BD68` | 2.60 | 6.43 |
| `FDE0` | 6.21 | 36.07 |
| `F290` | 4.30 | 7.03 |
| `BFD1` | 25.63 | 39.02 |

The admitted transform wrapper/body together have a 28.05 ms ceiling;
`B54B` is already inside `B52D`. `B8A1` has zero captured calls. Even removing
the entire admitted group at zero cost would leave about 361.95 ms under this
scaling assumption, before considering blocked candidates.

The pinned slave's unchanged transform source was assembled locally and all
acyclic branch paths costed with the corrected model (B3-cal). These are raw
source-kernel bounds, **excluding SWOTL adaptation**, not replacement prices.
Native call/return costs are included; `xpnorm20` excludes its called projection.

| Kernel | Model cycles/call, min–max |
|---|---:|
| `xform20` | 376.20–403.83 |
| `xdiv20` | 83.98–94.08 |
| `xproj20` (long path only) | 287.23–320.63 |
| `xpnorm20` (own body) | 179.84–193.10 |

Scope checks against A3:

- `B393` (the long projection path) executes 235/235/189 times across runs
  1/2/3, costing 190,244/190,246/153,619 cycles. Run 2's source-covered path
  has only a **2.61 ms** removal ceiling; charging its improvement to all
  1,036 projection calls would overprice it.
- `D5DA` has 6,801/6,888/9,161 poll visits across 827/836/1,101 normalise
  entries. The single-shift source price omits required visits and cannot be
  used as an adapted normalise price.
- `B4E2` returns intermediate BP as well as AX/DX, BX/CX and SI. The source's
  one-product result does not by itself reproduce BP; its adaptation needs
  additional work even with final-RAM/write-set U3.
- Transform has no live flags at entry or return in the current CFG.
  Its raw source still needs input packing, exact scratch stores, guest result
  reconstruction, the compute hook and the retained generated return.

### Adapted transform price (both U3 rules)

Analytical fast-path budget from the pinned `xform20`, not replacement code.
Keep the `B52D` wrapper and its guest call/check generated; install at most one
future callback at `B54B`. The source's two-register native save preserves guest
SP/BP; other guest result registers are reconstructed before restoring them.
The source's sign branches must test bit 15 as x86 does, without assuming the
matrix sign words contain only zero or 8000h.

| Adapter component relative to raw kernel | Executed bytes Δ | Reads Δ | Writes Δ | Taken Δ |
|---|---:|---:|---:|---:|
| Pack AX:BX, DX:CX, SI:DI into three longs | 16 | 0 | 0 | 0 |
| Store signed high words and magnitude halves | 60 | 0 | 9 | 0 |
| Replace three output long stores with original word stores | 24 | 0 | 3 | 0 |
| Reconstruct AX/DX, BX/CX, SI sign XOR and DI magnitude low | 24 | 2 | 0 | 0 |
| Save/restore SP/BP instead of the source's six registers | 0 | −4 | −4 | 0 |
| Compute hook and handled result | 20 | 0 | 1 | 2 |
| Retained generated return | 8 | 2 | 0 | 1 |
| Successful pre-mutation DS guard | 10 | 1 | 0 | 0 |

Added cost **214.2971 cycles**; total **590.4923–618.1316 cycles/call**.
The scratch inventory is nine words `22C6..22D6`; output is six words
`C38C..C396`. Each address is written once, so retaining all fifteen original
word stores satisfies either U3 rule at the same price. No dead-store exemption
or wide-store assumption is priced. Input packing uses eight register moves/swaps;
result reconstruction uses seven register operations, two word loads/ALU reads
and the SI move. No live entry/return flags in the current CFG.

Guard budget: compare guest DS with F000h, decline before mutation above it;
otherwise the constant-offset long reads stay within the 1 MiB RAM extent.
Original generated word-store paths remain. S3–S6 must establish equivalence,
actual guard eligibility, bookkeeping and the implemented instruction inventory.
This is not authorization to implement or weaken admission.

| Entry | Status | Every-byte history saving, ms/frame | Final RAM + written set saving, ms/frame |
|---|---|---:|---:|
| `B52D` | Admitted; same body saving as `B54B`, wrapper unchanged | 11.48–12.04 shared | 11.48–12.04 shared |
| `B54B` | Admitted; priced adapter above | 11.48–12.04 | 11.48–12.04 |
| `B4E2` | Enabled inside `B017` (F3a); measured below | Unpriced ms/frame | Unpriced ms/frame |
| `B017` | Whole routine with `B4E2` enabled (F3a); measured below | Unpriced ms/frame | Unpriced ms/frame |
| `D5A6` | D5DA loop enabled (R38) | Unpriced ms/frame | Unpriced ms/frame |
| `B8A1` | Admitted; no improved source, no A3 calls | 0 in A3; native cost unpriced | 0 in A3; native cost unpriced |
| `BB70` | No improved source; admitted (U5) | Unpriced | Unpriced |
| `109D6` | DOS call in callee; partial source only | Unpriced | Unpriced |
| `4DAE` | No improved source; `call dx` | Unpriced | Unpriced |
| `D69C` | No improved source; shared callee poll | Unpriced | Unpriced |
| `BD68` | No improved source; overlay call | Unpriced | Unpriced |
| `FDE0` | No improved source; overlay call | Unpriced | Unpriced |
| `F290` | Overlay call | Unpriced | Unpriced |
| `BFD1` | No improved source; unresolved callee flow | Unpriced | Unpriced |

User decision, 2026-10-21: **use ceilings and explicit unpriced rows** for
missing implementations/contracts. Their measured ceilings are above; unpriced
is neither zero cost nor zero potential. C's poll contract does not resolve all
B2 blockers. U3 retains every-byte write history; the relaxed alternative was not selected.

### N2 projection measurement

Authorized `B393..B4E1` long path only, from `xproj20`; the B017 prefix,
divides and short/special paths remain generated. Same-session target cost
809.612 → 596.125 cycles/call (−26.3690%); m4 meter −0.2838%.
No measured ms/frame saving is asserted. Full gate coverage green; speed-plan R36.
Superseded by F3a (whole `B017`, below). The C4 inventory describes the
original unhooked bodies. R38 keeps the projection call outside the
normalization replacement.

### N1 measured calibration

R35 keeps the authorized transform with complete byte-write history. Same-session
68020 captures: **1,182.182 → 634.432 cycles/call (−46.334%)**, 1,483/1,804 calls;
all 1,804 native calls handle. Saving 547.750 cycles is **92.59–97.12% of B3's
predicted saving**. The approved CS-window overlap guard was separately priced
at +20.4835 cycles before coding; against that price, the saving is 95.91–100.78%.
At A3 run 2's unchanged mix this calibrates the projection to **11.15 ms/frame**;
this is extrapolation, not a measured frame-rate gain. Other rows have no native
implementation price to rescale; their ceilings and raw-kernel bounds remain
explicitly unpriced. Reprice before each authorized implementation.

The meter falls 4.6800%; payload grows 446 bytes. The user accepted the
+0.0204% opening-bench median tradeoff (equal RAM, overlapping ranges).
Full gates pass; measurements are in speed-plan §1 and the R35 commit.

### B3 cumulative projection and limits

Run 2: 390 ms → **377.96–378.52 ms** after the transform pair, counted once;
`B8A1` adds zero observed work. Remaining gap to 240 ms: **137.96–138.52 ms**.
Unpriced rows add no asserted saving. The pair's generated inclusive cost is
1,378.1450 cycles/call; retaining its 196.0364-cycle wrapper gives an adapted
inclusive estimate of 786.5287–814.1681 cycles/call.

Across A3 runs 1/2/3, projected transform savings are 10.74–11.27,
11.48–12.04 and 15.12–15.86 ms/frame respectively, under either U3 rule.
These assume every call is eligible and the A3 work mix scales with P. A declined
call adds about 55.3706 model cycles to its unchanged generated body. For eligible
fraction q, use `calls × [q × (old − fast) − (1−q) × 55.3706]` as saved cycles;
convert with the same P/total factor. Do not treat the all-eligible projection
as a guaranteed speedup. N1 calibration is above; the older guard budget
does not include the CS-window overlap check.

TFH cross-check: its projection-entry saving was 278/1,360 = 20.44%, and
scenery 2,618/17,481 = 14.98%. Those original 68000 routines, callers and dropped
scratch writes differ from SWOTL's translated code. Applying either percentage
to SWOTL's entire projection/scenery row would invent a price. The transform's
47.71–50.05% body reduction was B3’s hypothesis; N1 calibration is above;
there is no corresponding measured TFH per-call transform ratio in the inputs.

Evidence: `tmp/native/B3/{baseline,path-costs,kernel-costs,transform-price,transform-contract-check}.json`,
with local reproduction scripts alongside them. Arithmetic checks, source hash,
all 14 rows, non-overlapping accounting and current admission/flag/store inventory
verified. The transform passed S3–S8; other replacements retain their blockers.
The consolidated decision table is under Candidates.

## Facts per candidate

### Transform `B52D`/`B54B` ↔ `2F48C`/`2F4AE`

F3b (U2, U10, 2026-10-24): `B52D` with `B54B` as one poll-free row. The
wrapper's four pushes are stored; SI, DI and BP keep their entry values (its
pops); the frame SP−8..SP+15 must not wrap (else decline). m4 meter
−1.5848%; flyby inclusive 820 → 629 cycles/call (−23.3%; native 565).
Evidence: `tmp/speed/f3/`.

- Wrapper: three 32-bit stack arguments into AX:BX, DX:CX, SI:DI.
- Point − camera (DS:`2276/227A/227E`; TFH A4+`103A/103E/1042`) as sign and magnitude,
  times matrix magnitudes `224E..225C` with signs `225E..226C` (TFH `1012..1020`,
  `1022..1030`). Rows of 3, 2 and 3 terms, each floor(|v|·m/65536) from two `mul`s,
  signed. First row x·m`2256` + y·m`225C` + z·m`2254` (TFH m`101A`, `1020`, `1018`).
- Outputs, 32-bit: DS:`C394`, `C38C`, `C390` (TFH `108C`, `1084`, `1088`).
- Slave: one `mulu.l` per term (bits 16–47 equal the halves' sum; no carry out).

### Normalise `D5A6` ↔ `3041C`

R38 enables the authorized D5DA–D5F6 loop, resuming at D5F8. The generated
prefix, sign restoration, stores, projection call and returns remain. U5 moves D5DA's poll to D5F8 in both arms. No guest writes
occur inside the native loop. The counted shift retains the original BP and
all six coordinate words. Measured loop-plus-poll cost 427.549 → 138.246
cycles/call (−67.6654%); whole meter −1.3373%. No ms/frame saving claimed.
Evidence: `tmp/native/N4-normalise/`; speed-plan R38.

- x and y as magnitudes (signs from DS:`2399/239B`); x, y, z shifted right together
  until x|y|z < 8000h (loop `D5DA..D5F6`, poll point `D5DA`); signs back; words
  DS:`22BA/22BE/22C2` (TFH `1090/1092/1094`); then `B017`.
- Slave: one shift by the counted amount (`bfffo`).

### Divide `B4E2` ↔ `2F374`

Enabled by R37 (U4, 2026-10-22): original return retained, all register
results including intermediate BP exact, no guest stores or poll changes.
Measured 251.151 → 153.673 cycles/call (−38.8126%); whole meter −0.6499%.
No measured ms/frame saving claim. Evidence: `tmp/native/N2-divide/`.

- Two word divides → 32-bit quotient, × scale, rounded with 8000h, numerator's sign;
  explicit zero denominator. Denominator DS:`22C2`, scale `22D8` (TFH `1094`, `10A8`).
- Slave: `divu.l` + `mulu.l`. Keep quotient overflow and fault behaviour.

### Projection `B017` ↔ `2F160` (32-bit path `2F28A`)

F3a (U4, U10, 2026-10-24): `B017` with `B4E2` as one poll-free row, all paths,
four returns; the earlier `B393` (R36) and `B4E2` (R37) rows are folded in.
Near-call return addresses, every global store and all register results
(BP from the divide only where it reaches a return) are exact. m4 meter
−1.4854%; flyby inclusive 1,083 → 837 cycles/call (−22.7%; native 745, hook,
dispatch and retained return 92). Evidence: `tmp/speed/f3/`.

- Two divides, rotate and combine, viewport offsets, reject out of range; several
  returns (`B15F`, `B163`, …). Scale `B4` (180) vs TFH `78` (120); SWOTL's short path
  `E9` with an 8-bit scale, TFH's `E8BA` 16-bit.

### Facing test `B8A1` ↔ `2F822`

- Coefficient magnitude/sign pairs, magnitudes 0 and 1 special; three signed
  products summed in 48 bits (DS:`2330/2332/2334`; TFH `10F4/10F6/10F8`); result
  total ≥ 0. A 32-bit dot product is not equivalent.

### Classify `BB70` ↔ `2FA12`; edges `BD68` ↔ `2FBB2`

- Eight-byte screen points (DS:`2445`): extremal y, tied-vertex count, per-vertex bits,
  viewport extremes; a packed classification for `BD68`. Tie rules matter.
- `BD68` builds edge records for `BFD1`; TFH draws with its own rasterizer.
  Its exact-poll edge-loop design was deferred by the user (2026-10-23, R43):
  planning budget 843,635 versus 667,905 generated model cycles; no native
  implementation built.

### Ground objects `109D6` ↔ `1142C` (vertex loops `11604..11B34`)

- R40 clear-only adapter `10A2F..10A51 → 10A53`: final host meter
  −0.150466%; target 606.930 → 405.636 cycles/call (−33.1659%).
  Bench +0.030708% accepted as noise by the user 2026-10-23; relevant
  correctness checks pass. Vertex loops remain deferred. Evidence: speed-plan §7.

- Offset-table select, clear vertex state, 7-byte header, faces with indexed vertices,
  facing test, transform uncached vertices, midpoint vertices, project, submit;
  vertices × 64 + origin; coefficient records built in below 80h, extra above.
- Calls: `10BEA` `B8A1`, `10CD6` `B52D`, `10F13` `D5A6`, `10FFD` `BB70`, `11036`
  `BD68`, `110D8`/`1111B` `D69C`; sprites `111AA`/`1120B`.
- SWOTL header bytes 3/4/5, face byte & 0Fh; TFH counts at 4/5.

### Sprite decoder `4D7D`/`4DAE` ↔ `2BA28`/`2BACE`

- R42 replaces only `4ECD–4F07 → 4F09`, preserving every original poll,
  table read and byte-write history. Generated decoding and `call dx` remain.
  Measured 815.176 → 782.000 target cycles/packet; exact host-instruction
  weighting −5.261052%, full meter −0.131085%. Bench −0.007312%, equal RAM;
  no frame-rate gain claimed. Evidence: `tmp/native/N4-sprite/`, R42 commit.
- Setup `4CA1` ↔ `2B9A2`: two orientation contexts (DS:`12BE/1A78`), `9291` only on an
  angle miss. Header 5 bytes (x origin byte 0, or −byte 2 mirrored; y byte 1;
  transparent selector byte 4); packets: FF ends, count + 3 advances, forward or
  reverse; low nibble scaled advance, high nibble colour.
- SWOTL advance tables DS:`0FA6/10A6` (`90F2` rebuilds them only when `0FA0` changes),
  spans at DS:`08BB`, pixels through the walk (`4FF7`, clipped `5139`). TFH writes
  nibbles with mask/OR.
- Transparency is decided on the selector, before colour mapping. Palette setup `4D1D`
  has no cache guard.

### Rasterizer `BFD1` (no TFH equivalent, no improved source)

- Priority searches C2F2/C32D remain generated: user deferred R46 after
  bench no-slowdown acceptance remained unproved. Ordering, expiry and
  advance scopes are authorized. User deferred expiry/advance (R47):
  address-reuse designs have no positive price. R48 keeps guarded ordering/
  merging C0C2 → C1C2 with wrapping BX-index reuse and every original poll.
  Meter −0.100064%; exact target weighting −10.780077%; bench +0.001462%
  accepted as noise by the user. Measured details: speed-plan §1.

- Edge records, 16 bytes (arena DS:`2360`, ≤ 500; buckets `1F40 + 16·y`, active list
  `4060/4062`): +0 lifetime, +2 priority (DS:`252F`), +4 colour, +5 event and slope
  flags, +6 x, +8 endpoint then fraction, +A/+C step, +E start row.
- Stages: add `C04B..C0AA`; order and merge `C0C2..C1BF` (equal-x edges may cancel or
  merge: not a sort); visibility `C1C2..C394` (priority table `41F0`, background
  DS:`25A1`); expire `C395..C3DE`; advance `C3DF..C429` (lazy slope `C8E0`).
- Output: DS:`233E` ≠ 0 `CD99` → `5260` → walk; = 0 `CE3C` `rep stosb`.
- Terrain priority is submission order (`C450` from 10h, +2 per accepted polygon).

### Terrain `FDE0` ↔ `104B6..10830`; rings `F290` ↔ `11138`

- FDE0 cache-loop scopes 10008 → 10126/1004B and 1012F → 101DE/10186
  admit under exact polling, but the initial address-reuse design has no
  positive price (476,194 budget versus 434,107 generated model cycles).
  User deferred it on 2026-10-23; generated code remains. R45 evidence:
  `tmp/native/N4-polygons/`.

- `FDE0`: cells `(645C−60)>>6`, `(658E−40)>>6`; 13×13×5 table (far pointer `BF02`),
  ≤ 5 polygon IDs per cell, FF ends, marked visited before transform; transform and
  projection caches, 25 entries each, one-based, no eviction; camera-plane clip
  `FLIGHT+17086` ↔ `11D60`; then `BB70`, `BD68`. TFH visits 11 fixed polygons with
  six-axis rejection: not importable.
- `F290`: the same 11 ring offsets (`DATA.OVL+631C`, DS:`54CC`); SWOTL 50×50 bytes,
  TFH 64×64 nibbles.

### Line `D69C` ↔ `30486`

- R44 scopes D92A → D93D and D95C → D96F admit under exact polling.
  Guarded ordinary-memory loops retain every pixel write and original poll;
  clipping, shared callees and returns remain generated. Meter −0.040939%,
  target work with exact instruction weighting −5.866799%, bench −0.016083%;
  all selected checks pass. Evidence `tmp/native/N4-line/`, speed-plan §1.
  No TFH original code imported.

- Two consecutive points, ordered by y, rejected and interpolated at the viewport.
  SWOTL swaps the source records, TFH copies; endpoint order differs. `DAD3`/`D43F`
  vs `302B8`: equivalence not established.

### Orientation clipping `58B9`/`5307` ↔ `2BEAC`/`2BF00`

- Eight cases (SWOTL tables `58FE/5315`; TFH offsets `2BEF0/2BF18`). Init: SWOTL
  `592A 5B54 5D7E 5FE7 6250 642D 6636 683C`, TFH `2BF28 2C0CA 2C274 2C44E 2C632 2C7EA
  2C9CE 2CBAC`. Advance: SWOTL `5AAC 5CD5 5F39 619B 638A 656B 6783 6986`, TFH `2C028
  2C1DE 2C3AA 2C582 2C74C 2C90C 2CAF4 2CCD4`.
- SWOTL repeats the origin normalisation and accumulates `09C3` (TFH once); its case 1
  advance and case 5 rejection write state TFH skips; VGA builders (cases 0–3 two
  segment/base pairs at CS-relative `9B32..9B38`, 4–7 one) vs TFH packed offsets.
  Callers: sprites `4DF9/5163`, background `E742/EAFF/F0E6`.

### Cell walk `6A4D..8E2C` ↔ TFH offset tables

- Cells `mov [bx+disp16],al`, a BX/DS reload, the planted RET (translator-design D16);
  displacements patched by `8F60..9096` (key `8F6A`); producers `4FF7`, `5139`, `52D5`,
  `EBBC`.
- TFH `2CD7A` builds long offsets (and nibble masks) only on an orientation change;
  `2BC80..2BE04` loads an offset, adds the base, writes. Reference for speed-plan R20.

### Kept in SWOTL

- Animation `FLIGHT+55A2` ↔ `176A2` (cadence, redirects ≥ C000h, BFFFh) and actor
  selection `FLIGHT+519C` ↔ `17214`: faster drawing must not change their timing.
- Projectiles: classes 7/8 from `FLIGHT+7E3E`; zero coordinate → stamp `49B2` (↔
  `2B7DC`), else `109D6`; TFH stamps both.
- Small-resource switching `5324..53E9` ↔ `17598..1765A`; delayed ground effects
  `FLIGHT+1682B`.

## Oracle cases

- Transform and projection: zero and maximal magnitudes, negative inputs, zero
  denominator, divide overflow, rounding at 8000h, every projection path.
- Facing test: magnitudes 0 and 1, all sign combinations, 48-bit carries.
- Classify: tied vertices, viewport edges.
- Sprites: mirrored, every scale-table boundary, transparent runs, clipping, colour remap.
- Rasterizer stages: coincident edges with equal and different colours, same x with
  different priorities, negative counts, zero-life edges, overflow buckets, both emitters.
- Walk: immediate RET, runs across the reload, 16-bit BX+disp wrap, rebuilt
  displacements, restored RET bytes.
- Clipping: rejection state, large origins, edge equality, case 1 at boundary −1.
