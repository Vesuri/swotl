# SWOTL — DOS x86 to Amiga 68020 static translator

Port Secret Weapons of the Luftwaffe 2.2 (Totally Games / Lucasfilm Games,
1991, VGA DOS) to a PAL A1200 (68020, AGA, 2 MiB Chip) by translating its
16-bit real-mode x86 code offline to 68020 assembly. The translator is the
product. The original running under a PC emulator is the ground truth.
Scope: VGA (RTSVGA, mode 13h) and AdLib FM (SPAZ), the only non-speaker
audio the game has; RTSEGA, RTSTANDY and SFXA (PC speaker) are out.

## Standing rules

- One commit per coherent, verified whole; do not mix unrelated work. Vesuri
  identity, no hooks, no signing, no co-author trailers.
- Be concise. Docs hold rules, facts and pointers; no essays or prose.
- Done items belong in git history, not in docs. `docs/open-work.md` is the
  single, always current list of open work; update it in the same commit.
- This file carries rules and pointers only.
- `ref/`, `tmp/`, generated code (`build/gen/`), captures, traces and any
  other byte-derived game material stay local and are never committed.
- `tmp/` holds local artifacts only: game-derived bytes, captures, traces,
  RAM dumps, frozen builds, logs. Tooling and knowledge are committed:
  reusable scripts in `tools/` (listed in the relevant doc), plans and
  decisions in `docs/`, and the method behind every committed number in a
  committed tool or its commit message. A script stays in `tmp/` only if it
  is a one-off that nothing committed names or relies on.
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
- Reuse what the sibling ports learned (Slicks, Revs, Vette, Pokeri, Rescue on
  Fractalus): it is merged in AmigaXDev's docs (below); do not re-derive.

## Validation scope

- Run only gates relevant to changed code and its affected callers, consumers
  and shared contracts. State the selected checks and why before running them.
- Audio-only changes: FM waveform/quality/envelope/allocation checks, TFH and
  backend integration where affected, and their sabotage; build and smoke the
  Amiga image for platform changes. Do not rerun translator, DOS/file/input,
  whole-game host or diagnostic replay suites for isolated audio synthesis.
- Translator or shared runtime changes: affected differential/guard/sabotage
  tests and relevant original-game host/replay fixtures; broaden when shared
  memory, flags, control flow, interrupts or other cross-cutting contracts change.
- Docs-only changes: consistency and diff checks. Build/release changes: affected
  builds, image audits and launch/package checks.
- Preserve every selected check, oracle and tolerance. Scope by dependencies,
  never by whether a test passes. Existing reference/test-change approval rules
  remain. Use `make gates` only when the impact spans its suites or the user asks;
  it is not a per-commit requirement. Retain green results for unchanged inputs.

## Shared environment and knowledge

Shared guidance starts at `~/.local/share/amiga/docs/index.md`: read the rows that match the
task. It routes to the playbooks (this project follows `docs/playbooks/new-port-playbook.md`),
the references (measurement, validation, 68020 optimisation, Amiga hardware, headless FS-UAE,
toolchain) and the shared tools and material (`docs/environment.md`; local list:
`docs/toolchain.md`). The environment comes from AmigaXDev's `make setup`; `amiga/env.sh`
sources `~/.local/share/amiga/env.sh` and selects the arm64 FS-UAE. Generic lessons go into
AmigaXDev's docs (edit them there, then `make share`); this repo keeps what is specific to SWOTL.

## Pointers

- Index: `docs/README.md`.
- Method: `docs/architecture.md`, `docs/phases.md`,
  `docs/translator-design.md`,
  `docs/translation-lessons.md`, `docs/x86-notes.md`, `docs/method-lessons.md`
- Process: `docs/perf-method.md`, `docs/speed-plan.md` (speed work: its rules
  bind every agent), `docs/native-plan.md` (work after the translator steps),
  `docs/native-compute.md` (native routine contract), `docs/irq-plan.md`
  (interrupt delivery without polling),
  `docs/swotl-tfh-rendering-map.md`, `docs/tfh-cross-reference.md`
- Sound: `docs/sound-plan.md`
- Pointer: `docs/pointer-plan.md`
- Amiga: `docs/amiga-arch.md`, `docs/amiga-lessons.md`,
  `docs/m68k-optimisation.md`, `src/platform/amiga/framework/README.md`
- Tools: `docs/toolchain.md`, `docs/headless-fsuae.md`,
  `docs/pc-reference-loop.md`
- Guest map: `docs/plink.md`, `docs/external-surface.md`,
  `docs/source-inventory.md`, `docs/indirect-coverage.md`, `docs/game-timing.md`,
  `annotations/`
- Release: `docs/whdload.md`, `docs/release.md`
- Build: `make amiga`, `make smoke`, bench/diagnostic sync image `make amiga-sync`; original: `make reference-staging`;
  ref facts: `make inspect`, `make hash`/`check-ref`; milestones `make
  reference`, `make coverage`; map `make map`, `make ghidra`;
  translator `make gen`, `make test` (G2 lint, decoder, x86 and 68020
  differentials, block differential, G1, host run), `make test-sabotage`;
  runtime on host / A1200 model `make test-host` (`test-host-all`: m1–m7, the
  coverage scenarios, music skip), `make test-amiga`, `make test-amiga-keyboard`, `make test-amiga-workbench`; IRQ0 stress `make
  test-irq-stress` (irq-plan I6); audio `make gates-audio`;
  WHDLoad slave `make whdload`, `make test-whdload`; release `make release`,
  `make test-install-data`, `make test-release-installer`; full
  suite `make gates` (select relevant gates as above); `SetPatch` from
  `$SETPATCH`. Facts: `docs/source-inventory.md`.
