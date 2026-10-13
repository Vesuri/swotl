# 68000/68020 code generation and optimisation

The merged rules (cost model per target, 68000 versus 68020, reading compiler output, loops,
inlining, registers, arithmetic, hand-written assembly, code generators and translators, size
versus cycles) are maintained in AmigaXDev `docs/reference/m68k-optimisation.md`; add generic
lessons there. Measuring: [perf-method.md](perf-method.md); x86 lowering:
[translation-lessons.md](translation-lessons.md), [translator-design.md](translator-design.md).

## This target

- A1200, 68020, AGA, 2 MiB Chip, no Fast RAM: all code and data are Chip accesses, the 256-byte
  instruction cache is the only cache, so executed code volume is the main cost.
- Measured on FS-UAE's 68020 with 8 MiB Fast:

| Fact | Source |
| --- | --- |
| Generated code costs ≈ 1.09 cycles per code byte + 2.27 per data read + 3.07 per data write (per-PC fit, R² 0.83); bytes inside cached loops are nearly free | `speed-plan.md` §6 |
| Probes: indexed Fast word/long load 4.16/4.16 cycles, immediate word/long store 6.22/8.28; `and.l #$ffff,dN` 6.1 vs `tst.l` 2.1; high-byte write `ror`/`move.b`/`ror` 6.4 vs `BFINS` 4.1; untaken short branch 1.3–1.4; immediate word/long compare 4.0/6.4–6.6 | round 1 (git `781975e`, speed plan T2–T8) |
| Moving code shifts the cost of untouched instructions by up to ±0.7% (branch-target alignment, i-cache placement) | `speed-plan.md` §5 |

- Guest memory is byte-reversed (speed-plan R1: guest byte at linear L at host TOP − L), so a
  little-endian guest word is a native big-endian word one byte below
  ([translator-design.md](translator-design.md)).
## Standalone instruction probes

Run `bash amiga/cost_probe.sh` (no game build). It generates a separate
executable from `tools/m68k_cost_probe.py`, checks arithmetic/load/store
results on target, and profiles three fresh boots: 50 PAL fields each,
first/last discarded. No breakpoint is active inside the capture. Code and
data must be Fast RAM, with the data base four-byte aligned. Each case must
execute at least 1,000 times. `COST_PROBE_PLANT=1` deliberately corrupts an
arithmetic oracle and must fail; GDB's register cache is flushed after profiling.
Captures are deleted after reporting; source, ELF, disassembly, launch options,
hashes, logs and JSON reports remain in a private `tmp/cost-probe.*` directory.

Measured 2026-10-13, `df529b7` checkout plus the standalone probe (game code
not linked): default A1200/68020, PAL, 2 MiB Chip + 8 MiB Fast, no warp;
FS-UAE SHA-256 `ffd5c960322f445e72a02bc47c84312dfb8b189ce8327b55e1211d7fa170148d`,
probe ELF `4a0eed682b7996d18240eb99d0f4f4ea7e8837edf677c6ea8fd60acc092b6a63`.
Reports: `tmp/cost-probe.PkzNkg/pass-{1,2,3}.json`; 68 cases, minimum 2,304
executions per case per run. Capture metadata: clock 28,375,160, cycle unit
128; values below are the profiler's emulated CPU cycles per selected PC,
excluding operand setup, result checks and loop control. They are not
instruction latency or physical 68020 timings.

| Operation | Cache-sized loop (8 copies) | Oversized loop (128 copies) |
| --- | ---: | ---: |
| `mulu.l` 32×32→32 or →64 | 4.125 | 4.125 |
| `divu.l` 32÷32 quotient, `divul.l` quotient/remainder, 64÷32 | 4.120–4.142 | ≈ 4.125 |
| Control: `mulu.w`, fixed 1234h × 17 | ≈ 22.0 | ≈ 21.125 |
| Control: `divu.w`, fixed 123456h ÷ 257 | ≈ 36.0 | ≈ 35.125 |
| Control: `move.l d1,d0` | 2.0 | 1.125 |

Long arithmetic covers zero, sparse and dense operands, reset before every
operation; division has nonzero divisors and representable quotients. The
model charges long arithmetic far less than the word controls: these are
**emulator costs, not hardware costs**. The translator's cost-model weights
are unchanged. Per-PC costs depend on loop shape (even register controls
are cheaper in the oversized arm); this is not a cache-off test.

Fast RAM `move.w/l (a0),d0` and `move.w/l d0,(a0)`; ranges span all three runs:

| Access | Address mod 4 | Cache-sized | Oversized |
| --- | --- | ---: | ---: |
| Word load | 0, 1, 2 | 3.306–3.319 | 3.415–3.424 |
| Word load | 3 | 6.308–6.315 | 6.415–6.423 |
| Word store | 0, 1, 2 | 3.525–3.539 | 3.428–3.437 |
| Word store | 3 | 6.524–6.536 | 6.433–6.442 |
| Long load | 0 | 3.312–3.322 | ≈ 3.415 |
| Long load | 1, 2, 3 | 6.307–6.319 | 6.415–6.424 |
| Long store | 0 | 3.524–3.532 | ≈ 3.428 |
| Long store | 1, 2, 3 | 6.526–6.543 | 6.428–6.439 |

Crossing a four-byte boundary adds approximately three model cycles. An odd
word address with residue 1 does not cross it and has no measured penalty.
These are direct Fast RAM accesses, not indexed guest-memory lowerings,
Chip RAM accesses or whole-game speed measurements.
