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
   The engine sites need a single-engine sortie with an engine hit
   (indirect-coverage.md). Isolated original-code formatting tests await approval;
   they must not be presented as gameplay execution coverage.
9c. PLINK flag bit 13 (set on DATA only): meaning unknown; no effect seen.
9e. `tools/sweep.py` does not seed `annotations/runtime.csv` entries, so
   `callf [56EAh]` at SWOTL+140DB (`__harderr_handler`) has no
   `indirect.csv` row (it dispatches; counted in `tests/audit.csv`).

## Translator and validation

14b. Optional speed work: ≤ 240 ms/frame is a guide, not a target (user 2026-10-28);
    the ReadMe recommends a 68030 or better. Left: F10 (present/C2P on `3B9A`'s spans,
    1.0–1.5%), unpriced `FLIGHT+1538C`, `FLIGHT+0A8D2` and F2's `cmpsw` searches
    ([native-plan.md](native-plan.md) §F). Frames-fixture 68020 run medians on `c21d035`
    (ZI, irq-plan I11, 2026-10-27, arm64) 300, 290 and 300 ms/frame
    ([speed-plan.md](speed-plan.md) §1, §9). Same-session
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
    the user as noise (speed-plan §7) and D8's tiny bench regressions (speed-plan §3).
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

## User report (A1200, 68060, 2026-10-29)

42. Speed and mouse: caches and per-request mouse counters with the field
    cap are in; the cap above 50 fps is proven only by
    `tests/test_display_queue.py`. Confirm on the tester's 68060. If the
    mouse still feels wrong, the user picks a sensitivity setting or
    frame-time scaling.
43. Joystick: digital and analog modes in port 2 are checked by register
    and game-code tests only. Confirm both with real sticks (analog axis
    polarity and range, the startup calibration).
44. NTSC: window, CIA timer, Paula clock, FM and TFH field rates and key
    repeat follow graphics' NTSC flag (checked in FS-UAE). Confirm the
    centring on the tester's NTSC machine.
45. EGA for non-AGA Amigas: out of scope (VGA only); awaiting the user's
    decision to decline.
