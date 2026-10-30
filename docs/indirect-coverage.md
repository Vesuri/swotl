# Indirect coverage boundaries

`annotations/indirect.csv` records execution separately from static targets.
A default initializer is not execution evidence or a proof against later writes.
The exclusions below are the user-approved scope of the coverage pass, not
translator assumptions. Keep every guard, return check and fail-loud dynamic
transfer; do not mark an excluded row executed.

## Default-runtime and video exclusions

| Sites | Reason and evidence |
|---|---|
| SWOTL+4F7B, +50A5 | EGA/Tandy cell walk requires `[2581]=0`. VGA sets 1 at +3C03; all ten callers of setup +E50E pass its current value. |
| FRONTEND+A90D | EGA branch: +A8FB/+A900 test `[9936]=0`; admitted incoming edges are fall-through, without an external seed. |
| SWOTL+137F7, +1380D, +138EB | Optional runtime hook `[5876]` starts null in DATA. |
| SWOTL+14459 | Optional runtime hook `[56F0]` starts null in DATA. |
| SWOTL+15B8A | Optional runtime hook `[5856]` starts `FFFFFFFF` in DATA. |
| SWOTL+14D4F, +14D74, +14D8D, +14DAB | Floating-point runtime slots 583C/5840/5848/584C initialize, with segment relocation, to +150F2: the FP-not-loaded error stub. Original snapshots confirm the targets. |
| SWOTL+13754 | Runtime error-exit callback `[5638]` defaults to +1389B (`__exit`); the divide-error path at +1373D selects +13884 (`_exit`). Not a normal-play fixture; keep dynamic dispatch. |

## Paths still requiring execution coverage

These are not excluded merely because current fixtures miss them.

| Sites | Condition or existing evidence |
|---|---|
| FLIGHT+17DB4 | Engine overheat: `[9792]=1` (single engine, aircraft field AF28, copied at SWOTL+123C1; B-17 damage captures have 4), damage on (`[6312]=0`; flight school defaults to 1, `W` on its setup screen toggles it), `[8452+4*player]>60` and nonzero engine-state words. Heat (FLIGHT+14F6C) rises only while `(throttle*[AF2C]+8000h)>>16 + 160*[8452] > [AF2E]`; the P-47 at full throttle gives BFFFh against DC00h, so `[8452]` must first reach about 45 from hits (damage routine FLIGHT+0C410). Recorded missions end with `[8452]=0`; flight school with damage on and 40 `equals` presses to full throttle never heats (2026-10-28). Needs a P-47 sortie with an engine hit. `[6A60]` resolves through PLINK to RTSVGA+44F1; target identity does not cover the call. |
| PANEL+33B2 | Cockpit damage display through `[AABC]`: pilot station `[6210]=0`, an active D4A0 slot and DD74 coordinate bit 15. Existing wing captures activate slots 0/2; engine slots 4/6 require a low engine-status nibble of 1..4, absent from those captures. |
| FRONTEND+A4D1, +A629 | Special formatting branches. Inspected direct callers pass ordinary parameters; the required sentinel and complete incoming-flow proof remain open. |

The pending formatting-test approval: open-work 9b.

Damage investigation: the B-17 runs consumed all 40 shifted function-key
codes, including a run with Shift visible at keyboard-status queries, but
engine state did not change. Do not repeat those inputs as if delivery were
unverified. The recorder has `equals`/`minus` (throttle up/down by 0800h,
FLIGHT+030D8/+0315D; approved 2026-10-28).
