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

14b. Speed target remains unmet: frames-fixture 68020 run medians on `c21d035`
    (ZI, irq-plan I11, 2026-10-27, arm64) 300, 290 and 300 ms/frame against ≤ 240 ms
    ([speed-plan.md](speed-plan.md) §1, §9): 60 ms (20%) more to cut. Same-session
    pre-irq-plan medians 330, 330, 320 ms do not overlap, a frame-rate gain. No priced translator candidate remains;
    flag-word packing is rejected (speed-plan §10). The
    [U8 extensions](native-compute.md#contract-extensions-u8) (C4) are
    implemented; since irq-plan I9 every row is
    [poll-free](native-compute.md#loops-and-the-sync-set-rc5) (U5 and exact
    polls retired, RC5).
    N4's R48 edge ordering/merging is folded into F5's whole `BFD1` row.
    U7 paused speed work; U9 (2026-10-23) resumes it under native-plan F.
    Flyby profile (speed-plan §1 F0): EMS paging takes 25% of CPU with close
    bombers (F1 kept: c12 meter −27.72%; F2 kept: REP MOVSW by longs; F3a kept: `B017` whole,
    meter −1.4854%; F3b kept: `B52D` whole, meter −1.5848%, bench +0.025% accepted by the user as noise; F4 kept:
    FM cache and render loop, flyby `fm_field` −24.4%/call, bench +0.20% accepted by the user as noise; F5 kept:
    `BFD1` scanline loop, meter −0.0167%, flyby `BFD1` −2.1%/call; F9 kept: SPAZ
    OPL delay loops, meter −1.4996%, flyby `0CEE` −36.4%/call); ranked plan F0–F10,
    approved under U9: native-plan F.
    F5 covers the R46 priority searches and R47 expiry/advance inside the
    whole `BFD1` row.
    irq-plan I10 (user 2026-10-26) re-opened the deferred rows poll-free: `D5A6`
    prefix, `BB70`, `F290`, `FDE0`, `109D6`, `BD68`, F9 O(1), `BFD1`
    re-entries, `D69C`, `4DAE` span setup (meter −4.9158%; speed-plan §7 I10).
    Not built: `EA74` (cell-walk driver, all exits), N2 `B8A1` (no calls).
    The `4DAE` walk loop (4FD3..5032, ~10.7M of m4) joins `sprite_row` under the
    user's contract extension of 2026-10-27 (native-compute "Code writes and the
    cell walk"): meter −1.2038%, bench +0.025% (speed-plan §7 F8).
    Current meter and target costs: speed-plan §1; candidate facts and native
    source mapping: [swotl-tfh-rendering-map.md](swotl-tfh-rendering-map.md).
    Interface: [native-compute.md](native-compute.md). Native replacement needs
    per-routine authorization; the remaining-candidates authorization does not
    waive admission, pricing, exactness, validation or contract decisions.
    Bench acceptance for platform/layout work (D5) and a later palette window
    (D6) are approved. Fidelity gates and no slowdown remain mandatory except
    the specific R20/R35 tradeoffs and R36/R40/R48/F3b/F4 and irq-plan I7 (+0.117%) bench differences accepted by
    the user as noise (speed-plan §7) and D8's tiny bench regressions (speed-plan §3). Z1 leaves the target unmet; plan F is next.
    Guest native steps after irq-plan I9 are priced without polls or write
    histories ([irq-plan](irq-plan.md) RC5).
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

28. `make test-amiga AMIGA_MILESTONE=m2-choose-side` (plain fixture) ends
    `SWOTL_MILESTONE_WRONG_HANDOFF`, already at 1020874; m2 passes in
    `test-amiga-replay`.
41. `alignas(4)` on even-sized globals of 4 bytes or more, with a link audit
    (L104): not applied; m68k GCC aligns them to 2.
45. Hardware-sprite pointer ([pointer-plan.md](pointer-plan.md), user 2026-10-26): the
    guest's software pointer masked out of the presented frame, an AGA sprite at the guest
    position plus lead written at the vertical blank, on every pointer screen incl. the film
    room; no toggle; the sprite toggles only on a state held for a field (user 2026-10-27).
    Authorized: observe-only HLE row at tracker exit `0320:1011`. Two sprites, `F9` as the
    black (user 2026-10-27). P1–P5 done; next: P6.

## Release

42. Manual pass of the Installer requesters (wording, layout) and one install
    from real ACC floppy images on an A1200 (the FS-UAE test scripts every answer).
