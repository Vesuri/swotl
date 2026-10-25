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
| Memory | 2 MiB Chip for DMA data; Fast RAM required (D15, [translator-design.md](translator-design.md)); default 4 KiB Shell stack, L52 |
| Launch | Shell. To run the same executable: Workbench (L84, open-work 39) and a WHDLoad slave (kickemu, INITAGA; [whdload.md](whdload.md)) |
| Display | 320×200, 8 non-interleaved planes, 256 colours from the 18-bit VGA palette, L31 |
| Timebase | PAL vblank (50 Hz) for display, input and audio; PIT channel 0 on a CIA-B timer (D8) |

## Layers

| Layer | Contents | Rule |
| --- | --- | --- |
| Framework | `src/platform/amiga/framework/`: `AmigaHardware`, `Bitmap`, `CopperList`, `Palette24Bit` (+ `Palette`, `Sprite`, `Util` headers) from SL's DanceDiverse3 set | C++ bodies only; every local change recorded in `framework/README.md` (L90, L95) |
| Platform | takeover, VBI, display views, C2P, Paula, keyboard/mouse, PIT timer, I/O windows, allocation | single owner per hardware register group; no game logic |
| Runtime | `src/runtime/`: the reference machine as the guest sees it (DOS, BIOS/EMS, INT 33h, IVT; PIC/PIT/AdLib/joystick ports in `ports.c`); RTSVGA and SPAZ run translated | behind `platform.h`, one implementation for host and A1200; any other port stops ([architecture.md](architecture.md)) |
| Translated game | generated 68020 code | calls the runtime through explicit register contracts ([translator-design.md](translator-design.md)) |

Not used: the framework's `Production`/`Part`/`Script` timeline and module player
(RV, VT `framework/UPSTREAM.md`). `Swotl` follows `ProductionRunner`'s takeover through
`AmigaHardware` but owns Exec's VERTB vector, not the level-3 autovector (L10, L13). The
template (dA JoRMaS `Template/C++`) has no AGA 256-colour palette; the vendored
DanceDiverse3 set (`Palette24Bit`, `setPalette24Bit`) is kept for it.

## Lifecycle

1. **Entry.** Workbench start (L84) is not handled yet (open-work 39); open dos/graphics
   outside `Forbid`; require AGA (L8); parse `GetArgStr` (L85).
2. **Reserve.** Every game-owned block, all-or-nothing, largest first; Chip only for DMA
   data (L53, L54); only find-first's name records are allocated later, inside their I/O
   window (`plat_alloc`). Failure frees everything before takeover; `main` returns 0
   either way (20 on failure: open-work 39).
3. **Load.** The optional TFH `sfx.rsc` (argument `TFH`) before takeover (L82); the
   guest's own files later, through I/O windows.
4. **Build.** Bitmaps, copper lists and palettes completely, then publish them to the ISR
   (L15).
5. **Take over** in SL's order (L2, L3), VERTB vector (L10), keyboard ICR (L72), `Forbid`
   (L6).
6. **Run.** The translated program runs on its own stack (`amiga_guest_run`); posted
   interrupts are taken at its poll points (D8); the field task presents (D9). Disk access only
   inside I/O windows (L7). SWOTL: every DOS call of `amiga_platform.c` is one window
   (`Swotl::beginIO`/`endIO`): Exec's VERTB and SOFTINT vectors, saved INTENA and DISK|BLITTER DMA
   back, `Permit`; the copper display and the keyboard interrupt stay; fields the OS
   serves are added from `GfxBase->VBCounter`.
7. **Return** in SL/VT's order (L4), then pending saves, frees, `releaseBlitterQueue`
   (L50), library closes (the Workbench reply, L84: open-work 39). A readable-state restore check runs in
   the harness (L5).

## Interrupts

