# Method lessons

Cross-project process rules. One line each: **rule** — why — provenance
(project, path; `git:` = deleted file, read with `git show <hash>^:<path>`).
Projects: Slicks (DOS→A1200, x86), Pokeri (68008→Amiga), RoF (Atari 6502→A500),
Revs (BBC 6502→A500), Vette (Mac 68000→A1200). Target-hardware lessons:
[amiga-lessons.md](amiga-lessons.md); translation specifics:
[translation-lessons.md](translation-lessons.md); performance method:
[perf-method.md](perf-method.md).

## A. Scope drift and the translator

1. **The translator is the product; a hand-written routine is a defect, not progress.**
   Slicks set out to build x86→IR→68020; from the second day every "Translate X"
   commit was a hand-written `native/*.s` file, then hand-recovered C
   (`race_runtime.c`), and the translator phases were dropped as out of scope.
   — Slicks `docs/phases.md`, `docs/architecture.md`, git `4508f2c`..`7d9d7b0`.
2. **Do not hand-port code before proving it is linked/reached.** Slicks
   translated routines the shipped game never linked (readback, colour remap,
   checker fill, …); they and their tests were later deleted.
   — Slicks `docs/validation-harness.md`.
3. **Every gate in the order; no gate skipped because a later one looks easy.**
   Reference loop → proven runtime image → static/live map → semantics → lowering
   → end-to-end target skeleton → optimise. — Slicks `AGENTS.md` §Gates.
4. **Build discovery and validation infrastructure exhaustively up front,
   not reactively.** Every RoF scar (missed indirect targets, vacuous greens,
   late reference loops) came from growing them on demand.
   — RoF `docs/postmortem.md`.
5. **Improve generator output before mass-generating.** One generator fix
   upgrades the whole corpus and shrinks the hand-twin backlog; RoF's flag-elision
   peephole landed late and every regen until then paid for it.
   — RoF `docs/postmortem.md` §2.1.
6. **Emit the mechanism, not a snapshot of it.** Revs' 24 SMC sites were three
   mechanical classes with exact runtime forms; hand-stubbing them would have
   meant 10 unvalidated routines in the hottest code. — Revs `docs/method-lessons.md`.
7. **"Read it at run time, to be safe" adds machinery whose preconditions rot.**
   Narrow what varies when evidence allows; a conservative operand read later
   broke an unpatched circuit. — Revs `docs/method-lessons.md`.
8. **A ported heuristic may encode the previous binary's shape.** Ask what it is
   evidence of (orphan-run ownership rule dropped an IRQ chain-on in Revs).
   — Revs `docs/method-lessons.md`.
9. **A silent no-op is the most expensive translation choice.** Untranslatable
   input (BRK, unmapped target, unlisted SMC value, fixture-less validated name)
   must fail at generation or report loudly at run time; a `TODO` in generated
   output is not loud. Do not suppress generated-code warnings.
   — Revs `docs/method-lessons.md`; Slicks `AGENTS.md` (unknown control flow fails loudly).
10. **Read bounds/counts from the instruction, never from the first example.**
    Assert the instruction shape relied on (patch count differed per track;
    unpack tables overwritten mid-sequence). — Revs `docs/method-lessons.md`.
11. **A static count of a dynamic mechanism under-counts by its dynamism;
    operand encoding is the strongest evidence of the legal target set.**
    — Revs `docs/method-lessons.md`.

## B. False evidence (how agents fooled themselves)

12. **A probe that reads the same source as the code under test is vacuous.**
    — Revs `docs/method-lessons.md`.
13. **Every "not observed" needs a positive control in the same run** proving
    execution reached the surrounding path. Three zero-hit probes on main-loop
    sites came from a run stuck in the front end.
    — Revs `docs/method-lessons.md`; Slicks `docs/validation-harness.md`.
14. **A dropped probe symbol reads garbage that looks like data.** gc-sections
    removed a counter, gdb resolved it into `.text`; root every probe symbol in
    the link and audit it. — Revs `docs/method-lessons.md`; Vette `AGENTS.md` (`PROBE_SYMS`).
15. **A gdb script aborts at the first unknown symbol**; "trace stopped after the
    header" = stale script. — Revs `docs/method-lessons.md`; Pokeri `AGENTS.md`.
16. **Assert name-keyed harness inputs resolve.** jsbeeb `RETURN` was undefined,
    so every press was a silent no-op. — Revs `docs/method-lessons.md`.
17. **A hedge is not a control.** Writing "this 0 may be a wrapped bracket" under
    a headline table does not license the headline; test it or don't publish.
    — Revs `docs/method-lessons.md`.
