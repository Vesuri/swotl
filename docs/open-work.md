# Open work

The single list of open work. Remove items when done; history is in git.
Step plans: [plan-reference-map.md](plan-reference-map.md) (phases 1–2),
[translator-design.md](translator-design.md) (phases 3–5, decisions D1–D16).

## Guest map follow-ups

9a. Cross-reference TFH Amiga `BOB` (Aztec C, same source family) in Ghidra
   for routine naming and `.PAC`/`.GOB` formats; evidence only.
9b. 215 indirect sites are static-only (no traced target,
   `annotations/indirect.csv`), mostly `lcall [mem]` through DGROUP
   pointers (203); FRONTEND has 6.7 KB of unreached code-like residue. Add
   coverage scripts (campaign play, other aircraft, film load/save) where a
   generated path needs them.
9c. PLINK flag bit 13 (set on DATA only): meaning unknown; no effect seen.

## Phases 3–4 — translator

11. Pick translator language and layout (`translator/`, `annotations/`);
    add the G1 hash check and G2 lint before any generated code exists.
12. Build the x86 flag/shift/segment-wrap differential corpus on Unicorn
    (Python binding missing; Slicks used the C library).
13. Set up the host 68k oracle (Unicorn 68020, as Slicks).
14. Decide RET mapping: guest return addresses on the byte-exact guest stack
    vs native return.
15. Microbenchmark 68020 costs on the A1200 model (barrel shift, `mulu.l`/
    `divu.l`, unaligned word/long, byte-swap) to replace [arch] guesses in
    `m68k-optimisation.md`.
16. Lookup-table policy with no Fast RAM (tables are Chip reads).

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
