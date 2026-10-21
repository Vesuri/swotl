# Translation lessons

Rules for building the offline x86 -> IR -> 68020 translator, taken from the
sibling ports. Format: **rule** — why — *provenance*. Abbreviations: SL Slicks,
RoF Rescue on Fractalus, RV Revs, VT Vette, PK Pokeri. Paths are relative to
each project. Target-side Amiga lessons live in [amiga-lessons.md](amiga-lessons.md), the
measurement and validation method in AmigaXDev `docs/reference/measurement-method.md` and
`docs/reference/validation-harness.md`, and x86 facts in [x86-notes.md](x86-notes.md).

## Guardrails

Why (Slicks planned this pipeline and shipped without it) and the generic translator rules:
AmigaXDev `docs/playbooks/new-port-playbook.md` §7. The numbered rules below are SWOTL's own,
cited by number from code, tests and [x86-notes.md](x86-notes.md).

Guardrails for SWOTL (feed into `architecture.md`/`phases.md`):

| # | Guardrail | Enforced by |
|---|---|---|
| G1 | Guest routines exist only as generator output. Generated files carry a generator/annotation hash header and are never edited. | Build check: every `.s` under the generated dir has a valid header; regen is byte-identical. |
| G2 | Hand-written code is the **runtime** only: DOS/BIOS services, port/device models, overlay loader, interrupt delivery, display/audio/input. Named by surface item (`int21_3Dh`, `port_3C9`), never by guest address. | Lint: no guest-address-named symbol outside generated code. |
| G3 | Native replacements of guest routines (HLE) are an explicit table in annotation data, each entry: guest range, reason (device-bound/hot), oracle target. Default empty; growth reviewed. Callers of a replaced leaf stay generated. | `make gen` prints the table and count; RV `MANUAL_FUNCS` empty precedent. |
| G4 | A wrong result is fixed in IR semantics, lowering or annotations, then regenerated — never by patching output or adding a hand routine. | G1 hash check. |
| G5 | Phase order is a hard gate: instruction differential corpus green before block lowering; block lowering green before any target build links game code. No target milestone counts unless its pixels come from generated code. | phases.md exit criteria name generated-code coverage, not pictures. |
| G6 | `make gen` reports coverage against the DOSBox trace: executed guest instructions translated / interpreted / HLE / untranslated. The HLE and fallback shares are tracked numbers. | Trace-driven report; fails on executed-but-unclassified bytes. |
| G7 | First visible output early **from the translator**: pick a small, self-contained traced subgraph and get its generated code on target in the first days, so the translator, not hand work, is the fast path to pixels. | Plan the first vertical slice around generator output. |
| G8 | No captured frames, invented behaviour or speculative names in shipped code. Names carry an evidence class. | SL `7c89a44`, `f4728a1`, `fa6060d`, `d71b7af`; VT `symbols.csv` evidence column. |

## Process and scope

1. **Standing rules must name the failure modes you expect, both of them** — SL's rules blocked emulation but not hand-porting, and it hand-ported. *SL AGENTS.md; AmigaXDev playbook §7*
2. **Build discovery and validation infrastructure exhaustively up front, not reactively** — every reactive addition on RoF was a scar. *RoF postmortem (one-sentence version)*
3. **Translator output quality is a prerequisite milestone before mass generation** — one generator fix upgrades the whole corpus; late fixes left every intermediate regen worse. *RoF postmortem 2.1; RV transpiler.md*
4. **Generation fails rather than emitting a plausible stub** (unknown ROM/OS call, annotation address not an instruction start, unresolvable target) — a silent stub reads like a routine that runs and does nothing. *RV transpiler.md §What make gen reports*
5. **Unknown control flow, code writes, overlays, interrupts, port I/O and device memory fail loudly until deliberately supported.** *SL AGENTS.md*
6. **Oracle-tested code that is never linked is deleted** — SL removed 2,035 such lines. *SL `974ff50`*
7. **Profile an end-to-end slow skeleton on the target before choosing optimisation work** — RoF's "algorithmic floor" was wrong; the ceiling was GCC. *RoF postmortem 4.1; SL AGENTS.md*
8. **A structural fix is not a performance fix** — measure separately. *RV transpiler.md (build_regions bought no framerate)*

