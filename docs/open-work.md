# Open work

The single list of open work. Remove items when done; history is in git.
Step plans: [plan-reference-map.md](plan-reference-map.md) (phases 1–2),
[translator-design.md](translator-design.md) (phases 3–5, decisions D1–D16).

## Phase 2 — static/live map

6b. D16 evidence: classify the self-modified executed bytes that
   `tools/load_image.py` lists by writer (root `+4FFC`, `+52DA`, `+8FD5`,
   `+9030`, `+E5FD..+E626`): patched code vs code-segment variables.
7. Reverse the PLINK overlay manager (thunks and table:
   `source-inventory.md`): call path to non-resident overlays, return
   stack, residency rules, the table's last word; which overlays coexist
   (FLIGHT's range covers CAMPAIGN/NOTCAMP and REPLAY/PANEL).
8. Recursive-descent sweep of root and overlays; settle int 21h/67h/33h and
   port inventories (`SFXA`/`SPAZ` contain `CD 21` byte pairs).
9. Identify the compiler runtime (Microsoft C 5.x per strings) and calling
   convention; check whether the MS C floating-point emulator is linked
   (INT 34h–3Dh fixups) and used.
9a. Cross-reference TFH Amiga `BOB` (Aztec C, same source family) in Ghidra
   for routine naming and `.PAC`/`.GOB` formats; evidence only.

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
