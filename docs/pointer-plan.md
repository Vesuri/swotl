# Pointer plan (open-work 45, done 2026-10-28)

Goal: the game's software mouse pointer is shown as an AGA hardware sprite that looks
the same and moves smoothly, its position written at the vertical blank. Every screen that
uses the guest's pointer (menus, film room). Guest code and memory stay as in the original;
only the display differs. Plan and decisions: user 2026-10-26. One step, one commit, checks
stated before running (AGENTS.md validation scope). Evidence: `tmp/pointer/<step>/`.

## Facts (static reading of the IR, 2026-10-26)

`SWOTL.EXE` segment `0320`, data in DGROUP (`ds`):

| Item | Where | Behaviour |
|---|---|---|
| Poll | `05B6` | INT 33h AX=3 (`AA04`/`AA88`, unread) then AX=0Bh: motion → `A8F8` clamped to ±BFh, `A9A8` to ±7Fh; buttons → `A86A` via table `05E8` |
| Position | `0C64(x, y)` | `9C1A`, `9CBA`; menus hit-test against them |
| Shape | `0C76(n)` | table `ds:05F0` (8 B: width, height, hotspot x, y) → `9D62`, `9D86`, `9D3A`, `9D4C`; image pointer `ds:065C+2n` → `9DC8` |
| Bounds | `0CFC` | x `[9F52, 9FCE)`, y `[A0EA, A1D0)` |
| Hide | `0CAC` | `callf [AE04]` (restore) from buffer `ds:A42A`, rect (x+hx, y+hy, w, h) |
| Show | `0CD2` | `callf [AD50]` (save) into `A42A`, then `callf [BA1E]` |
| Draw | `RTSVGA+4184` | pointer pixels to `es = [284C]`; `FDh` transparent; rows outside 0–199 and columns outside 0–319 skipped |
| Tracker | `0D1A` | motion ÷ 2 (`idiv`, toward zero; only if nonzero), arrow keys (`A4E6` 1–4, accel `5E82`/`5F28`), joystick; clamp to bounds; if moved: hide, store, show; exit `1011` |
| Driver table | `0320:08AC..08CD` | `AD50`, `AE04`, `BA1E` from `ds:06C0+si`, `06CC+si`, `06D8+si` (driver entries) |

- `A42A` and `BA1E` have no other users. Callers of `0CAC`/`0CD2`: FRONTEND 53/52,
  NOTCAMP 22/26, CAMPAIGN 12/12, REPLAY 6/3; FLIGHT none.
- Shapes (`DATA.OVL`, DGROUP = DATA image + 580h): 0 arrow 6×7, hotspot (0, 0), colours
  `00h`, `FEh`; 1 crosshair 7×7, hotspot (−3, −3), colours `F0h`, `FEh`. No others.
- Amiga display: `FMODE = 3` (16-pixel sprites), DDF `$38`, DIW from `setPlayfield`,
  `BPLCON4 = $0011`, sprite DMA off, sprites cleared at takeover.
- Frame path: `video.c` `present()` copies changed rows into its persistent chunky frame at
  a vertical blank's poll point or field task, outside driver calls.

## Design

- **Mask.** In `present()`, while every opaque shape pixel in VGA memory equals the shape,
  replace those pixels in the chunky frame by the save buffer's. The guest's own cursor
  never reaches the bitplanes.
- **Visibility.** The shape is complete in VGA memory at a present, or not (hidden, partly
  drawn or overwritten: no mask, frame as the reference). The sprite follows that state only
  once it has held at two consecutive presents, so for at least a field: the guest moves
  its pointer by hide, store, show, and a present between them must not blank the sprite
  (the DOS flicker is not reproduced; user 2026-10-27). The sprite's image changes only
  with the shape. The state rides the queued list and takes effect when the vertical
  blank shows that list.
- **Position.** Vertical blank, before sprite DMA fetches: guest position + hotspot + lead.
  Lead = motion not yet applied by the guest, by its own rule (±BFh/±7Fh, ÷ 2 toward zero,
  bounds). Single-writer counters: platform totals; runtime records each AX=0Bh result; HLE
  row `pointer_tracked` (observe only, EQ) at tracker exit `0320:1011` marks it applied
  (user 2026-10-26). A second AX=0Bh before that exit (motion discarded) stops the lead
  until the next exit.
- **Colours.** Two sprites, `BPLCON4 = $00FF` (bank `F`): sprite 6 draws the shape's `FE`
  pixels as colour 2 (entry `FE`, exact); sprite 4 draws its other colour (arrow `00`,
  crosshair `F0`) as colour 1, entry `F9` := that colour's DAC value, set on a shape
  switch. `F9` is never displayed on a pointer screen (P2 census); `FD` and `FF` stay as
  they are (user 2026-10-27, after the census found `FF`, the text colour, on every
  pointer screen).