## Runtime image and static map

9. **Disassemble the image that executes, not the file** — SL Compack and RV self-relocation both made the loaded image wrong where it mattered; prove the runtime image by two independent captures. *SL README/phases 1; RV static-map.md §REVS2 unpacks itself*
10. **One address convention, never mixed** — VT `(segment, offset)`; SL normalised to load segment 0 with 4,192 relocations reversed. SWOTL needs `(overlay, segment, offset)`. *VT static-map.md; SL README*
11. **The entry-point sweep is complete before the first generated line**: indirect/computed jumps and their full tables, every vector (IVT, `int 21h AH=25h` targets), callbacks, mid-function entries. Seeds live in a reproducible `entrypoints.csv`. *RoF postmortem 1.1; RV entrypoint-sweep.md*
12. **Definition of done: no referenced-but-undecoded address; residue counted and reported** — RV accepted 685 bytes explicitly; VT reports 5.2%. *RV static-map.md; VT static-map.md*
13. **A coverage number that improves because the tool got looser is worse than no number** — RV's widened pointer lookback fabricated targets and was reverted. *RV static-map.md*
14. **Never use linear sweep to classify mixed code/data** — VT rejects it; on SWOTL a linear sweep of `FLIGHT.OVL` invents hundreds of `INS`/`OUTS`/`BOUND` from ASCII (see x86-notes). *VT static-map.md; measured here*
15. **Combine static and live evidence; static is an upper bound, the trace is a lower bound** — SL inventory "is an upper-bound ... runtime traces decide"; VT checks every live trap site against the static map. *SL source-inventory.md; VT static-map.md*
16. **A body no scenario drives is unproven, not dead** — trace absence is not proof. *RV faithfulness-seam.md §transtrap; RV wide-value-cleanup.md*
17. **Code at an address can be different code at another time** — overlays (SWOTL) and runtime-built pages (RV `$7B00`). Key translated code by resident image, not address alone. *RV entrypoint-sweep.md*
18. **Orphan runs and nested calls are classic boundary bugs** — RV dropped code that ended in a terminator and turned a call into a goto; report every orphan, never infer membership from fall-through alone. *RV transpiler.md §Porting checklist*
19. **Loops spanning a mid-function entry must stay branches** — splitting at entries turned loops into mutual recursion and stack growth in RV's C. In asm, a guest jump is a `bra`, a guest call is a `bsr`; never conflate. *RV transpiler.md §build_regions*
20. **Behavioural naming is an early concentrated pass; one symbol file feeds the generator; names need evidence.** *RoF postmortem 1.2; VT static-map.md*

## Self-modifying and runtime-built code

21. **Classify every code write mechanically and emit a faithful runtime form; do not hand-stub** — RV had 59 sites in five classes (operand, opcode, branch, call, extent); unhandled values report, never pick a branch. *RV transpiler.md §Self-modifying code*
22. **Prove absence of code writes with a byte-level trace check, per path** — SL found zero writes to executed bytes on BASIC only. *SL external-surface.md*
23. **A patched call/jump target set is explicit and checked at generation time.** *RV transpiler.md*

## Seam between translated and native code

