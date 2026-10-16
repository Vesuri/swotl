# TFH Amiga cross-reference

Evidence only; no TFH code or data enters the port. Names below describe observed
behaviour, not recovered source symbols or authorization for native replacements.
SWOTL/DOSBox remains the correctness oracle.

## Inputs and addresses

- TFH 1.0 `data/BOB`, SHA-256
  `4b5931c8500e60b5f4cdbfa7f8e37930c731c14443bd1f88757090fb22443877`.
- HUNK code: 204,352 bytes; initialized data: 43,888 bytes in a 64,020-byte
  allocation; separate BSS: 4 bytes. No symbol/debug hunks.
- Research load bases: code `10000`, data `41E40`, BSS `51854` (hex).
  1,511 RELOC32 entries applied. Startup at `40BBC` establishes A4=`49E3E`;
  A4-relative calls enter absolute-long jump thunks in the data hunk.
- TFH offsets below are relative to the code hunk; add `10000` for Ghidra.
  SWOTL offsets follow `swotl_model.py`: root load-image or overlay-file offsets.
- Ghidra's generic 68000 decompiler assumes the wrong C integer/argument layout
  for Aztec's mixed word/long stack arguments. Disassembly settles sizes and
  offsets. Scanned `LINK A5` prologues are candidates, not proof of code coverage.

## Routine correspondence

| Descriptive name | TFH code offset | SWOTL counterpart | Evidence and limits |
|---|---|---|---|
| Index sprite records | `+139A` | `SWOTL.EXE+1D2A` | Save each record pointer, skip five header bytes, skip packets by first byte + 3, stop at FF; advance sprite index. SWOTL additionally records bank ownership. |
| Copy sprite indices | `+141A` | `SWOTL.EXE+1DFA` | Copy the two parallel normal/small sprite-index tables. |
| Load delimited records | `+146A` | `SWOTL.EXE+1E1E` | Open resource, collect FF-delimited records, optional leading-record skip, store pointers, close. This loads packed images but is not itself a decompressor. |
| Read resource into buffer | `+18EC` | `SWOTL.EXE+1EC4` | Open/read/copy/close. TFH's DOS branch uses 1,024-byte chunks and has another disk path; SWOTL uses 512-byte chunks. |
| Draw packed image | `+27D40` | `RTSVGA.OVL+3DCD` (thunk `SWOTL.EXE+16FCE`) | FD explicit run, FE next row, FF end, transparent colour argument. TFH writes four bitplanes; VGA writes bytes and adds FB/FC operations. |
| Visit terrain rings | `+11138` | `SWOTL.EXE+F290` | Shared 11-entry ring-offset table, phase-selected signed byte coordinate pairs, terrain-cell lookup, object selection. TFH uses a 64×64 nibble map; SWOTL uses a 50×50 byte map. Algorithm-family correspondence, not equivalent routines. |
| Draw ground object | `+1142C` | No one-to-one routine assigned | TFH reads the seven-byte object header and face/vertex streams indexed from `gobs.gob`; identified from consumers, not the extension alone. |

## PAC family

The extension is not a single schema: screen streams, aircraft sprite records,
palettes and text/control resources all use it. Do not feed every PAC to one parser.

Screen operations, established at TFH `+27DC0..+27E46` and
RTSVGA `+3E14..+3E7E`:

| Token | TFH screen | SWOTL VGA screen |
|---|---|---|
| Short run | Byte < FD: colour `b >> 3`, length `(b & 7)+1` | Byte < FB: colour `(b >> 2)+bank`, length `(b & 3)+1` |
| FB | Ordinary short run | Next byte selects colour bank |
| FC | Ordinary short run | Next bytes: first colour, length−1; alternate colour and colour+1 |
| FD | Next bytes: length−1, colour | Same explicit-run layout; colour is not bank-adjusted |
| FE | Advance row, reset horizontal position | Same |
| FF | End record | Same |

The transparent-colour argument suppresses normal-run writes; it is not a global
meaning of FD. Only the low four colour bits reach TFH's planar writer. VGA's FC
alternating run writes directly, bypassing the normal transparency check.

Aircraft sprites instead have five header bytes followed by packets whose first
byte counts payload bytes after two further packet bytes; FF at a packet boundary
ends the sprite. Both indexers skip these without decoding pixels. This establishes
record framing, not interchangeable compressed pixel payloads.

Local checks (`tools/tfh_xref.py`): all 16 TFH aircraft PACs and 26 SWOTL aircraft
PACs contain exactly 51 framed sprites and end exactly there. The three non-aircraft
files in SWOTL `AC/` (VGA palette and two camouflage resources) are not sprite tests.
The first screen in TFH `intro.pac`/`screens/menu.pac` and SWOTL
`FE/ABRIEF.PAC`/`FE/GBRIEF.PAC` expands to exactly 200 rows of 320 pixels.
Bytes after the first FF are not assumed to be another image (intro includes text).

## GOB family

- TFH `gmat.gob`: 2,048-byte 64×64 terrain map, two IDs per byte (even x high
  nibble), followed by 746 bytes of signed coordinate pairs. Load at Ghidra `129FE`;
  split at `+800`; consumers at `+111E4..+112D0` in code-offset
  notation. Ring offsets live at Ghidra `44998`, read as 11 big-endian words.
- SWOTL `GRING.GOB`: 746 bytes of coordinate pairs; the same 11 offsets are stored
  little-endian at `DATA.OVL+631C` (DS:`54CC`). The payload differs in 15 bytes;
  it is not a substitute for TFH's data. Root `+F2DD..+F354` uses those pairs to
  visit its byte-per-cell terrain map.
- TFH `gobs.gob`: 35 ground-object records, 2,822 bytes. Their offset table is
  **in BOB**, at Ghidra `44456`, not an archive directory in the GOB file.
  `+109E0..+109F6` selects a record; `+1142C` consumes it.
- Record header bytes: minimum-detail gate (0); two culling arguments (1–2);
  queue-selection flag (3); vertex count (4); face count (5); vertex-data offset
  (6). Names of the two culling arguments remain unassigned.
- Faces start at byte 7: index count, material selector, bounds selector, then
  vertex indices. Advance by index count + 3. Vertex data starts at the next
  even offset and uses signed big-endian 16-bit triples (6 bytes/vertex).
  Bounds selectors ≥80h select additional 12-byte records after the vertices;
  lower selectors use BOB's built-in table (`+1155A..+115C6`).
- All 35 indexed spans exactly fit face records, even alignment, vertices and
  the referenced extra records. This verifies framing, not every rendering field.
  SWOTL `SQUARES.GOB` is a different terrain resource; no identical object schema
  or one-to-one renderer match is asserted. `.GOB` here does not imply an archive.

## Reproduce locally

```sh
python3 tools/tfh_xref.py
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
tools/ghidra/ghidra_12.1_PUBLIC/support/analyzeHeadless tools/ghidra-proj TFH \
  -import tmp/tfh-xref/BOB.bin -overwrite -processor 68000:BE:32:default \
  -loader BinaryLoader -loader-baseAddr 0x10000 \
  -scriptPath "ghidra_scripts;$HOME/.local/share/amiga/ghidra_scripts" \
  -preScript SeedTfh.java \
  -postScript ExportAuditListing.java tmp/tfh-xref/BOB.txt
```

Use `-process BOB.bin` instead of `-import ... -overwrite` to retain later manual
annotations. Do not open this project in the GUI during headless analysis.
The SWOTL listings are produced by `make ghidra`; compare their addresses using
the module layout, not the raw segmented spelling printed by Ghidra.
All images, listings and project databases remain ignored local material.
