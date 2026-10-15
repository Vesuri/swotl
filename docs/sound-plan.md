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
- Effects use 2-op FM only (never additive), waveforms 0-3, feedback 7 in
  most noise patches; SPAZ ramps carrier TL itself on its 236.7 Hz tick
  (fast decays) and slides F-numbers (engines, sweeps).
- FM re-hoster: `src/platform/amiga/fm_paula.c` (per field: OPL registers +
  key-on counts → 4 voice commands; loop pool in 256-byte pages). Check
  `make t-fm` (`tools/fm_check.cpp`, vs Nuked per channel): level within
  3 dB (±1 field, above −30 dB, Paula's 6-bit volume) on ≥ 95% of fields,
  pitch within 10 cents on ≥ 99% of measurable fields; effect runs 98.4-98.9%
  and 100% (worst 8.3 cents); title music 93.4% (reprogramming within a
  field), not gated. Noise timbre is sensitive to modulator level: 0.75 dB
  key steps.

References: `make sound-reference` ([pc-reference-loop.md](pc-reference-loop.md)):
`opl.csv`, `probe.csv`, Nuked OPL WAVs in `tmp/sound/`; `make sound-fm`: the
re-hoster's Paula WAVs beside them (`NAME-paula.wav`).

## Decisions

- Music: skipped in SPAZ play (HLE `music_skip`, user 2026-10-14;
  translator-design.md). Default off while the plan is developed (user
  2026-10-15): music plays through the re-hoster; `MUSIC` keeps it off.
- Effects, two modes behind one toggle, one Paula backend:
  - **FM**: OPL register re-hoster (default; user's SWOTL files only).
  - **TFH**: SPAZ effect entries replaced (HLE, user 2026-10-14) by a sample
    player; SWOTL id → TFH sound table; samples extracted at install time
    from the user's TFH `sfx.rsc`, never committed.
- Rejected: real-time software OPL (15–35% CPU); whole-effect pre-renders
  (Chip; kept as a per-effect fallback for FM).

## Steps

1. **Paula backend (Amiga).** Key-on edge counter per channel in `rt_out8`
   (B0-B8 bit 5 rising); `fm_field` at the vertical blank in `Swotl.cpp`;
   Chip pool allocated before takeover; DMA on, silence = volume 0,
   waveform restarts staged in blanking; mute in the I/O windows and on pause; Alt-S/Alt-E.
   Checks: soak (68030, 68040), meter delta, listening.
2. **TFH mode.** Install-time extractor (TFH `sfx.rsc` → sample bank);
   id table; HLE play/stop/stop all/engine query/stop/pitch with the
   delay queue (ids ≥ 100); engine period from the pitch arguments; distance
   variants → volume. Oracle: effect-call stream vs `probe.csv`; host render
   for listening; Chip budget (open-work 19).
3. **Close.** Music skip default back on (`rt_music_skip`, ports.c) unless
   the user decides otherwise; D10 settled in `translator-design.md`;
   open-work 17 replaced by what remains (music method).
