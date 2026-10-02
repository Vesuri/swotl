# x86 real-mode notes for the translator

Facts the decoder, IR and 68020 lowering must get right. Source tags:

- **[SL]** measured or documented in `~/Documents/Slicks` (file named).
- **[SW]** measured here on `ref/` (command or method named).
- **[K]** general architecture knowledge (Intel/Motorola manuals). Not yet
  checked against our oracle; every [K] row needs a differential case before
  the lowering that relies on it is accepted.
- **UNKNOWN** — open; must be measured, not assumed.

Lessons and provenance: [translation-lessons.md](translation-lessons.md).

## SWOTL binary facts [SW]

| Item | Value | Method |
|---|---|---|
| `SWOTL.EXE` | 100,112 bytes, SHA-256 `0223a4e3…5444915` | SL `tools/mz_info.py` |
| MZ header | 4,096 bytes; 1,006 relocations; overlay number 0; no Compack | same |
| Load image | 96,000 bytes = `1770h` paragraphs; 16 zero bytes after the declared size | same, `xxd` |
| Entry | CS:IP `1617:0382` (image offset `164F2h`, last ~4.6 KiB of image) | same |
| Stack | SS:SP `4A9E:0800`; minalloc `33AEh` para. Image end + minalloc = `4B1E0h` = SS:SP top exactly: 2 KiB stack at the end of the minimum allocation | arithmetic |
| Relocated segment words | 46 distinct values, incl. `1770h 18E4h 1E7Ch 210Eh 218Dh 23A1h 3156h 3449h 344Dh 36D6h 39AAh 4B1Eh` | relocation table walk |
| Runtime strings | `Copyright (C) 1984, 1985, 1986 by Phoenix Software Associates Ltd.`; `Ovl stack underflow $`, `Ovl stack overflow $`, `No mem for ovl stack $`, `Dos 2.0 required $` (`$`-terminated: `int 21h AH=09h` style); the 12 `.OVL` names | `strings` |
| Compiler runtime | UNKNOWN. No Borland ("Abnormal program termination") or Microsoft (`R6xxx`) runtime strings found | `strings` grep |
| `.OVL` format | Not MZ. Files start with tables of little-endian far pointers (offset, segment) | `xxd` |
| `.OVL` segment words | `SFXA`,`SPAZ`: `1770h`; `RTSVGA`,`RTSEGA`,`RTSTANDY`: `18E4h` (5 entries, then zeros); `FRONTEND`: `1E7Ch`,`1F40h`; `FLIGHT`: `1E7Ch`,`210Eh`,`218Dh`,…; `CAMPAIGN`: `3156h`,`3449h`; `NOTCAMP`: `3156h`,`33A0h`,`344Dh`; `REPLAY`: `36D6h`,`39AAh`; `DATA`: `3BAFh`,`4133h` | `xxd`, crude table parse |

Interpretation (hypothesis, verify with a runtime dump): overlays are linked
at fixed paragraph addresses relative to the load segment; `1770h` is exactly
the end of the root image; files sharing a segment are alternatives in one
overlay area (sound drivers; graphics drivers; FRONTEND/FLIGHT;
CAMPAIGN/NOTCAMP); the root holds relocated far pointers into overlay segments.

### Linear-sweep inventory is garbage [SW]

A Capstone linear sweep (every byte from 0) gives, for `FLIGHT.OVL`, 126
`OUTSW`, 105 `OUTSB`, 104 `INSB`, 42 `BOUND`, 30 `DAA` — ASCII `l m n o b '`
decoded as instructions. Use only recursive descent from proved entries plus
the trace. Linear-sweep upper bounds (root only, unverified): `int 21h` 74,
`int 67h` (EMS) 14, `int 33h` (mouse) 6, `int 10h` 2, `int 16h` 1. `SFXA.OVL`
and `SPAZ.OVL` each contain three `CD 21` byte pairs: the claim "int 21h only
in the root" is UNKNOWN until the sweep proves those are data.

## PLINK overlays

Known [SW]: Phoenix PLINK copyright (1984–86); an overlay return stack exists
("Ovl stack" errors); 12 named `.OVL` files; segment words above.

UNKNOWN — all must come from the reference trace and the root's manager code:

- How a call reaches a non-resident overlay: direct relocated far call plus
  fault-in, thunk/stub table, interrupt, or `int 21h AX=4B03h` (DOS load
  overlay). The manager's entry and its register contract.
- Whether `.OVL` files carry fixups; how far-pointer tables are used.
- File-to-area mapping, residency rules, which overlays can coexist.
- What the overlay return stack stores and when it reloads a caller's overlay
  on return (a return can change resident code).
