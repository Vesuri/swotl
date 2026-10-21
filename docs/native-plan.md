# Native routine plan (open-work 14b)

Work after the translator steps, in order: candidate table (B), native routines
(N, each by procedure S), contract for routines with polls (C), close (Z). User decisions (U) gate it. Rules: speed-plan §2; nothing
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
| U0 | Approved 2026-10-21: adapt the user's improved slave source; TFH's original game code/data remain excluded | — |
| U1 | Approved 2026-10-21: executed backward branches only (taken back edges in the measured workload) | — |
| U2 | Approved 2026-10-21: transform pilot at `B54B` from `xform20`; retain generated `B52D` wrapper and return checks | — |
| U3 | Confirmed 2026-10-21: keep every byte's complete write history, SMC/display bookkeeping and all other state checks | — |
| U4 | Deferred 2026-10-21: further routines need viable prices/contracts and individual authorization | N2 |
| U5 | Approved 2026-10-21: chosen polls (removed interior polls, return poll, optional sync sites), up to one PIT period of interrupt delay in a native routine, affected references re-recorded per row ([contract](native-compute.md#poll-contract-u5), implemented by C3) | — |
| U6 | Authorize each routine that needs C | N4 |
| U7 | Direction if Z1 leaves the target unmet (FM quality tradeoff, `BFD1`, revised target) | — |
| U8 | Approved 2026-10-21: REP away from kept polls, divide-fault decline, multiple returns; range/unresolved flow by annotations ([extensions](native-compute.md#contract-extensions-u8), implemented by C4); routines still need U4/U6 | — |

## Candidate evidence

Source inventory and adaptation requirements: [rendering map](swotl-tfh-rendering-map.md#slave-source-inventory).
Admission results: [compute inventory](swotl-tfh-rendering-map.md#compute-admission-inventory).
Candidate prices: [B3](swotl-tfh-rendering-map.md#b3-candidate-prices).
User, 2026-10-21: missing implementations/contracts retain measured ceilings and
explicit unpriced savings; do not invent a native price for them.

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

- **N2** The other admitted poll-free routines in B3 price order, each after U4:
  `B017` (`xproj20`, four returns), `B4E2` (`xdiv20`, divide decline), `B8A1`
  (no A3 calls).

## C. Contract for routines with polls and loops

Contracts: [U5](native-compute.md#poll-contract-u5) (`hle.csv` `polls`;
`t-compute-polls`) and [U8](native-compute.md#contract-extensions-u8) (`end`;
`t-compute-u8`), implemented. Admission on the candidates (C4,
[inventory](swotl-tfh-rendering-map.md#compute-admission-inventory)): `D5A6`
(its poll removed) and `BB70` (7 polls removed, no sync site needed) admit
under U5. Outside every contract: `F290`, `BD68`, `FDE0` (with `end`) call
another overlay through the PLINK manager; `109D6` reaches DOS (`int 21h` in
the callee at `144B7`); `4DAE` has `call dx`; `BFD1` reaches unresolved flow in
a callee; `D69C`'s callee poll `D4FA` is shared. Each needs a narrower row (end
the replacement before the call) or annotations, with its routine.

- **N4** Routines that need C, each after U6, by S1–S9 plus C's cases, in B3 price
  order; S8 includes re-recording the references its poll set affects. Price each
  with its return/sync polls and exits. Admitted: `D5A6` (`xpnorm20`), `BB70`;
  the others after narrower rows: `109D6` (`scen_verts`, `clr_scenery`), `F290`
  (`tile_scenery`), `4DAE`, `BD68`, `D69C`, `FDE0`, `BFD1`.

## Z. Close

- **Z1** After N3 and after N4: frames fixture P, three runs, parent as control. P ≤ 240 ms
  closes 14b; otherwise U7.
