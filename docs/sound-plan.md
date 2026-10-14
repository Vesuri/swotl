# Sound plan (open-work 17, D10)

Sound effects first; music is skipped. Each step is one commit with gates
green; remove a step from this file when it is done.

## Facts (2026-10-14)

- Audio is AdLib OPL2 FM only (SPAZ + `ADLIB.SFX`); no sampled sound. SPAZ
  runs translated; its OPL writes reach `rt_opl` (`src/runtime/ports.c`),
  read by nothing yet.
- SPAZ API (far C calls, SPAZ file offsets): init `+0246`, shutdown `+02EE`,
  play(id·4) `+03D5` (id ≥ 100: delayed by game `[CFA8]`/4 effect ticks;
  record byte 6 = 80h: music), stop(id) `+05AF`, stop all `+0666`, engine
  query `+06F9`, engine stop `+06D8`, engine pitch(val, base, div) `+0713`,
  detect `+12D4`. Game side: FLIGHT wrapper `+38EC..+3F9F` (same source as
  TFH `bob:2ec0..324c`); engine query + pitch once per flight frame.
- Effects: 39 ids. 0–6 engines/wind (loop, slot 0 = OPL ch 0–2), 7–18 guns
  (4 kinds × near/mid/far), 19–38 one-shots; slots 1–2 (ch 3–5, 6–8) by
  priority. 1–3 OPL channels per effect, plain 2-op FM, feedback 7 in 35 of
  101 patches, no rhythm mode in effects.
- Music: anthems on the title and the side choice only; it stops all
  effects and effects are ignored while it plays.
- The SPAZ timer (`+07CC`, 236.7 Hz) also advances game clocks: SPAZ keeps
  running with sound off. Alt-S all sound, Alt-E engine, Alt-P pause.
- Their Finest Hour (Amiga): 13 sampled sounds in `data/sfx.rsc` (≈ 107 KB),
  20 game ids, 4-channel priority driver on the vertical blank.

References: `make sound-reference` ([pc-reference-loop.md](pc-reference-loop.md)):
`opl.csv`, `probe.csv`, Nuked OPL WAVs in `tmp/sound/`.

## Decisions

- Music: skipped in SPAZ play (HLE `music_skip`, user 2026-10-14;
  translator-design.md). The diagnostic argument `MUSIC` lets it through.
- Effects, two modes behind one toggle, one Paula backend:
  - **FM**: OPL register re-hoster (default; user's SWOTL files only).
  - **TFH**: SPAZ effect entries replaced (HLE, user 2026-10-14) by a sample
    player; SWOTL id → TFH sound table; samples extracted at install time
    from the user's TFH `sfx.rsc`, never committed.
- Rejected: real-time software OPL (15–35% CPU); whole-effect pre-renders
  (Chip; kept as a per-effect fallback for FM).

## Steps

1. **FM re-hoster core** (platform C, host-testable): OPL shadow → 4 Paula
   voices (slot 0 engine, slots 1–2 loudest channel, voice 3 next loudest);
   loop rendered from patch registers on key-on or timbre change (cached;
   ≈ 1 KB loops for feedback ≥ 6); period from F-number/block; volume from
   TL + envelope per 50 Hz field; key-on counter for sub-field notes. Host
   test: `opl.csv` → commanded Paula output → WAV; pitch exact, envelope
   timing within one field; WAV pairs with the references for listening.
2. **Paula backend (Amiga).** Vertical-blank stage in `Swotl.cpp`; Chip pool
   allocated before takeover; DMA on, silence = volume 0, waveform restarts
   staged in blanking; mute in the I/O windows and on pause; Alt-S/Alt-E.
   Checks: soak (68030, 68040), meter delta, listening.
3. **TFH mode.** Install-time extractor (TFH `sfx.rsc` → sample bank);
   id table; HLE play/stop/stop all/engine query/stop/pitch with the
   delay queue (ids ≥ 100); engine period from the pitch arguments; distance
   variants → volume. Oracle: effect-call stream vs `probe.csv`; host render
   for listening; Chip budget (open-work 19).
4. **Close.** D10 settled in `translator-design.md`; open-work 17 replaced by
   what remains (music method).
