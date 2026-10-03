# Translator design

Skeleton for phase 5 on (phases 3–4 done: decoder, IR, 68020 backend). Fixed parts are decided; decision points D1–D16
list options, the evidence that settles them (from
[plan-reference-map.md](plan-reference-map.md)) and the default if evidence
does not object. Replace each decision with its outcome when settled.
Overview and guardrails: [architecture.md](architecture.md).

## Fixed

### Components

| Module | Role |
|---|---|
| `translator/image.py` | proved root/overlay images (`tools/swotl_model.py`), annotations, run-time bytes of self-modified regions |
| `translator/decode.py` | own table-driven 8086 decoder; 186+/FPU opcodes raise (none in SWOTL) |
| `translator/cfg.py` | recursive descent from `annotations/` seeds; CS along flow; PLINK manager calls and parent chain; self-modified regions recorded, not decoded |
| `translator/ir.py`, `sem.py` | IR ops; lifting of every decoded instruction |
| `translator/interp.py` | host IR interpreter (the semantics under test) |
| `translator/gen.py` | `make gen`: `build/gen/<module>.ir` with hash header; coverage report (G6) |
| `translator/check.py` | G1 header/digest/regeneration check, G2 lint |
| `translator/lower.py` | one decoded instruction -> 68020 text under the register contract (templates per op family; the IR stays the semantic reference) |
| `translator/flags.py` | flag demand: per-instruction store set and CCR fusion with the next reader |
| `translator/emit.py` | program mode: global flag liveness, leaders, labels, transfers, `build/gen/<module>.s` |
| `translator/support.py` | state-block equates, flag/BCD helpers (`build/gen/support.s`) |
| `tests/` | `test_decode.py` (Capstone), `x86_diff.py` + `x86_sabotage.py` (Unicorn x86-16), `m68k_diff.py` (instructions/short blocks, test mode) + `m68k_blocks.py` (generated program, traced blocks) + `m68k_sabotage.py` (Unicorn 68020), `test_guards.py` (G1/G2 plants), `audit.csv` (audit expectations), `uc.py` (ctypes binding) |

Language: Python 3.11 (sibling tooling, Capstone binding present). Offline,
so translator speed is irrelevant.

### IR

Specification in `translator/ir.py`. Per instruction: an op list over
width-typed temporaries with local labels (REP loops, CL-count guards,
divide checks), explicit stack traffic, and one exit (`jump`, `call`,
`ret`, far forms, `int`, `fault`) or fall-through. Flags: `flags kind w a b
r` defines the status flags of `kind` and marks the undefined ones
(`FLAG_KINDS`; count-dependent for shifts/rotates); reading an undefined
flag is an error, never a value. Guest registers 16-bit with explicit
8-bit halves; segment registers separate; FLAGS bits 12–15 as `flagsx`.
Listings in `build/gen` carry `(module, offset, CS:IP)` per instruction.

### Generated code contract

Registers (D4, fixed program-wide; spill audit 0):

| 68k | Guest | Rule |
|---|---|---|
| d0 d1 d2 d3 d4 d5 | AX CX DX BX SP BP | 16-bit, upper word always 0 (so `(base,Rn.l)` indexes) |
| a4 a5 | SI DI | same; written via `movea.l` of a cleaned value |
| a1 a2 a3 | ES SS DS base | a6 + seg*16, recomputed on every segment write |
| a6 | guest RAM | linear 0, byte-exact little-endian; state block below |
| d6 d7 a0 | scratch | a0 also CS base (`lea (cs*16,a6)`); CS is static per instruction |
| a7 | native stack | `jsr`/`rts` only |

State block (`G_*` equates at a6-16..a6-1): `G_FL` low byte = CCR image of
CF (C), OF (V), ZF (Z), SF (N), X not guest state; PF = even parity of
`G_PF`; AF = bit 4 of `G_AF`; `G_DF`/`G_IF`/`G_TF` bytes; `G_FX` = FLAGS
bits 12–15; `G_ES`/`G_SS`/`G_DS` segment values. Run-time CS =
`LOADSEG+link`, `LOADSEG` = 0822h (the reference load segment, so guest RAM
diffs directly); relocated words in instructions are emitted as
`LOADSEG+value`.

- Word access: `move.w` + `ror.w #8` (68020 allows odd addresses); a word
  at offset FFFFh is two consecutive linear bytes, offsets wrap at 64 KiB.
- Flags (D6): a setter stores the defined flags live after it (`flags.py`,
  global liveness in `emit.py`). The next instruction reads the CCR directly
  when it is not a leader, reads only flags the setter's 68k op holds with
  x86 meaning (`CCR_OK`), and the setter's tail leaves the CCR intact; else
  readers load `G_FL`. PF/AF are stored as result / `a^b^r` bytes only when
  live. adc/sbb/rcl/rcr derive X from `G_FL` and preset Z for `addx`/`subx`.
