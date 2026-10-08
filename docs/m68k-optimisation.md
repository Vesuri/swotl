# 68000/68020 code generation and optimisation

Merged from the sibling ports. Tags: **[020]** measured on a 68020 (Slicks, Vette,
Pokeri A1200); **[000]** measured on a 68000 (RoF, Revs A500; cycle figures are
68000 timings and do **not** transfer); **[both]** holds on both; **[arch]**
architectural fact not measured by any sibling. Verify [arch] items on the
target model before relying on them. **GEN** marks items a code generator must
encode. Process: [method-lessons.md](method-lessons.md); measuring:
[perf-method.md](perf-method.md); x86 semantics/lowering:
[translation-lessons.md](translation-lessons.md); hardware:
[amiga-arch.md](amiga-arch.md).

Sources: Slicks `docs/performance.md`, `rendering.md`, `native-graphics-abi.md`,
`CLAUDE.md`; Vette git `56032f5^:docs/perf-method.md` (§A1200 C2P entries),
`docs/performance.md`; Pokeri `docs/performance.md` §Alignment, `docs/architecture.md`;
RoF `docs/m68k-optimisation.md`, `docs/flight-perf-log.md`, `docs/asm-migration-plan.md`;
Revs `docs/m68k-optimisation.md`, `docs/perf-method.md`.

## 1. Cost model for this target (A1200, 2 MiB Chip, no Fast RAM)