24. **Write the seam rule before the first native routine**: is the behaviour defined by the guest code? Then it stays generated/validated; platform variation is a small guarded addition. *RoF postmortem 5; RV faithfulness-seam.md*
25. **Replace device-bound routines, not device ports one by one** — SL saw 10.3 M port ops, 1.36 M VGA writes from 16 sites; per-port emulation defeats ahead-of-time translation. *SL external-surface.md*
26. **Every seam has an explicit register/flag/memory contract in both directions** — SL native-graphics-abi.md register table; SL architecture "runtime exits publish exactly the guest state required". *SL*
27. **A seam hands over every register live at that address, not what the default callee reads** — RV shipped a months-long corruption from a stale Y. *RV faithfulness-seam.md*
28. **Treat an OS/BIOS call as clobbering everything its contract does not preserve** — RV MOS calls clobbered registers invisible in the listing. *RV faithfulness-seam.md*
29. **Flags can escape a routine** — RV: V survived `CMP` to the caller. Default: flags live at return unless interprocedural analysis proves otherwise; function exits all-live. *RV faithfulness-seam.md; RoF/RV transpiler.md liveness*
30. **A trap/exit happens at the guest instruction boundary, after preceding stores.** *RV faithfulness-seam.md*
31. **Interrupts are delivered at safe guest boundaries, never by running game code inside an Amiga interrupt.** *PK porting-approach.md*
32. **The timer ISR is asynchronous state, not a call** — SL's INT 08h handler ran from game code and during DOS services. *SL external-surface.md*
33. **Spin-waits: a wait on an I/O port is a device-model gap; a wait on RAM is a hook candidate. Report candidates; add hooks only for waits that own a frame.** RV used 1 of 41. *RV transpiler.md §Spin-waits*

## Validation

34. **Ground truth is the original under the PC reference loop, never the port or a host approximation.** *SL, RoF, RV*
35. **Differential oracle must be independent of the translator** — RV's transliteration oracle shared the generator, so generator changes were invisible to it. SL's pattern (original bytes in Unicorn x86-16 vs generated code in Unicorn 68020) is independent. *RV validation-harness.md §SIXTH; SL validation-harness.md*
36. **Name what the two sides of a differential share; check that thing another way.** *RV validation-harness.md*
37. **No vacuous green: zero comparisons fails; a registered test without fixtures fails.** *RoF postmortem 3.1; RV validation-harness.md*
38. **Compare complete live-out: registers, flags, memory, port-write sequence, interrupts, faults** — RV: 4 of 9 sabotages passed a memory-only diff; order of hardware writes is semantic. *RV validation-harness.md §FIFTH; SL harness hooks `OUT`*
39. **Mask undefined flags; do not canonise them.** *SL validation-harness.md*
40. **Randomise whole state including gating bytes; decorrelate flags from values** — a branch on a flag is not a branch on the value. *RoF postmortem 3.1; RV faithfulness-seam.md*
41. **Add explicit boundary cases random state cannot reach** (equality, wrap, `FFFFh`, zero counts). *RV validation-harness.md §TWELFTH; SL external-surface.md*
42. **Sabotage every new oracle before trusting its green.** *RV validation-harness.md*
43. **Endianness cannot hide behind a host run** — run differentials big-endian (68020 engine) and lint wide aliases of guest RAM. *RoF postmortem 3; RV validation-harness.md*
44. **Whole-run determinism: byte-equal guest RAM at a frame against a recorded reference, on more than one trajectory; record from a clean tree.** *RV validation-harness.md §SIXTH*
45. **Every negative observation needs a positive control; a time limit is never success.** *SL validation-harness.md, reference-contract.md*
46. **Build-flag changes must invalidate objects, or a "green" tests stale code.** *RoF transpiler.md §flag guard*
47. **Count fallback/interpreter entries in production scenarios and fail on any unexpected one.** *RV `make transtrap`; SL architecture.md §Performance audits*

## Reference loop products (SL, reuse)

48. **Record per milestone: executed addresses and block entries, direct/indirect edges, interrupt number with registers, port events, code-region writes, file events, framebuffer/state hashes; normalise addresses to load segment.** *SL reference-contract.md*
49. **Two CPU personalities when the binary probes the CPU** — SL ran 286 (primary) and 386. *SL reference-contract.md*
50. **Instrument the reference emulator by patch, kept in-repo** — SL `tools/patches/dosbox-x-slicks-*.patch` (trace, interrupts, ports, memory, primitive arguments). *SL tools/patches*
