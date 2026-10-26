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

14b. Speed target remains unmet: frames-fixture 68020 run medians on `130bd18`
    (ZF3, 2026-10-24, arm64) 330, 300 and 300 ms/frame against ≤ 240 ms ([speed-plan.md](speed-plan.md)
    §1, §9). The middle run needs 60 ms (20%) less; same-session pre-F3
    medians 360, 350, 360 ms do not overlap, so F3+F4 is a frame-rate gain. No priced translator candidate remains;
    flag-word packing is rejected (speed-plan §10). The U5
    [poll contract](native-compute.md#poll-contract-u5) (C3) and the
    [U8 extensions](native-compute.md#contract-extensions-u8) (C4) are
    implemented, as is the exact-poll contract used by R42's sprite packet loop
    and R44's line pixel loops.
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
    Deferred by the user: F3's `D5A6` prefix (2026-10-24; poll-set change and
    reference re-recording for ~0.5% of the flyby), N2 `B8A1` (no calls in m4/c13/c27), N4 `BB70`
    (sync-preserving design has no positive price), `109D6` vertex loops
    (initial guarded adapter exceeded its budget), `F290` (narrow
    tile-selection adapter has no positive price, R41), `BD68` (edge-loop
    address-reuse design has no positive price, R43), and `FDE0` (cache-loop
    design has no positive price, R45; deferred 2026-10-23).
    These remain generated.
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
    histories (open-work 43, RC5).
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
43. Interrupt delivery without polling ([irq-plan.md](irq-plan.md), user
    2026-10-24 with its rule changes): SPAZ's IRQ0 handler from the CIA-B
    interrupt, keyboard and mouse at the vertical blank, sync points for
    lockstep, native rows poll-free (U3/U5 retire). I1 measured, I2 proved,
    I3 monitored, I4 private-stack entry, I5 field task, I6 asynchronous IRQ0, I7
    keyboard at the vertical blank (irq-plan Facts). Next: I8 (sync points); F10
    skipped by the user (2026-10-25).
    The deferred natives it unblocks (D5A6 prefix, BB70, F9 O(1), FDE0, BD68,
    F290, 109D6; exact-poll rows rebuilt) are done at its I10.

## Amiga platform

28. `make test-amiga AMIGA_MILESTONE=m2-choose-side` (plain fixture) ends
    `SWOTL_MILESTONE_WRONG_HANDOFF`, already at 1020874; m2 passes in
    `test-amiga-replay`.
39. Workbench start (L84): without a CLI, take the WBStartup message before
    opening dos.library and reply it last under `Forbid`; return 20 when a start
    fails (`src/main.cpp` returns 0; the gcc8 `_start` does neither). Read the
    options from the icon's tooltypes (user 2026-10-25): icon.library
    `GetDiskObject` on the WBArg's lock and name, `FindToolType` for the same
    keywords as item 44's template, `FreeDiskObject`.
40. LED filter (L69): left as booted (on, ~5 kHz low-pass); the original AdLib
    output has none. Turn it off at takeover, restore it on exit.
41. `alignas(4)` on even-sized globals of 4 bytes or more, with a link audit
    (L104): not applied; m68k GCC aligns them to 2.
44. Arguments through dos.library `ReadArgs` (user 2026-10-25): the hand scan of
    `GetArgStr()` in `amiga_guest_open` (`amiga_platform.c`) is case-sensitive, so
    `swotl tfh` silently plays FM. Template for TFH, MUSIC, KEYS=, BENCH; case-
    insensitive, `?` help, bad arguments fail with the DOS error. The WHDLoad slave's
    `SetArgStr` line must still parse (`RDA_Source` from `GetArgStr()`, or check that
    ReadArgs sees it). Refs: `~/.local/share/amiga/ndk/Autodocs/dos.doc` (ReadArgs,
    FreeArgs, RDArgs), `adcd21/Reference/Amiga_Mail_Vol2/II-27/readargs.c`. Checks:
    fixtures that pass KEYS/MUSIC/BENCH, `test-whdload` FM and TFH, lower-case `tfh`.

45. Hardware-sprite pointer ([pointer-plan.md](pointer-plan.md), user 2026-10-26): the
    guest's software pointer masked out of the presented frame, an AGA sprite at the guest
    position plus lead written at the vertical blank, on every pointer screen incl. the film
    room; no toggle. Authorized: observe-only HLE row at tracker exit `0320:1011`. Next: P1.

## Release

42. Manual pass of the Installer requesters (wording, layout) and one install
    from real ACC floppy images on an A1200 (the FS-UAE test scripts every answer).
