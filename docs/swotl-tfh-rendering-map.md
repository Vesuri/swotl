# Their Finest Hour: what to adapt and how

Plan and evidence for speeding up SWOTL's rendering with what Their Finest Hour's
Amiga version (TFH, same engine family) and its WHDLoad slave show. Static research
2026-10-16, plan and prices 2026-10-17. Open work: [open-work.md](open-work.md) 14b, 31, 33.
Rules: [speed-plan.md](speed-plan.md) §2. The full research notes are kept locally in
`tmp/tfh-xref/swotl-tfh-rendering-map.2026-10-16.md`.

## Rules

- No TFH code or data enters the port ([tfh-cross-reference.md](tfh-cross-reference.md)).
  TFH and the slave are references for algorithms, register use and test cases.
- Translator work first. Native code for a guest routine only after the user
  authorizes that routine (speed-plan §2.2), as an `hle.csv` row with reason and oracle.
- SWOTL's original x86 is the oracle (Unicorn, DOSBox references); TFH and the slave's
  checks are not. Keep SWOTL's constants, rounding, branch order, scratch writes and
  tables; never take TFH's.

## Inputs

| Input | Where |
|---|---|
| TFH `bob` v1.1, 254,400 bytes, SHA-256 `4b5931c8…22443877` (tfh-cross-reference.md says 1.0; same file) | `../Their Finest Hour/tmp/game/TheirFinestHour/data/bob`; listing `tmp/tfh-xref/BOB.txt` |
| TFH addresses | code-hunk offsets; `jsr d16(a4)` enters a data-hunk `jmp` thunk (A4 = data + 7FFE): resolve it first |
| The slave (the user's): register and 68020 versions of TFH's transform, projection, divide, normalisation and scenery loops; models of the originals | `../Their Finest Hour/whdload/transform.s`, `render.s`, `tools/xform_check.py`, `docs/internals.md` |
| SWOTL costs | `5ecdf79` frames captures, 2026-10-17, three runs of 100 fields, 28,420,397 cycles each (`tmp/item30/frames-{1,2,3}/`): own time per generated call target; inclusive time per call by A7 (`tmp/item30/inclusive.py`: hardware interrupts and guest interrupt deliveries not charged) |

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

1. **Translator steps** (open-work 31, each ≤ 2.8%) in price order, by the speed-plan
   procedure (§3). No authorization needed. The cell cache is built (speed-plan R20:
   meter −15.31%; the walk is 3.62% of the corrected build’s first capture).
2. **Native contract** (open-work 33): interface, rules and oracle below.
3. **User decision per routine** from the priced table.
4. **Native routines**, each only after its authorization; poll-free leaves first.

Bounds (first `5ecdf79` capture): the transform/projection group (`B52D`, `B54B`,
`B4E2`, `B017`, `D5A6`) is 14.82% (R17 19.82%); with all of it gone, 400 ms would
become ~341 ms. The 240 ms target needs −40%: every row below together is 49.9%, so
~5× faster on average. R20's medians are 370–390 ms; the rows below are the
`5ecdf79` capture's, before R20.

## Candidates

First `5ecdf79` capture: own share, calls per 100 fields, own and inclusive cycles per
call. The other two captures lie within −25% to +32% of these shares, except `D69C`
(0.60–1.03%) and `4DAE` (2.44–5.38%, 8–41 calls); walk 12.94–16.46%.
Poll points from `build/gen/poll-points.csv`, routine start to its first `ret` (a lower
bound where a routine returns early); `B017..BB6F` has none at all.

| SWOTL | Function | Share | Calls | Own | Incl. | Polls | TFH | Slave |
|---|---|---:|---:|---:|---:|---:|---|---|
| `B52D`→`B54B` | camera-relative point transform | 1.08 + 6.16% | 1,478 | 208 + 1,185 | 1,393 | 0 | `2F48C`→`2F4AE` | `xform` |
| `B4E2` | perspective divide, rounded scale | 1.81% | 2,024 | 254 | 254 | 0 | `2F374` | `xdiv20` |
| `B017` | projection, rotation, viewport reject | 2.98% | 1,012 | 837 | 1,345 | 0 | `2F160`, `2F28A` | `xproj` |
| `D5A6` | normalise x/y/z to 15 bits, project | 2.79% | 843 | 941 | 2,312 | 1 | `3041C` | `xpnorm` |
| `B8A1` | face-facing test (no generated call target) | — | — | — | — | 0 | `2F822` | — |
| `BB70` | polygon bounds, top-vertex classify | 1.35% | 178 | 2,155 | 2,162 | 7 | `2FA12` | — |
| `109D6` | ground-object faces and vertices | 2.73% | 110 | 7,053 | 25,325 | 6 | `1142C` | `scen_verts` |
| `4DAE` | scaled packet sprite decoder | 5.05% | 41 | 35,006 | 50,389 | 7 | `2BACE` | — |
| `D69C` | clipped line | 1.03% | 136 | 2,152 | 2,574 | 9 | `30486` | — |
| `BD68` | polygon edge submission | 0.68% | 94 | 2,056 | 4,821 | 5 | `2FBB2` (related) | — |
| `FDE0` | terrain polygon selection, submission | 1.67% | 5 | 94,924 | 531,336 | ≥ 3 | `104B6..10830` | — |
| `F290` | terrain rings, scenery selection | 1.23% | 5 | 69,914 | 111,149 | 2 | `11138` | `tile_scenery` |
| `BFD1` | active-edge scan conversion, priority sweep | 4.83% | 5 | 274,541 | 799,860 | ≥ 2 | none | — |
| `6A4D` walk | shared pixel writer (cells) | 16.46% | 3,055 walks | 1,531 per walk | — | — | `2CD7A`, `2BC80` | — |

Not candidates: RTSVGA `+3B9A` (3.21%, changed-row copy; TFH `283A0` converts 4-bit
chunky to planar), RTSVGA `+3DCD` packed images (`27D40`; SWOTL's FB/FC tokens), TFH
image payloads and terrain map, TFH projectile dispatch, TFH's two-chain rasterizer
in place of `BFD1`.

## Native contract (open-work 33)

- Range: the routine's first instruction to the one before its `ret`/`retf`; the guest
  return and its return check still run.
- Registers: every guest register the original writes holds the original's value at
  the resume unless the translator proves it dead (no annotation asserts it, §2.3).
  Flags exact where live at the resume.
- Memory: every store the original makes, same value. The slave keeps TFH's scratch
  in registers because it proved every other user writes first; SWOTL's host run
  compares RAM with DOSBox. `B54B` writes scratch DS:`22C6..22D4` besides its outputs.
- Layout: a guest word at L is the 68k word at TOP−L−1, a dword the 68k long at
  TOP−L−3; no byte swaps. 16-bit offset wrap keeps its x86 meaning.
- Interrupts: poll-free routines leave delivery unchanged. Routines with poll points
  need a user decision: §2.9 forbids removing or thinning them, and the host run
  replays each reference interrupt at the same visit of the same poll point.
- Interface: `hle.csv` passes at most two guest word registers (d7/d6); a compute row
  reads and writes the guest register file and stack directly: extend the emit
  contract and the block differential.
- Oracle: the original x86 under Unicorn on recorded entry states (as
  `tools/sfx_levels.py` runs SPAZ): registers, live flags and every write compared,
  with the cases below; `make test-host-all` with the row on and references unchanged;
  one sabotage plant per row.
- Price `mulu.l`/`divu.l` on the 68020 model (speed-plan §4), not from the slave's shares.

## Facts per candidate

### Transform `B52D`/`B54B` ↔ `2F48C`/`2F4AE`

- Wrapper: three 32-bit stack arguments into AX:BX, DX:CX, SI:DI.
- Point − camera (DS:`2276/227A/227E`; TFH A4+`103A/103E/1042`) as sign and magnitude,
  times matrix magnitudes `224E..225C` with signs `225E..226C` (TFH `1012..1020`,
  `1022..1030`). Rows of 3, 2 and 3 terms, each floor(|v|·m/65536) from two `mul`s,
  signed. First row x·m`2256` + y·m`225C` + z·m`2254` (TFH m`101A`, `1020`, `1018`).
- Outputs, 32-bit: DS:`C394`, `C38C`, `C390` (TFH `108C`, `1084`, `1088`).
- Slave: one `mulu.l` per term (bits 16–47 equal the halves' sum; no carry out).

### Normalise `D5A6` ↔ `3041C`

- x and y as magnitudes (signs from DS:`2399/239B`); x, y, z shifted right together
  until x|y|z < 8000h (loop `D5DA..D5F6`, poll point `D5DA`); signs back; words
  DS:`22BA/22BE/22C2` (TFH `1090/1092/1094`); then `B017`.
- Slave: one shift by the counted amount (`bfffo`).

### Divide `B4E2` ↔ `2F374`

- Two word divides → 32-bit quotient, × scale, rounded with 8000h, numerator's sign;
  explicit zero denominator. Denominator DS:`22C2`, scale `22D8` (TFH `1094`, `10A8`).
- Slave: `divu.l` + `mulu.l`. Keep quotient overflow and fault behaviour.

### Projection `B017` ↔ `2F160` (32-bit path `2F28A`)

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

### Ground objects `109D6` ↔ `1142C` (vertex loops `11604..11B34`)

- Offset-table select, clear vertex state, 7-byte header, faces with indexed vertices,
  facing test, transform uncached vertices, midpoint vertices, project, submit;
  vertices × 64 + origin; coefficient records built in below 80h, extra above.
- Calls: `10BEA` `B8A1`, `10CD6` `B52D`, `10F13` `D5A6`, `10FFD` `BB70`, `11036`
  `BD68`, `110D8`/`1111B` `D69C`; sprites `111AA`/`1120B`.
- SWOTL header bytes 3/4/5, face byte & 0Fh; TFH counts at 4/5.

### Sprite decoder `4D7D`/`4DAE` ↔ `2BA28`/`2BACE`

- Setup `4CA1` ↔ `2B9A2`: two orientation contexts (DS:`12BE/1A78`), `9291` only on an
  angle miss. Header 5 bytes (x origin byte 0, or −byte 2 mirrored; y byte 1;
  transparent selector byte 4); packets: FF ends, count + 3 advances, forward or
  reverse; low nibble scaled advance, high nibble colour.
- SWOTL advance tables DS:`0FA6/10A6` (`90F2` rebuilds them only when `0FA0` changes),
  spans at DS:`08BB`, pixels through the walk (`4FF7`, clipped `5139`). TFH writes
  nibbles with mask/OR.
- Transparency is decided on the selector, before colour mapping. Palette setup `4D1D`
  has no cache guard.

### Rasterizer `BFD1` (no TFH equivalent; translator work only)

- Edge records, 16 bytes (arena DS:`2360`, ≤ 500; buckets `1F40 + 16·y`, active list
  `4060/4062`): +0 lifetime, +2 priority (DS:`252F`), +4 colour, +5 event and slope
  flags, +6 x, +8 endpoint then fraction, +A/+C step, +E start row.
- Stages: add `C04B..C0AA`; order and merge `C0C2..C1BF` (equal-x edges may cancel or
  merge: not a sort); visibility `C1C2..C394` (priority table `41F0`, background
  DS:`25A1`); expire `C395..C3DE`; advance `C3DF..C429` (lazy slope `C8E0`).
- Output: DS:`233E` ≠ 0 `CD99` → `5260` → walk; = 0 `CE3C` `rep stosb`.
- Terrain priority is submission order (`C450` from 10h, +2 per accepted polygon).

### Terrain `FDE0` ↔ `104B6..10830`; rings `F290` ↔ `11138`

- `FDE0`: cells `(645C−60)>>6`, `(658E−40)>>6`; 13×13×5 table (far pointer `BF02`),
  ≤ 5 polygon IDs per cell, FF ends, marked visited before transform; transform and
  projection caches, 25 entries each, one-based, no eviction; camera-plane clip
  `FLIGHT+17086` ↔ `11D60`; then `BB70`, `BD68`. TFH visits 11 fixed polygons with
  six-axis rejection: not importable.
- `F290`: the same 11 ring offsets (`DATA.OVL+631C`, DS:`54CC`); SWOTL 50×50 bytes,
  TFH 64×64 nibbles.

### Line `D69C` ↔ `30486`

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
