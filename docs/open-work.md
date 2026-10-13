# Open work

The single list of open work. Remove items when done; history is in git.
Phase gates: [phases.md](phases.md); contract: [translator-design.md](translator-design.md);
speed work: [speed-plan.md](speed-plan.md).

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

## Translator and validation

14. Coverage gaps: no reference has mouse input, so INT 33h motion and
    buttons (transcribed from DOSBox-X) are untested (needs scripted motion
    in the DOSBox-X mouse patch); the A1200 model is checked only at
    m1b-logo (it runs on wall-clock time, not replayed); table targets
    from `annotations/tables.csv` that no reference executed are checked
    by the instruction differential only; find-first gives platform files
    no DOS time/date.
14a. Display and takeover: the changed rows of each published frame are
    converted into the shown bitmap (tears; no double buffer). A double
    buffer must carry the other buffer's changed rows too (Vette: back
    buffer inherits the previous update's rectangles). No readable-state
    restore check after the takeover (L5, SL `restore_status`). Keyboard
    and mouse input through the takeover are untested by any reference
    (scripted input enters past the CIA and JOY0DAT reads).
14b. Speed: [speed-plan.md](speed-plan.md) has no planned step (§1, §7).
    Frames fixture 19–19.5 fields against the ≤ 12 bar (§9). Next is the
    user's choice: a re-profile for new translator forms, or native
    replacement, which needs per-routine authorization (§2.2). When the
    code changes: rerun `tools/align_targets.py`. Current alignment check:
    234/510 labels at their requested residue (229/497 applied pads);
    investigate `gen.pad` convergence and refresh stale alignment candidates.
    `tools/profile_report.py` roles still match the old poll point and state
    block forms.
14c. Differential background RAM is one repeated byte (`tests/x86_diff.py`
    `Harness`: each byte drew from a fresh generator with the same seed).
    A random background is stronger but changes every corpus case; needs
    user approval.
15. Microbenchmark the remaining [arch] 68020 costs on the A1200 model
    (`mulu.l`/`divu.l`, unaligned word/long); shifts, swaps, loads, stores and
    branches are measured (`m68k-optimisation.md`).
16. Lookup-table policy with no Fast RAM (tables are Chip reads).
24. Lockstep RAM compare (phase 6): undefined flags and FLAGS words pushed
    below SP (PUSHF, interrupt frames) differ from DOSBox by design. The host
    run masks dead stack (below SS:SP at a service or hardware interrupt,
    not rewritten by the guest); decide whether lockstep needs more (dead
    flag bits in pushed images under the remaining `annotations/flags.csv`
    pair).

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
