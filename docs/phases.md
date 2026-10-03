# Phases and gates

Each gate must pass before work of the next phase is committed. Exit
criteria name generated-code coverage, not pictures.

| # | Phase | Exit |
|---|---|---|
| 1 | PC reference loop | Original runs unattended from a disposable copy of `ref/`; deterministic input; root image and each in-scope overlay captured at a named state; capture reproduced from file + loader semantics. |
| 2 | Static/live map | PLINK mechanism, overlay load areas, entry points, indirect targets, interrupts, ports and VGA use mapped; static and trace agree; no executed byte unclassified. |
| 3 | x86 semantics | Decoder + IR cover every opcode present; randomized instruction and short-block differential vs Unicorn is clean. |
| 4 | 68020 backend | Generated blocks match the x86 oracle on the host 68k core; audits pass (no unexpected spills, full-flag materializations, dispatcher exits). |
| 5 | First vertical slice | A traced subgraph runs on the A1200 model from generated code only, with the minimum runtime; RAM/frame matches the reference at a named point. |
| 6 | Whole game | All overlays translated; runtime surfaces complete; lockstep vs DOSBox clean over the reference milestones; coverage report shows HLE share and zero unclassified. |
| 7 | Performance | Profiled on target; optimizations in translator or G3 table only; every fidelity gate still green. |
| 8 | Package | WHDLoad slave, installer for the user's own data, release audits ([release.md](release.md), [whdload.md](whdload.md)). |
