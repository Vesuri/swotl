# Release pipeline — rules

Converged sibling pipeline plus SWOTL's use (`SWOTL:` rows). Provenance: `Sl` Slicks, `Ve` Vette, `Rv` Revs, `Po` Pokeri (newest:
0.91, commit 60cf93f), `RoF` Rescue on Fractalus, `SDK` `~/.local/share/amiga/WHDLoad`
(`Install Template/Xxx Install`). Slave design: [whdload.md](whdload.md).

## Hard rule: no copyrighted bytes

- SWOTL data, manual, ROMs, RTBs, Kickstart, WHDLoad, Installer, SetPatch never in repo or archive (AGENTS.md, Sl, Po).
- Packager uses an explicit **file allowlist**, never a directory sweep (Sl, Po).
- Packager refuses any member whose SHA-256 is in the originals table; checker repeats it independently (Sl, Po).
- Rv: scans every member for any 256-byte block of the original engine → refuse. Stronger than whole-file hash; use for any exe that could embed original tables (Rv).
- Checker also rejects extension patterns of user/original files (`.cfg`, `.dat`, saves, keys) (Po).
- Private keys/saves read only at test runtime; never in source, generated headers, logs, package (Sl registration-support).
- SWOTL: `release/originals.sha256` (560 hashes: DOS ACC install, `ref/`, CLASSICS volumes, local images, TFH `sfx.rsc`), written and checked by `tools/originals.py`. The checker also scans every member for any 64-byte block of `ref/` SWOTL.EXE and the OVLs, forward and reversed: none in the 0.90 exe (2026-10-24).

## Version

- `VERSION` file (e.g. `0.90`) is the source; archive `dist/<Name>-$(cat VERSION).lha` (Sl).
- Literal version+date in: game `$VER`, slave `slv_info` + `$VER`, install helper `$VER`, `Install` `; $VER: Install x.yy (dd.mm.yyyy)`, ReadMe History (Sl, RoF §5).
- Checker asserts all of them match `VERSION` and date; no build-time date stamping → reproducible (Sl, Po, RoF §5).
- First public = 0.90; earlier numbers internal only (Po, Sl).

## Local executable

`make amiga-release` writes `amiga/out/Swotl-release.exe` using the installed
converter's `elf2hunk input.elf output.exe -s`. It verifies no symbol/debug
records remain and every loadable record matches `Swotl.exe`, including
relocations and allocation headers. The debug executable and ELF remain
unchanged; perf continues to use them. `make smoke-release` boots the separate
artifact using the same smoke fixture and emulator options. The slave
([whdload.md](whdload.md)) loads this stripped executable as `data/Swotl`.

## Make targets

SWOTL: `make install-data`, `make test-install-data`, `make release` (refuses a
tree with uncommitted tracked changes; `amiga-release whdload install-data`,
`tools/originals.py --check`, `tools/package_release.py`, `tools/check_release.py`
→ `dist/Swotl-$(cat VERSION).lha`), `make release-check`,
`make test-release-installer`. Sibling shape:

| Target | Does | Prov |
|---|---|---|
| `make dist` (alias `release`) | clean Amiga rebuild → helper → slave → `elf2hunk -s` stripped exe → `package_release.py` → `check_release.py`. Refuses to overwrite existing archive. `RELEASE_DIR` overrides output | Sl |
| `make release-check` | host oracle checks + helper tests + **two clean builds, `cmp` stripped exes** + scratch package audit in `build/release-check/` | Sl |
| no diagnostic builds packaged | clean-rebuild with default options before `dist`; SHADOW/profile/probe builds never shipped | Sl, Po |
| loop unrolling off in release, no symbol/debug hunks, no diagnostic markers | release code audit | Po, Rv |

## LHA packaging

- Archive with AmigaXDev `amigaxdev.release`: LHa for UNIX (`LHA` override, else the shared build; Homebrew `lhasa` extracts only), level-0 headers it owns, sorted members after the drawer icon, fixed DOS stamp, refusal of originals and of an existing archive; `tools/package_release.py` keeps only the file map (Po).
- LH5 only, fail rather than fall back to LH0 (Ve).
- Checker decodes each member independently with Lhasa, verifies header+payload CRC, exact member set, HUNK magic `000003f3`, icon magic, slave `WHDLOADS` header and memory/flag/quit-key bytes, byte identity with build outputs (Sl, Po).
- Record per release: archive size + SHA-256 of archive, exe, slave, helper (Sl).

## Package layout (converged)

