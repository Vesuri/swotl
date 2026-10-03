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

PLINK overlay table: 12 records of 16 bytes at root `+169E8` (in
`.OVL` name order; name offsets relative to `+169E0`). The `.OVL` file is
the fixup list (`nfix` far pointers `off, link seg`, padded to a
paragraph), then `paras` paragraphs of code. Load (proved by
`tools/load_image.py`, gate 1): code at load seg + link seg; each fixup
word += load seg. The loader reads code at `SWOTL.EXE+16328`, then the
fixup list in 128-byte chunks into a buffer at root `+160D4`.

| # | Overlay | nfix | Link seg | End seg | Paras | Last word |
|---|---|---|---|---|---|---|
| 0 | SPAZ | `8D` | `1770` | `18E4` | `174` | 0 |
| 1 | SFXA | `08` | `1770` | `187A` | `10A` | 0 |
| 2 | RTSVGA | `05` | `18E4` | `1D5A` | `476` | 0 |
| 3 | RTSTANDY | `05` | `18E4` | `1D87` | `4A3` | 0 |
| 4 | RTSEGA | `05` | `18E4` | `1E7C` | `598` | 0 |
| 5 | FRONTEND | `4C0` | `1E7C` | `3156` | `12DA` | 6 |
| 6 | CAMPAIGN | `2CB` | `3156` | `3B53` | `9FD` | 6 |
| 7 | NOTCAMP | `371` | `3156` | `3AE5` | `98F` | 0 |
| 8 | FLIGHT | `3A3` | `1E7C` | `36D6` | `185A` | 9 |
| 9 | REPLAY | `ED` | `36D6` | `3A85` | `3AF` | 9 |
| 10 | PANEL | `60` | `36D6` | `3A14` | `33E` | `6000` |
| 11 | DATA | `234` | `3B53` | `4B1E` | `F4B` | `FFFF` |

Record words 4–5 are zero in the file (runtime state); the last word is
open (2.2). DATA is the C data segment: DS = load seg + `3BAB`. Load
segment in all runs: `0822`.

Other first-run facts: PIT reprogrammed (~250 Hz INT 8); AdLib music
(`388h/389h`); joystick probe on `201h`; mouse via INT 33h; EMS 4.0 used
for paging data (INT 67h AH=40–44); keyboard via C runtime `kbhit`
(INT 21h AH=0Bh at `SWOTL.EXE+13ED3`) and INT 16h AH=02h; only RTSVGA
touches VGA memory and ports.

## Launcher

`sw.bat`: `swotl V S 5 N Y Y 64`, pinned for reference runs. Parsed in
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