- **Hardware.** All eight `SPRxPT` in both copper lists, unused channels at an empty
  sprite (L9); sprite DMA on; sprites in front (L32); BRDSPRT clear (display window clips);
  `SV8`/`EV8` for rows past `$FF`.
- **Placement.** Guest addresses in `annotations/pointer.csv`, emitted by `gen`; runtime
  `pointer.c` (mask, visibility, lead), shared with the host; Amiga `Pointer.cpp` (sprite
  words, colours, VBI write). No toggle: the sprite replaces the software pointer.

## Measurements (P1, 2026-10-27)

`amiga/pointer_measure.sh`, 68030 model, main menu, production image at `aea0e90`:

| Window | Fields | Moves (hide, show) | Frames shown | Present inside a move | Inside a menu redraw |
|---|---|---|---|---|---|
| mouse moved every field, 48 steps | 49 | 48 | 48 | 1 | 0 |
| at rest, 5000 mouse reads | 25 | 0 | 1 | 0 | 0 |

- The guest polls the mouse about 100 times per field at rest, so a move is shown in
  the field its motion arrives: the lead stays small in the menu, larger on slow screens.
- 1 move in 48 is presented between hide and show (the frame without a pointer): the
  visibility rule above keeps the sprite on through it.
- Breakpoints on the polls distort the model's field timing, and a stop with an interrupt
  pending is reported again: the script stops on cold paths and counts state changes.

## Static facts and census (P2, 2026-10-27)

`tools/pointer_static.py` (test with plants: `tests/test_pointer_static.py`):

- Shape selects: 17 sites push constants, 16 × 0 (FRONTEND, NOTCAMP, CAMPAIGN), 1 × 1
  (`FRONTEND+06E31`). Only `0C76` writes the shape words, only `0C64` and the tracker
  the position, only hide/show name `A42A`.
- VGA driver entries (index 8): save `RTSVGA+40E6`, restore `+4138`, draw `+4184`. Save
  and restore copy w bytes per row at `row(y) + x`, unclipped; the row table (`cs:35FC`)
  is 320·y; the draw writes rows 0–199 and columns 0–319 of segment `A000`. Buffer byte
  `r·w + c` is therefore screen byte `320·(y0 + r) + x0 + c` of every drawn pixel.
- Census, 99 reference snapshots, 52 with the pointer complete: entries `F0`–`FF` hold
  one fixed set of colours on all 52 (`F0` black, `FE` yellow, `FF` white text on every
  screen, `FD` grey on 41 pixels of 7); `F9` (light blue) and `AB` are never displayed.
  No bank's sprite entries are all unused, hence the two sprites above.

## Mask and host model (P3, 2026-10-28)

- `annotations/pointer.csv` → `pointer_guest` (gen); HLE `pointer_tracked` at `0320:1011`
  records DGROUP (`rt_pointer_ds`). `src/runtime/pointer.c`: at each present, complete
  (every opaque on-screen pixel holds the shape, one colour besides `FE`) → those frame
  pixels from `A42A`, `rt_pointer` filled; the masked box is presented from VGA memory again
  at the next present (`video.c`). `rt_pointer_visible`: a state applies once it holds at
  two blanks in a row. Mask only with `rt_pointer_sprite` (host: on; Amiga: P5).
- `tests/host_run.py` `check_pointer`, every present of every host run: the oracle's state
  from DGROUP and VGA memory = `rt_pointer`; frame = VGA memory with the masked pixels from
  the buffer; frame + modelled sprite = VGA memory; no `F9` while shown. `test-host-all`:
  90 fixtures, 279945 presents, 7977 with the pointer shown (83 fixtures), all equal.
- The fixtures never show the crosshair: `tests/test_pointer_model.py` calls the mask on
  built states (arrow, crosshair, clipped, overwritten, two colours, off screen, no DGROUP,
  no sprites) and the visibility sequence; plants hotspot, equality, visibility caught.

## Lead (P4, 2026-10-28)

- `input.c`: each AX=0Bh result goes to `rt_pointer_read` (pending mickeys:
  `rt_mickey_x/y`). `pointer_tracked` calls `rt_pointer_tracked`: the position at the exit,
  reads cleared. `rt_pointer_lead(dx, dy)` (vertical blank, platform motion not yet read
  by INT 33h): exit position + read motion (one read) + unread motion, each by the guest
  rule; two reads before an exit: no lead (the last value) until the next exit.
