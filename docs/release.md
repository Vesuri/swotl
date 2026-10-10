# Release pipeline — rules

Converged sibling pipeline plus SWOTL's planned use. `[PLAN]` = SWOTL intent,
not built. Provenance: `Sl` Slicks, `Ve` Vette, `Rv` Revs, `Po` Pokeri (newest:
commit a0d16a2), `RoF` Rescue on Fractalus, `SDK` `~/.local/share/amiga/WHDLoad`
(`Install Template/Xxx Install`). Slave design: [whdload.md](whdload.md).

## Hard rule: no copyrighted bytes

- SWOTL data, manual, ROMs, RTBs, Kickstart, WHDLoad, Installer, SetPatch never in repo or archive (AGENTS.md, Sl, Po).
- Packager uses an explicit **file allowlist**, never a directory sweep (Sl, Po).
- Packager refuses any member whose SHA-256 is in the originals table; checker repeats it independently (Sl, Po).
- Rv: scans every member for any 256-byte block of the original engine → refuse. Stronger than whole-file hash; use for any exe that could embed original tables (Rv).
- Checker also rejects extension patterns of user/original files (`.cfg`, `.dat`, saves, keys) (Po).
- Private keys/saves read only at test runtime; never in source, generated headers, logs, package (Sl registration-support).
- **[PLAN]** SWOTL: hash table of the v2.2 DOS install files (`ref/`) kept local-only (hashes, not bytes, may be committed as Sl/Ve do); add block-scan if any original table is compiled into the exe.

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
artifact using the same smoke fixture and emulator options. This target builds
an executable only; packaging below remains planned.

## Make targets (Slicks shape)

| Target | Does | Prov |
|---|---|---|
| `make dist` (alias `release`) | clean Amiga rebuild → helper → slave → `elf2hunk -s` stripped exe → `package_release.py` → `check_release.py`. Refuses to overwrite existing archive. `RELEASE_DIR` overrides output | Sl |
| `make release-check` | host oracle checks + helper tests + **two clean builds, `cmp` stripped exes** + scratch package audit in `build/release-check/` | Sl |
| no diagnostic builds packaged | clean-rebuild with default options before `dist`; SHADOW/profile/probe builds never shipped | Sl, Po |
| loop unrolling off in release, no symbol/debug hunks, no diagnostic markers | release code audit | Po, Rv |

## LHA packaging

- Encoder: LHa for UNIX (`github.com/jca02266/lha` @ `16619b06`), `LHA` env override, default the shared `~/.local/share/amiga/lha-compressor/src/lha`. Homebrew `lhasa` extracts only (Ve, RoF §3, Sl).
- LH5 only, fail rather than fall back to LH0 (Ve).
- Deterministic: sorted members, fixed date headers, packager owns every header field (level-0 in Sl/Ve/Po; RoF level-1) (Sl, Po).
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
- Packager edits only the length-prefixed `APPNAME` field — fix the 4-byte BE length too (Sl, RoF §4).
- Install icon: default tool Installer, `MINUSER` (Sl keeps `AVERAGE`; Po requires Intermediate; RoF used `NOVICE`), `LOG=FALSE`, `PRETEND=FALSE`; no stale `SCRIPT` (Sl, Po, RoF).
- Installer sets game icon: `setdefaulttool "WHDLoad"`, `Slave=<Name>.slave`, `PreLoad`, `setstack` (Sl 16384, Po 10240), `noposition` (Sl, Po).

## ReadMe

- Plain text, template warranty block first, then sections: Requirements, Installation, (First run), Playing and quitting, Controls, History, Contact, Credits, helper licence (Sl, Po).
- State: data not included and where the user gets it; WHDLoad 17+, Installer 43+, Kickstart 3.1 + RTB names, CPU/chipset; quit key vs saving exit (Sl, Po).
- Checker asserts section headings, History entry and project URL (Sl).
- Copied into installed drawer with icon (`copyfiles … (infos)`) (Sl, Po).

## Installer script (Pokeri a0d16a2 = newest)

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
| Originals present → Reinstall / Use existing, default Use existing, skips source questions | Sl, Po, Ve, Rv |
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

**[PLAN] SWOTL**

- Originals are a DOS **installed** directory (reference: v2.2, `ref/`), so the Pokeri pattern (source-drawer copy, no helper) is the default candidate.
- User supplies their own copy: an existing PC/DOSBox install copied to the Amiga, original disks installed on a PC, or a digital re-release (GOG/Steam). Re-release layouts, versions and whether they match v2.2 are **unverified**.
- Installer asks for the drawer, checks an allowlist of required files by size and (helper or exe) SHA-256 against known versions; unsupported version → clear refusal.
- Exe re-validates at startup and fails with DOS error 20 before takeover.
- Whether files need conversion (e.g. disk images or archives from re-releases) decides whether a helper is needed; avoid one if plain copy suffices.

## Credits (ReadMe)

- Original game: authors/publisher; Amiga port: Vesa Halttunen (Vesuri) (Sl).
- WHDLoad kick31/kickfs framework: WHDLoad SDK (public domain) (Sl).
- Reused components: dA JoRMaS display framework, Kalms C2P (public domain), puff (zlib licence text shipped beside helper) (Sl).
- Contact: project GitHub URL; whdload.de / Aminet pointers (Sl).
- **[PLAN]** SWOTL: credit Totally Games / Lucasfilm Games as original; list only components actually used.
