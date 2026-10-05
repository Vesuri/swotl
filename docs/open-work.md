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
14a. Display: c2p into the shown screen bitmap every 5th vertical blank
    (tears; no double buffer) on an Intuition screen while the OS serves
    dos.library; D9's framework (copper) display needs file I/O that
    survives the takeover.
14b. Speed (68020 + Fast, demo flight, first profile; plan doc pending).
    Reference: one drawn frame per 9 PIT ticks (~36 ms, ~28 fps; host-run
    census of m4-demo-frames). 68020 model: demo flight starts at frame
    4438; a 100-field window had 4 `FLT_15E82` calls and no mouse poll or
    RTSVGA update (rendered-frame rate not yet measured). Shares: c2p ~61%
    (~870K cycles per present, every 5th field, whole screen), generated
    code 20% (~13 cycles per guest instruction), runtime 10% (interrupt
    delivery ~5.5%), Kickstart 7%. All A0000h writes in m2, m4, m6, m7 come
    from ~13 RTSVGA instructions; RTSVGA already copies only changed words
    (m4: ~300 bytes, median 6 rows per frame), so dirty rows at those
    writers would remove most c2p work. m5 census not yet run.
15. Microbenchmark 68020 costs on the A1200 model (barrel shift, `mulu.l`/
    `divu.l`, unaligned word/long, `ror.w #8` swap) to replace [arch]
    guesses in `m68k-optimisation.md`.
16. Lookup-table policy with no Fast RAM (tables are Chip reads).
24. Lockstep RAM compare (phase 6): undefined flags and FLAGS words pushed
    below SP (PUSHF, interrupt frames) differ from DOSBox by design. The host
    run masks dead stack (below SS:SP at a service or hardware interrupt, not rewritten by the
    guest); decide whether lockstep needs more (dead flag bits in pushed
    images under the remaining `annotations/flags.csv` pair).
25. `Swotl.exe` is 3.7 MB: elf2hunk keeps the symbols of ~140K generated
    labels (needed by GDB fixtures); strip for release.

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
