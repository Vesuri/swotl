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
| U3 | Confirmed 2026-10-21: keep every byte's complete write history, SMC/display bookkeeping and all other state checks; write histories retire at [irq-plan](irq-plan.md) I9 (U12) | — |
| U4 | Approved 2026-10-22: `SWOTL.EXE+B017`, adapting the slave’s `xproj20`, by S1–S9. B4E2 adapting `xdiv20` authorized 2026-10-22; B8A1 authorized then deferred 2026-10-22: no calls in the acceptance workload; the `B393` long-path hook returning at `B4E1` is approved | N2 |
| U5 | Approved 2026-10-21: chosen polls (removed interior polls, return poll, optional sync sites), up to one PIT period of interrupt delay in a native routine, affected references re-recorded per row (implemented by C3); retired at [irq-plan](irq-plan.md) I9 (U12) | — |
| U6 | Approved 2026-10-22: D5A6 adapting xpnorm20; normalization loop D5DA–D5F6 → D5F8 with explicit non-return endpoint extension and U5 polls. BB70, 109D6, F290, 4DAE, BD68, D69C, FDE0 and BFD1 authorized 2026-10-22 by the remaining-candidates goal; admission, pricing and S1–S9 remain required | N4 |
| U7 | User paused speed work 2026-10-23; resumed under U9 the same day | — |
| U8 | Approved 2026-10-21: REP away from kept polls, divide-fault decline, multiple returns; range/unresolved flow by annotations ([extensions](native-compute.md#contract-extensions-u8), implemented by C4); routines still need U4/U6 | — |
| U10 | Approved 2026-10-24: "Replace B52D too, go ahead with F3": F3 replaces whole geometry routines, `B52D` included (widens U2) | F3 |
| U11 | Approved 2026-10-24: allow `end` on continuation rows (escaping flow, returns and nested hooks still reject) for F5's whole `BFD1` row | F5 |
| U12 | Approved 2026-10-24: [irq-plan](irq-plan.md) with rule changes RC1–RC6; U3 write histories, U5 and exact native polling retire at its I9 (RC5) | irq-plan |
| U9 | Approved 2026-10-23: "I approve resuming the speed work and the things required to fix those top 10 bottlenecks": [F](#f-flyby-plan) F0–F10 with each step's listed needs, including F9's §2.9 exception; S1–S9 and §3 acceptance still apply | F |

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

Contracts: U5 (`hle.csv` `polls`; retired at irq-plan I9 by RC5 for
[poll-free loop rows](native-compute.md#loops-and-the-sync-set-rc5)) and
[U8](native-compute.md#contract-extensions-u8) (`end`; `t-compute-u8`), implemented. Admission on the candidates (C4,
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
Since irq-plan I10 guest calls are continuation exits with
[re-entries](native-compute.md#re-entries-irq-plan-i10-user-2026-10-26)
(`BFD1`, `BD68`, `F290`, `FDE0`, `109D6`); `4DAE`'s `call dx` walk stays
generated.

- **N4** Routines that need C, each after U6, by S1–S9 plus C's cases, in B3 price
  order; S8 includes re-recording the references its poll set affects. Price each
  with its return/sync polls and exits. `BB70` deferred by the user 2026-10-22: preserving its seven sync sites
  has no positive price;
  `109D6` vertex loops deferred by the user 2026-10-22 after the initial
  guarded adapter exceeded its diagnostic budget.
  `F290` deferred by the user 2026-10-23: its narrow tile-selection adapter
  has no positive price (R41).
  No non-deferred candidate remained; U9 resumes speed work under plan F.
  User approved exact-poll scopes C0C2 → C1C2 (ordering), C2F2 → C302
  and C32D → C33D (priority), C395 → C3DF/C000 (expiry), and
  C3DF → C429/C3EB (advance) on 2026-10-23. Price each and implement
  viable designs; drawing and slope-initialization calls stay generated.
  Priority searches deferred by the user 2026-10-23 (R46): meter and
  target cost improve, but bench no-slowdown acceptance remains unproved.
  User deferred expiry/advance on 2026-10-23 (R47): address-reuse
  designs have no positive price. R48 keeps ordering C0C2 → C1C2 with
  exact original polls; measurements: speed-plan §1.
  The 4DAE packet loop used the approved exact-poll contract (poll-free since
  irq-plan I9);
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
  irq-plan I10 (user 2026-10-26) lifted these deferrals: `BB70`, `109D6`,
  `F290`, `BD68`, `FDE0` and the `D5A6` prefix are rows (speed-plan §7 I10).

## F. Flyby plan

From the flyby profile (speed-plan §1, F0; first run, F8 and F1 ranges from both). Shares are of clip CPU. Estimates
apply the measured per-call reductions of earlier natives (26–68%) to the part
still generated; they are not measurements. Whole-routine scopes: narrow scopes
lost their gain to guards, hooks, exits and polls (R41–R47).

| Step | Item | Kind | Ceiling | Estimate | Needs |
|---|---|---|---:|---:|---|
| F0 | `amiga/perf_flyby.gdb`, `tools/profile_tree.py`, `tools/ab_runs.py`; re-profile after each kept step | instrument | — | — | U9 |
| F1 | EMS map copy (`ems.c`): long-word copy, exact identical-remap skip. Done: c12 meter −27.72% (speed-plan §1); a write-back skip needs a cheap exact unmodified test | runtime | 1.8–10.3% | 1.4–8% | — |
| F2 | `RTSVGA+3B9A` frame compare and changed-span copy. Done as a lowering: its cost is its REP instructions; REP MOVSW by longs, flyby `rep movsw` −29% (speed-plan §1). Left: `repne cmpsw` 1.0–1.4% and `repe cmpsw` 1.4–1.5% of the clip, already word/long loops; a native merging search and copy has no price yet | translator | 4.11% | 0.3% kept | — |
| F3 | Geometry as whole routines: `B52D`+`B54B`; `D5A6`→`B017` all paths→`B4E2`. `B017` whole with `B4E2` done (folds the `B393` and `B4E2` rows): meter −1.4854%, flyby cycles/call −22.7% (speed-plan §1). `D5A6` stays a separate row: `B017` is also called directly (~15% of calls) and nested hooks reject. `B52D` whole with `B54B` done: meter −1.5848%, flyby cycles/call −23.3%; bench +0.025% (8 runs per arm), accepted by the user as noise. `D5A6` prefix done at irq-plan I10: the row is D5A6..D614, continuing at the `B017` call | guest | 4.57% generated | 2.3–3.0% | U10 |
| F4 | FM synthesis speed, output unchanged. Done in C (asm not needed): loop cache and render loop; flyby `fm_field` −24.4% per call (10.75% → 8.11% of the clip); bench +0.20% (frames 4–11 render no loops), accepted by the user as noise 2026-10-24 (speed-plan §1) | platform | 10.97% | 3.3–5.5% | user only if output changes |
| F5 | `BFD1` rasterizer, one scope. Done: `C000..C42C`, guest calls as continuation exits (U11), folds R48; meter −0.0167%, bench −0.044%, flyby `BFD1` −2.1%/call (speed-plan §1): far below the estimate | guest | 7.58% | 3.0–4.2% kept 0.05% | U11 |
| F6 | Terrain `FDE0`+`F290`+`EA74`, scope ends before the PLINK call. Done at irq-plan I10: `F290` (−0.84M m4) and `FDE0` (−0.59M) whole with exits and re-entries; `EA74` (cell-walk driver) has no positive scope | guest | 7.09% | 2.5–3.5% | — |
| F7 | `109D6` whole, native geometry called directly, DOS call a generated exit. Done at irq-plan I10: vertex loops 10C08–10F5F, −0.66M m4 | guest | 5.0% | 2.0–2.8% | — |
| F8 | Sprite decoder `4D7D`/`4DAE` incl. `call dx` dispatch. irq-plan I10: span setup with the packet loop (`sprite_row`); the walk loop 0623–064F (~10.6M m4) needs a native planting code writes and calling the cell walk | guest | 3.9–14.8% | 1.6–7% | contract extension (user) |
| F9 | SPAZ OPL write `0CEE` delay loops. Done with every iteration, poll and stack store kept: meter −1.4996%, flyby `0CEE` −36.4%/call (speed-plan §1). O(1) done at irq-plan I10 | guest | 2.67% | ~2.4% kept ~1.0% | U9 |
| F10 | Present/C2P reusing `3B9A`'s changed spans | platform | 5.22% | 1.0–1.5% | none (D5 bench) |

Next: `FLIGHT+1538C` object drawing (1.1–1.6%), `FLIGHT+0A8D2` AI scan (~1.5%).
All estimates: clip −28–36% (555 → 355–400 ms/frame); frames fixture, EMS ≈ 0,
−22–31% (340 → 235–265 ms): 240 ms only at the top of the range.
Each guest step follows S1–S9 with whole-scope prices and the exact-poll
contract; runtime/platform steps follow speed-plan §3. Z-style frames
checkpoints after F3, F7 and F10. After F3 (run after F4, ZF3 2026-10-24):
330, 300, 300 ms against pre-F3 360, 350, 360 ms (speed-plan §1).

## Z. Close

- **U7** Speed work paused by the user on 2026-10-23, resumed under U9. Z1's final run
  medians are 340, 340 and 350 ms (`9afe0b8`), above 240 ms. Parent ranges
  overlap; no frame-rate gain claimed. Routine and contract approvals still
  apply. Measurements: speed-plan §1.
- **U9** Speed work resumed 2026-10-23 under the [flyby plan](#f-flyby-plan).
