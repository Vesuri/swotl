# PLINK overlays (SWOTL 2.2)

Phoenix PLINK overlay manager as linked into `SWOTL.EXE`. Root offsets are
load-image offsets; `seg:off` are link (unrelocated) values. Checked by
`tools/plink_check.py` over the trace corpus (94 traces, m0–m7 + c1–c85):
1,009 load calls reading 1,128 files, 4,109,156 calls on resident overlays,
0 model violations.
Load layout proved by `tools/load_image.py` (gate 1).

## Pieces

| Piece | Where | Fact |
|---|---|---|
| Manager code | `1617:0000` = root `+16170..+1657E` | DOS/INT helpers, load routine, startup |
| Manager data | `1606:0000` = root `+16060` | `[70]` DOS ≥ 2 flag, `[72]` open handle, `[74]` 128 B fixup buffer (`+160D4`), `[FC]` name offset of the open file, `[100]` load mode; `$` messages "Ovl stack underflow/overflow", "No mem for ovl stack", "Dos 2.0 required" (no stack code uses them in this build) |
| Overlay table | `169E:0000` = root `+169E0` | word 0 = load segment (written at startup), then 12 records of 16 B at `+169E6 + 16·(id−1)` |
| Thunks | root `+16B66..`, 12 B each | `call far 1617:034C` · `dw id` · `jmp far seg:off` (target in overlay `id`) |
| Startup | MZ entry `1617:0382` (root `+164F2`) | own stack (`169E:[4]`, SP 100h), relocate table segments, DOS version check, preload every overlay with flag bit 14, then `jmp far 1369:0002` (C startup) |

Table record (all words; segment words are relocated by MZ relocations, so
absolute at run time):

| Offset | Field | Note |
|---|---|---|
| `+0` | flags | bit 15 resident (run time), bit 14 preload at startup, bit 13 set on DATA only (meaning open: open-work 9c), bits 0–12 parent id |
| `+2` | nfix | fixup count; file code starts at `(nfix·4 + 15) & ~15` |
| `+4` | seg | load segment of the code |
| `+6` | end | first segment after the overlay's area |
| `+8` | name | offset in `169E` of the file name |
| `+A`, `+C` | file position | paragraphs, dword; 0 for every overlay (one file each) |
| `+E` | paras | code size |

| id | Overlay | seg | end | Parent | Flags (file) |
|---|---|---|---|---|---|
| 1 | SPAZ | `1770` | `18E4` | — | 0 |
| 2 | SFXA | `1770` | `187A` | — | 0 |
| 3 | RTSVGA | `18E4` | `1D5A` | — | 0 |
| 4 | RTSTANDY | `18E4` | `1D87` | — | 0 |
| 5 | RTSEGA | `18E4` | `1E7C` | — | 0 |
| 6 | FRONTEND | `1E7C` | `3156` | — | 0 |
| 7 | CAMPAIGN | `3156` | `3B53` | 6 FRONTEND | 6 |
| 8 | NOTCAMP | `3156` | `3AE5` | 6 FRONTEND | 6 |
| 9 | FLIGHT | `1E7C` | `36D6` | — | 0 |
| 10 | REPLAY | `36D6` | `3A85` | 9 FLIGHT | 9 |
| 11 | PANEL | `36D6` | `3A14` | 9 FLIGHT | 9 |
| 12 | DATA | `3B53` | `4B1E` | — | `6000` (preload) |

## Call path

1. Caller does `call far` to a thunk (from root or any overlay).
2. Thunk `call far 1617:034C`: manager saves flags + 9 registers, reads
   `id` at its return address, advances the return address by 2, calls the
   load routine `1617:02F2` (root `+16462`) with CX = id, restores, `retf`
   to the thunk's `jmp far`.
3. Load routine, per id then parent (`flags & 1FFFh`) until 0: if bit 15
   is clear, clear bit 15 of every overlay whose `[seg, end)` overlaps
   (`+16205`), read the code (file position + header paragraphs) to `seg`,
   read the fixup list 32 entries at a time into `1606:0074`, add the load
   segment (`169E:[0]`) to each `seg:off` word (`+16456`), set bit 15. The
   file stays open while the same name is loaded again (`[FC]`); INT 24h
   is redirected to a fail stub during the read.
4. `jmp far` goes straight to the overlay. No return stack, no return
   thunk: the overlay's `retf` returns to the original caller.

Consequences (all held over the corpus):

- An overlay is read exactly when its bit 15 is clear; calls on resident
  overlays cost the manager's register save only.
- No load ever replaces the code that issued the call (probe
  `caller_intact`). The design relies on swaps being made from the root or
  from an overlay outside the replaced area.
- Coexisting sets: driver areas `1770–18E4` (SPAZ | SFXA) and `18E4–1E7C`
  (one RTS driver) are disjoint from the game area; the game area holds
  FRONTEND + (CAMPAIGN | NOTCAMP) or FLIGHT + (REPLAY | PANEL); DATA
  (`3B53–4B1E`) is preloaded and never displaced. FLIGHT's range covers
  CAMPAIGN/NOTCAMP, so loading FLIGHT evicts them and FRONTEND.
- Loading a child pulls its parent back: NOTCAMP reloads FRONTEND, REPLAY
  reloads FLIGHT (seen in m2 and m6).
- Errors: open/read failure → message and exit (`+161C0`, AH=4Ch); not
  seen in traces.

## Tracer probe

The trace patch records each call of the load routine (`plink.csv`:
caller module, id, via thunk, resident before, loaded, caller intact,
count; `plink` events for loads and violations).
