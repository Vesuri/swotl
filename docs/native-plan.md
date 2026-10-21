# Native routine plan (open-work 14b)

Work after the translator steps, in order: baseline (A), translator follow-up (X),
candidate table (B), native routines (N, each by procedure S), contract for routines
with polls (C), close (Z). User decisions (U) gate it. Rules: speed-plan §2; nothing
here authorizes a routine (§2.2). Interface and oracle: [native-compute.md](native-compute.md);
facts per candidate: [swotl-tfh-rendering-map.md](swotl-tfh-rendering-map.md).
Evidence: `tmp/native/<id>/`.

## Improved sources

Native routines start from the slave's improved routines (the user's TFH WHDLoad slave,
`../Their Finest Hour/whdload/`), their 68020 variants, never from TFH's originals where
the slave has a version. SWOTL's x86 stays the oracle; its constants, rounding, branch
order, scratch writes and tables are kept.

| SWOTL | Function | Improved source | What improves | Polls |
|---|---|---|---|---:|
| `B52D`→`B54B` | point transform | `transform.s` `xform20` | one `mulu.l` per term; intermediates in registers | 0 |
| `B4E2` | perspective divide | `transform.s` `xdiv20` | one `divu.l`, one `mulu.l` | 0 |
| `B017` | projection | `transform.s` `xproj20` (TFH's 32-bit path `2F28A`; entry `2F160` unpatched) | one `mulu.l` per product, rounding carried | 0 |
| `D5A6` | normalise, then `B017` | `transform.s` `xpnorm20` | one shift by a `bfffo` count, not one per pass | 1 |
| `109D6` | ground objects | `render.s` `scen_verts` (vertex loops `11604..11B34`), `clr_scenery` | register loops; long clears | 6 |
| `F290` | terrain rings, scenery | `render.s` `tile_scenery` | register version of compiled C | 2 |
| `CE3C` `rep stosb` | background fill | `render.s` `cpu_fill` (blitter fill → long CPU fill) | translator step X1, not native | — |
| `B8A1` `BB70` `BD68` `D69C` `4DAE` `FDE0` | facing, classify, edges, line, sprites, terrain | none; TFH originals `2F822` `2FA12` `2FBB2` `30486` `2BACE` as reference (`FDE0` not importable) | — | 0–9 |
| `BFD1` | rasterizer | none (no TFH equivalent) | — | ≥ 2 |

Already equivalent: chunky buffers in Fast RAM; C2P (SWOTL runs Kalms'
`c2p1x1_8_c5_bm` on changed rows; the slave's `c2p_merge` is the same technique for 4-bit
chunky). The slave drops intermediate global writes it proved dead (`xform20`: ~60
accesses per call); the native contract compares every byte's write history (U3).
The slave's `tools/xform_check.py` models TFH's originals: test ideas only.

## User decisions

| ID | Decision | Blocks |
|---|---|---|
| U0 | Adapt the slave's code (the user's) into SWOTL native routines, or use it as algorithm reference only; TFH's own code and data never enter. Recommended: adapt, and update the rendering map's rule | S5 |
| U1 | Meter loop definition (open-work 37): any backward branch, or executed back edges only | A4 |
| U2 | Authorize the pilot: transform `B52D`/`B54B` from `xform20` | N1 |
| U3 | Write rule for poll-free routines: every byte's write history (now), or final RAM plus the written-address set (nothing else runs inside a poll-free routine; SMC and display bookkeeping kept). B3 prices both | S5, S6 |
| U4 | Authorize each further poll-free routine from B4 | N2 |
| U5 | Approve the poll contract (C1) | C3, N4 |
| U6 | Authorize each routine that needs C | N4 |
| U7 | Direction if Z1 leaves the target unmet (FM quality tradeoff, `BFD1`, revised target) | — |

## A. Baseline (no authorization)

- **A2** Open-work 36: `tools/lowering_cost.py` counts guest entries only at unsuffixed and
  `_bp` labels and recovers zero-code alias entries. Test and plant. Done: R22's first
  capture gives 2,290,967; rejected R23's count recovers its 68,070.
- **A3** Re-profile HEAD (speed-plan §4): frames fixture P, three runs; 100-field frames
  capture; bench, three runs. Per candidate: own share, calls per 100 fields, own and
  inclusive cycles per call (`tmp/item30/inclusive.py` method). Done: speed-plan §1, §9
  and the 14b gap updated from these runs.
