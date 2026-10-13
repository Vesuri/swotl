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
- Remaining [arch] 68020 costs to microbenchmark on the A1200 model: [open-work.md](open-work.md).
