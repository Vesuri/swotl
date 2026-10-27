# Amiga lessons

The maintained, merged version of these rules is AmigaXDev `docs/reference/amiga-hardware.md`
(with `docs/reference/port-toolchain.md` for §L); add or correct generic lessons there. This
numbered register stays because SWOTL's code and [amiga-arch.md](amiga-arch.md) cite its items
by number (L2, L8, …).

Target-side rules from the sibling ports. Format: **rule** — why — *provenance*.
Abbreviations: SL Slicks (DOS→A1200 AGA), PK Pokeri (68008→Amiga), RoF Rescue on
Fractalus (Atari→A500), RV Revs (BBC→A500), VT Vette (Mac→A1200). Paths are relative
to each project; `git:<hash>` = deleted file, read with `git show <hash>^:<path>`.
**[000]** marks numbers measured on a 68000/OCS machine: re-measure before relying on
them here. Structure for this port: [amiga-arch.md](amiga-arch.md). Elsewhere:
[toolchain.md](toolchain.md), [headless-fsuae.md](headless-fsuae.md),
[perf-method.md](perf-method.md),
[m68k-optimisation.md](m68k-optimisation.md), [whdload.md](whdload.md),
[release.md](release.md), [translation-lessons.md](translation-lessons.md).

## A. OS takeover and return

1. **Take the display over; no OS screen.** — per-line copper work and direct Paula need
   it; an OS screen re-inserts the system list after every `WaitTOF`. — *RoF
   `amiga/ARCH.md`; RV `docs/amiga-arch.md`*
2. **Takeover order:** save `ActiView`, `GfxBase->copinit`, DMACONR, INTENAR →
   `LoadView(0)`, `WaitTOF`×2 → INTENA/INTREQ `$7fff`, all DMA off → swap the VERTB vector
   under `Disable` → install copper (immediate) → DMA MASTER|COPPER|RASTER → INTENA
   INTEN|VERTB|PORTS → `Forbid`. — shipped and restore-checked. — *SL
   `src/platform/amiga/amiga_platform.cpp` `slicks_amiga_platform_begin`*
3. **Install your copper list with display DMA off; enable copper DMA last.** — otherwise
   an OS-copper frame intermittently resets your one-time register writes. — *RV
   `docs/amiga-arch.md`*
4. **Return order:** stop own INTENA/DMA → COP1LC = `copinit` + COPJMP1 → BPLCON3 `$0c00`
   → copper DMA on → drain blitter → restore VERTB vector → clear all, then restore the
   exact saved DMACON/INTENA → `Permit` → `LoadView(saved)` + `WaitTOF`×2. Free display
   memory only after DMA stops. — `LoadView` restores neither COP1LC nor DMA; freeing
   before disabling DMA returned to an all-white Workbench. — *SL `amiga_platform.cpp`
   `slicks_amiga_platform_end`; VT `src/platform/amiga/PlatformAmiga.cpp`;
   git:56032f5 VT `docs/amiga-arch.md`*
5. **Prove the return with readable state** (ActiView, vector triple, DMACONR, INTENAR;
   COP1LC is write-only). — catches partial restores cheaply. — *SL
   `slicks_amiga_platform_restore_status`; this repo `make test-amiga-restore`*
6. **`Forbid` for the whole run; nothing inside may `Wait`.** Library opens/closes and
   `WaitTOF` pairs stay outside. — no scheduler is needed; a `Wait` under `Forbid` breaks
   it. — *RV `docs/amiga-arch.md`*
7. **For disk I/O, hand back interrupts, not the display:** restore the VERTB vector,
   saved INTENA, DISK|BLITTER DMA and the keyboard ICR, `Permit`; keep `LoadView(NULL)`
   and your copper/raster DMA; reverse on return. `WaitTOF` works inside the window. —
   lets the loading panel stay on screen. — *SL `slicks_amiga_platform_begin_io`/`end_io`,
   `docs/rendering.md`*