18. **Every instrument prints a total-accounting check each run** (bracketed vs
    elapsed must be ~100%). — Revs `docs/method-lessons.md`.
19. **Suspect the instrument hardest when it agrees with the expectation.**
    — Revs `docs/method-lessons.md`.
20. **A metric that improves because the tool got looser is worse than no
    number.** Ask whether the thing changed or only the measuring.
    — Revs `docs/method-lessons.md`.
21. **A wrong static analysis still emits a confident ranked table.** Point new
    analyses at a known-good case first. — Revs `docs/method-lessons.md`.
22. **Top-N reports answer magnitude, not presence.** Ownership/dependency
    questions live in the tail; print the full distribution and a partition check.
    — Revs `docs/method-lessons.md`.
23. **Two runs of one instrument disagreeing on a shared input is an instrument
    defect.** — Revs `docs/method-lessons.md`.
24. **A windowed census zero means "none in this window".** — Revs `docs/method-lessons.md`.
25. **Never assert "pre-existing" without bisecting.** Wrong three times of four.
    — Revs `docs/method-lessons.md`.
26. **Re-measure; never quote an old number.** A stale "~6 FPS" (really 14.4)
    steered scope for months; RoF's "algorithmic floor" was GCC's floor.
    — Revs `docs/method-lessons.md`; RoF `docs/perf-budget.md`, `AGENTS.md`.
27. **A plausible cycle-accounting story is not evidence**; the first
    "register pressure" diagnosis of a regression was retracted (it was an
    inlining eviction). — Revs `docs/m68k-optimisation.md`.
28. **Prove the binary is the source you think it is.** Identical small mismatch
    counts across unrelated sabotages = stale binary; equal-to-total = saturation.
    `rm` objects before each sabotage build. — Revs `docs/validation-harness.md`.
29. **Never rebuild an ELF an emulator or oracle is using; freeze exe+ELF for long
    runs; don't edit a running launcher.** — Slicks `docs/development-verification.md`;
    Pokeri `docs/testing.md`, `AGENTS.md`.
30. **Clean after changing build flags or widely included headers**; a stale
    partial build links a working-but-wrong binary.
    — RoF `AGENTS.md`; Revs `AGENTS.md`; Vette `AGENTS.md`.
31. **A run that timed out is not a pass.** Each case requires an explicit
    success record and rejects loud stops. — Vette `docs/gameplay-coverage.md`,
    `docs/development.md`.
32. **Instrument persistent state, not events** (read the stack to see a call in
    progress). — Revs `docs/method-lessons.md`.
33. **On a wrapping quantity, assert both ends**; a watermark without its
    predecessors was arrived at from the other side. — Revs `docs/method-lessons.md`.
34. **Corrupt data that looks foreign (ASCII in an index) → ask who else writes
    that range.** — Revs `docs/method-lessons.md`.
35. **gdb `$ps`/`$pc`/`$sp`/`$d0`… are CPU registers**; `set $ps=…` corrupts SR.
    Name script variables `$sXxx`. — RoF `docs/flight-perf-log.md` §19.7.
36. **Never quote the better of two runs; record the binary md5 per run**; a
    killed batch left a stale binary that measured as a phantom regression.
    — RoF `docs/flight-perf-log.md` §15.4, §19.7.