- A pointer shown away from the exit's position (set by `0C64`, or a present between the
  tracker's show and its exit) is adopted with no read pending (`rt_pointer_mask`).
- Consistency: every main-thread write (INT 33h taking the platform's counts, AX=0Bh's read
  and clear, the exit, the adopt) runs with `serial` odd; the blank keeps its last result
  then. `rt_pointer` also carries the hotspot for the platform.
- Bounds from the tracker's clamp words (`x_min` `9F52`, `x_end` `9FCE`, `y_min` `A0EA`,
  `y_end` `A1D0`, `pointer.csv`).
- `tests/host_run.py`, every tracker exit after the first whose motion came from the mouse
  (A8F8/A9A8 = applied C37C/C37E) and not from `0C64`: the lead's prediction = guest
  position. `test-host-all`: 915298 exits, 914792 predicted (805 with motion), all equal;
  plants clamp and trunc caught on c9. No fixture reaches an upper bound or reads twice
  before an exit: `tests/test_pointer_model.py` drives the lead on built states (rest,
  read, pending, both, clamp, trunc, bounds, discard, a write open at the blank, a direct
  set) against a Python reference; plants clamp, trunc, bound, discard, serial, adopt
  caught.

## Amiga sprites (P5, 2026-10-28)

- `src/platform/amiga/Pointer.cpp`: per display buffer, sprites 4 and 6 (16 wide, 16 rows)
  in Chip RAM; both lists set all eight `SPRxPT` before the palette (idle channels at an
  empty sprite), `BPLCON4 $00FF`, sprite DMA on. A present (`finishDisplayUpdate`) records
  the frame's state with its buffer and rewrites that buffer's sprite data only when the
  shape changes (the last shape stays through frames without the pointer). Entry `F9`
  holds the other colour in a frame with the pointer and in the next; otherwise sprite 4
  stays off (the yellow part alone for a field if a frame with the pointer is replaced
  before it is shown).
- Vertical blank, after `Input` (newest mouse counts): `rt_pointer_visible` of the shown
  buffer's state, position = lead + hotspot, `HSTART = $80 + x`, `VSTART = $38 + y`
  (DIWSTRT `$3881`), SV8/EV8; then the handoff seam. `amiga_sprite_late` counts writes at
  or after line 25 (the display audit fails on any).
- Checks: `tests/amiga_sprites.py` decodes the dumped sprite words over the shown planes
  (sprite 4 covers 6, the window clips). `test-amiga` and the replays: shown + sprites =
  the DOSBox frame, entry `F9` = the stolen colour's DAC (the capture waits up to two blanks
  while the sprite's state settles). Display audit: bitmap = presented frame, presented
  frame = A0000h outside the masked pointer, shown + sprites = A0000h, palette with `F9`.
  Results: `test-amiga` (m1b) ok; replays m2-choose-side and c9-mouse-menu composed
  (stolen `00`), equal to DOSBox; display audit 68030 and 68040 40 captures ok, no late
  sprite write (the audit's screens have no pointer). Plant `HSTART = $81 + x` on the c9
  replay: 12 pixels differ.

## Steps

| Step | Work | Checks |
|---|---|---|
| P1 | Measure on the A1200 model: tracker exits and pointer presents per field in menus | short `pN` scripts, counters; numbers in the commit |
| P2 | Static: shapes ≤ 16 wide and fit the slots; `A42A` row layout (w bytes per row); census of the sprite's stolen entry on pointer screens (reference corpus; `FF` was shown: two sprites and `F9`, user 2026-10-27) | new tool + test, sabotage |
| P3 | `pointer.csv`, runtime mask and visibility, host model | c9 and the pointer-screen coverage fixtures: masked frame + modelled sprite = VGA memory at every present; plants: hotspot sign, equality rule, visibility |
| P4 | Lead: AX=0Bh record, `pointer_tracked` row | at every mouse-driven tracker exit lead (motion consumed) = guest position, plants clamp and truncation (host); bound off by one and discarded motion on built states (model test) |
| P5 | Amiga sprites 4 and 6, copper, colours, VBI write | `make amiga`, smoke, test-amiga, display audit 68030/68040; model shot at rest = DOSBox frame with its pointer; horizontal offset calibrated there |
| P6 | Docs: amiga-arch Display/Input, open-work; generic lessons to AmigaXDev | consistency |

Gates: the new tests and plants, the host fixtures above, Amiga build and image checks; no
`make gates` (translator semantics unchanged; the HLE row uses the existing EQ path).