- **A4** Open-work 37: both loop definitions' calibration fit and R27 Δ → U1 → `cost_meter.py
  --calibrate CAPTURE ELF --write`, `--plant-check`. Done: 37 closed.

## X. Translator follow-up (no authorization)

- **X1** REP STOSB has no long fast path (`lower.py`: two elements per long for STOSW only).
  Price `CE3C`'s background fill and every other hot `rep stosb` from A3; if it saves, a
  speed-plan step (§3 procedure, R24 as template). Done: kept or one line in §10.

## B. Candidate table (no authorization)

- **B1** For each row of "Improved sources": the slave routine's lines, its preconditions
  (registers, globals proved dead) and every SWOTL difference from the rendering map.
- **B2** Admission: `translator/compute.py` on a trial `kind=compute` row per guest
  candidate, not enabled. Record admitted, or the rejecting rule (poll, cycle, REP,
  unresolved flow, device effect).
- **B3** Price per candidate: A3's generated cycles per call × calls against the adapted
  improved source costed with `tools/cost_model.json` (`mulu.l`/`divu.l` at the 68020
  model's cost), under both U3 rules; the slave's measured gains as a check (projection
  1,360 → 1,082 cycles per call, scenery 17,481 → 14,863). Output: ms per frame each,
  cumulative against 240 ms, admitted now vs needs C.
- **B4** Replace the rendering map's `5ecdf79` table with B1–B3; ask U0–U4.

## S. Procedure per native routine (one commit each, as the next speed-plan R step)

- **S1** Quote the authorization (date) in the `hle.csv` reason.
- **S2** Write the price (B3) in speed-plan §7 before coding.
- **S3** Entry states: DOSBox snapshots at the routine entry from at least three fixtures
  reaching it (m4 demo flight, a gunnery scenario, a campaign flight), plus the
  rendering map's oracle cases and every decline/fallback case.
- **S4** `tools/compute_oracle.py --generated MODULE+offset` passes on all S3 inputs.
- **S5** Implement from the improved source, adapted to the generated-code ABI: SWOTL's
  constants and rounding, stores through the generated memory path, decline before any
  mutation for unhandled cases (fault, overflow). Named by function in `src/runtime/`,
  never by guest address; `hle.csv` row `kind=compute` with reason and oracle command.
- **S6** Native differential on the S3 inputs without the x86 results: registers, live and
  control flags, writes (per U3), all RAM. The row's sabotage plant is caught.
- **S7** Meter and bench (three runs per arm, same session, equal final RAM); FS-UAE frames
  capture per arm: the routine's cycles per call before and after. Accept by §3.
- **S8** Full `make gates` with the row active, references unchanged.
- **S9** Docs: speed-plan §1 and §7, open-work 14b, the rendering map row (measured).

## N. Native routines

- **N1** Pilot (U2): `B52D`/`B54B` from `xform20`, by S1–S9. Then compare its measured
  saving with B3's price and rescale the remaining prices. Done: kept or reverted, with
  the ratio in the rendering map.
- **N2** The other admitted routines in B3 price order, each after U4 (expected `B4E2` from
  `xdiv20`, `B017` from `xproj20`).
- **N3** Checkpoint: frames fixture P, three runs against A3; report the remaining gap.
  Decides whether C starts.

## C. Contract for routines with polls and loops

- **C1** Design (docs only; may start after B4): native code keeps every poll visit of the
  original. At each poll site it checks `G_IRQ`; with one pending it writes the exact guest
  state of that site (registers, live flags, stores so far) and exits to the generated
  code at that site, which delivers it. Visit counts are kept where the improved
  algorithm has fewer passes (`xpnorm20`'s one shift for `D5A6`'s loop). Oracle: x86
  stopped at the n-th visit of each site; an interrupt forced at every site.
- **C2** U5, recorded in native-compute.md.
- **C3** Admission, emitter (exit sites as leaders), oracle, tests and plants: stale
  register at an exit, missing store before an exit, skipped visit, wrong exit site,
  wrong visit count. Done: plants caught, full gates green.
- **N4** Routines that need C, each after U6, by S1–S9 plus C's exit cases, in B3 price
  order: expected `D5A6` (`xpnorm20`), `109D6` (`scen_verts`, `clr_scenery`), `F290`
  (`tile_scenery`), then `4DAE`, `BB70`, `BD68`, `D69C`, `FDE0`, `BFD1`.

## Z. Close

- **Z1** After N3 and after N4: frames fixture P, three runs, parent as control. P ≤ 240 ms
  closes 14b; otherwise U7.
