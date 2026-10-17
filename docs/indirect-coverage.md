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
| FLIGHT+17DB4 | Requires `[9792]=1` (aircraft field AF28, copied at SWOTL+123C1); B-17 damage captures have 4. Also requires `[8452+4*player]>60` and nonzero engine-state words; the recorded P-47 dive satisfies `[9792]=1` but ends with damage byte 0. `[6A60]` resolves through PLINK to RTSVGA+44F1; target identity does not cover the call. |
| PANEL+33B2 | Cockpit damage display through `[AABC]`. |
| FRONTEND+A4D1, +A629 | Special formatting branches. Inspected direct callers pass ordinary parameters; the required sentinel and complete incoming-flow proof remain open. |

The c26 usage-exit reference separately requires exact EMS release support on
the host. DOSBox evidence includes retained mappings, reused handles and
backing-page aliases; clearing a handle alone is not an exact implementation.