8. **Require AGA via `GfxBase->ChipRevBits0 & GFXF_AA_LISA` and set
   `AmigaHardware::hasAGAChipSet`.** The AA bits are set only after `SetPatch` on KS 3.1,
   so every boot path runs `SetPatch` first. — otherwise an A1200 silently takes the OCS
   path. — *SL `amiga_platform.cpp`, `docs/toolchain.md`; git:7c298658 RoF
   `docs/amiga-spike.md` #4*
9. **Leave sprite DMA off unless sprites are used; if used, point idle channels at an
   empty sprite.** — SL runs with COPPER|RASTER only; VT parks unused channels. — *SL
   `amiga_platform.cpp`; VT `docs/amiga-arch.md`*

## B. Interrupts

10. **Take over `SysBase->IntVects[INTB_VERTB]` (under `Disable`) instead of
    `AddIntServer`.** — drops graphics/gameport/timer servers off the vblank: ~780 µs per
    frame, 3.9% of wall clock [000]. RoF's `amiga/ARCH.md` still describes
    `AddIntServer`; RV, VT and SL replaced it. Keep an `AddIntServer` A/B build for
    bisecting. — *RV `docs/amiga-arch.md`, `docs/amiga-lessons.md`; SL `amiga_platform.cpp`*
11. **A vector handler clears `INTREQ` VERTB itself.** — Exec's chain walker did; missing it
    re-triggers level 3 forever. — *RV `docs/amiga-lessons.md`; SL
    `vertical_blank_handler`*
12. **`WaitTOF` is dead while the vector is yours;** wait on your own vblank counter and
    restore the vector before the closing `LoadView`/`WaitTOF`. — WaitTOF is signalled by
    graphics.library's VERTB server. — *RV `docs/amiga-lessons.md`*
13. **Leave PORTS (level 2) on Exec's chain; hook the keyboard through `ciaa.resource`.** —
    starving FS-UAE's host-filesystem trap server resets the emulated machine; leaving it
    costs ~0.3% [000]. — *RV `docs/amiga-lessons.md` (from RoF)*
14. **Mask INTF_BLIT during takeover unless you use the framework blitter queue; restore
    INTENA verbatim.** — each blit-done was a useless graphics.library dispatch, ~6 × 52 µs
    per render iteration [000]; the queue, if used, needs BLIT to drain. — *RV
    `docs/amiga-lessons.md`; PK `docs/architecture.md`*
15. **Publish objects to the ISR only after they are fully built; guard with a flag set
    on the last line of `initialize()`, not a non-null pointer.** — the VBI fired during
    construction, installed a half-built copper list and latched it: a black screen whose
    every probe read healthy. — *RV `docs/amiga-lessons.md`; VT `PlatformAmiga.cpp`*
16. **VBI work fits well under one frame; bracket it with VPOSR/VHPOSR.** — overrun silently
    drops a displayed frame (RoF: a 19.7 ms decode in the VBI [000]). — *RV
    `docs/amiga-lessons.md`*
17. **Copper/bitplane/sprite publication runs first in the VBI, then input, then audio.** —
    a Paula restart busy-waits and must not delay a beam-critical write. — *RV
    `docs/amiga-arch.md`; VT `docs/amiga-arch.md`*
