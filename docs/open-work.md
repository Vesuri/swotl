# Open work

The single list of open work. Remove items when done; history is in git.
Step plans: [plan-reference-map.md](plan-reference-map.md) (phases 1–2),
[translator-design.md](translator-design.md) (phase 5 on, decisions D1–D16).

## Guest map follow-ups

9a. Cross-reference TFH Amiga `BOB` (Aztec C, same source family) in Ghidra
   for routine naming and `.PAC`/`.GOB` formats; evidence only.
9b. 232 indirect sites are static-only (no traced target,
   `annotations/indirect.csv`), mostly `lcall [mem]` through DGROUP
   pointers (221). Add coverage scripts (campaign play, other aircraft,
   film load/save) where a generated path needs them.
9c. PLINK flag bit 13 (set on DATA only): meaning unknown; no effect seen.
9e. `tools/sweep.py` does not seed `annotations/runtime.csv` entries, so
   `callf [56EAh]` at SWOTL+140DB (`__harderr_handler`) has no
   `indirect.csv` row (it dispatches; counted in `tests/audit.csv`).

## Translator

14. Past the milestones: the host run matches m1–m7 and c6-flight-keys
    (`make test-host-all`; files the guest writes stay in memory there);
    the A1200 model (68030) runs the attract demo for minutes unattended,
    checked only at m1b-logo (it runs on wall-clock time, not replayed).
    With `KEYS=` the model goes from the logo through the menus into flight
    and moves and clicks the menu pointer. INT 33h motion and buttons are
    transcribed from DOSBox-X but untested: no reference has mouse input
    (needs scripted motion in the DOSBox-X mouse patch). Next: the D16
    cell walk is a per-cell form match (perf:
    specialise once the shape is fixed); find-first gives platform files
    no DOS time/date; table targets added by
    `annotations/tables.csv` that no reference run executed are checked by
    the instruction differential only.
14a. Display: the changed rows of each published frame are converted into
    the shown copper bitmap (tears; no double buffer). A double buffer must
    carry the other buffer's changed rows too (Vette: back buffer inherits
    the previous update's rectangles). Takeover: no readable-state restore
    check yet (L5, SL `restore_status`); keyboard and mouse input from the
    takeover are untested by any reference (scripted input enters past the
    CIA and JOY0DAT reads).
14b. Speed: [translator-plan.md](translator-plan.md), T1–T9 under
    [speed-plan.md](speed-plan.md) §0–§1. Target ≤12 fields on 68020 + 8 MB Fast.
    T11 remains the latest kept lowering: 24.5 fields (490 ms), code payload
    1,325,164 bytes; release 1,367,420 bytes. T12 and T13 rejected under the
    no-slowdown rule. T13 saved 460 bytes, but median cycles/guest rose
    14.97 → 15.03 and 68k/guest 4.153597 → 4.155287; frame timings overlap.
    Both implementations reverted; added oracle/entry coverage and sabotage
    retained. All five restored gates pass. Pause after two consecutive rejections;
    user authorization is required before further T9 work. The earlier T7/T8
    continuation did not remove this hard stop. T9's no-candidate audit is not
    complete: remaining SP/representation and restoration tradeoffs need screening.
    Keep code size visible; T2 block duplication remains rejected for size.
    Native replacements only when the user authorizes each routine.
15. Microbenchmark 68020 costs on the A1200 model (barrel shift, `mulu.l`/
    `divu.l`, unaligned word/long, `ror.w #8` swap) to replace [arch]
    guesses in `m68k-optimisation.md`.
16. Lookup-table policy with no Fast RAM (tables are Chip reads).
24. Lockstep RAM compare (phase 6): undefined flags and FLAGS words pushed
    below SP (PUSHF, interrupt frames) differ from DOSBox by design. The host
    run masks dead stack (below SS:SP at a service or hardware interrupt, not rewritten by the
    guest); decide whether lockstep needs more (dead flag bits in pushed
    images under the remaining `annotations/flags.csv` pair).

## Amiga platform

17. AdLib/OPL music: no sibling port moved FM to Paula; choose a method.
18. Framework copy declares `getVBR`, `isLongFrame`, `isBlitterBusy`,
    `blitterWait` without bodies; supply C++ bodies before the first blit.
19. Memory budget (Chip-only vs WHDLoad expansion memory) after first
    measurements.
20. Check whether the game uses F10; choose the WHDLoad quit key.

## Release

21. Local SHA-256 table of the v2.2 originals; decide whether embedded
    tables need Revs' block scan in the release audit.
22. Establish which original data sources users can supply (disks,
    GOG/Steam re-releases if they exist) and whether conversion is needed.
