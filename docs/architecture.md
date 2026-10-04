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
| `annotations/` | entries, indirect-target tables, data ranges, HLE table, names (with evidence class) | tracked |
| `build/gen/` | generated `.s`, hash header (translator + annotations + input image) | ignored: derived from game bytes |
| `src/runtime/` | DOS/BIOS services, port/device models, overlay loader, interrupt delivery | tracked |
| `src/platform/amiga/` | framework-based display/audio/input/file layer | tracked |

## Guardrails (from translation-lessons.md G1–G8)

1. Guest code exists only as generator output; generated files are never
   edited. Regeneration is byte-identical; the build checks the hash header.
2. Hand-written code is the runtime only, named by surface item
   (`int21_3Dh`, `port_3C9`), never by guest address. A lint enforces it.
3. Native replacement of a guest routine (HLE) needs an `annotations/` entry:
   guest range, reason (device-bound or measured hot), oracle. Starts empty.
   Callers of a replaced routine stay generated.
4. Wrong output is fixed in IR semantics, lowering or annotations, then
   regenerated.
5. Phase gates are hard ([phases.md](phases.md)); a target milestone counts
   only if its pixels come from generated code.
6. `make gen` reports executed guest bytes as translated / HLE /
   unclassified against the DOSBox trace; unclassified executed bytes fail.
7. Unresolved indirect control flow, writes to translated code and unknown
   ports/interrupts stop with a report. No interpreter fallback in release.

## Target model (contract: translator-design.md; D8–D11 open)

- Guest RAM: one contiguous block at a6, byte-exact little-endian, linear
  address `seg*16+off` with the reference load segment, so RAM images diff
  directly against captures.
- Segments: ES/SS/DS bases cached in a1–a3 and recomputed on every write;
  CS static per instruction. 64 KiB offset wrap honoured everywhere (phase 7
  may drop it where analysis rules it out).
- Registers: AX–DX, SP, BP in d0–d5, SI/DI in a4/a5, zero-extended; d6/d7/a0
  scratch. AH-class halves lowered explicitly.
- Flags: virtual; stored only where live, read from the CCR by the next
  instruction where the 68k flags agree; PF/AF only when live.
- Endianness: word access via `ror.w #8` on load/store. Alternatives (e.g.
  byte-reversed memory) only after a measured A/B.
- Calls: guest stack byte-exact; native `jsr`/`rts` with a return-site check
  of the popped IP/CS.
- Overlays: each `.OVL` is a separately translated module at its proved load
  address, all resident in native code (D2); the translated PLINK manager
  loads the bytes into guest RAM and its thunks jump to the native module.
- Memory: Fast RAM required (D15): ~1.44 MB code + 1.06 MiB guest RAM.
- Runtime (`src/runtime/`): the reference machine as the guest sees it
  (DOS 5 PSP/MCBs/environment, IVT values, BIOS/EMS answers) behind
  `platform.h`; one implementation for the host harness and the A1200.
- Drivers: RTSVGA and SPAZ are replacement candidates at
  their call interface (G3 table), implemented on the dA JoRMaS layer.

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
- Whole game: lockstep against DOSBox with recorded input; compare guest RAM
  and the mode 13h framebuffer at frame boundaries
  ([pc-reference-loop.md](pc-reference-loop.md)).
