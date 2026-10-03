# Translator design

Skeleton for phases 3–5. Fixed parts are decided; decision points D1–D16
list options, the evidence that settles them (from
[plan-reference-map.md](plan-reference-map.md)) and the default if evidence
does not object. Replace each decision with its outcome when settled.
Overview and guardrails: [architecture.md](architecture.md).

## Fixed

### Components

| Module | Role |
|---|---|
| `translator/image.py` | load proved root/overlay images, relocations, module map |
| `translator/decode.py` | own table-driven 8086/186/286 decoder; Capstone cross-check in tests |
| `translator/ir.py` | per-instruction semantic ops (below) |
| `translator/cfg.py` | blocks, functions, overlay modules from `annotations/` + decoded edges |
| `translator/flags.py`, `live.py` | flag demand, register liveness |
| `translator/lower.py` | IR -> 68020 instruction selection under the register contract |
| `translator/emit.py` | Motorola `.s` per module with hash header |
| `translator/coverage.py` | executed bytes (trace) vs translated / HLE / unclassified |
| `tests/` | instruction + block differentials, lint, hash check |

Language: Python 3.11 (sibling tooling, Capstone binding present). Offline,
so translator speed is irrelevant.

### IR

- Values: 8/16/32-bit temporaries; guest registers as 16-bit with explicit
  8-bit halves; segment registers separate.
- Ops: `get/put reg`, `load/store(seg, offset_expr, width)`, arithmetic and
  logic with explicit flag outputs, `flags_def/flags_use` sets per op,
  `branch/call/ret/jmp_indirect/int/in/out/hlt`, `rep` loops expanded to IR
  loops with DF.
- Every op carries its guest `(module, offset)` for diagnostics and coverage.

### Generated code contract

- Guest register mapping fixed program-wide (D4); exits publish exactly the
  registers their contract names.
- Runtime entry points are `jsr` targets with a per-service register
  contract (`int21_3Dh`, `port_out_3C8`, `overlay_load`, `stop_unknown`).
- `stop_unknown(kind, module, offset)` prints and halts; never resumes.
- Generated files: `build/gen/<module>.s`, header = SHA-256 of translator
  sources, annotations and input image. Build fails on mismatch.

### Annotations (`annotations/`, CSV)

`entries.csv`, `indirect.csv` (site -> targets), `data.csv` (ranges),
`hle.csv` (guest range, service, reason, oracle; starts empty), `names.csv`
(name, evidence class).

### Tests

- Instruction differential: per opcode form, random registers/flags/memory;
  original bytes in Unicorn x86-16 vs generated code in Unicorn 68020 on the
  same guest-memory layout; compare registers, defined flags, memory.
- Block differential: traced blocks with captured entry states.
- Audits: spills, full-flag materializations, dispatcher exits, `stop_unknown`
  sites, HLE count — reported by `make gen`, regressions fail.

## Decision points

