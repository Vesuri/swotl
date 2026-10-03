# Source inventory

SWOTL 2.2 as in `ref/` (eXoDOS install). Reproduce with `make inspect`;
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

Other first-run facts: PIT reprogrammed (~250 Hz INT 8); AdLib music
(`388h/389h`); joystick probe on `201h`; mouse via INT 33h; EMS 4.0 used
for paging data (INT 67h AH=40–44); keyboard via C runtime `kbhit`
(INT 21h AH=0Bh at `SWOTL.EXE+13ED3`) and INT 16h AH=02h; only RTSVGA
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

PLINK thunks (root `+16B66` onwards, 12 bytes each): `call far 1E39:034C`
(overlay manager), `dw` overlay id, `jmp far` target.

## Coverage

`make map` over `tmp/pc-runs/ref-*` (milestones m0–m7 + coverage scripts
c1–c6). Bytes of each module's code part. Static = reached by the sweep
(traced starts, direct flow, PLINK thunks, switch tables); executed = bytes
of traced instructions (m0–m7 alone in brackets). Residue = never decoded:
zero fill, text, code-like (MS C prologue or fixup-anchored far call: code
reached only through untraced pointers), other (tables, data in code
segments; FRONTEND's includes its far data `+F348..`, 19,800 B of
strings). Self-modified: root block `+6A4D..+89FD` (24,339 B), classified
by `annotations/self-modifying.csv`. Executed bytes outside sweep code: 0.

| Module | Code part | Static | Executed (m0–m7) | Switch tables | Residue: zero / text / code-like / other |
|---|---|---|---|---|---|
| SWOTL | 96,000 | 79,968 | 45,727 (39,886) | 110 | 137 / 66 / 1,840 / 13,879 |
| SPAZ | 5,952 | 4,324 | 3,308 (3,308) | 0 | 1,458 / 0 / 133 / 37 |
| RTSVGA | 18,272 | 3,694 | 2,326 (2,278) | 0 | 14,550 / 0 / 0 / 28 |
| FRONTEND | 77,216 | 49,108 | 8,533 (7,858) | 172 | 1 / 0 / 6,699 / 21,236 |
| CAMPAIGN | 40,912 | 35,733 | 3,856 (2,237) | 78 | 0 / 0 / 0 / 5,101 |
| NOTCAMP | 39,152 | 36,088 | 6,983 (5,350) | 80 | 0 / 0 / 0 / 2,984 |
| FLIGHT | 99,744 | 93,879 | 38,736 (30,242) | 642 | 0 / 4,728 / 83 / 412 |
| REPLAY | 15,088 | 13,698 | 5,902 (2,528) | 54 | 0 / 0 / 0 / 1,336 |
| PANEL | 13,280 | 13,200 | 6,724 (6,414) | 0 | 0 / 0 / 0 / 80 |

DATA.OVL (62,640 B) is DGROUP: no code. Executed coverage still rises
with each new script (c1–c6 added 0–134 %), so the translator works from
static reach and unknown indirect targets stop loudly (D7).

## Their Finest Hour (Amiga) — cross-reference only

`tmp/TheirFinestHour&Missions_v1.1_0037&1369.lha` (WHDLoad install,
extracted to `tmp/tfh/`). Evidence for naming and structure in phase 2;
never a source of port code (guest code reaches the Amiga only as
translator output).

| Fact | Value |
|---|---|
| Version | TFH 1.0, 28 Apr 1990 (`data/read.me`) |
| Executables | `data/BOB` (game, hunks code 204,352 / data 64,020 / bss 4 B), `data/MB` (mission builder) |
| Compiler | Manx Aztec C (`MANX` marker; `LINK A5`/`UNLK A5` frames); no symbol or debug hunks |
| Shared with SWOTL | UI strings ("Insert Your Campaign Disk", "Do you want to fly the same mission again?") present in SWOTL's root/overlays: common C source |
| Data formats | `.PAC` and `.GOB` in both; `.PAC` opcode bytes (`FD`/`FE`/`FB`) look like the same RLE family |