| Source | Owner | Content |
| --- | --- | --- |
| Level 3 VERTB | taken-over Exec vector | clear INTREQ (L11) → display publication (L17, L25–27) → field counter → mouse and typematic repeat (L77, L79–80) → Paula staging (L62–63) → request SOFTINT |
| Level 1 SOFTINT | taken-over Exec vector | field task ([irq-plan](irq-plan.md) I5): clear INTREQ → key script, `fm_field` on an OPL snapshot taken under `Disable` → the due present (D9) unless a driver call or the main thread's present or video BIOS call runs (`video.c` busy) |
| Level 2 PORTS | Exec chain | keyboard via `ciaa.resource` (L13, L72) |
| Level 6 EXTER | Exec chain | PIT via a `ciab.resource` timer (`amiga_platform.c`): SPAZ's handler at once through `rt_irq_interrupt` when `rt_irq0_ready` ([irq-plan](irq-plan.md) I6), EXTER acknowledged and the mask lowered to 2 so the vertical blank preempts it; else posts vector 08h (always under `BENCH`) |
| Level 3 BLIT | masked | unless the framework blitter queue is adopted (L14) |
| Others | Exec | untouched; restored masks on exit |

The original's keyboard (INT 09h) handler does not run in Amiga interrupt context
(L18). SPAZ's timer handler runs in the CIA-B interrupt (RC1, L18 exception, irq-plan I6);
[irq-plan](irq-plan.md) moves keyboard reading into the vertical blank (RC4). A tick the
interrupt cannot run, and the keyboard's events, go to `rt_irq_ring` (keys to
`rt_key_ring`); the guest's or the runtime's BIOS handler runs at the next poll point with
guest IF set ([translator-design.md](translator-design.md) D8). Shared rings are guarded
by `Disable`/`Enable` (L20).

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

Game time is the original's own PIT channel 0 at the rate the guest programs
(`plat_timer_rate`: CIA latch = PIT divisor scaled to the PAL E-clock), one posted INT 08h
per period (L44). Publication never feeds back into simulation; missed slots are not queued
(L43). `BENCH` replaces the timer by ticks from guest progress for deterministic benchmarks
([speed-plan.md](speed-plan.md) §4).

## Audio

- No digital path: SPAZ plays music and effects (`ADLIB.SFX`) on the OPL only
  (ports `388h/389h`; no SB DSP access traced).
- **Music and effects**: SPAZ runs translated into the runtime's OPL register shadow; a
  Paula-only re-hoster (`fm_paula.c`, `Audio.cpp`) never decides what sounds (L71);
  optional TFH samples. Facts and decisions: [sound-plan.md](sound-plan.md).
- **Shared rules.** Channel ownership between music and effects is an explicit policy
  (L59); stereo placement deliberate (L68); the LED filter is left as booted (L69: open-work 40).

## Input

The CIA-A keyboard handler (L72) maps each raw key edge through one table to a PC set 1
make/break code and posts it to `rt_key_ring` with vector 09h; unmapped codes are counted
(`amiga_unmapped_keys`, L76). Presses stay pending until the original reads them (L75);
typematic repeat runs in the VBI (L77). The mouse (port 0) is sampled once per VBI
(L79–80); its deltas feed the runtime's INT 33h driver (`plat_mouse`). No Amiga joystick:
port `201h` answers as the reference's absent one (`src/runtime/ports.c`).

## Files

Each guest DOS file call (open, create, read, write, seek, delete, directory) is one
dos.library call in its own I/O window, relative to the current directory (L7). Saves are
the guest's own create/write calls; L83 and L88 are not applied. Any code loaded or patched
at runtime is followed by `CacheClearU()` (L87).

## Build rules

`-m68020 -msoft-float -nostdlib -fcheck-new`, framework headers via `SASCCompat.h`,
`AmigaHardware.h` included last, vasm `-no-opt` for hand-written asm, replaced
`memset`/`memcpy`, `elf2hunk -s` for release (L94, L96–103, L105); L104 (`alignas(4)` with a
link audit) not applied (open-work 41). Exact flags: [toolchain.md](toolchain.md).

## Standing target checks

| Check | Proves | Source |
| --- | --- | --- |
| Restore status | OS view, vector, DMA and INTENA restored | `make test-amiga-restore` |
| Beam watch | zero late display handoffs; no conversion into the shown bitmap | `amiga/display_audit.sh` |
| Audio VBI spills | Paula work stays in blanking | none here; Slicks `g_slicks_audio_vbi_spills` |
| C2P store verifier | converters write only final, correct plane words | none here; Slicks `tools/verify_planar_writes.sh` |
| Allocation audit | zero outstanding blocks, repeat launch, low-Chip failure | none here; Slicks `tools/memory_audit.py` |
| Stack watermark | fits the 4 KiB default stack | none here; Slicks `STACKCHECK=1` |