| Fact | Tag | Source |
| --- | --- | --- |
| All code and data live in Chip RAM; a Chip access ≈ 7 CPU cycles, a cached instruction ≈ 2.5 | [020] | Slicks `performance.md` §Cost model |
| 68020 has a 256-byte instruction cache and **no data cache**; every longword fetched from outside the I-cache is a Chip access | [020] | Slicks |
| **Executed code volume, not arithmetic, is the main cost**; compiled-C profiles are flat | [020] | Slicks |
| A literal (instruction-for-instruction) asm rewrite gained <1%; gains come from executing less: cache-sized inner loops, state in registers, hoisted invariants, skipping provably unchanged work | [020] | Slicks |
| Per-object overhead adds up (ex: 32 stationary objects, ~1000 px, once ~30% of a track's work) | [020] | Slicks |
| Chip-destination writes cost 1.5× Fast-destination writes for the same C2P routine | [020] | Vette `C2P_SPLIT` |
| With no Fast RAM, every lookup table is a Chip read; a table must beat the ALU sequence it replaces (ex: velocity reciprocal table slower than `DIVS`) | [020] | Slicks §Rejected |
| Reduce the number of memory accesses; never justify a buffer as "cheaper RAM" | [both] | RoF/Revs `CLAUDE.md`; on this target true by construction |
| Blitter shares the bus; it pays only when it **replaces** CPU work (D-only clear), not beside it | [000] | Revs `m68k-optimisation.md` §MODE 7 |
| A500 cycle→ms needs a ~1.6 contention factor; not measured on A1200 | [000] | Revs §EIGHT ADDRESS REGISTERS |
| SWOTL measurement model (68020 + 8 MB Fast, FS-UAE): generated code costs ≈ 1.09 cycles per code byte + 2.27 per data read + 3.07 per data write (per-PC fit, R² 0.83); bytes inside cached loops are nearly free | [020] | SWOTL `translator-plan.md` §3 |
| Probes on that model: indexed Fast word/long load 4.16/4.16 cycles, immediate word/long store 6.22/8.28; `and.l #$ffff,dN` 6.1 vs `tst.l` 2.1; high-byte write `ror`/`move.b`/`ror` 6.4 vs `BFINS` 4.1; untaken short branch 1.3–1.4; immediate word/long compare 4.0/6.4–6.6 | [020] | SWOTL round 1 (git `781975e`, translator-plan T2–T8) |
| Moving code shifts the cost of untouched instructions by up to ±0.7% (branch-target alignment, i-cache placement) | [020] | SWOTL `translator-plan.md` §2 |

## 2. 68000 vs 68020 — what changes

| Topic | 68000 | 68020 | Evidence |
| --- | --- | --- | --- |
| Instruction cache | none: unrolled cold arms are never fetched, so 282→785 instructions cost nothing | 256 B: loop must fit; Vette 64-px C2P unroll regressed 2.927→2.711 vs 32-px | Revs §HAND-UNROLL [000]; Vette [020] |
| Data cache | none | none | Slicks [020] |
| Scaled index `(d8,An,Xn*4)` | absent: shift + copy base + add per lookup | present: Vette C2P kernel −21.6% from scaled long index | Vette §scaled C2P indexing [020] |
| Word index sign extension | — | scaled `Xn.w` is sign-extended; tables addressed from their midpoint (rotated by 32768) removed 8 index clears/32 px, −4.4% | Vette §signed C2P indexing [020] |
| Bitfield ops (`BFINS`, `BFEXTU`, `BFFFO`) | absent (`bfffo` emulated with tables cost +27.56 ms in one Revs build) | present; Slicks sparse-pixel C2P uses per-pixel `BFINS` into all planes | Revs `perf-method.md` L1612 [000]; Slicks `rendering.md` [020] |
| Word/long at odd address | address-error fault | permitted, extra bus cycles | Revs/RoF [000]; [arch] for 68020 |
| Longword at addr ≡ 2 mod 4 | — | extra bus cycle; 101 hot globals misaligned → ~8% slower cold start, 0.65% gameplay; fix `alignas(4)` + build audit | Pokeri §Alignment [020] |
| 32-bit `mul`/`div` | none: GCC emits `__mulsi3` etc. (~200–600 cycles); hard ban + objdump audit | `mulu.l`/`divu.l`/`divs.l` exist [arch]; Slicks uses direct 68020 constant division and found `DIVS` faster than a reciprocal table | RoF/Revs `CLAUDE.md` [000]; Slicks [020] |
| Shifts | `lsl.l #8` 24, `ror.w #8` 22 cycles (2n+8): byte-swaps and pair builds are expensive | barrel shifter; `ror.w #8` ≈ 1.8 cycles on the SWOTL model, i.e. its 2 code bytes | RoF `m68k-optimisation.md` [000]; SWOTL `translator-plan.md` §3 [020] |
| `(d16,An,Xn)` / 32-bit displacements | only `(d8,An,Xn)`; far table needs its own An | full-format EA with 16/32-bit displacements [arch] | Revs §WRITING A HAND-ASM ROUTINE [000] |
| Published cycle tables (abs.l 16, d16(An) 12, (An)+ 8, `bne.s` 8/10, `bne.w` 12) | valid | **do not use**; price by memory accesses + code bytes fetched outside the cache, then measure | RoF/Revs [000]; Slicks [020] |
| `movem` prologue cost | 10 regs ≈180 vs 3 regs ≈68 cycles; can exceed a whole win | still scales with registers × Chip accesses (derived) | RoF §pointer-walk [000] |

## 3. Generator rules (GEN)

### Registers and state
- **GEN Keep guest registers resident across blocks; materialise full guest state
  only at a proven boundary; no CPU struct in translated regions.** — Slicks `CLAUDE.md`, `architecture.md`.
- **GEN One base register for guest RAM**: `abs.l` operands → `d16(An)` saved 16→12
  cycles and 6→4 bytes per operand **and one HUNK RELOC32 per operand** (20 folds:
  −14,352 B). Revs: one `a5 = mem+$628F` reached all cells below `$E28E` via
  negative/positive `d16`. Derived for x86: a base at segment+`$8000` puts a whole
  64 KiB segment in `d16` range. — RoF `CLAUDE.md`, `flight-perf-log.md` §23/§26 [000]; Revs [000].
- **GEN A hoisted pointer is a second representation**; if every input is already
  live, hoisting buys an add and sells a register (spill). When the register file is
  saturated, the question is whether to hoist at all. — Revs §A HOISTED BASE POINTER [000].
- **GEN Address taken = memory for the whole loop**: state reachable through a pointer
  or an escaping struct is reloaded per iteration (ex: value-in/packed-out ABI
  −4.79 ms; locals synced only around the cold call −6.58 ms). — Revs `perf-method.md` [000].
- **GEN Pack registers only where one pack serves many reloads** (no byte-insert
  instruction: pack/unpack 3 bytes ≈ 40 cycles on 68000; `BFINS` on 68020 [arch]).
  — Revs `perf-method.md` [000].
- **GEN Saturation tells**: `n(sp)` operands on loop invariants; pointers living in `Dn`.
  Fix by splitting fused find/act loops rather than hand-tuning. — Revs §EIGHT ADDRESS REGISTERS [000].
- **GEN When a callee uses all 15 registers, cross-call state has nowhere cheaper
  than its own memory cell.** — Revs §span PASS [000].
- **GEN C ABI at runtime exits**: GCC callees clobber d0/d1/a0/a1; a5/a6 may be the
  frame pointer; arguments pushed as longs right-to-left. Oracles must check
  stack, callee-saved registers and return path. — Revs §WRITING A HAND-ASM ROUTINE; Slicks `performance.md` §Correctness guards.
- **GEN Width**: spell byte ops in byte width (`subq.b`), not as masked word ops; a mask
  needing a constant register caused a spill. — Revs §SPELL AN OPERATION [000].
- **GEN Make store targets statically known**: a store to a constant guest RAM address
  needs no device/bus check; only genuinely variable destinations do (ex: −1.17 ms
  from removing an unreachable range test). — Revs `CLAUDE.md`, `perf-method.md`.

### Flags / CCR
- **GEN Flags stay virtual; compute a flag only when a reader is live; reuse CCR
  where semantics agree.** Parity/aux carry only when live. — Slicks `architecture.md`, `phases.md` §Phase 4.
- **GEN Replay only escaping flags**: a guest flag write costs several stores;
  removing push/pop-flags memory traffic gave +5.9% FPS. — Revs `perf-method.md` [000].
- **GEN Reuse an instruction's own flags** (V from `add.w`). — Revs `perf-method.md` L2890–2901.
- **`ROR`/`ROL` do not touch X; `MOVEQ` does not write X.** Seed X with `lsr.b #1`;
  extract with `moveq #0` + `addx.b`. Found only by on-target sweep (4500/40000
  failures). — Revs §ROR/ROL [both, ISA].
- **`MOVE` sets N/Z; `EXG` sets no flags** (`tst / exg / bmi` works, `tst / move / bmi`
  does not). — Revs §span PASS [both, ISA].
- Patched/replaced routines preserve all live registers and **all five CCR bits incl.
  X** (Vette copy-row: final-byte N/Z and X). — Vette `performance.md`; Pokeri/Vette `CLAUDE.md`.

### Endianness and byte swaps
- **GEN Guest RAM stays byte-exact; every native word/long access states its endian
  and alignment rule.** — Slicks `CLAUDE.md`. SWOTL translator-plan R1 (user,
  2026-10-08) moves guest memory to a byte-reversed layout (guest byte at linear L
  at host TOP − L): a little-endian guest word is then a native big-endian word one
  byte below.
- **Never alias LE guest memory through wide pointers** except uniform-byte
  broadcast (all bytes equal); lint for it. Host-green/target-garbage happened.
  — RoF `m68k-optimisation.md`; Revs `CLAUDE.md`.
- **Pair build cost [000]**: `(hi<<8)|lo` = 74 cycles (46 shifting); `lo + 256*hi` = 58;
  two pairs added 152→98. — RoF `m68k-optimisation.md`.
- **High byte without a shift [000]**: `move.w d,-(sp)` / `move.b (sp)+,x` 24 vs `lsr.w #8` 38.
  — Revs `perf-method.md` L3017–3031. On 68020 re-measure: barrel shifter [arch].
- **A native big-endian copy of a guest word keeps its low byte at offset +1** (Slicks
  `sui_color_slot`, `1(a2)`). — Slicks `native-graphics-abi.md`.
- **GEN Prefer keeping wide guest values in registers in native order and converting
  only at the memory boundary** (derived from the above; cost is per access).

### Branches and dispatch
- **GEN Leave branch sizes to the assembler** (`jbcc`/unsized `bne`); a hand-sized short
  branch that stops reaching is an error, and `bcc.s` to the very next instruction is
  illegal. — Revs §WRITING A HAND-ASM ROUTINE, §MODE 7.
- **GEN Cold arms in `.subsection 1`** so the hot path falls through without branching
  over cold code (GNU as). — Revs §WRITING A HAND-ASM ROUTINE.
- **GEN Conditional back edge, not `bra` at bottom + exit in middle** (rotated loop ≈ 8
  cycles/unit bookkeeping on 68000). — Revs §LOOP ROTATION [000].
- **GEN Indexed dispatch**: PC-relative `jmp tab(pc,d.w)` of `bra.w` (table within 8-bit
  displacement, i.e. immediately after) beat a compare chain (36 flat vs 49.5 weighted,
  −99 cycles/call); a 256-byte decode table with `$FF` = "cannot mean" beats a compare
  chain for a byte with ~17 legal values; `pea (a5,d7.w)` / `rts` for a computed entry.
  — RoF `asm-migration-plan.md` §Phase 9 [000]; Revs §span walk.
- **GEN Computed entry into unrolled code** for variable-length scans/fills
  (ex: `move.l (a0)+,d0 / beq.s` ×20). — Revs `perf-method.md` L2850–2879 [000]; on 68020
  check the unrolled body still fits the 256-byte cache (Vette).
- **GEN A dispatch must not modify the value it dispatches on.** — RoF `asm-migration-plan.md` §Phase 9.1.

### Loops and memory access
- **GEN Post-increment walks, pointer-compare exits**; test the pointer whose final
  value is used after the loop (else it is reconstructed with a shift/multiply).
  — RoF/Revs `m68k-optimisation.md`.
- **GEN Unroll for constant displacements** (`d16(An)` instead of pointer bumps; one back
  edge for N units); pick the factor from the run-length distribution. On 68020 the
  limit is the I-cache (Vette: 32 px yes, 64 px no). — Revs §HAND-UNROLL; Vette.
- **GEN Batch sequential bytes into `move.l`** when the address is even (68000) or
  4-aligned (68020 speed). "Odd offset" ≠ odd address; abutting runs merge.
  — RoF `m68k-optimisation.md`; Pokeri §Alignment.
- **GEN Don't index→address per step**: deriving an address from a cell index each step
  (lsl/lea/and) cost 76% of a walk (+25.46 ms); a stride multiply in an address emitted
  `__mulsi3`. Walk pointers. — Revs `perf-method.md` [000].
- **Longword strided copy** with unrolled `move.l` (8 per 32 B): 2.366× the C path.
  Write pipelining (interleave lookups between plane writes) **lost** (2.521→2.315)
  unless it also cuts instructions. — Vette §Fixed-stride publisher, §C2P destination split [020].
- **Skip unchanged work** (dirty flags, memoised outputs keyed on inputs); shadow-compare
  scans are themselves full scans. Narrowing a dirty signal requires surveying every
  reader. — RoF `m68k-optimisation.md`; Revs `method-lessons.md`; Slicks `performance.md`.
- **Reject-path floor**: a "check before doing" scheme re-reads the byte the check
  avoids; it recovers only the bookkeeping. — RoF `perf-budget.md`.

### Arithmetic
- **Exactness first**: sign-magnitude multiply → `mulu.w` + conditional `neg`, not
  `muls.w` + `asr` (off by one); some "multiplies" are not plain products (table).
  — RoF `flight-perf-log.md` §3.
- **Constant division/modulo**: fold `⌊n/(ab)⌋ = ⌊⌊n/a⌋/b⌋`, compare-subtract wraps,
  `(ab) mod m` identities. — RoF `m68k-optimisation.md`. On 68020: direct division
  (Slicks `slicks_div100`, oracle-tested).
- **Divide→table** only when it beats the divide on this target (Revs 68000: 512-byte table
  replaced `divu`+`divs` ≈300 cycles; Slicks 68020: reciprocal table lost to `DIVS`).

## 4. Runtime support code (GCC, if any C remains)

Translated code is generated asm; these apply to the runtime/platform C.

| Rule | Source |
| --- | --- |
| `-O3` for hot TUs (Slicks: `-O2` worse max, `-Os` 7–9% worse) | Slicks `performance.md` |
| Audit objdump for `__mulsi3`/`__divsi3`/`__udivsi3`/`__modsi3`/`__umodsi3` on every link | RoF/Revs/Vette `CLAUDE.md` |
| `alignas(4)` on even-sized ≥4-byte globals; ELF audit rejects misalignment | Pokeri `CLAUDE.md` [020] |
| Freestanding `memset`/`memcpy`/`memmove` are byte loops (24/28/~40 cycles/byte [000]); GCC turns fill loops back into `memset` — use `-fno-tree-loop-distribute-patterns` | Revs `perf-method.md`; RoF |
| `__chip` static initialisers are discarded (`.MEMF_CHIP` is BSS); fill at runtime | RoF/Pokeri `CLAUDE.md` |
| Size-changing edits flip inlining; count `jsr <hot leaf>` (and `.part.N`/`.constprop.N`) in objdump after each edit | Revs §MAKING A FUNCTION SMALLER |
| Growing a shared `always_inline` leaf multiplies by its call sites; diff per-function sizes and intersect with call sites | Revs §FOURTH CASE |
| A short list with an explicit count is peeled/unrolled by its declared bound; terminate positionally | Revs §THIRD CASE |
| `#pragma GCC unroll` honoured in one Revs case (GCC 15.1, 8-trip loop) and ignored in another (-O2, byte-identical) — hand-unroll when it matters | Revs §EIGHT ADDRESS REGISTERS vs §HAND-UNROLL |
| `__builtin_expect` on the mismatch condition keeps the common case fall-through | Revs §EIGHT ADDRESS REGISTERS |
| 3+ pointer loops: GCC makes one index + N bases `(0,An,Dn.L)`; pointer-compare exit + post-increment all | RoF `m68k-optimisation.md` |
| Byte-typed indices and volatile round-trips blind loop analysis | RoF `m68k-optimisation.md` |
| `volatile` only for state something actually races | RoF `flight-perf-log.md` §20.2 |
| A call boundary is an aliasing barrier (same note: 67 cycles inline, ~2700 via `jsr`) | Revs `perf-method.md` |
| Size accepted by `.text` for cycles, by final HUNK (incl. relocs) for bytes | RoF `m68k-optimisation.md` |

## 5. Assembler (GNU as, Motorola syntax)

- `m68k-amiga-elf-as --register-prefix-optional`; `.macro` with `\name\()_suffix` pasting;
  `.type`/`.size` so the PC sampler names routines; put the `.size` end label in
  subsection 1 or use a `.L` end label (a plain end symbol names the next function).
  — Revs §WRITING A HAND-ASM ROUTINE.
- `|` is the comment character: `#A|B` silently truncates; name constants with `.equ`.
  — Revs §MODE 7.
- Parenthesise macro arguments in expressions (`\y*ROWB` with `y=2*0+1`). — Revs §MODE 7.
- A sabotage that deletes the instruction a short branch skips must leave a same-size
  no-op. — Revs §WRITING A HAND-ASM ROUTINE.
- Assemble only the routines that need 68020 modes for 68020 if the rest must stay
  68000-compatible (Vette `C2P.s`). — Vette §scaled C2P indexing.