- Whether driver overlays are called only through their 5-entry tables.
- Whether `DATA.OVL` is code at all.

Consequences for the translator: translated code is keyed by
`(overlay, segment, offset)`; an overlay load is a runtime boundary that
switches resident translated code; every root far pointer into an overlay
segment is an entry candidate; a return into a different overlay must be
checked, not assumed.

## Flags vs 68k CCR [K]

FLAGS bits: CF0, 1, PF2, AF4, ZF6, SF7, TF8, IF9, DF10, OF11. On a 286 in
real mode `PUSHF` stores bits 12–15 as 0 (8086: 1; 386 can set 12–14) — the
classic CPU probe. [SL] found a CPU probe selecting an optional 386 path
(operand-size prefixes, `PUSHAD`, `PUSHFD`, FS/GS) in Borland's runtime
(`docs/source-inventory.md`).

| Topic | x86 | 68k | Lowering consequence |
|---|---|---|---|
| Carry on SUB/CMP/SBB/NEG | CF = borrow | C = borrow (X too) | Same convention; reuse CCR |
| CMP operand order | `cmp a,b` = a−b | `cmp src,Dn` = Dn−src | Swap operands |
| Unsigned/signed branches | JB JAE JBE JA / JL JGE JLE JG / JS JO | BCS BCC BLS BHI / BLT BGE BLE BGT / BMI BVS | Direct map when the producer is ADD/SUB/CMP |
| `MOV`, `LEA`, `XCHG`, `CBW`, `CWD`, `PUSH`/`POP` | no flags | `MOVE`/`CLR`/`EXT` write N Z, clear V C; `MOVEA`, `LEA`, `EXG`, `MOVEM` don't | 68k data moves clobber CCR: schedule flag consumers first or rematerialise |
| `INC`/`DEC` | OF SF ZF AF PF; **CF kept** | `ADDQ/SUBQ` to Dn write C and X; to An write nothing | Preserve CF when live (`MOVE CCR,Dn` is 68010+) |
| `AND OR XOR TEST` | CF=OF=0, SF ZF PF, AF undefined | V=C=0, N Z | Match except PF |
| `ADC`/`SBB` | ZF from result | `ADDX`/`SUBX` use X, Z only cleared (sticky); Dn,Dn or −(An),−(An) only | Set X=CF first; Z needs seeding or separate test |
| `NEG` | CF = (src≠0) | C = X = (result≠0) | Same |
| `MUL`/`IMUL` | CF=OF = high half significant; SF ZF AF PF undefined | `MULU/MULS` N Z, V=C=0 | Compute CF/OF only if live |
| `DIV`/`IDIV` | flags undefined; quotient AX, remainder DX; overflow or /0 → INT 0 (286+: return address = the DIV) | `DIVU/DIVS.W`: quotient low word, remainder high; /0 → vector 5; overflow sets V, no trap, operand unchanged | Swap halves; overflow must raise the guest INT 0 path |
| IDIV rounding | toward zero, remainder has dividend's sign | same | Same |
| AF | nibble carry | none | Compute lazily: needed by `DAA DAS AAA AAS`, `LAHF`, `PUSHF` |
| PF | even parity of low 8 result bits | none | Lazy; consumers `JP JNP LAHF PUSHF` |
| `LAHF`/`SAHF`, `PUSHF`/`POPF` | expose SF ZF AF PF CF / whole word | — | Full materialisation boundary; [SL] architecture: build it only when observed |
| `LOOP`, `JCXZ` | no flags | `SUBQ` clobbers CCR; `DBcc` doesn't | `DBcc` with a biased counter, or keep flags virtual |

## Shifts and rotates [K]

- 186+ (incl. 286) mask the count to 5 bits; 8086 does not. Count 0 after
  masking: no flags change. 68k register counts are mod 64; count 0 clears C
  (X unchanged), `ROXL/ROXR` count 0 set C=X.
- `SHL/SAL`: CF = last bit out; OF defined only for count 1 (MSB(result) xor
  CF); SF ZF PF from result, AF undefined. 68k `ASL` sets V if the MSB changed
  at any step; `LSL` clears V. Lower SHL as `LSL`, derive OF only when live and
  count = 1.
- `SHR`: count 1 OF = MSB(original). `SAR`: count 1 OF = 0. 68k `LSR`/`ASR`
  clear V.
- Count ≥ operand width (possible after 5-bit masking of a 16-bit operand):
  CF/OF undefined per Intel. Mask in the oracle; reproduce the result bits.
- `ROL/ROR`: only CF and OF change; SF ZF PF kept. 68k `ROL/ROR` write N Z and
  clear V — clobbers flags x86 keeps.