```text
<Name> Install.info            drawer icon (template drawer)
<Name> Install/
  <Name>                       native exe (stripped)
  <Name>.slave
  <Name>.inf                   game icon template → installed as <Name>.info
  <Name>InstallData            optional extraction/validation helper
  Install, Install.info
  ReadMe, ReadMe.info          MultiView default tool
  <license>.txt                only for third-party helper code
```

Installed: `<Name>/{<Name>.slave, <Name>.info, ReadMe, ReadMe.info, data/{<Name>, originals…, saves}}`; `slv_CurrentDir = "data"` (Sl, Ve, Po).
Credits live in ReadMe, no separate CREDITS file (Sl).

## Icons

- Icons kept as base64 text (`release/icons/*.b64`) + `README.md` provenance: drawer from WHDLoad template, Install/game/ReadMe icons from released RoF archive (Sl, Po, Ve).
- Packager edits only the length-prefixed `APPNAME` field — fix the 4-byte BE length too (`amigaxdev.release.installer_icon`; Sl, RoF §4).
- Install icon: default tool Installer, `MINUSER` (Sl keeps `AVERAGE`; Po requires Intermediate; RoF used `NOVICE`), `LOG=FALSE`, `PRETEND=FALSE`; no stale `SCRIPT` (Sl, Po, RoF).
- Installer sets game icon: `setdefaulttool "WHDLoad"`, `Slave=<Name>.slave`, `PreLoad`, `setstack` (Sl 16384, Po 10240), `noposition` (Sl, Po).

## ReadMe

- Plain text, template warranty block first, then sections: Requirements, Installation, (First run), Playing and quitting, Controls, History, Contact, Credits, helper licence (Sl, Po).
- State: data not included and where the user gets it; WHDLoad 17+, Installer 43+, Kickstart 3.1 + RTB names, CPU/chipset; quit key vs saving exit (Sl, Po).
- Checker asserts section headings, History entry and project URL (Sl).
- Copied into installed drawer with icon (`copyfiles … (infos)`) (Sl, Po).

## Installer script (Pokeri 0.91 = newest)

| Rule | Prov |
|---|---|
| Abort if `@installer-version < 43*65536` | Sl, Po |
| `(welcome)`; `#source = (pathonly @icon)`; `@execute-dir #source` | Sl, Po |
| Show ReadMe before questions: `run SYS:Utilities/MultiView`, on nonzero fall back to `More` | Po, RoF/SDK template |
| `cd SYS:\nWhich WHDLoad` — abort with whdload.de pointer if missing | Sl, Po, RoF §4 |
| Soft warning if no Kickstart 3.1 + `.RTB` in `Devs:Kickstarts` or `WHDCOMMON:` (three supported names) | Sl, Po |
| Default destination from `getenv WHDLInstPath`; after `askdir`, `setenv WHDLInstPath` + `copy ENV:WHDLInstPath ENVARC:` | Po, SDK template |
| `openwbobject #dest` only if `@installer-version >= 44*65536+10`; Installer 43 skips it | Po, SDK template |
| Existing drawer: Remove/Keep, default Keep; Keep updates program files, preserves saves | Po, Ve |
| Originals present → Use existing / Replace (older: Reinstall / Use existing), default Use existing, skips source questions | Sl, Po, Ve, Rv |
| Extract/validate into unique staging drawer; copy to `data/` only on success; failure leaves install untouched | Sl, Ve |
| Never recursively delete user drawers holding saves/keys; retire obsolete launch files explicitly | Sl |
| Pre-create fixed-size save slots; refuse wrong-sized existing saves | Po |
| Keep template variable names; `@app-name` = title, `#prefix` = file name; drop RawDIC/Patcher/DIC checks | RoF §4 |
| Template file is ISO-8859-1: preserve encoding when editing | RoF §4, SDK |

## Installer testing traps

- Drive real Installer 43.3 in FS-UAE with scripted answers; log every `message` (Rv, Po, Sl).
- Boot without `ENV:`/`ENVARC:` hangs on "insert volume ENV:" at first `getenv` (Rv).
- `textfile` fails if the file exists → requester hang; unique file per logged form (Rv).
- Noninteractive viewer stand-ins exercise MultiView success / More fallback; fixture checks WHDLInstPath persistence; Installer 43 must skip `openwbobject` (Po testing.md).
- Sabotage check: old script must fail the new scenarios (Rv).
- Requester wording/layout still needs a manual pass (Rv).
- Final gate: one manual FS-UAE install + play + quit on stock target, standalone and WHDLoad, PRELOAD on/off (Sl).

