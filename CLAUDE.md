# SWOTL — DOS x86 to Amiga 68020 static translator

Port Secret Weapons of the Luftwaffe 2.2 (Totally Games / Lucasfilm Games,
1991, VGA DOS) to a PAL A1200 (68020, AGA, 2 MiB Chip) by translating its
16-bit real-mode x86 code offline to 68020 assembly. The translator is the
product. The original running under a PC emulator is the ground truth.

## Standing rules

- One commit per coherent, verified whole; do not mix unrelated work. Vesuri
  identity, no hooks, no signing, no co-author trailers.
- Be concise. Docs hold rules, facts and pointers; no essays or prose.
- Done items belong in git history, not in docs. `docs/open-work.md` is the
  single, always current list of open work; update it in the same commit.
- This file carries rules and pointers only.
- `ref/`, `tmp/`, generated code (`build/gen/`), captures, traces and any
  other byte-derived game material stay local and are never committed.
- Guest code reaches the Amiga only as translator output. Never hand-port a
  guest routine to C or asm, never edit generated files, never fix output by
  hand: fix the translator or `annotations/` and regenerate.
- Hand-written code is the runtime and platform layer only, named by surface
  item, never by guest address. Native replacement of a guest routine needs
  an HLE table entry with reason and oracle.
- Phase gates in `docs/phases.md` are hard. A milestone counts only if its
  pixels come from generated code.
- Unknown control flow, code writes, ports and interrupts fail loudly.
- Tests settle correctness: x86 semantics vs Unicorn, generated 68k on the
  host 68k core, whole game in lockstep with DOSBox. Never compare the port
  with itself.
- Reuse the sibling ports (`~/Documents/Slicks`, `Revs`, `Vette`, `Pokeri`,
  `Rescue on Fractalus`) and their lessons in `docs/`; do not re-derive.

## Pointers

- Method: `docs/architecture.md`, `docs/phases.md`,
  `docs/translation-lessons.md`, `docs/x86-notes.md`
- Process: `docs/method-lessons.md`, `docs/perf-method.md`
- Amiga: `docs/amiga-arch.md`, `docs/amiga-lessons.md`,
  `docs/m68k-optimisation.md`, `src/platform/amiga/framework/README.md`
- Tools: `docs/toolchain.md`, `docs/headless-fsuae.md`,
  `docs/pc-reference-loop.md`
- Release: `docs/whdload.md`, `docs/release.md`
- Build: `make amiga`, `make smoke`; original: `dosbox-staging -conf
  reference/dosbox-staging.conf`; `SetPatch` expected at `tmp/SetPatch`.