18. **Never run the original's timer-driven game body inside the Amiga ISR.** The VBI
    counts ticks; the main loop drains them at points where the engine is provably not
    drawing. — RV's body-in-ISR moved rows under the decode (238 bad frames → 0). VT runs
    original VBL callbacks only at safe trap-return boundaries. — *RV `docs/amiga-arch.md`;
    VT `docs/amiga-arch.md`* SWOTL exception (user 2026-10-24): SPAZ's IRQ0 handler, whose
    footprint is disjoint from drawing state ([irq-plan](irq-plan.md) RC1), in the CIA-B
    interrupt since I6 ([amiga-arch.md](amiga-arch.md#interrupts)).
19. **Derive PC time from the beam:** `vblank_count*313 + line`, re-read until count and
    VPOSR agree; treat a read just after line 0 that looks backwards as zero elapsed. BIOS
    ticks: accumulate 1193182 per VBI, tick at 65536×50. — exact for the 15625 Hz line rate.
    — *SL `docs/frame-pacing.md`, `slicks_amiga_platform_raster_time`*
20. **Main-loop/ISR shared state under nested `Disable`/`Enable`; no ISR allocates.** —
    *SL `docs/audio.md`; PK `docs/architecture.md`*
21. **Under WHDLoad the VBR is moved; never assume vectors at 0.** Exec `IntVects` takeover
    is unaffected. — *PK `amiga/ARCH.md`, `docs/architecture.md`*

## C. Copper

22. **The Slicks framework lineage does not NOP-fill new lists; an all-zero word halts the
    copper.** `MEMF_CLEAR` Chip RAM is all halts, so every slot up to the terminator must
    be written (SL checks the built length). RV/VT's constructor prefills `$01FE0000`. —
    symptom: the whole screen uses the top region's parameters. — *RV
    `docs/amiga-lessons.md`; SL `framework/CopperList.cpp`, `build_copper`*
23. **Slot 0 (`WAIT 16,0`) and the last slot (`WAIT 255,254`) belong to the constructor;
    builders start at 1.** A variable-length list terminates right after its content. —
    stale tails of double-buffered lists flicker. — *RV `docs/amiga-lessons.md`*
24. **Colour MOVEs take effect immediately.** Split at `WAIT(R-1,$E0)`, pointers first, then
    colours; a colour that must hit the first pixel needs its own slot before the
    pointers. One WAIT per line; drop zero-height bands. — *RV `docs/amiga-lessons.md`*
25. **Never poke a live list's BPLxPT mid-frame; swap pointers in the VBI.** Colour-only
    mid-frame pokes are tolerable. — torn hi/lo pointer garbages a frame. — *RV
    `docs/amiga-lessons.md`*
26. **"In the VBI" is not "in the blank": stamp the beam line at every publication and keep
    a standing check at 0 late.** — a rewritten WAIT behind the beam skips every later
    band; frame-boundary dumps cannot see it (12 clean captures preceded a broken screen).
    — *RV `docs/amiga-lessons.md`, `amiga/beam_watch.gdb`; git:56032f5 VT
    `docs/amiga-lessons.md`*
27. **Double-buffered lists: build the inactive one, then COP1LC + COPJMP1 in the VBI; never
    edit the active list; drop poke-on-change caches.** An immediate COPJMP1 is safe only at
    vblank. — VT measured all handoffs at lines 1–3 on 68020/030/040. — *git:56032f5 VT
    `docs/amiga-lessons.md`; RV `docs/amiga-lessons.md`*
28. **Alternative handoff: write COP1LC without COPJMP1 from the main thread in safe lines,
    retire the old buffer at the next VBI.** — a late interrupt can never restart the list
    mid-screen. — *PK `docs/architecture.md`*
29. **Re-run deadline checks on a 68040 configuration.** — slow CPUs hide early writes; RoF's
    A1200 run reported zero violations that `--cpu=68040` exposed. — *RV
    `docs/amiga-lessons.md`*
30. **Every write-only register (BPLCON2, …) is scene state with a named owner; never cache
    one.** CPU reads of `$DFF104` return the floating bus. `PFxP=0` = playfield in front;
    `4` (`$0024`, what `setPlayfield` writes) = all sprites in front. — *RV
    `docs/amiga-lessons.md`; SL `framework/CopperList.cpp`*

## D. AGA display and palette

31. **Reuse SL's proven mode exactly:** `setPlayfield(1,320,200,8,true,false,false,false,
    false,true,0x9c)` → FMODE 3, interleaved 320-byte rows, BPL1/2MOD 280, DIWSTRT `$3881`,
    DIWSTOP `$00c1`, DIWHIGH `$2100` (window `$38..$ff`), then validate those words. — the
    framework's AGA DDF branch is unverified by derivation (`[ASSUMED]` in VT); SL's call is
    the only exercised one. — *SL `docs/rendering.md`, `validate_framework_view`;
    git:56032f5 VT `docs/amiga-arch.md`*
32. **Interleave the bitmap so chunky and planar share the row offset (`y*320`).** — one
    `mult320` serves both. — *SL `docs/rendering.md`*
33. **DIWHIGH is always written, never inherited; DIW is in lores, non-interlaced units.** —
    on ECS/AGA it overrides DIWSTOP's H8/V8 rules and stays written. — *git:56032f5 VT
    `docs/amiga-arch.md`; RV `framework/UPSTREAM.md`*
34. **Wide fetches need 8-byte-aligned plane pointers and rows padded to the fetch unit.** —
    PK pads to 640 px and allocates +8 bytes. — *git:77fb8ce PK `docs/phase5-amiga.md`*
35. **VGA 6-bit → 8-bit as `v<<2 | v>>4`; a 24-bit colour is two MOVEs (high nibbles, then
    BPLCON3 LOCT `$0200` low nibbles) with a bank switch every 32.** A 256-colour load is
    ~528 MOVEs; SL's list is 558 longs. — *SL `amiga_platform.cpp`, `copper_palette.h`,
    `framework/CopperList.cpp` `setPalette24Bit`*
36. **Record each colour MOVE's index once and patch words in place for palette changes;
    rebuild a list only after waiting for display blank.** — never rewrite an executing
    list. — *SL `slicks_copper_palette_map`, `slicks_amiga_platform_set_view`*
37. **Apply queued palette changes at publication time.** — a change applied mid-frame splits
    one frame. — *SL `docs/rendering.md`, `docs/frame-pacing.md`*

## E. C2P, buffering and frame pacing

38. **Full rows: Kalms `c2p1x1_8_c5_bm`** (width multiple of 32, x multiple of 8). It reads 32
    bytes past the source: allocate +32 bytes. — *SL `docs/rendering.md`,
    `c2p1x1_8_c5_bm.s`; git:9018da5 SL `docs/display-corruption-investigation.md`*
39. **Dirty rectangles: SL's 16-pixel `c2p16_interleaved`** storing only final plane words;
    sparse pixels by per-pixel `BFINS`. 8-pixel and hybrid C2P gave no gain in game. — *SL
    `docs/rendering.md`, `docs/performance.md`*
40. **Verify C2P on a 68020 emulator against a bit-level reference, hooking every
    destination store.** — catches intermediate values written to the shown bitmap. — *SL
    `make verify-c2p16`, `tools/verify_planar_writes.sh`*
41. **Dirty regions: 16-px aligned, merged on overlap, bounded; overflow unions, never
    drops.** — *SL `docs/rendering.md`*
42. **A double-buffered back buffer also converts the rectangles changed in the previous
    update.** — else partial updates show two-frame-old pixels. — *VT `docs/amiga-arch.md`*
43. **Single-buffered publication waits for the display-end edge (line `$100`), as an
    edge, not a level; a late update publishes at once and missed slots are not queued.**
    — SL: 33–48 → 46–50 updates/s, no visible tearing. Not a guaranteed blanking bound.
    — *SL `docs/frame-pacing.md`, `slicks_amiga_platform_wait_publication`*
44. **Game time comes from the real-time clock in the original's own units, never a fixed
    credit per drawn frame.** — the fixed clock ran slow motion when an update spanned two
    frames; keep it only for deterministic benchmarks. — *SL `docs/frame-pacing.md`*
45. **On fast CPUs, cap source-defined animation loops at one step per field** (remember the
    last vblank count, compare by equality for wrap). — *VT `docs/frame-pacing.md`*
46. **Double buffering costs a second 64,000-byte Chip bitmap and every dirty region twice;
    decide on measured headroom.** — SL rejected it at ~95 KB free. — *SL
    `docs/frame-pacing.md`*

## F. Blitter

47. **The blitter is a measured candidate, not free.** It shares the Chip bus: an RV
    whole-row blitter paint was byte-exact and 2× slower; only blits replacing CPU work
    (D-only clears) paid [000]. With a faster CPU it becomes the bottleneck. — *RV
    `docs/m68k-optimisation.md`, `docs/span-render-plan.md`, `docs/perf-method.md`*
48. **CPU reads of blitter targets wait for pending blits; drain before CPU writes, cache
    eviction, free and teardown.** — *PK `docs/architecture.md`*
49. **Interleaved bitmaps multiply blit height by the plane count; split tall blits.** — PK's
    4-plane 292-row clear needed two chunks. — *PK `docs/architecture.md`*
50. **The framework's statically allocated blitter queue leaks 49,158 bytes per launch;
    call `AmigaHardware::releaseBlitterQueue()` at shutdown.** — *SL `fe94b50`*
51. **This framework copy declares `getVBR`, `isLongFrame`, `isBlitterBusy` and
    `blitterWait` but defines none (asm-only upstream); every framework blit calls them.**
    Supply C++ bodies or use `WaitBlit()` before the first blit. — dormant under
    `--gc-sections` (L91). — *this repo `framework/AmigaHardware.h`/`.cpp`,
    `src/platform/amiga/Swotl.cpp`*

## G. Memory

52. **Design for 2 MiB Chip, no Fast RAM, the default 4 KiB Shell stack.** WHDLoad adds no
    expansion memory (`FASTMEMSIZE = 0`). — *SL `docs/memory.md`, `docs/whdload.md`*. SWOTL:
    Fast RAM required (D15).
53. **`MEMF_CHIP` only for what DMA reads (bitplanes, copper, sprites, Paula, blitter
    operands); everything else `MEMF_ANY`.** — uses Fast RAM when present. — *PK
    `docs/architecture.md`; SL `docs/memory.md`*
54. **Reserve all game memory at startup, all-or-nothing; no Exec allocation after the
    startup checkpoint.** Large blocks before many small ones; lifetimes borrow owner-tagged
    spans. — *SL `docs/memory.md`*
55. **Big buffers go in BSS or the heap, never on the stack.** — SL builds copper palettes
    from static arrays to keep 2 KiB off the 4 KiB stack. — *SL `build_copper`,
    `STACKCHECK=1`*
56. **`__chip` statics are zeroed BSS; initialisers are discarded. Fill at runtime and
    guard the link.** — a waveform became silence. — *RoF `docs/asset-extraction.md` §6.1;
    PK `amiga/ARCH.md`*
57. **Keep the original pointer when aligning; free that pointer, with the same size.** —
    *PK `docs/architecture.md`*
58. **Audit allocations from the host (AllocMem/FreeMem breakpoints), with repeat launches
    and a low-Chip failure run.** — caught SL's per-launch leak. — *SL `docs/memory.md`*

## H. Paula audio

59. **Four DMA channels, no software mixer; allocate channels by explicit priority rules
    and document adaptations.** — *SL `docs/audio.md`*
60. **Period = 3546895 / Hz (PAL), clamp 124..65535; for higher rates switch to load-time
    half/quarter-rate loops with hysteresis.** — *SL `docs/audio.md`*
61. **Convert samples once at load into Chip as signed 8-bit with the original's gain.** —
    *SL `docs/audio.md`*
62. **One-shot = start, then one VBI later set the reload pointer to a two-byte silent
    loop; expire by VBI counters.** — Paula has no one-shot mode. — *SL `docs/audio.md`;
    VT `docs/amiga-arch.md`*
63. **Keep DMA control in blanking: stop in one VBI, program and start in the next.** —
    DMA control during display coincided with one-refresh horizontal strips in static
    scenery (reported by the user; bitmap audits found no stray writes); costs 20–40 ms
    latency. — *SL `docs/audio.md`; git:9018da5 SL `docs/display-corruption-investigation.md`*
64. **If a restart must wait inline, wait ≥2 sample periods of the largest period since
    the last stop.** — a pitch change need not reload the counter at once (RKM 5-2-7). —
    *VT `docs/amiga-arch.md`*
65. **Or leave all DMA on and silence with AUDxVOL 0;** period/volume changes are then plain
    pokes and only waveform changes need a restart. — *RV `src/platform/amiga/RevsAudio.h`*
66. **AUDxLEN counts words; PTR/LEN latch only at a loop wrap.** Odd loops need an aligned
    copy; no header bytes inside a loop. — *RV `RevsAudio.h`; VT `docs/amiga-arch.md`*
67. **Clear the pending audio interrupt before writing AUDxDAT for direct output.** — *VT
    `docs/amiga-arch.md`*
68. **Channels 0+3 are left, 1+2 right.** — place mono voices deliberately. — *RV
    `RevsAudio.h`*
69. **The LED filter is on at boot (~5 kHz low-pass); turn it off when the original had no
    such filter.** — *RV `RevsAudio.h`*
70. **Volume is linear 0..64; map relative levels, not RMS.** — *SL `docs/audio.md`; VT
    `docs/amiga-arch.md`*
71. **Synthesised chips were re-hosted as chip state → Paula loops, never per-note rendered
    banks:** square loops at computed periods; noise from a rendered LFSR (RV) or five
    evolving 8 KiB buffers refreshed in slices (PK); envelopes clocked from the VBI (RV's
    100 Hz from 50 Hz quantises steps in pairs; a CIA timer is the fix). No sibling
    re-hosted FM/OPL. — *RV `RevsAudio.h`; PK `docs/architecture.md`*

## I. Input

72. **Keyboard: CIA-A SP via `AddICRVector`; if it returns the owner, remove theirs, add
    yours, restore on exit.** Code = `ROR(~SDR,1)`; handshake holds SPMODE output ~85 µs. —
    *SL `keyboard_begin`/`keyboard_handler`; RV `docs/amiga-lessons.md`*
    SWOTL (irq-plan I7) has no keyboard interrupt: `AbleICR` disables SP, the vertical blank
    samples it with `SetICR(0)` and clears it (never read ICR directly); the keyboard
    waits for the handshake (143 ms) before its next byte, so a byte per field loses none.
73. **Clear modifier state at takeover.** — releases while the OS owned the keyboard never
    reach you. — *SL `keyboard_begin`*
74. **Keep a level map and an edge queue/latch.** A level poll misses taps shorter than its
    period (RV: ~37 ms); latch the down-edge, consume on answer, expire after a few fields.
    Never feed held keys only through an event queue. — *RV `docs/controls.md`; VT
    `docs/amiga-arch.md`*
75. **Deliver a press until the original actually reads it.** — a generated input clock edge
    is not acknowledgement; PK lost taps that way. — *git:77fb8ce PK `docs/input-response.md`*
76. **One raw-key → original-code table; count unmapped codes.** — a missing mapping is
    otherwise silent. — *RV `docs/controls.md`; git:9018da5 SL `docs/amiga-skeleton.md`*
77. **Emulate BIOS typematic repeat if the original relies on it** (SL: 500 ms delay,
    10.9/s). — *SL `slicks_amiga_platform_typematic_key`*
78. **Joystick: JOYxDAT is crosswise quadrature** (fwd = b8^b9, left = b9, back = b0^b1,
    right = b1); fire = CIA-A PRA bit 7 (port 1) / bit 6 (port 0); button 2 = POTINP
    bit 14; sample once per VBI. — *RoF `docs/controls.md`*
79. **Mouse: left = CIA-A PRA bit 6, right/middle = POTINP bits 10/8 after `POTGO = 0`.** —
    without it they read held on real hardware; FS-UAE does not model this. — *RV
    `src/platform/amiga/RevsInput.cpp`, `docs/bbc-hardware.md`*
80. **JOY0DAT counters are 8-bit and wrap; take the delta every frame; confirm the sign by
    moving a real mouse.** — *RV `RevsInput.cpp`*
81. **CD32 pad support is a bit-banged read with interrupts off,** detected over several
    spaced samples at boot. — *RoF `docs/controls.md`*

## J. Files and OS lifecycle

82. **Load before takeover; touch the disk only at explicit boundaries inside an I/O
    window.** — *SL `docs/memory.md`; VT `docs/amiga-arch.md`*
83. **Whole-file reads in one Read; saves rewrite the file in place in one write, skipped
    when unchanged (CRC); no temp, backup or rename.** — every WHDLoad OS switch is a
    visible pause plus write delay. — *SL `docs/whdload.md`; PK `docs/architecture.md`*
84. **Handle Workbench startup yourself:** without `pr_CLI`, `WaitPort`/`GetMsg` the
    WBStartup before opening dos.library; reply last, under `Forbid`. — the freestanding CRT
    does neither. — *VT `src/main.cpp`*
85. **Arguments via `GetArgStr`; data via PROGDIR.** — identical under Shell, Workbench and
    the slave. — *SL `docs/whdload.md`*
86. **The shared `_start` ignores `main`'s return; supply a start that preserves it.** —
    *git:77fb8ce PK `docs/memory-audit.md`*
87. **Call `CacheClearU()` after writing code at runtime.** — *git:56032f5 VT
    `docs/amiga-arch.md`*
88. **Pre-create files that saves will overwrite.** — creating new files under WHDLoad's
    write cache hung in low memory. — *PK `docs/architecture.md`*
89. **WHDLoad's quit key cannot run deferred saves; pick one the game does not use.** — RV
    moved it off F10, a game key. — *SL `docs/whdload.md`; RV `docs/whdload.md`*

## K. Framework traps

90. **Two framework lineages exist.** This repo has SL's DanceDiverse3 set: C++ bodies only
    for GCC (`ASSEMBLER` undefined), AGA `setPlayfield`/`Palette24Bit`, no copper NOP
    prefill. RV/VT carry the template set: vasm asm bridges and NOP prefill (VT also
    fixed its interlace, window and hires fetch). Fixes do not carry over automatically. — *SL `framework/README.md`; RV/VT
    `framework/UPSTREAM.md`*
91. **`--gc-sections` hides dormant link traps until the first caller; partial-link the
    framework (`ld -r`) to see them.** — VT found `isLongFrame`'s bridge with no asm and
    `patternWithMask` pulling `__mulsi3`. — *VT `framework/UPSTREAM.md`*
92. **Bitmap's non-interleaved asm arms were silent no-ops; treat interleaved as an
    invariant.** — *VT `framework/UPSTREAM.md`*
93. **The factories leaked Chip storage when the second allocation failed, and `Bitmap`
    allocated `width/8` while drawing at word-padded stride.** — *git:77fb8ce PK
    `docs/memory-audit.md`*
94. **Include every system header first, `AmigaHardware.h` last.** — its bare register
    macros collide with `struct Custom` members. — *RV `docs/amiga-lessons.md`*
95. **Record every local framework change in `framework/README.md`.** — makes re-sync
    possible. — *RV `docs/amiga-arch.md`*

## L. GCC, vasm, elf2hunk

96. **A1200-only: `-m68020 -msoft-float`.** The template defaults to `-m68000` for A500s. —
    *SL `amiga/Makefile`; PK `framework/GCC-PORT.md`*
97. **`volatile` on every custom-chip pointer and ISR-written flag.** — `-O2` turned a
    blitter-queue wait into `bra.s .` and duplicated a BLTSIZE store. — *git:7c298658 RoF
    `docs/amiga-spike.md` #2*
98. **Normalise asm `Scc` results (`$FF`) with `!= 0` before `bool`.** — `!b` gave `$FE`. —
    *PK `framework/GCC-PORT.md` §3*
99. **No function-local statics.** — they need `__cxa_guard_*`, which the freestanding CRT
    lacks. — *VT `src/main.cpp`*
100. **`-fcheck-new`** so `operator new` failure returns null. — *SL `amiga/Makefile`;
     git:77fb8ce PK `docs/memory-audit.md`*
101. **Replace the support library's byte-loop `memset`/`memcpy`** (SL `memory.s`; RV
     `-Wl,--wrap`), keeping asm referenced from C in `.text`. — *SL
     `src/platform/amiga/memory.s`; RV `src/platform/amiga/fastmem.c`; see
     m68k-optimisation.md*
102. **Cross-object `bsr` is `R_68K_PC16`, which elf2hunk cannot represent; use `jsr`.** —
     *PK `framework/GCC-PORT.md` §4*
103. **vasm `-no-opt` is load-bearing; size hot short branches `.s` by hand;** rename
     dot-in-middle labels (vasm reads them as local). — *RV `docs/amiga-lessons.md`; VT
     `framework/UPSTREAM.md`*
104. **`alignas(4)` on even-sized globals ≥4 bytes, with a link audit.** — m68k GCC aligns
     to 2. — *PK `docs/architecture.md`; see m68k-optimisation.md*
105. **Strip with `elf2hunk -s`; keep the ELF for debugging.** DWARF never reaches the
     hunk. — *RoF `docs/asset-extraction.md` §6*