## Installing the user's original data

Sibling patterns:

| Pattern | Validation | Prov |
|---|---|---|
| Publisher archive (ZIP) → bundled C helper extracts allowlisted files | SHA-256 of whole archive, per-file CRC, bounded buffers, no whole-archive alloc | Sl |
| Third-party archive (StuffIt/NDIF/HFS) → helper extracts two forks | exact size + SHA-256 per file | Ve |
| Source drawer of unpacked files → plain copy | presence + exact size | Po |
| Disc image → plain copy | exact size | Rv |

Common: helper writes to staging, removes own partial outputs, rejects existing different files; exe validates originals and returns 20 with a DOS error before display takeover (Ve, Sl, RoF §1).

**SWOTL: Air Combat Classics floppies only**

- Source: the three 1.44 MB PC floppies of Air Combat Classics (LucasArts 1993; SWOTL 2.2, BattleHawks 1942, Their Finest Hour). Their SWOTL.EXE and OVLs equal `ref/`. v1.2 floppies and the 1.x zip run other code (differing EXE, OVLs, 13 data files; 301 files fewer) and are refused. `ref/` is a repack: `_` for `-` in MIS names, missions in `CM/`, three patched files; the ACC tree is canonical.
- Input: drawer with `Disk1-3.img` (FAT12; `.ima` also) or `CLASSICS.001-003`. Sizes 1,251,008 / 1,457,152 / 481,082; SHA-256 pinned in `tools/install-data/install.c` and `release/originals.sha256`.
- Archive (INSTALIT): one PKWARE DCL implode stream per file (zlib contrib `blast`). Logical stream = CLASSICS.001[:1,204,461] + 002 + 003; the catalog (`\x05[PVM]`, 46,547 B, 808 records) occupies the rest of 001 from 1,204,461.
- Record (55 B, first at catalog+6): `0x1c`; +1 LE32 offset in start disk; `0xf0`; +6 name (13); +19 attr; +20 compressed size (spans volume splits); +24 DOS date/time; +28 CRC-32; +32 start disk; +35 size; +39 LE16 product (1 SWOTL, 2 BH1942, 3 TFH/BoB 1940); +51 LE16 directory (1 root, 2 AC, 3 CP, 4 FE, 5 FX, 6 MIS). Start offset = in-disk offset + 1,204,461 for disk 2, + 1,457,152 more for disk 3.
- SWOTL: 542 records; 539 installed (INSTALL.EXE, INSTALL2.BAT, READ.ME skipped), equal to the drawer the DOS ACC INSTALL.EXE writes (DOSBox, 2026-10-24).
- Helper `SwotlInstallData` (`tools/install-data/`): volume SHA-256 first, per-file size and CRC-32, new destination only, removes its own files on failure or Ctrl-C. Installer runs it into `Swotl/InstallStaging`, then copies into `data/`; Replace overwrites only archive files (pilots, films, missions survive).
- TFH mode: Installer asks for the user's Amiga TFH `sfx.rsc` (`TheirFinestHour/data/sfx.rsc`, 108,002 B, SHA-256 pinned); the helper checks and stages it; the game icon gets `Custom1=1` ([sound-plan.md](sound-plan.md)).
- Tests: `tools/install-data/test_install.py` (host helper vs the DOS install; damaged/missing disks, refusal, cancel, sfx), `tools/test_release_installer.py` (Installer 43 + Amiga helper in FS-UAE: fresh, tfh, keep, replace, remove, bad-disks, bad-sfx; `INSTALL_SCRIPT` sabotage override; `--archive` installs from a release LHA, `--keep` keeps the drawer). `tools/pack_preinstalled.py` packs a kept drawer as a local-only preinstalled LHA (holds game data; never shared); `tools/test_whdload.py --installed DIR [--setup a1200-040]` runs it unchanged.

## Credits (ReadMe)

- Original game: authors/publisher; Amiga port: Vesa Halttunen (Vesuri) (Sl).
- WHDLoad kick31/kickfs framework: WHDLoad SDK (public domain) (Sl).
- Reused components: dA JoRMaS display framework, Kalms C2P (public domain), puff (zlib licence text shipped beside helper) (Sl).
- Contact: project GitHub URL; whdload.de / Aminet pointers (Sl).
- SWOTL: Lucasfilm Games / Totally Games; WHDLoad kickemu; AmigaXDev install helpers (LGPL, `LICENSE.LGPL.txt`) and blast (zlib, `blast-license.txt`) shipped beside the helper.
