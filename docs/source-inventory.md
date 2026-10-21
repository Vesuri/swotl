# Source inventory

SWOTL 2.2 as in `ref/` (eXoDOS install); the installer, `Source.7z` and
install instructions as supplied are in `ref-originals/` (local only). Reproduce with `make inspect`;
SHA-256 of every `ref/` file in `tmp/ref.sha256` (`make hash`, local only).

## Root `SWOTL.EXE`

| Fact | Value |
|---|---|
| SHA-256 | `0223a4e3fc063a591d17cf789b8e9b3ec03eac925c935688ab78a98f05444915` |
| Size | 100,112 B; declared 100,096 (16 B trailer) |
| Header | 4,096 B; load image 96,000 B = `1770h` paragraphs |
| Entry / stack | `1617:0382` / `4A9E:0800` |
| Alloc min / max | `33AEh` / `FFFFh` paragraphs |
| Relocations | 1,006 |
| Compiler runtime | Microsoft C ("MS Run-Time Library - Copyright (c) 1987"; R6000–R6009 messages incl. "floating point not loaded") |
| Linker | Phoenix PLINK (copyright 1984–86 string; "Ovl stack underflow/overflow", "No mem for ovl stack") |
| Overlay names | in the root: SPAZ SFXA RTSVGA RTSTANDY RTSEGA FRONTEND CAMPAIGN NOTCAMP FLIGHT REPLAY PANEL DATA |

## Overlays

PLINK table, file format, loader and residency rules:
[plink.md](plink.md). Each `.OVL` is its fixup list (padded to a
paragraph) followed by the code; code lands at load seg + link seg and each
fixup word gets the load segment added (gate 1). DATA is the C data segment
(DGROUP): DS = load seg + `3BAB`. Load segment in all runs: `0822`.

Other first-run facts: PIT reprogrammed (236.7 Hz INT 8); AdLib music
(`388h/389h`); joystick probe on `201h`; mouse via INT 33h; EMS 4.0 used
for paging data (INT 67h AH=40–44); keyboard via C runtime `kbhit`
(INT 21h AH=0Bh at `SWOTL.EXE+13ED1`) and INT 16h AH=02h; only RTSVGA
touches VGA memory. Full inventory: [external-surface.md](external-surface.md).

## Launcher

`sw.bat`: `swotl V S 5 N Y Y 64`, pinned for reference runs; args 1–2
fixed by scope (VGA, AdLib). Parsed in
`main` (`SWOTL.EXE+0000`, argc at `[bp+6]`, argv at `[bp+8]`); no
arguments prints "Run INSTALL".

| # | Value | Effect | Evidence |
|---|---|---|---|
| 1 | `V` | graphics driver: `V/v` VGA (3, RTSVGA), `E/e` EGA (0), `T/t` Tandy (2); other: interactive prompt | `+3BB6` switch → `[9936]` |
| 2 | `S` | sound: `S`/`A` AdLib FM (SPAZ + `ADLIB.SFX`, port `388h`; no SB DSP access seen); `I`/`N` PC speaker (SFXA + `SFX.SFX`, ports `42h/61h`); default `I` | `+0122` → PLINK thunk, overlay 9; runs with each value |
| 3 | `5` | initial graphics detail level: `atoi−1` (0–4) → `[9DB0]`; FLIGHT cycles it in flight; objects drawn when level ≥ their minimum; with VGA, DS byte table `[078C+n]` → `[233E]` | `+3C36`, FLIGHT `+1D63`, root `+F379`, FLIGHT `+B9EB` |
| 4 | `N` | joystick: `N/n` clears `[A6C6]` (joystick present) after the port `201h` probe | `+3560`, probe `+42B0` |
| 5 | `Y` | mouse: `N/n` → `[A71A]=0`, else 1, after INT 33h vector check | `+3545`, `+44C0` |
| 6 | `Y` | film disk cache: `N/n` → `[612A]=0` (film room "DISK CACHE: OFF"), else 1 | `+0152`, film room run with `Y N 32` |
| 7 | `64` | film cache size in KB: if arg 6 ≠ N `[61E6]=max(atol,16)`, else `3FFh`; film room "CACHE SIZE: 64K" | `+01C2`, film room run with `Y Y 32` |

