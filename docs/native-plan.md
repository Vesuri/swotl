# Native routine plan (open-work 14b)

Work after the translator steps, in order: candidate table (B), native routines
(N, each by procedure S), contract for routines with polls (C), flyby plan (F), close (Z). User decisions (U) gate it. Rules: speed-plan §2; nothing
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
| U4 | Approved 2026-10-22: `SWOTL.EXE+B017`, adapting the slave’s `xproj20`, by S1–S9. B4E2 adapting `xdiv20` authorized 2026-10-22; B8A1 authorized then deferred 2026-10-22: no calls in the acceptance workload; the `B393` long-path hook returning at `B4E1` is approved | N2 |
| U5 | Approved 2026-10-21: chosen polls (removed interior polls, return poll, optional sync sites), up to one PIT period of interrupt delay in a native routine, affected references re-recorded per row ([contract](native-compute.md#poll-contract-u5), implemented by C3) | — |
| U6 | Approved 2026-10-22: D5A6 adapting xpnorm20; normalization loop D5DA–D5F6 → D5F8 with explicit non-return endpoint extension and U5 polls. BB70, 109D6, F290, 4DAE, BD68, D69C, FDE0 and BFD1 authorized 2026-10-22 by the remaining-candidates goal; admission, pricing and S1–S9 remain required | N4 |
| U7 | User chose to pause speed work, 2026-10-23; target and deferred candidates remain open | — |
| U8 | Approved 2026-10-21: REP away from kept polls, divide-fault decline, multiple returns; range/unresolved flow by annotations ([extensions](native-compute.md#contract-extensions-u8), implemented by C4); routines still need U4/U6 | — |
| U9 | Pending: resume under the flyby plan, F0 fixture and F2–F9 needs ([F](#f-flyby-plan)) | F |

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
- **S8** Checks relevant to the row, its callers, consumers and shared contracts
  (AGENTS.md; user reaffirmed 2026-10-22), with the row active and references
  unchanged. State the selection before running; retain green unchanged inputs.
- **S9** Docs: speed-plan §1 and §7, open-work 14b, the rendering map row (measured).

## N. Native routines

- **N2** The other admitted poll-free routines in B3 price order, each after U4:
  `B8A1` deferred by the user 2026-10-22 (no calls in m4/c13/c27).

## C. Contract for routines with polls and loops

Contracts: [U5](native-compute.md#poll-contract-u5) (`hle.csv` `polls`;
`t-compute-polls`) and [U8](native-compute.md#contract-extensions-u8) (`end`;
`t-compute-u8`), implemented. Admission on the candidates (C4,
[inventory](swotl-tfh-rendering-map.md#compute-admission-inventory)): `D5A6`
(its poll removed) and `BB70` admit structurally
under U5 on their original unhooked bodies. Structural admission alone does not
establish BB70’s latency bound; its deferred prototype retained seven sync sites. With B393 and B4E2 enabled, D5A6 must
keep its projection call outside the native body (nested hooks reject). R38
uses the approved continuation endpoint for D5DA–D5F6 → D5F8.
User approved multiple proved non-return endpoints for 109D6 on 2026-10-22;
its transform/projection calls and return checks remain generated.
User approved the same endpoint contract for F290 tile selection on 2026-10-23:
F31A → F339/F35F/F3B4; object processing and calls remain generated
([contract](native-compute.md#multiple-continuation-endpoints-user-2026-10-22)).
Outside every contract: `F290`, `BD68`, `FDE0` (with `end`) call
another overlay through the PLINK manager; `109D6` reaches DOS (`int 21h` in
the callee at `144B7`); `4DAE` has `call dx`; `BFD1` reaches unresolved flow in
a callee; `D69C`'s callee poll `D4FA` is shared. Each needs a narrower row (end
the replacement before the call) or annotations, with its routine.

- **N4** Routines that need C, each after U6, by S1–S9 plus C's cases, in B3 price
  order; S8 includes re-recording the references its poll set affects. Price each
  with its return/sync polls and exits. `BB70` deferred by the user 2026-10-22: preserving its seven sync sites
  has no positive price;
  `109D6` vertex loops deferred by the user 2026-10-22 after the initial
  guarded adapter exceeded its diagnostic budget.
  `F290` deferred by the user 2026-10-23: its narrow tile-selection adapter
  has no positive price (R41).
  No non-deferred candidate remains; speed work is paused under U7.
  User approved exact-poll scopes C0C2 → C1C2 (ordering), C2F2 → C302
  and C32D → C33D (priority), C395 → C3DF/C000 (expiry), and
  C3DF → C429/C3EB (advance) on 2026-10-23. Price each and implement
  viable designs; drawing and slope-initialization calls stay generated.
  Priority searches deferred by the user 2026-10-23 (R46): meter and
  target cost improve, but bench no-slowdown acceptance remains unproved.
  User deferred expiry/advance on 2026-10-23 (R47): address-reuse
  designs have no positive price. R48 keeps ordering C0C2 → C1C2 with
  exact original polls; measurements: speed-plan §1.
  The 4DAE packet loop uses the approved exact-poll contract
  ([native-compute.md](native-compute.md#exact-native-polling-user-2026-10-23));
  broader sprite decoding and dispatch remain generated.
  `BD68` deferred by the user 2026-10-23: its approved exact-poll edge-loop
  scopes have no positive price under the initial address-reuse design (R43).
  User approved D69C's exact-poll pixel scopes D92A → D93D and
  D95C → D96F on 2026-10-23; clipping, shared callees and returns stay
  generated. R44 enables the guarded pixel loops; measurements: speed-plan §1.
  User approved FDE0’s exact-poll cache-loop scopes 10008 → 10126/1004B
  and 1012F → 101DE/10186 on 2026-10-23; cache misses, transform/projection
  and overlay calls remain generated. User deferred FDE0 on 2026-10-23:
  the initial cache-loop design has no positive price (R45).

## F. Flyby plan

From the flyby profile (speed-plan §1, F0). Shares are of clip CPU. Estimates
apply the measured per-call reductions of earlier natives (26–68%) to the part
still generated; they are not measurements. Whole-routine scopes: narrow scopes
lost their gain to guards, hooks, exits and polls (R41–R47).

| Step | Item | Kind | Ceiling | Estimate | Needs |
|---|---|---|---:|---:|---|
| F0 | `amiga/perf_flyby.gdb` + committed inclusive-cost tool; re-profile after each kept step | instrument | — | — | user: supplementary fixture (§2.9) |
| F1 | EMS map copy (`ems.c`): long-word/`movem` copy, same semantics; then a dirty-page design if the frame is never written in flight | runtime | 10.30% | 7.5–8% | none for the copy; dirty design to the user |
| F2 | `RTSVGA+3B9A` frame compare and changed-span copy | guest | 4.11% | 2.5–2.9% | authorization (new) |
| F3 | Geometry as whole routines: `B52D`+`B54B`; `D5A6`→`B017` all paths→`B4E2` | guest | 4.57% generated | 2.3–3.0% | scope (U2 kept `B52D` generated) |
| F4 | FM synthesis inner loop in asm, bit-exact to the C | platform | 10.97% | 3.3–5.5% | user only if output changes |
| F5 | `BFD1` rasterizer, one scope (annotate unresolved callee flow) | guest | 7.58% | 3.0–4.2% | scope; deferred R46/R47 scopes |
| F6 | Terrain `FDE0`+`F290`+`EA74`, scope ends before the PLINK call | guest | 7.09% | 2.5–3.5% | lift deferrals; `EA74` authorization |
| F7 | `109D6` whole, native geometry called directly, DOS call a generated exit | guest | 5.0% | 2.0–2.8% | lift deferral; scope |
| F8 | Sprite decoder `4D7D`/`4DAE` incl. `call dx` dispatch | guest | 3.9% | 1.6–2.1% | scope |
| F9 | SPAZ OPL write `0CEE`: delay loop in O(1), exact final state | guest | 2.67% | ~2.4% | user: §2.9 out of bounds |
| F10 | Present/C2P reusing `3B9A`'s changed spans | platform | 5.22% | 1.0–1.5% | none (D5 bench) |

Next: `FLIGHT+1538C` object drawing (1.1–1.6%), `FLIGHT+0A8D2` AI scan (~1.5%).
All estimates: clip −28–36% (555 → 355–400 ms/frame); frames fixture, EMS ≈ 0,
−22–31% (340 → 235–265 ms): 240 ms only at the top of the range.
Each guest step follows S1–S9 with whole-scope prices and the exact-poll
contract; runtime/platform steps follow speed-plan §3. Z-style frames
checkpoints after F3, F7 and F10.

## Z. Close

- **U7** Speed work paused by the user on 2026-10-23. Z1's final run
  medians are 340, 340 and 350 ms (`9afe0b8`), above 240 ms. Parent ranges
  overlap; no frame-rate gain claimed. Resume only at the user's request;
  routine and contract approvals still apply. Measurements: speed-plan §1.
- **U9** Pending: resume under the [flyby plan](#f-flyby-plan), approve F0
  and the per-step needs (F2–F9).
