# Open work

The single list of open work. Remove items when done; history is in git.
Phase gates: [phases.md](phases.md); contract: [translator-design.md](translator-design.md);
speed work: [speed-plan.md](speed-plan.md).

## Guest map follow-ups

9b. Paused at user request. 17 indirect sites remain static-only (`annotations/indirect.csv`).
   [Coverage boundaries](indirect-coverage.md) document 13 video/default-runtime
   exclusions with fail-loud dispatch retained. The other 4 need VGA execution
   coverage: engine/cockpit damage (2), formatting (2). Do not infer unreachability from missed fixtures.
   c26 usage exit also needs exact EMS release (AH=45h), including retained
   mappings and backing-page aliases; clearing the handle alone is insufficient.
   EMS implementation is explicitly deferred by the user.
   Before resuming coverage, resolve pending approvals for `equals`/`minus`
   recorder keys (damage scenarios) and isolated original-code formatting tests.
   Such tests must not be presented as gameplay execution coverage.
9c. PLINK flag bit 13 (set on DATA only): meaning unknown; no effect seen.
9e. `tools/sweep.py` does not seed `annotations/runtime.csv` entries, so
   `callf [56EAh]` at SWOTL+140DB (`__harderr_handler`) has no
   `indirect.csv` row (it dispatches; counted in `tests/audit.csv`).

## Translator and validation

14b. Speed target remains unmet: frames-fixture 68020 run medians on `7a5087a`
    (N3, 2026-10-21) 370, 350 and 340 ms/frame against ≤ 240 ms ([speed-plan.md](speed-plan.md)
    §1, §9). The middle run needs 110 ms (31.4%) less; no controlled frame-rate
    gain claimed against saved A3. No priced translator candidate remains;
    flag-word packing is rejected (speed-plan §10). The U5
    [poll contract](native-compute.md#poll-contract-u5) (C3) and the
    [U8 extensions](native-compute.md#contract-extensions-u8) (C4) are
    implemented. Remaining: N2 `B8A1`; N4 `BB70`, `109D6`, `F290`, `4DAE`,
    `BD68`, `D69C`, `FDE0`, `BFD1`. All nine authorized 2026-10-22.
    The other N4 candidates call other overlays, DOS or
    unresolved/shared code (native-plan C). Other admitted routines still need a
    native price (S2); the other candidates need admitted scopes.
    B8A1 deferred by the user (no calls in m4/c13/c27); BB70 deferred by the
    user 2026-10-22 (sync-preserving repair has no positive price). Both remain
    generated. Next: 109D6 scope/admission and price, adapting `scen_verts` and
    `clr_scenery`; multiple proved continuation endpoints await user approval
    to keep transform/projection calls generated. S1–S9 still applies.
    Current meter/target costs: speed-plan §1; candidate facts: the rendering map.
    Native replacement
    requires per-routine authorization (§2.2); what to adapt from Their Finest Hour:
    [swotl-tfh-rendering-map.md](swotl-tfh-rendering-map.md); interface and validation:
    [native-compute.md](native-compute.md).
    Bench acceptance for platform/layout work (D5) and
    a separate later palette window (D6) are approved; all fidelity gates and
    no slowdown remain mandatory, except the explicitly accepted R20/R35 opening-bench
    tradeoffs and R36’s specific bench difference accepted as noise (speed-plan §7).
14c. Differential background RAM is one repeated byte (`tests/x86_diff.py`
    `Harness`: each byte drew from a fresh generator with the same seed).
    A random background is stronger but changes every corpus case; needs
    user approval.
24. Lockstep RAM compare (phase 6): undefined flags and FLAGS words pushed
    below SP (PUSHF, interrupt frames) differ from DOSBox by design. The host
    run masks dead stack (below SS:SP at a service or hardware interrupt,
    not rewritten by the guest); decide whether lockstep needs more (dead
    flag bits in pushed images under the remaining `annotations/flags.csv`
    pair).

## Amiga platform

18. Framework copy declares `getVBR`, `isLongFrame`, `isBlitterBusy`,
    `blitterWait` without bodies; supply C++ bodies before the first blit.
19. WHDLoad memory budget: Chip-only is impossible (D15: code and guest RAM
    exceed 2 MiB), so the slave needs expansion memory; size it from
    measurements. Sound takes 64 KB Chip (FM loops) plus 107,298 bytes in TFH
    mode. A1200/68020, 8 MiB Fast: TFH free Chip 1,722,072 bytes, largest
    block 1,721,968 (1,500-field soak, 2026-10-15).
20. Check whether the game uses F10; choose the WHDLoad quit key.
28. `make test-amiga AMIGA_MILESTONE=m2-choose-side` (plain fixture) ends
    `SWOTL_MILESTONE_WRONG_HANDOFF`, already at 1020874; m2 passes in
    `test-amiga-replay`.
29. Real A1200/full 68040 with MMU active: supplied preinstalled TFH archive
    crashes during startup with a Line F emulator exception. Fault PC/opcode
    and Guru number are unavailable. Reproduce and fix against evidence.
    Build flags specify 68020 and soft float; cause is not yet established.
39. Workbench start (L84): without a CLI, take the WBStartup message before
    opening dos.library and reply it last under `Forbid`; return 20 when a start
    fails (`src/main.cpp` returns 0; the gcc8 `_start` does neither).
40. LED filter (L69): left as booted (on, ~5 kHz low-pass); the original AdLib
    output has none. Turn it off at takeover, restore it on exit.
41. `alignas(4)` on even-sized globals of 4 bytes or more, with a link audit
    (L104): not applied; m68k GCC aligns them to 2.

## Release

21. Local SHA-256 table of the v2.2 originals; decide whether embedded
    tables need Revs' block scan in the release audit.
22. Establish which original data sources users can supply (disks,
    GOG/Steam re-releases if they exist) and whether conversion is needed;
    TFH mode: the installer copies the user's TFH `sfx.rsc`.