- Calls (D1): the guest stack stays byte-exact (return CS:IP pushed as the
  CPU does); a guest call is `jsr`, `ret`/`retf` pop into d7/d6 and `rts`;
  the return site checks d7 (and d6) against its own IP/CS and jumps to
  `rt_ret_mismatch` otherwise. A PLINK manager call's return site is 2 bytes
  later (the manager advances the return IP).
- Indirect transfers (D7): compare chain over the known targets
  (`annotations/indirect.csv`); a proved switch table falls back to
  `rt_stop_unknown`, other sites to `rt_dispatch_near`/`rt_dispatch_far`
  (target in d7, CS in d6; the run-time table holds the program's entries).
- Runtime entries (`jsr`, contract in registers): `rt_int` (d7 next IP, d6
  vector; services read no guest flags and leave undefined-by-them flags in
  the state block), `rt_fault` (divide error; returns to re-execute),
  `rt_in8/16`, `rt_out8/16` (d7 port, d6 value), `rt_halt`,
  `rt_stop_unknown` (prints and halts; never resumes).
- Generated files: `build/gen/<module>.s` and `support.s`, header = SHA-256
  of translator sources, annotations and input image (`make gen-check`).

### Annotations (`annotations/`, CSV)

`entries.csv`, `indirect.csv` (site -> targets), `data.csv` (ranges),
`hle.csv` (guest range, service, reason, oracle; starts empty), `names.csv`
(name, evidence class).

### Tests

- Instruction differential (`make test-m68k`): the x86 corpora (forms,
  space, boundary, blocks) lowered in test mode (every exit through a stub,
  all flags live at the end), Unicorn x86-16 vs Unicorn 68020 on the same
  guest-memory layout; registers, segments, CS:IP, defined flags, FLAGS
  12–14, memory, OUT sequence, interrupt/fault.
- Block differential (`make test-blocks`): the generated program as emitted,
  run from executed leaders to the first transfer with random states; flags
  compared where live at the successor reached; calls also run the return
  protocol (right IP reaches the return site, wrong IP `rt_ret_mismatch`).
- Audits (`make gen`): spills, full-flag materializations, PF/AF stores,
  dispatcher exits, `stop_unknown` sites against `tests/audit.csv` (above
  expected fails), plus flag stores/merges/loads and return checks; HLE count.

## Decision points

| # | Decision | Options | Evidence | Default |
|---|---|---|---|---|
| D2 | Overlay model | (a) all translated modules resident; (b) translated modules loaded on demand like PLINK | [plink.md](plink.md): 9 in-scope modules, ~0.38 MB code; 57 loads in the corpus; a load never replaces the caller; parents reload with children | (a) if it fits D15 |
| D8 | Interrupt delivery | (a) runtime runs translated guest ISRs at safe points (loop back-edges, calls); (b) HLE of the game's ISRs | [external-surface.md](external-surface.md): guest installs INT 00h/05h/08h (SPAZ tick)/23h/24h; INT 09h/1Ch stay BIOS | (a) |
| D9 | Graphics drivers | (a) HLE at RTSVGA's call table on the dA JoRMaS layer; (b) translate driver + emulate VGA ports/memory | chained mode 13h via INT 10h, no VGA ports, no page flip; entries = PLINK thunks with id 3 | (a), with RTSVGA itself as oracle |
| D10 | Sound | SPAZ HLE at its table; AdLib music method open (OPL -> Paula) | 2.5; open-work AdLib item | HLE |
| D11 | String ops | per-element loops, one body per DF (done); `rep movs/stos` fast paths when DF and overlap provable | corpus + profile | fast paths in phase 7 |
| D15 | Memory target | (a) 2 MiB Chip only (Slicks); (b) require Fast RAM | guest RAM need + generated code size: first `make gen` assembles to 1.29 MB of 68020 code for all modules (x86 code ~0.4 MB) plus 1 MiB+ guest RAM | (b) likely if D2(a) |
| D16 | Self-modifying code | (a) runtime stop; (b) annotate as data + regenerate per variant; (c) translate the block with patched operands read from guest bytes at run time and the patched RET as a computed exit | root unrolled block `+6A4D..+89FD` only (`annotations/self-modifying.csv`): RET written at an instruction start around `call dx`, word operands patched at stride 4 per call and at setup; executed in menus and in flight (m2–m5). Run-time bytes differ from the file at every byte phase (opcodes too: file `and/or [bx+2710h]` template, run time `mov [bx+disp],al` runs then template); file = m0/m1, 5 further variants over 16 snapshots; the file template continues to `+8E2C` past the region | (c); (a) is not viable |

## Phase 5 steps

| Step | Deliverable | Done when |
|---|---|---|
| 5.1 | Minimum runtime (DOS file I/O, memory, timer, `rt_*` entries, dispatch table) + overlay loader (D2) | M0→M1 path runs generated on host Unicorn 68020 |
| 5.2 | First target slice: generated path to M1/M2 on the A1200 model, display via D9 | RAM + framebuffer match the reference snapshot at the milestone — **gate 5** |