- `RCL/RCR`: through CF; 16-bit count is 5-bit masked then mod 17. 68k
  `ROXL/ROXR` rotate through X, not C: set X from CF first.
- Signedness [SL]: coordinates include `FFFFh`; keep unsigned 16-bit
  arithmetic and logical shifts (`docs/external-surface.md`).

## Segments, addresses, endianness

- [K] Physical = seg×16 + off. Effective-address offsets wrap mod 64 KiB
  (`[bx+si+disp]`, `SI/DI` in string ops, `SP`). Above 1 MiB: wraps or HMA
  depending on A20 — UNKNOWN whether SWOTL ever forms such addresses.
- [K] A word access at offset `FFFFh`: 8086 wraps to offset 0; 286+ real mode
  faults (INT 0Dh). Emulator behaviour UNKNOWN; fail loudly.
- [K] Default segments: `BP`-based → SS, others → DS, string destination
  ES:DI (not overridable), stack SS:SP. Prefixes `26 2E 36 3E` (ES CS SS DS).
  `MOV SS` / `POP SS` inhibit interrupts for one instruction.
- [K] Far pointer in memory = offset word, then segment word. `LES`/`LDS`.
- [SL] 16-bit address wrap is real in game code: VGA plane offsets and a
  screen-transition source wrap at 64 KiB; plot offset is the low 16 bits of
  `base + y×stride + x/4` (`docs/native-graphics-abi.md`, `external-surface.md`).
