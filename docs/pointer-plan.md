# Pointer plan (open-work 45)

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
- **Visibility.** The sprite shows iff the shape is complete in VGA memory at the present
  (hidden, partly drawn or overwritten: no mask, no sprite, frame as the reference). The
  state rides the queued list and takes effect when the vertical blank shows that list.
- **Position.** Vertical blank, before sprite DMA fetches: guest position + hotspot + lead.
  Lead = motion not yet applied by the guest, by its own rule (±BFh/±7Fh, ÷ 2 toward zero,
  bounds). Single-writer counters: platform totals; runtime records each AX=0Bh result; HLE
  row `pointer_tracked` (observe only, EQ) at tracker exit `0320:1011` marks it applied
  (user 2026-10-26). A second AX=0Bh before that exit (motion discarded) stops the lead
  until the next exit.
- **Colours.** Sprite 6, `BPLCON4 = $00FF`: value 1 → entry `FD` := `DAC[00]`, 2 → `FE`
  (same entry, exact), 3 → `FF` := `DAC[F0]`. Overrides only while the pointer is active;
  no palette change on a shape switch.
- **Hardware.** All eight `SPRxPT` in both copper lists, unused channels at an empty
  sprite (L9); sprite DMA on; sprites in front (L32); BRDSPRT clear (display window clips);
  `SV8`/`EV8` for rows past `$FF`.
- **Placement.** Guest addresses in `annotations/pointer.csv`, emitted by `gen`; runtime
  `pointer.c` (mask, visibility, lead), shared with the host; Amiga `Pointer.cpp` (sprite
  words, colours, VBI write). No toggle: the sprite replaces the software pointer.

## Steps

| Step | Work | Checks |
|---|---|---|
| P1 | Measure on the A1200 model: tracker exits and pointer presents per field in menus | short `pN` scripts, counters; numbers in the commit |
| P2 | Static: shapes ≤ 16 wide and fit the slots; `A42A` row layout (w bytes per row); census: `FD`, `FF` never displayed on pointer screens (reference corpus). If `FF` is shown, stop and ask | new tool + test, sabotage |
| P3 | `pointer.csv`, runtime mask and visibility, host model | c9 and the pointer-screen coverage fixtures: masked frame + modelled sprite = VGA memory at every present; plants: hotspot sign, equality rule, visibility |
| P4 | Lead: AX=0Bh record, `pointer_tracked` row | at every tracker exit lead (motion consumed) = guest position; plants: ±BFh clamp, floor for truncation, bound off by one, discarded motion |
| P5 | Amiga sprite, copper, colours, VBI write | `make amiga`, smoke, test-amiga, display audit 68030/68040; model shot at rest = DOSBox frame with its pointer; horizontal offset calibrated there |
| P6 | Docs: amiga-arch Display/Input, open-work; generic lessons to AmigaXDev | consistency |

Gates: the new tests and plants, the host fixtures above, Amiga build and image checks; no
`make gates` (translator semantics unchanged; the HLE row uses the existing EQ path).
