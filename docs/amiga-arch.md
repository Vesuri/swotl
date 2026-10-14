# Amiga platform architecture

How the target side of this port is structured. Each rule is derived from what shipped
in Slicks (SL), Vette (VT) and Revs (RV); the numbered lessons cited as `L<n>` are in
[amiga-lessons.md](amiga-lessons.md). Translation design: [translation-lessons.md](translation-lessons.md);
build: [toolchain.md](toolchain.md); emulator harness: [headless-fsuae.md](headless-fsuae.md);
slave: [whdload.md](whdload.md).

## Target contract

| Item | Value |
| --- | --- |
| Machine | PAL A1200, 68020, AGA required (`GFXF_AA_LISA` after `SetPatch`), L8 |
| Memory | 2 MiB Chip, no Fast RAM assumed, default 4 KiB Shell stack, L52 |
| Launch | Shell, Workbench and WHDLoad (kickemu, INITAGA) run the same executable |
| Display | 320×200, 8 planes, 256 colours from the 18-bit VGA palette, L31 |
| Timebase | PAL vblank (50 Hz) plus beam position; no other timer unless measured necessary |

## Layers

| Layer | Contents | Rule |
| --- | --- | --- |
| Framework | `src/platform/amiga/framework/`: `AmigaHardware`, `Bitmap`, `CopperList`, `Palette24Bit` (+ `Palette`, `Sprite`, `Util` headers) from SL's DanceDiverse3 set | C++ bodies only; every local change recorded in `framework/README.md` (L90, L95) |
| Platform | takeover, VBI, display views, C2P, Paula, keyboard/joystick/mouse, I/O windows, allocation | single owner per hardware register group; no game logic |
| Runtime services | native replacements for the original's DOS/BIOS/port boundaries (VGA, PIT/INT 08h, INT 09h keyboard, mouse, joystick, AdLib, INT 21h files) | replace the *routine* behind a port sequence, never emulate ports one access at a time (SL `docs/external-surface.md`) |
| Translated game | generated 68020 code | calls runtime services through explicit register contracts (SL `docs/native-graphics-abi.md`) |

Not used: the framework's `Production`/`Part`/`Script` timeline and module player
(RV, VT `framework/UPSTREAM.md`). `Swotl` follows `ProductionRunner`'s takeover through
`AmigaHardware` but owns Exec's VERTB vector, not the level-3 autovector (L10, L13). The
template (dA JoRMaS `Template/C++`) has no AGA 256-colour palette; the vendored
DanceDiverse3 set (`Palette24Bit`, `setPalette24Bit`) is kept for it.

## Lifecycle

1. **Entry.** Take the WBStartup message if there is no CLI (L84); open dos/graphics
   outside `Forbid`; require AGA (L8); parse `GetArgStr` (L85).
2. **Reserve.** Every game-owned block, all-or-nothing, largest first; Chip only for DMA
   data (L53, L54). Failure frees everything and returns 20 before takeover.
3. **Load.** Original data files that the first screens need, before takeover (L82).
4. **Build.** Bitmaps, copper lists and palettes completely, then publish them to the ISR
   (L15).
5. **Take over** in SL's order (L2, L3), VERTB vector (L10), keyboard ICR (L72), `Forbid`
   (L6).
6. **Run.** Main loop: drain timer ticks → translated game step → present. Disk access only
   inside I/O windows (L7). SWOTL: every DOS call of `amiga_platform.c` is one window
   (`Swotl::beginIO`/`endIO`): Exec's VERTB vector, saved INTENA and DISK|BLITTER DMA
   back, `Permit`; the copper display and the keyboard interrupt stay; fields the OS
   serves are added from `GfxBase->VBCounter`.
7. **Return** in SL/VT's order (L4), then pending saves, frees, `releaseBlitterQueue`
   (L50), library closes, Workbench reply last (L84). A readable-state restore check runs in
   the harness (L5).

## Interrupts

| Source | Owner | Content |
| --- | --- | --- |
| Level 3 VERTB | taken-over Exec vector | clear INTREQ (L11) → display publication (L17, L25–27) → vblank/beam counters and BIOS tick (L19) → input sampling (L78–80) → Paula service (L62–63) |
| Level 2 PORTS | Exec chain | keyboard via `ciaa.resource` (L13, L72) |
| Level 3 BLIT | masked | unless the framework blitter queue is adopted (L14) |
| Others | Exec | untouched; restored masks on exit |

