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
| Linker | Phoenix PLINK (copyright 1984–86 string; "Ovl stack underflow/overflow", "No mem for ovl stack") |
| Overlay names | in the root: SPAZ SFXA RTSVGA RTSTANDY RTSEGA FRONTEND CAMPAIGN NOTCAMP FLIGHT REPLAY PANEL DATA |

## Overlays

`.OVL` files are raw images (no header) that start with a far-pointer table.
Pointer segments are link-time segments in the root's numbering, i.e. the
overlay's link address; relocation by the load segment is still open (2.2).
`tools/ovl_info.py` stops the table at the first zero segment and may
overrun into code (PANEL).

| Overlay | Bytes | Paras | Link seg (first entry) | Shares link seg with |
|---|---|---|---|---|
| SFXA | 4,288 | 268 | `1770` | SPAZ (= end of root image) |
| SPAZ | 6,528 | 408 | `1770` | SFXA |
| RTSVGA | 18,304 | 1,144 | `18E4` | RTSEGA, RTSTANDY; 5-entry table |
| RTSEGA | 22,944 | 1,434 | `18E4` | |
| RTSTANDY | 19,024 | 1,189 | `18E4` | |
| FRONTEND | 82,080 | 5,130 | `1E7C` | FLIGHT |
| FLIGHT | 103,472 | 6,467 | `1E7C` | FRONTEND; extends to `37BF`, over `3156` and `36D6` |
| CAMPAIGN | 43,776 | 2,736 | `3156` | NOTCAMP |
| NOTCAMP | 42,688 | 2,668 | `3156` | CAMPAIGN |
| REPLAY | 16,048 | 1,003 | `36D6` | PANEL |
| PANEL | 13,664 | 854 | `36D6` | REPLAY |
| DATA | 64,896 | 4,056 | `4133` (most entries `3BAF`) | |

Static reading, to be proved by load captures (1.4): one sound area, one
graphics-driver area, then a FRONTEND/FLIGHT area that FLIGHT extends over
the CAMPAIGN/NOTCAMP and REPLAY/PANEL areas.

## Launcher

`sw.bat`: `swotl V S 5 N Y Y 64` (arguments decoded in 1.8).