37. **Wait for a run to finish before starting the next** (run 1's log printed
    run 2's output); identical results from 120 s and 300 s runs mean the machine
    stopped. — RoF `docs/flight-perf-log.md` §15.3, `docs/asm-migration-plan.md` §Phase 8.
38. **Check a plan's factual premises against the binary before building on
    them** (Vette's plan had two load-bearing errors); any OS/trap inventory is a
    lower bound until run. — Vette git `56032f5^:docs/postmortem.md`.

## C. Oracles and differential testing

39. **Tests, not agent confidence, settle correctness.** Every instruction
    semantic and every lowering is differentially tested against an independent
    x86 oracle (Unicorn x86-16 vs Unicorn 68020 in Slicks).
    — Slicks `AGENTS.md`, `docs/validation-harness.md`.
40. **Never compare the port with itself or a host approximation.** Ground truth
    is the original under the reference emulator. — Slicks/SWOTL `AGENTS.md`;
    RoF `AGENTS.md`; Revs `AGENTS.md`.
41. **Fixture-or-fail.** A validated name with no fixture must fail the run
    (RoF printed PASS with zero comparisons). — RoF `docs/postmortem.md` §3;
    Revs `docs/validation-harness.md`.
42. **Run the differential on the big-endian target, or lint wide aliases of
    little-endian guest RAM.** Host-green, Amiga-garbage happened.
    — RoF `docs/postmortem.md`; Revs `AGENTS.md` (`endian-lint`).
43. **No "incidental difference" bucket.** Declare live exit registers/flags;
    undeclared ones are asserted dead. — RoF `docs/postmortem.md`; Revs `docs/validation-harness.md`.
44. **Memory is half the output.** Compare the hardware-write sequence, traps,
    OS calls and stack too; a mem-only diff passed 4 of 9 sabotages.
    — Revs `docs/validation-harness.md` §FIFTH/§SEVENTH/§FOURTEENTH.
45. **Sabotage every new gate**: inject a few deliberate defects, confirm they
    fail, remove them. A first-run PASS is indistinguishable from blindness.
    — Revs `AGENTS.md`, `docs/validation-harness.md`.
46. **A sabotage must be reachable in value space** (threshold moved to an
    unproducible odd value proved nothing). — Revs `docs/validation-harness.md`.
47. **A differential is blind to what its two sides share** (code or input);
    name it and find a check that does not share it.
    — Revs `docs/validation-harness.md`.
48. **Generator/CPU-model changes alter the oracle too**; record whole-program
    determinism baselines before, compare after, and never re-record to make a
    failure pass. Re-record only from a clean tree. — Revs `AGENTS.md`,
    `docs/validation-harness.md` §SIXTH.
49. **Randomise inputs incl. gating bytes by default; narrow only to a stated
    game representation invariant**, written at the fixture with its writer.
    — Revs `docs/validation-harness.md` §DOMAIN RULE; RoF `docs/postmortem.md`.
50. **Validate results, not implementation details.** Dead scratch cells and dead
    flags are ignorable only with a written reader audit; accepted numeric
    departures use a derived tolerance, not an ignore mask.
    — Revs `docs/validation-harness.md` §RESULTS RULE, `AGENTS.md`.
51. **A shim/boundary reproduces every register and flag its callers read**,
    transitively, even if the native core does not need it.
    — Revs `AGENTS.md`, `docs/native-maintenance.md`; Vette/Pokeri `AGENTS.md`.
52. **Exercise every mode/session type**; a mode the tests never run is a whole
    untested subsystem (practice skipped the multi-car path).
    — Revs `docs/method-lessons.md`.
53. **Prove pure reorderings on the host** (old vs new body over randomised
    inputs), then re-measure cost: byte-identical ≠ cost-identical.
    — Revs `docs/method-lessons.md`.
54. **Target-only asm needs an in-process differential with a nonzero check
    count**; inline asm is unverified until it has run on the target (ROR/ROL-X
    bug assembled and disassembled correctly). — Revs `AGENTS.md`,
    `docs/m68k-optimisation.md`.
55. **Isolated oracle, smoke test and production-screen comparison prove
    different things; none proves whole-game fidelity.**
    — Slicks `docs/development-verification.md`; Revs `AGENTS.md`.
56. **Audit architecture, not just output**: generated code is rejected for
    unexpected guest-context traffic, helper calls, flag materialisations and
    dispatcher exits. — Slicks `docs/validation-harness.md`, `docs/architecture.md`.

## D. Faithfulness vs improvement

57. **Fidelity before improvement; every deviation is either fixed or listed
    with its reason and the user's decision.** — Slicks `docs/fidelity.md`.
58. **Remove port-only additions** (Slicks F01/F03/F11/F16 footer, rows, mouse
    exits); do not add optional UI to hide a failure. — Slicks `docs/fidelity.md`;
    Vette `AGENTS.md`.
59. **Keep original decisions; implement their services.** Unknown calls stay
    named loud stops. — Pokeri `AGENTS.md`; Vette `AGENTS.md`.
60. **Decide the faithful-vs-platform seam rule before the first native routine**;
    prefer a small `#ifdef` variation over moving code out of the validated tier.
    — RoF `docs/postmortem.md` §5; Revs `docs/faithfulness-seam.md`.
61. **Before calling drift a bug, look for the original's own compensation
    table.** — Revs `docs/method-lessons.md`.
62. **Undefined/garbage original behaviour is a user decision**, recorded as a
    deviation (Slicks D2/D4). — Slicks `docs/fidelity.md`.
63. **Timing departures (frame-rate-independent sim, real-time clock) are written
    departures with a per-piece argument and their own gate.**
    — Revs `docs/faithfulness-seam.md`; Slicks `docs/frame-pacing.md`.
64. **Ask the user at genuine decision points** (scope, architecture, fidelity).
    — RoF/Pokeri `AGENTS.md`.

## E. Gating and process

65. **Gate a change by what it can affect**: doc-only → link/syntax checks;
    pure helper → host checks; runtime → original-byte checks + bounded target run.
    Do not change fidelity or scope as housekeeping. — Revs `AGENTS.md`; Vette `AGENTS.md`.
66. **Fail fast**: build + quick oracle → parent timing → expensive validation
    only for promising candidates → final timing. — Slicks `AGENTS.md`,
    `docs/development-verification.md`.
67. **Read the measured dead ends before retrying; require a changed premise and
    a new measurement.** — Revs `AGENTS.md`; RoF `AGENTS.md`; Slicks `docs/performance.md`.
68. **Fixed-hardware target: get an end-to-end skeleton running and profiled on
    the target first.** — RoF `docs/postmortem.md` §4; Slicks `AGENTS.md`.
69. **Never kill all fs-uae/gdb; PID-scoped cleanup; close every session you
    start.** Several projects share the host. — RoF/Pokeri/Vette `AGENTS.md`;
    Slicks `docs/development-verification.md`.
70. **Judge appearance only from a clean real run**; the debugger greys the
    display. Decode screenshots against memory dumps rather than eyeballing.
    — Revs `docs/method-lessons.md`.

## F. Commits

71. **One coherent, verified change per commit, committed before the next.**
    Commit on user confirmation when behaviour is user-visible.
    — Slicks/Revs/Vette/Pokeri `AGENTS.md`; RoF `AGENTS.md`.
72. **Preserve unrelated worktree edits.** — Revs/Vette `AGENTS.md`.
73. **Never commit original or byte-derived material**; check
    `git status --ignored` before adding new files (extensionless ROMs slipped).
    — Pokeri `AGENTS.md`; SWOTL `AGENTS.md`.
74. **Repo identity, no hooks/signing/co-author trailers.** — SWOTL/Slicks/Pokeri `AGENTS.md`.

## G. Documentation

75. **AGENTS.md = standing rules and pointers only**; it is re-read every turn,
    so keep it small. Detail goes in the matching `docs/` file.
    — RoF/Pokeri/Revs `AGENTS.md`.
76. **One work queue (`docs/open-work.md`); remove completed entries; history
    lives in git.** Adding an item needs a demonstrated defect, not "verify more".
    — Slicks `docs/open-work.md`; Revs `AGENTS.md`; Vette `AGENTS.md`.
77. **Completed experiments are not instructions to repeat them.** Keep one-line
    dispositions (kept/rejected + reason), not logs. — Pokeri `AGENTS.md`,
    `docs/performance.md`; Slicks `docs/performance.md`.
78. **Mark evidence level (MEASURED/DERIVED/INFERRED)**; a plausible name is not
    a fact. — Pokeri `AGENTS.md`; Vette `AGENTS.md`; Revs `AGENTS.md`.
79. **Record names and entry points the moment they are found** (rename list,
    `entrypoints.csv`); wrong names tax every later step.
    — RoF `AGENTS.md`, `docs/postmortem.md` §1.2; Revs `docs/method-lessons.md`.
80. **A rename is a re-read of the sentences** built on the old name.
    — Revs `docs/method-lessons.md`.
81. **Stale figures are wrong by default**; a doc that quotes a number names
    build, window and date. Obsolete descriptions are deleted, not annotated.
    — RoF `AGENTS.md`; Slicks `docs/fidelity.md` (removed "atomic saves").
82. **Reduce logs to conclusions in versioned docs before deleting them**; do not
    remove another task's files or runs. — Pokeri `docs/testing.md`.
83. **`tmp/`/`ref/` may hold the only copy of inputs; inspect before cleaning.**
    — Vette `AGENTS.md`, `docs/development.md`.

## H. When to stop optimising

84. **Stop when the user-defined bar is met**; do not reopen closed candidates for
    margin. — RoF `AGENTS.md` (flight perf closed at 25 FPS).
85. **Stop when the profile is flat and experiments move totals by <1%**; fix the
    symptom structurally instead (Slicks: real-time clock + adaptive publication
    made game speed correct, worst-case 20 ms declared out of scope).
    — Slicks `docs/frame-pacing.md`, `docs/performance.md`, `docs/phases.md`.
86. **Closed means measured at ~0 or negative, not pessimism about small numbers**;
    several honest 5-point wins add up. — RoF `docs/perf-budget.md`.
87. **Build an experiment behind a switch, measure, let the number decide**; keep
    its oracle if reusable and say plainly it did not ship. Check whether an
    earlier change already took the same prize. — Revs `docs/method-lessons.md`.
88. **Below instrument resolution, stop re-running for a better number**; use the
    static count or differential as the evidence. — RoF `docs/flight-perf-log.md` §15.4, §24.4.