The original's timer (INT 08h) and keyboard (INT 09h) handlers do not run in Amiga
interrupt context. The VBI and CIA handler record time and key edges; translated handlers
run from the main loop at boundaries where the game is not mid-draw, in the original's
own tick units (L18, L19). Shared state is guarded by `Disable`/`Enable` (L20).

## Display

- **Mode.** 320×200, eight non-interleaved planes, 40-byte rows; the framework
  programs AGA wide fetches and DIW `$38..$ff`. Plane allocations are 8-byte aligned.
- **Surfaces.** Translated drawing writes guest VGA memory. The runtime snapshots
  published dirty rectangles into persistent chunky storage with 32 bytes of C2P
  lookahead; the platform alone converts to bitplanes.
- **Conversion.** Kalms `c2p1x1_8_c5_bm`: full-width bands in one call, narrower
  rectangles row by row. Dirty bounds originate in guest painter stores, never
  framebuffer comparisons.
- **Buffering.** Two Chip bitmaps and two complete copper lists. Each bitmap retains
  dirty rows until its own conversion, including updates superseded before a VBI.
  Main withdraws the pending list before writing its bitmap; VERTB publishes only
  completed lists. No wait is added before guest interrupt polling.
- **Palette.** DAC changes invalidate both physical lists. A publication
  rebuilds its inactive list only if stale, and carries forward its dirty
  pixels, including palette-only updates. Validity is main-thread state. The list and bitmap are handed
  off together; live copper words are never patched.
- **Publication timing.** Queued handoffs are beam-stamped and deferred if VERTB
  arrives too late. `amiga/display_audit.sh` requires zero late switches, also on
  `AMIGA_CPU=68040` (L26, L29).
- **Copper lists.** Fully written up to the terminator (no NOP prefill in this lineage,
  L22); one owner per write-only register (L30).

## Timing

Game time advances by the original's own clock read from `vblank_count*313 + line`
(L19, L44). Publication never feeds back into simulation; missed slots are not queued
(L43). A fixed-clock mode exists only for deterministic benchmarks. Fast-CPU caps apply
per source-defined loop (L45).

## Audio

- No digital path: SPAZ plays music and effects (`ADLIB.SFX`) on the OPL only
  (ports `388h/389h`; no SB DSP access traced).
- **Music and effects** (AdLib/OPL path): no sibling re-hosted FM synthesis. The proven pattern for
  chip music is a faithful chip-state producer (the original's driver writing a register
  shadow) plus a Paula-only re-hoster that never decides what sounds (RV
  `RevsAudio.h`, L71). The OPL re-hosting method is an open design decision.
- **Shared rules.** Channel ownership between music and effects is an explicit policy
  (L59); stereo placement deliberate (L68); LED filter decided (L69).

## Input

CIA-A keyboard handler produces both a 128-entry level map and an ordered edge queue
(L72–74). One table maps Amiga raw keys to PC scan codes for the translated INT 09h
handler; unmapped codes are counted (L76). Joystick (port 1) and mouse (port 0) are
sampled once per VBI (L78–80); mouse deltas feed the translated INT 33h service. Presses
stay pending until the original reads them (L75).

## Files

Original files are read whole, from PROGDIR, inside I/O windows (L7, L82, L85). Saves
are single in-place writes of pre-existing files, skipped when unchanged (L83, L88). Any
code loaded or patched at runtime is followed by `CacheClearU()` (L87).

## Build rules

`-m68020 -msoft-float -nostdlib -fcheck-new`, framework headers via `SASCCompat.h`,
`AmigaHardware.h` included last, vasm `-no-opt`, replaced `memset`/`memcpy`, `alignas(4)`
audit, `elf2hunk -s` for release (L94, L96–105). Exact flags: [toolchain.md](toolchain.md).

## Standing target checks

| Check | Proves | Source |
| --- | --- | --- |
| Restore status | OS view, vector, DMA and INTENA restored | `make test-amiga-restore` |
| Beam watch | zero late display handoffs; no conversion into the shown bitmap | `amiga/display_audit.sh` |
| Audio VBI spills | Paula work stays in blanking | SL `g_slicks_audio_vbi_spills` |
| C2P store verifier | converters write only final, correct plane words | SL `tools/verify_planar_writes.sh` |
| Allocation audit | zero outstanding blocks, repeat launch, low-Chip failure | SL `tools/memory_audit.py` |
| Stack watermark | fits the 4 KiB default stack | SL `STACKCHECK=1` |
