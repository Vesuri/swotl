# Translator architecture

Offline static translation of SWOTL's 16-bit real-mode x86 code to 68020
assembly. No CPU struct, no generated C, no dispatcher per block, no
hand-ported game routines. Rationale and failure history:
[translation-lessons.md](translation-lessons.md). x86 facts:
[x86-notes.md](x86-notes.md).

## Pipeline

```text
root EXE + .OVL images (proved against DOSBox captures)
  -> decoder (recursive descent from annotated entries; no linear sweep)
  -> typed semantic IR per instruction (flags, segments, widths explicit)
  -> blocks / functions / overlay modules
  -> flag-demand + liveness analysis
  -> 68020 register allocation (guest registers resident)
  -> Motorola-syntax .s (vasm), direct branches between known targets
  -> link with the hand-written runtime -> Swotl.exe
```

## Products and ownership

| Path | Content | Git |
|---|---|---|
| `translator/` | decoder, IR, analyses, backend, coverage report | tracked |
| `annotations/` | entries, indirect targets, switch tables, runtime names (with evidence), self-modified regions, HLE table, profile choices | tracked |
| `build/gen/` | generated `.s`, hash header (translator + annotations + input image) | ignored: derived from game bytes |
| `src/runtime/` | DOS/BIOS services, port/device models, overlay loader, interrupt delivery | tracked |
| `src/platform/amiga/` | framework-based display/audio/input/file layer | tracked |

## Guardrails (from translation-lessons.md G1–G8)

1. Guest code exists only as generator output; generated files are never
   edited. Regeneration is byte-identical; the build checks the hash header.
2. Hand-written code is the runtime only, named by surface item
   (`int21_3Dh`, `port_3C9`), never by guest address. A lint enforces it.
3. Native replacement of a guest routine (HLE) needs an `annotations/` entry:
   guest range, reason (device-bound or measured hot), oracle. User-authorized
   per routine ([speed-plan.md](speed-plan.md) §2.2).
   Callers of a replaced routine stay generated.
4. Wrong output is fixed in IR semantics, lowering or annotations, then
   regenerated.
5. Phase gates are hard ([phases.md](phases.md)); a target milestone counts
   only if its pixels come from generated code.
6. `make gen` reports executed instruction starts as translated /
   self-modified / HLE / unclassified against the DOSBox traces;
   unclassified ones fail.
7. Unresolved indirect control flow, writes to translated code and unknown
   ports/interrupts stop with a report. No interpreter fallback in release.

## Target model (contract: [translator-design.md](translator-design.md))

- Guest RAM: one contiguous block below a6, byte-exact and reversed (linear
  `seg*16+off` at a6 − linear, so a little-endian word is a native word),
  with the reference load segment, so RAM images diff (reversed) against
  captures.
- Segments: ES/SS/DS bases cached in a1–a3 and recomputed on every write;
  CS static per instruction. 64 KiB offset wrap honoured everywhere (under
  an exact guard where a fast form drops it).
- Registers: AX–DX, SP, BP in d0–d5, SI/DI in a4/a5, low words only (upper
  words undefined), SP/BP mirrored (offset ^ 7FFFh); d6/d7/a0 scratch. AH-class halves lowered
  explicitly.
- Flags: virtual; stored only where live, read from the CCR by the next
  instruction where the 68k flags agree; PF/AF only when live.
- Endianness: none at run time (reversed memory, speed-plan R1).
- Calls: guest stack byte-exact; native `jsr`/`rts` with a return-site check
  of the popped IP/CS.
- Overlays: each `.OVL` is a separately translated module at its proved load
  address, all resident in native code (D2); the translated PLINK manager
  loads the bytes into guest RAM and its thunks jump to the native module.
- Memory: Fast RAM required (D15): ~1.36 MB code + 1.06 MiB guest RAM.
- Runtime (`src/runtime/`): the reference machine as the guest sees it
  (DOS 5 PSP/MCBs/environment, IVT values, BIOS/EMS answers) behind
  `platform.h`; one implementation for the host harness and the A1200.
- Drivers: RTSVGA and SPAZ run translated. RTSVGA's video-memory stores
  are marked and their changed rows presented once per game frame (D9); SPAZ's
  OPL2 writes reach the runtime's register file, which the FM re-hoster
  plays on Paula (D10, [sound-plan.md](sound-plan.md)).

## Oracles

- x86 semantics: Unicorn x86-16 (C library, as in Slicks, via ctypes `tests/uc.py`):
  `make test` (gate 3); its known deviations: [x86-notes.md](x86-notes.md).
- Generated program + runtime on host: `make test-host` runs it on Unicorn
  68020 to a milestone and checks the service log (every software INT's
  registers in and out, recorded by the tracer) and RAM against the
  reference, and at mode 13h milestones framebuffer and DAC; `make
  test-amiga` checks the A1200 model's capture likewise, plus the frame
  the Amiga screen shows.
- Generated 68020 code on host: Unicorn 68020 (as Slicks) runs the same
  cases (`make test-m68k`) and the generated program's traced blocks
  (`make test-blocks`), so differentials need no Amiga (gate 4).
- Whole game: lockstep against DOSBox with the reference's input and
  interrupts replayed (the host run above): the service log throughout, guest
  RAM, framebuffer and DAC at the milestones
  ([pc-reference-loop.md](pc-reference-loop.md)); whether it must compare more:
  open-work 24.