| # | Decision | Options | Evidence | Default |
|---|---|---|---|---|
| D1 | `RET` mapping | (a) native `bsr`/`rts` + guest return IP also pushed; `RET` checks popped IP, mismatch -> table lookup; (b) guest stack only, `RET` dispatches via IP->native table; (c) shadow stack | return-address manipulation: PLINK manager reads its inline id from and advances its return address ([plink.md](plink.md)); no overlay return stack; MS C `push cs; call` far idiom ([x86-notes.md](x86-notes.md)); `call dx` into the patched block (D16) | (a) |
| D2 | Overlay model | (a) all translated modules resident; (b) translated modules loaded on demand like PLINK | [plink.md](plink.md): 9 in-scope modules, ~0.38 MB code; 57 loads in the corpus; a load never replaces the caller; parents reload with children | (a) if it fits D15 |
| D3 | Segments | (a) DS/SS folded to constants, ES/far computed; (b) all computed with cached linear bases | MS C medium model, DS = SS = DGROUP (DATA.OVL) for C code; asm routines load DS/ES from `cs:` variables (e.g. `+6A48`) | (a) |
| D4 | Register allocation | (a) fixed mapping program-wide; (b) per-function with edge shuffles | spill audit after (a) | (a) |
| D5 | Byte order | (a) swap on word load/store; (b) byte-reversed guest memory | 68020 cost microbenchmark (open-work), word-access share | (a) |
| D6 | Flags | lazy: keep operands of last flag-setter, materialize on use; reuse CCR when semantics match | instruction corpus | as stated |
| D7 | Indirect control flow | sorted/hashed guest-linear IP -> native table; recognised jump tables lowered directly; unknown -> `stop_unknown` | `annotations/indirect.csv`: 449 sites, 214 executed (all with traced targets), 41 MS C switch tables resolved statically, 215 static-only sites unresolved (203 `lcall [mem]`) | as stated |
| D8 | Interrupt delivery | (a) runtime runs translated guest ISRs at safe points (loop back-edges, calls); (b) HLE of the game's ISRs | [external-surface.md](external-surface.md): guest installs INT 00h/05h/08h (SPAZ tick)/23h/24h; INT 09h/1Ch stay BIOS | (a) |
| D9 | Graphics drivers | (a) HLE at RTSVGA's call table on the dA JoRMaS layer; (b) translate driver + emulate VGA ports/memory | chained mode 13h via INT 10h, no VGA ports, no page flip; entries = PLINK thunks with id 3 | (a), with RTSVGA itself as oracle |
| D10 | Sound | SPAZ HLE at its table; AdLib music method open (OPL -> Paula) | 2.5; open-work AdLib item | HLE |
| D11 | String ops | IR loops; `rep movs/stos` fast paths when DF and overlap provable | corpus + profile | as stated |
| D12 | Translator language | Python vs C++ | none | Python |
| D13 | Decoder | own vs Capstone | none | own, Capstone cross-check |
| D14 | 68k oracle | Unicorn 68020 (Slicks) vs Musashi | none | Unicorn |
| D15 | Memory target | (a) 2 MiB Chip only (Slicks); (b) require Fast RAM | guest RAM need + generated code size (x86 code ~0.4 MB, 68k output unmeasured): 1.4, 2.2, first `make gen` | measure; (b) likely if D2(a) |
| D16 | Self-modifying code | (a) runtime stop; (b) annotate as data + regenerate per variant; (c) translate the block with patched operands read from guest bytes at run time and the patched RET as a computed exit | root unrolled block `+6A4D..+89FD` only (`annotations/self-modifying.csv`): RET written at an instruction start around `call dx`, word operands patched at stride 4 per call and at setup; executed in menus and in flight (m2–m5) | (c); (a) is not viable |

## Phases 3–5 steps

| Step | Deliverable | Done when |
|---|---|---|
| 3.1 | `translator/` skeleton, `make gen`, G1 hash check, G2 lint | lint and hash check fail on a planted violation |
| 3.2 | Decoder for every opcode in the classified code | decodes all executed bytes; Capstone agrees |
| 3.3 | IR semantics + instruction corpus (flags, shifts, rotates, mul/div, segment wrap, string ops, DF) | differential clean vs Unicorn x86-16 (IR interpreted on host) — **gate 3** |
| 4.1 | Lowering for straight-line blocks under D4/D5/D6 | instruction corpus clean in Unicorn 68020 |
| 4.2 | Control flow: direct branches/calls, D1, D7 | block differential clean on traced blocks |
| 4.3 | Audits in `make gen` | **gate 4** |
| 5.1 | Minimum runtime (DOS file I/O, memory, timer) + overlay loader (D2) | M0→M1 path runs generated on host Unicorn 68020 |
| 5.2 | First target slice: generated path to M1/M2 on the A1200 model, display via D9 | RAM + framebuffer match the reference snapshot at the milestone — **gate 5** |