- [SL] Guest RAM stays byte-exact little-endian; every native word/long access
  states its endian rule. Never alias guest RAM as a wide native pointer (RV
  learned the same; see translation-lessons #43).
- [SL] Callers pass bytes as words; callees use only the low byte (far fill
  value, readback height). Do not assume a zero high byte
  (`external-surface.md`).

## String instructions [K]

- `MOVS STOS LODS SCAS CMPS` (+`INS OUTS` 186+). DF=0 increments, DF=1
  decrements. `REP` with CX=0 runs zero iterations and changes no flags.
- `REPE/REPNE` with `CMPS/SCAS` stop on ZF; flags are those of the last
  comparison. Source segment overridable, destination ES fixed.
- Overlap is defined per element, forward: `rep movsb` with DI = SI+1
  replicates a byte. Never lower to `memmove`.
- SI/DI wrap at 64 KiB independently mid-string.
- DF: assume nothing. Treat DF as a live guest flag; a translated block may
  specialise on DF=0 only where analysis proves it.
- [SL] An instrumented trace shows `REP` iterations as self-edges
  (`tools/analyze_execution_trace.py` classifies `destination == source` as
  "repeat").

## Calls, returns, stack [K]

- Near `CALL` pushes IP; far `CALL` pushes CS then IP; `RETF n` pops IP, CS,
  then adds n to SP. Compiler idiom `push cs; call near` calls a far routine
  in the same segment; `push seg; push off; retf` is a far jump.
- Code can pop or rewrite its return address (inline parameters, dispatch).
  Guest stack bytes must stay guest CS:IP values to keep RAM byte-exact, so a
  `RET` is a mapping from guest IP to native code unless call/return pairing is
  proved. Design decision for `architecture.md`.
- [SL] Borland far cdecl: caller cleans arguments; a far pointer argument is
  two words; static callers' `add sp,n` confirms arity
  (`docs/external-surface.md`). SWOTL's calling convention is UNKNOWN until
  its compiler is identified.

## Interrupts [K] unless tagged

- IVT at `0000:0000`, 4 bytes per vector (offset, segment). Set by
  `int 21h AH=25h` or direct stores; read by `AH=35h`. Every handler a program
  installs is an entry point.
- `INT n` pushes FLAGS, CS, IP and clears IF, TF; `IRET` pops IP, CS, FLAGS.
  `INTO` = INT 4 if OF; `INT3` = `CCh`; `BOUND` failure = INT 5 (186+).
- Master PIC IRQ0–7 → INT 08h–0Fh. IRQ0 PIT → 08h; IRQ1 keyboard → 09h. BIOS
  08h increments the dword tick count at `0040:006C` and calls INT 1Ch.
- [SL] Observed DOS services (Slicks): `1A 25 29 2A 2C 2F 30 35 37 38 3B 3D 3E
  3F 41 42 43 44 4A 4B 4D 4E 4F`; INT 10h `00 08 0F 12`; INT 2Fh `4300/4310`
  (XMS); INT 33h `0000 0003 0008 0009`. Trace kept AX..BP, SP, FLAGS per event
  (`docs/external-surface.md`). SWOTL's set is UNKNOWN; expect EMS (`int 67h`)
  and mouse from the sweep above.
- [SL] Timer handler entered from game code and while a DOS service was
  active: asynchronous state, not a call (`external-surface.md`).
- Delivery in the port: at safe guest boundaries, never as game code inside an
  Amiga interrupt (PK; translation-lessons #31).

## Port I/O

| Ports | Device | Notes |
|---|---|---|
| `20h`, `21h` | PIC | `out 20h,20h` = EOI; 21h = mask [K]; observed [SL] |
| `40h`–`43h` | PIT | 1,193,182 Hz input; 43h control (channel, access, mode); latch then read lo/hi from 40h; ch2 (42h) drives the speaker [K]. [SL]: millions of PIT reads per race |
| `60h`, `61h` | Keyboard / PPI | Set-1 scancodes, break = make\|80h, `E0` prefix; 61h bit 0 PIT gate 2, bit 1 speaker, bit 7 XT ack [K]. [SL] keyboard ISR at INT 09h |
| `201h` | Joystick | [SL] polled |
| `3C0h` | Attribute | flip-flop reset by reading 3DAh [K] |
| `3C4h/3C5h` | Sequencer | idx 02h map mask, idx 04h memory mode (chain-4) [K] |
| `3C7h–3C9h` | DAC | 3C8h write index, then R,G,B 6-bit to 3C9h, auto-increment; 3C7h read index [K] |
| `3CEh/3CFh` | Graphics ctrl | idx 04h read map, 05h mode, 08h bit mask [K] |
| `3D4h/3D5h` | CRTC | 0Ch/0Dh start address (page flip), 14h/17h for unchained modes [K] |
| `3DAh` | Input status 1 | bit 3 vertical retrace, bit 0 display disabled [K]. [SL] polled millions of times |

Linear-sweep evidence in SWOTL overlays (unverified): `SFXA` `out 42h`,
`in/out 61h` (speaker); `SPAZ` `out 43h`, `out 40h`, `out 20h`; `RTSVGA`
`out 40h`. [SL] rule: replace the routines around port traffic, not ports one
by one (translation-lessons #25).

## Mode 13h

- [K] `int 10h AX=0013h`: 320×200, 256 colours, chain-4, linear at
  `A000:0000`, 64,000 bytes, pixel at `y×320+x`. DAC 6-bit components.
- [K] Clearing chain-4 (sequencer 04h) plus CRTC 14h/17h gives an unchained
  planar layout (four 64 KiB planes, multiple pages).
- [SL] Slicks set mode 13h through BIOS, then went unchained: 100-byte stride,
  page separation 32,700, sequencer/GC programming in the inner loops. "Treating
  mode 13h as only a flat 320×200 framebuffer would be insufficient"
  (`external-surface.md`).
- SWOTL: UNKNOWN whether `RTSVGA` stays chained. Decide from the port trace.

## MZ relocation [K]

- Header: `+02` bytes in last page, `+04` 512-byte pages, `+06` relocation
  count, `+08` header paragraphs, `+0A/+0C` min/max alloc, `+0E/+10` SS/SP,
  `+14/+16` IP/CS, `+18` relocation table offset, `+1A` overlay number.
- Image loads at PSP+10h; each relocation `(offset, segment)` adds the load
  segment to the word at `load+segment : offset`. Entry DS = ES = PSP.
- [SL] Normalise by subtracting the load segment (4,192 relocations reversed
  for Slicks; `tools/rebuild_runtime_mz.py`) and compare traces against that.
- The relocation table marks segment-valued words: a free data/code
  classifier for far pointers and segment immediates. Not every segment value
  is relocated (computed segments, overlay segments, PSP-relative values).

## Borland/runtime surprises [SL]

- Compack unpacker at entry: no disassembly trusted before the handoff image
  was captured twice independently. SWOTL has no Compack signature.
- CPU probe plus a reachable 386 path in a "16-bit" program; reference runs
  pinned to a 286 personality with a 386 comparison.
- Far fill helper: byte-aligns an odd destination, then word stores, repeating
  only the low byte; also used on `A000h` and `B800h`, so library helpers can
  be device code.
- Palette nearest-colour helper: asymmetric signed/unsigned component handling
  exposed only by high input bytes (`docs/validation-harness.md`).
- Sub-rectangle blit: source x truncated to a byte offset yet added to the
  destination origin — an original quirk the oracle had to confirm.
- Borland RNG reproduced; RNG call order is checked by an oracle
  (`docs/toolchain.md` verify-surface-effects, `docs/performance.md`).
- No writes into executed instruction bytes on the measured path; other paths
  unproven (`external-surface.md`).
