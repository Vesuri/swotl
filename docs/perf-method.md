# Performance method

The method (order of work, units, instruments, A/B discipline, the experiment loop, pricing,
budgets, when to stop, and the traps that made measurements lie) is maintained in AmigaXDev
`docs/reference/measurement-method.md`; 68020 cost facts in `docs/reference/m68k-optimisation.md`
and this target's cost model in [m68k-optimisation.md](m68k-optimisation.md). The speed work and
its binding rules: [speed-plan.md](speed-plan.md).

## SWOTL instruments

- **Profile report**: `tools/profile_report.py CAPTURE ELF [--count LABEL]` decodes a
  `monitor profile N "" FILE` capture (gdb fixture, no breakpoints in the
  window) to class, module, guest routine/instruction (generated labels) and
  runtime shares; records without a PC are code outside the first hunk and
  ROM (today the Kalms c2p in hunk `code`).
  Module instruction counts include ordinary entries and R6 `_bp` copies;
  guard, poll and other helper entries add cycles but not guest instructions.
  These are label-derived counts; use lowering cost for semantic counts across aliases.
- **Lowering cost**: `tools/lowering_cost.py CAPTURE ELF` groups the
  same capture by x86 form (executions, cycles and 68k instructions per
  execution) and the generated code by 68k mnemonic and role. Use the matching
  ELF and generated `.s`/`.ir` (`--gen`). Ordinary and `_bp` entries count;
  helpers retain costs only. Shared-address entries follow the original IR
  successors and observed incoming guest edges, across host interrupt work;
  direct destination entry does not count an aliased jump. Reports distinguish
  entry-PC hits from recovered zero-code entries. Missing/ambiguous predecessors
  or unresolved indirect transfers fail loudly instead of inventing a ratio.
- **Counts**: `tools/host_census.py MILESTONE [--labels L…] [--strops]
  [--vram]` (host run between milestone snapshots: label executions, string-op
  elements, A0000h writers and rows per frame); `amiga/perf_frames.gdb` (frame
  period and a capture, [speed-plan.md](speed-plan.md) §4).
- **Target A/B**: `tools/ab_labels.py CAP_A ELF_A CAP_B ELF_B METER_A
  --meter-b METER_B` uses both meters' exact 68k execution counts. Each
  required target PC must match the host instruction and have samples. Changed-label
  comparisons include complete shared-address alias groups from both binaries.
  Guest-entry weighting alone confounds REP length/path changes with speed;
  per-PC weighting fixes those counts, while branch timing at a PC still
  reflects the capture's taken mix. Keep both reports; neither proves fidelity.
- Profile captures run with no breakpoint inside the window; the matching ELF is kept with the
  capture. Per-step speed decisions use the deterministic fixed-workload meter and the
  layout-blind lowering meter of [speed-plan.md](speed-plan.md) §3–4, not frame medians.