PLINK thunks: root `+16B66` onwards ([plink.md](plink.md)).

## Coverage

`make map` over `tmp/pc-runs/ref-*` (94 traces: milestones m0–m7 and coverage
scripts c1–c85). Bytes of each module's code part. Static = reached by the sweep
(traced starts, direct flow incl. `loop`/`jcxz`, PLINK thunks and the manager,
child-to-parent far calls, switch tables); executed = bytes
of traced instructions (m0–m7 alone in brackets). Residue = never decoded:
zero fill, text, code-like (MS C prologue or fixup-anchored far call: code
reached only through untraced pointers), other (tables, data in code
segments; FRONTEND's includes its far data `+F348..`, 19,800 B of
strings). Self-modified: root block `+6A4D..+8E2C` (9,184 B; the template ends at the RET at `+8E2C`), classified
by `annotations/self-modifying.csv`. Executed bytes outside sweep code: 0.

| Module | Code part | Static | Executed (m0–m7) | Switch tables | Residue: zero / text / code-like / other |
|---|---|---|---|---|---|
| SWOTL | 96,000 | 85,000 | 61,586 (39,886) | 190 | 138 / 66 / 1,217 / 9,389 |
| SPAZ | 5,952 | 4,324 | 3,374 (3,308) | 0 | 1,458 / 0 / 133 / 37 |
| RTSVGA | 18,272 | 3,694 | 2,899 (2,278) | 0 | 14,550 / 0 / 0 / 28 |
| FRONTEND | 77,216 | 55,487 | 39,830 (7,858) | 308 | 1 / 0 / 171 / 21,249 |
| CAMPAIGN | 40,912 | 35,733 | 27,778 (2,237) | 78 | 0 / 0 / 0 / 5,101 |
| NOTCAMP | 39,152 | 36,088 | 27,913 (5,350) | 80 | 0 / 0 / 0 / 2,984 |
| FLIGHT | 99,744 | 93,879 | 63,971 (30,242) | 642 | 0 / 4,728 / 83 / 412 |
| REPLAY | 15,088 | 13,698 | 8,498 (2,528) | 54 | 0 / 0 / 0 / 1,336 |
| PANEL | 13,280 | 13,200 | 12,376 (6,414) | 0 | 0 / 0 / 0 / 80 |

DATA.OVL (62,640 B) is DGROUP: no code. Executed coverage rises with the
scripts (c1–c85 add 2–1,142 % over m0–m7), so the translator works from
static reach and unknown indirect targets stop loudly (D7).

## Their Finest Hour (Amiga) — cross-reference only

`tmp/TheirFinestHour&Missions_v1.1_0037&1369.lha` (WHDLoad install,
extracted to `tmp/tfh/`). Evidence for naming and structure in phase 2;
never a source of port code (guest code reaches the Amiga only as
translator output).

| Fact | Value |
|---|---|
| Version | `data/BOB` v1.1, 254,400 bytes ([tfh-cross-reference.md](tfh-cross-reference.md)); `data/read.me` still says 1.0, 28 Apr 1990 |
| Executables | `data/BOB` (game, code 204,352 B; initialized data 43,888 B in a 64,020 B allocation; BSS 4 B), `data/MB` (mission builder) |
| Compiler | Manx Aztec C (`MANX` marker; `LINK A5`/`UNLK A5` frames); no symbol or debug hunks |
| Shared with SWOTL | UI strings ("Insert Your Campaign Disk", "Do you want to fly the same mission again?") present in SWOTL's root/overlays: common C source |
| Data formats | Related PAC image/sprite framing and GOB terrain-ring tables, with platform-specific layouts; [cross-reference and checks](tfh-cross-reference.md) |
