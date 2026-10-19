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

14b. Speed target remains unmet: frames-fixture 68020 run medians on R30
    (2026-10-19) 340, 340 and 340 ms/frame against ≤ 240 ms ([speed-plan.md](speed-plan.md)
    §1, §9). Roughly 29% further reduction is needed from 340 ms; parent intervals overlap. Remaining
    cost is mostly generated guest code; priced translator candidates are 31,
    FM synthesis is 34 (flag-word packing rejected, speed-plan §10). Native replacement
    requires per-routine authorization (§2.2); what to adapt from Their Finest Hour:
    [swotl-tfh-rendering-map.md](swotl-tfh-rendering-map.md), items 31, 33.
    Bench acceptance for platform/layout work (D5) and
    a separate later palette window (D6) are approved; all fidelity gates and
    no slowdown remain mandatory, except the explicitly accepted R20 opening-bench
    tradeoff (speed-plan §7).
14c. Differential background RAM is one repeated byte (`tests/x86_diff.py`
    `Harness`: each byte drew from a fresh generator with the same seed).
    A random background is stronger but changes every corpus case; needs
    user approval.
36. `tools/lowering_cost.py` sums helper entries into `guest_exec` (walk,
    IRQ and other suffixed labels). Keep their cycles/instructions, but count
    guest entries only at unsuffixed/`_bp` instruction labels, as
    `profile_report.py` does. R22's first capture: 2,317,066 reported versus
    2,290,967 guest entries. Zero-code jump aliases also hide executed guest
    instructions: rejected R23's m4 count drops by exactly the four removed jumps' 68,070
    entries. Recover semantic counts before comparing per-guest ratios across
    such layouts. Meter totals and alias-aware fixed-instruction A/B are unaffected.
37. `tools/cost_meter.py` flags a range as a cached loop when any backward branch
    within `LOOP` bytes closes it, executed or not: an R27 outlined range ends in a
    `bra` back to its target that never closes a loop, so R27's meter Δ is
    −0.6278%, −0.7903% counting only taken back edges (FS-UAE agreed in sign).
    Decide the definition (and recalibrate) at the next re-profile.
38. `make gates`: host-all's c52-campaign-loss passed the R26 gates but ran past its
    2,400 s wall-clock limit (`t-cov-%`, `host_run.py --timeout`) in the R27 and R28
    gates (load average up to 57: sabotage, host-all and FS-UAE at once, plus
    Spotlight), stopped short of the reference's services with no fault; alone 783 s
    and 853 s, exact. Decide: a longer limit for long scenarios, or fewer parallel jobs.
31. Translator candidates, repriced 2026-10-19 on the `a1df937` m4 meter (183,699,737
    model cycles) unless noted, in price order; each one a speed-plan step (R24 REP
    STOSW, R25 BP as data, R26 REPE CMPSW, R27 cold branch sides, R28 carry in X, R29
    far push and R30 repeated segment loads done). Evidence: `tmp/item31b/`.
    - Block layout (audit on `a1df937`): free-placement bound −5.31M, 22.7% of the
      taken weight `dbcc` back edges. Left: `jcc` over a lone `jmp` (the 8086 long
      conditional) as one inverted branch, static, −0.15M (118 executed sites); the
      block differential must follow the fused jump across the zero-code `jmp`.
      Bench acceptance (D5). R23 loop-tail placement rejected (speed-plan §10).
    - Far return (R29 pushes CS:IP as one long): `retf` as one `move.l` pop (−6 bytes,
      −1 read) and the return check as one `cmp.l`, the rest of the 5ecdf79 price of
      −1.75M for both (−1.52M if misaligned longs cost two accesses: long address ≡
      2 mod 4 at 57% of sampled `retf`). A wrapped pop needs its own `bvs.w` guard (a
      compare can match by chance), and runtime consumers of a far return read CS from
      d6: a return-protocol change, which needs user approval.
    - Push/pop runs, one `bvs.w` guard per run: −0.16M (−0.07%).
    Not worth it: index reuse across leaders (all predecessors agreeing,
    single-jump leaders, poll labels: −0.02M); the TFH map's forms (`R_0CE8B` never
    runs in m4 or the captures; `R_10028..R_10044`, `R_0C411`/`R_0C415` ≤ 0.02% each);
    `mul` (`mulu.w` is ~26 of its 31 cycles), indexed address formation itself,
    SPAZ's calibrated OPL delay spin. FLIGHT.OVL's cost per guest instruction is no
    lead: counting R6 copies it is 9.2 against SWOTL.EXE's 12.6 in that capture.
33. Native-routine contract (map: Native contract): emit interface for compute
    rows, register/flag/memory rules, poll-point policy (user decision, §2.9),
    Unicorn oracle on recorded entry states, sabotage. Needed before asking the
    user to authorize any routine.
34. FM synthesis is 8.15–9.71% of the three `5ecdf79` frames captures and 8.11% of
    R20's first (`loop_for`, `fm_field`, `eg_advance`); R17's whole runtime/platform
    share was 5.96%. Platform layer, outside the host meter: price and plan under D5
    with the sound gates.
16. Lookup-table policy with no Fast RAM (tables are Chip reads).
24. Lockstep RAM compare (phase 6): undefined flags and FLAGS words pushed
    below SP (PUSHF, interrupt frames) differ from DOSBox by design. The host
    run masks dead stack (below SS:SP at a service or hardware interrupt,
    not rewritten by the guest); decide whether lockstep needs more (dead
    flag bits in pushed images under the remaining `annotations/flags.csv`
    pair).

## Amiga platform

18. Framework copy declares `getVBR`, `isLongFrame`, `isBlitterBusy`,
    `blitterWait` without bodies; supply C++ bodies before the first blit.
19. Memory budget (Chip-only vs WHDLoad expansion memory) after first
    measurements; sound takes 64 KB Chip (FM loops) plus 107,298 bytes in TFH
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

## Release

21. Local SHA-256 table of the v2.2 originals; decide whether embedded
    tables need Revs' block scan in the release audit.
22. Establish which original data sources users can supply (disks,
    GOG/Steam re-releases if they exist) and whether conversion is needed;
    TFH mode: the installer copies the user's TFH `sfx.rsc`.
