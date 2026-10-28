# Documentation

How the port works and how it was built and checked. Players need only the
[README](../README.md) and the [release ReadMe](../release/ReadMe).

## Start here

- [architecture.md](architecture.md): the translator pipeline, ownership and guardrails.
- [phases.md](phases.md): the phase gates the port went through.
- [open-work.md](open-work.md): the single list of open work.
- [game-timing.md](game-timing.md): how the game keeps real-time speed on any CPU.

## Translator

- [translator-design.md](translator-design.md): the contract between generated code and the runtime.
- [translation-lessons.md](translation-lessons.md): rationale and failure history.
- [x86-notes.md](x86-notes.md): real-mode x86 facts the translator depends on.
- [m68k-optimisation.md](m68k-optimisation.md): 68020 code generation.
- [native-compute.md](native-compute.md): the contract for the few native routines.

## The original game

- [source-inventory.md](source-inventory.md): the files of version 2.2.
- [plink.md](plink.md): the PLINK overlay mechanism.
- [external-surface.md](external-surface.md): every interrupt, port and VGA access (generated).
- [indirect-coverage.md](indirect-coverage.md): indirect jumps without execution coverage.

## Amiga platform

- [amiga-arch.md](amiga-arch.md): display, input, files and memory on the A1200.
- [sound-plan.md](sound-plan.md): AdLib FM on Paula and the Their Finest Hour effects.
- [pointer-plan.md](pointer-plan.md): the mouse pointer as hardware sprites.
- [whdload.md](whdload.md) and [release.md](release.md): the slave, installer and release audits.

## Validation

- [pc-reference-loop.md](pc-reference-loop.md): the original under DOSBox as ground truth.
- [headless-fsuae.md](headless-fsuae.md): scripted A1200 runs under FS-UAE and GDB.
- [toolchain.md](toolchain.md): tools, paths and setup.

## Performance

- [perf-method.md](perf-method.md): measurement tools and method.
- [speed-plan.md](speed-plan.md): speed work rules and record.
- [irq-plan.md](irq-plan.md): interrupt delivery without polling.
- [native-plan.md](native-plan.md): native routine plan.
- [swotl-tfh-rendering-map.md](swotl-tfh-rendering-map.md) and
  [tfh-cross-reference.md](tfh-cross-reference.md): what the Amiga Their Finest Hour offers.

## Lessons from other ports

- [amiga-lessons.md](amiga-lessons.md) and [method-lessons.md](method-lessons.md): collected
  from the sibling ports; file references there are theirs.
