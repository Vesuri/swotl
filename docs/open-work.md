# Open work

The single list of open work. Remove items when done; history is in git.
Phase gates: [phases.md](phases.md); contract: [translator-design.md](translator-design.md);
speed work: [speed-plan.md](speed-plan.md).

## Guest map follow-ups

9a. Cross-reference TFH Amiga `BOB` (Aztec C, same source family) in Ghidra
   for routine naming and `.PAC`/`.GOB` formats; evidence only.
9b. 206 indirect sites are static-only (no traced target,
   `annotations/indirect.csv`). 186 are proved switch tables or `lcall`
   through a DGROUP slot whose other sites trace one PLINK thunk; 20 have
   neither: C runtime exit/error paths (SWOTL+13754..+15B8A, 11), `call dx`
   +4F7B/+50A5, FLIGHT+17DB4 `[6A60]`, FRONTEND+1958/+1B54 `[28EC]`,
   NOTCAMP+3DBC `[5FCE]`/+487C `[6104]`, PANEL+3159/+3215 `[68EE]`. Not
   scripted yet: campaign flight operations, film load (mouse pick in the
   list), custom mission creation, other German/US aircraft.
9c. PLINK flag bit 13 (set on DATA only): meaning unknown; no effect seen.
9e. `tools/sweep.py` does not seed `annotations/runtime.csv` entries, so
   `callf [56EAh]` at SWOTL+140DB (`__harderr_handler`) has no
   `indirect.csv` row (it dispatches; counted in `tests/audit.csv`).

## Translator and validation

14b. Speed target remains unmet: last normal-fixture 68020 run medians (R17)
    370–430 ms/frame against ≤ 240 ms ([speed-plan.md](speed-plan.md) §7, §9). Roughly 40%
    further reduction is needed from the median 400 ms. Remaining cost is
    mostly generated guest code; no further exact translator step is known
    (flag-word packing rejected, speed-plan §10). Native replacement requires
    per-routine authorization (§2.2). Bench acceptance for platform/layout work (D5) and
    a separate later palette window (D6) are approved; all fidelity gates and
    no slowdown remain mandatory.
14c. Differential background RAM is one repeated byte (`tests/x86_diff.py`
    `Harness`: each byte drew from a fresh generator with the same seed).
    A random background is stronger but changes every corpus case; needs
    user approval.
16. Lookup-table policy with no Fast RAM (tables are Chip reads).
24. Lockstep RAM compare (phase 6): undefined flags and FLAGS words pushed
    below SP (PUSHF, interrupt frames) differ from DOSBox by design. The host
    run masks dead stack (below SS:SP at a service or hardware interrupt,
    not rewritten by the guest); decide whether lockstep needs more (dead
    flag bits in pushed images under the remaining `annotations/flags.csv`
    pair).

26. Trap flag (user, 2026-10-14): translated code does not raise interrupt 1
    with TF set (Unicorn does). Establish that the game never sets TF
    (static: POPF/IRET sources; DOSBox-X references), then make TF = 1 stop
    loudly at POPF/IRET; TF = 1 corpus cases expect the stop. Single-step
    delivery is built only if a trace shows TF = 1. Exploratory TF cases:
    `tmp/item14b-agent/r19-deferred-coverage.patch`.

27. Guest-created file metadata (c11, c14 fail the host run; not in
    `HOST_COVERAGE`): FindFirst on a file the game wrote fills the DTA time
    from the platform's file time (DOSBox: its DOS clock at close) and keeps
    the runtime's cursor at `+0Dh` (DOSBox: its search slot, 0 in both
    references, unexplained by its source). The reference DOS date is the
    host's, so those references reproduce only on the recording day. The
    game is not seen to read these bytes. Fix (pin the date in the tracer,
    stamp on close, DOSBox slot) or mask (user approval).

## Amiga platform

17. Sound: effects first, music skipped; steps in [sound-plan.md](sound-plan.md).
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
