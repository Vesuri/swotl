# Open work

The single list of open work. Remove items when done; history is in git.
Phase gates: [phases.md](phases.md); contract: [translator-design.md](translator-design.md);
speed work: [speed-plan.md](speed-plan.md).

## Guest map follow-ups

9b. 29 indirect sites are static-only (`annotations/indirect.csv`):
   Static evidence is not execution coverage. Callback targets remain
   unresolved at SWOTL+137F7/+1380D/+138EB (`[5876]`), +14459 (`[56F0]`)
   and +15B8A (`[5856]`); their original initial values disable the hooks.
   Three sites are outside VGA scope. SWOTL+4F7B/+50A5 require
   `[2581]=0`: the out-of-scope
   EGA/Tandy walk (D16). VGA sets it to 1 at +3C03; all ten callers of
   setup +E50E pass its current value. FRONTEND+A90D is reached only through
   +A8FB/+A900 testing `[9936]=0` (EGA); all admitted incoming edges are
   fall-through, with no external seed. Keep these guards and static rows.
   Original flight snapshots resolve `[6A60]` → RTSVGA+44F1 and `[68EE]` →
   RTSVGA+4385 through PLINK thunks. Their setters are SWOTL+3B51 and
   +3B42; these targets do not prove the calling sites ran.
   C-runtime calls +14D4F/+14D74/+14D8D/+14DAB use DGROUP slots
   583C/5840/5848/584C. DATA initializers and their segment relocations
   resolve all four to SWOTL+150F2 (`1369:1A62`, the FP-not-loaded stub),
   also present in original snapshots. This is an initial-target fact,
   not a closed target-set or reachability proof; retain dynamic dispatch.
   The near callback at SWOTL+13754 uses slot 5638: its DATA initializer
   020B resolves to +1389B; the divide-error handler at +1373D writes 01F4,
   resolving to +13884. Neither fact proves execution of the callback.
   c26 usage exit reaches an unimplemented EMS release service (INT 67h,
   AH=45h) on the host; its original trace supplies the +1391D → +15DFE target.
9c. PLINK flag bit 13 (set on DATA only): meaning unknown; no effect seen.
9e. `tools/sweep.py` does not seed `annotations/runtime.csv` entries, so
   `callf [56EAh]` at SWOTL+140DB (`__harderr_handler`) has no
   `indirect.csv` row (it dispatches; counted in `tests/audit.csv`).

## Translator and validation

14b. Speed target remains unmet: last normal-fixture 68020 run medians (R17)
    370–430 ms/frame against ≤ 240 ms ([speed-plan.md](speed-plan.md) §7, §9). Roughly 40%
    further reduction is needed from the median 400 ms. Remaining cost is
    mostly generated guest code; unpriced translator candidates are 31 and 32
    (flag-word packing rejected, speed-plan §10). Native replacement requires
    per-routine authorization (§2.2); what to adapt from Their Finest Hour:
    [swotl-tfh-rendering-map.md](swotl-tfh-rendering-map.md), items 30–33.
    Bench acceptance for platform/layout work (D5) and
    a separate later palette window (D6) are approved; all fidelity gates and
    no slowdown remain mandatory.
14c. Differential background RAM is one repeated byte (`tests/x86_diff.py`
    `Harness`: each byte drew from a fresh generator with the same seed).
    A random background is stronger but changes every corpus case; needs
    user approval.
30. Pricing pass for 31, 32 and the TFH candidates (map: Plan 1): fresh frames
    capture (speed-plan §4) and host census on HEAD; fill the map's candidate
    table (calls, own and inclusive cycles per call) and price each item of 31
    and 32. R17's shares predate the sound work.
31. Translator candidates, unpriced (R17 lowering report, 2026-10-17); each
    one a speed-plan step:
    - BP as data: `or bp,cx` at SWOTL+D5DC is 5 68k instructions (mirror
      conversion both ways); keep BP's value in a scratch register through a
      run. `D5DA..D5DE` are 1.59% of the capture.
    - Block layout: near jumps and branches ≈ 4.4%; R16 counted 1,261,759
      uncached taken transfers (m4). Make the common successor fall through
      (D5A6's loop: 2 taken per pass, 1 possible).
    - Far call/return: `callf` 2.26% (9 instructions, 47 cycles), `retf`
      1.24%; one long push, pop and compare for CS:IP, SP-wrap guard.
    - Index reuse across single-predecessor fall-through edges (`[bx+disp]`
      is 3 instructions; `reuse.py` resets at labels).
    - Push/pop runs: one SP step per run (push 3.49%, pop 1.99%), SP-wrap guard.
    - Segment loads: `pop es` is 7 instructions, 25 cycles.
    - `repe cmpsw` (1.70%): more words per iteration.
    - From the TFH map: REP STOSB long fills (`R_0CE8B`), indexed `[bp+si]`
      copies (`R_10028..R_10044`), carry across address formation
      (`R_0C411`/`R_0C415`).
    - Lead: FLIGHT.OVL takes 20.9 cycles per guest instruction against
      SWOTL.EXE's 13.6 (13.67% of the capture): census by form.
    Not worth it: `mul` (`mulu.w` is ~26 of its 31 cycles), indexed address
    formation itself, SPAZ's calibrated OPL delay spin.
32. Cell cache re-price (D3; user 2026-10-17): decode once with the same form
    checks; a planted RET ends the run (checked at its restore sites) instead
    of invalidating; consecutive destinations written a long at a time; exact
    invalidation for every other store that can reach the region (R7b: CS
    stores, segment loads). Bound: matching is 6 of 17 loop bytes per mov cell
    (≤ 11.1M meter cycles); R7b priced −1.7%.
33. Native-routine contract (map: Native contract): emit interface for compute
    rows, register/flag/memory rules, poll-point policy (user decision, §2.9),
    Unicorn oracle on recorded entry states, sabotage. Needed before asking the
    user to authorize any routine.
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
