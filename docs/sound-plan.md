# Sound plan (open-work 17, D10)

Sound effects first; music is skipped. Each step is one commit with gates
green; remove a step from this file when it is done.

## Facts (2026-10-15)

- Audio is AdLib OPL2 FM only (SPAZ + `ADLIB.SFX`); no sampled sound. SPAZ
  runs translated; its OPL writes reach `rt_opl` (`src/runtime/ports.c`),
  read by the FM re-hoster.
- SPAZ API (far C calls, SPAZ file offsets): init `+0246`, shutdown `+02EE`,
  play(id·4) `+03D5` (id ≥ 100: delayed by game `[CFA8]`/4 effect ticks;
  record byte 6 = 80h: music), stop(id) `+05AF`, stop all `+0666`, engine
  query `+06F9`, engine stop `+06D8`, engine pitch(val, base, div) `+0713`,
  detect `+12D4`. Game side: FLIGHT wrapper `+38EC..+3F9F` (same source as
  TFH `bob:2ec0..324c`); engine query + pitch once per flight frame.
- Effects: 39 ids, all starting through SPAZ `+048C` (play and the gun
  delay tick), slot 0 (OPL ch 0–2) for engines, slots 1–2 (ch 3–5, 6–8) by
  priority. 0 single piston, 1 multi-engine, 2 wind (gliding), 3 jet, 4
  rocket (engines by aircraft class, pitch(val, base, div): F = (49000 −
  val)/div + base, val = 51840 − 64·mph); 7–18 guns, 4 kinds × own /
  other near / other far (FLIGHT `sfx_var`: near below 8000h, far below
  20000h, octagonal distance), only guns delayed (id + 100); 19 rockets
  fired, 20 bomb whistle, 21/26 flak near/far, 23 plane blows up, 24
  explosion, 25 ground impact, 28/29 player hit, 30/31 splash near/far,
  32 gear, 34 touchdown, 37 click, 38 weapon arming; 5, 6, 22, 27, 33, 36
  never played; 35's slot holds the anthem. 1–3 OPL channels per effect,
  plain 2-op FM, feedback 7 in 35 of 101 patches, no rhythm mode.
- FM levels of every id: `tools/sfx_levels.py` (the original SPAZ under
  Unicorn x86 from the c6 snapshot, Nuked render) → `tmp/sound/sfx-levels.csv`;
  e.g. light MG own/near/far −24.7/−33.6/−39.9 dB.
- Music: anthems on the title and the side choice only; it stops all
  effects and effects are ignored while it plays.
- The SPAZ timer (`+07CC`, 236.7 Hz) also advances game clocks: SPAZ keeps
  running with sound off. Alt-S all sound, Alt-E engine, Alt-P pause.
- Their Finest Hour (Amiga): 13 sampled sounds in `data/sfx.rsc` (≈ 107 KB),
  20 game ids, 4-channel priority driver on the vertical blank. `sfx.rsc`:
  long 0 = directory offset D; at D+4 a word count, then (word id, long
  offset); each resource a word length, 2 unused bytes, the payload.
  Descriptors 1001–1013 (33 bytes): +12 loop offset (0 one-shot, the loop
  runs to the sample end), +18 period, +20 priority, +22/+25 attack/decay
  rate, step, level, +28 sustain (60 Hz fields, FFFFh forever; PAL ×5/6),
  +30 release. Samples 2001–2013: signed 8-bit PCM. Envelope once a field:
  acc += rate, over 255 one step. Engine period 800 → 320 with airspeed.
- Effects use 2-op FM only (never additive), waveforms 0-3, feedback 7 in
  most noise patches; SPAZ ramps carrier TL itself on its 236.7 Hz tick
  (fast decays) and slides F-numbers (engines, sweeps).
- FM re-hoster: `src/platform/amiga/fm_paula.c` (per field: OPL registers +
  key-on counts → 4 voice commands). Period loops ≤ 64 bytes rendered on
  demand (3 dB modulator steps with hysteresis, one render a field beyond
  restarts, per-voice memo: a pitch change is a new period only) in a
  16 KB Chip pool of 256-byte pages. Feedback 6-7 is chaotic only with a
  strong modulator (fb 7 < 10.5 dB, fb 6 < 4.5 dB down): two 1 KB noise
  tables built at `fm_init`, played at the modulator's pitch.
- Check `make t-fm` (`tools/fm_check.cpp`, vs Nuked per channel): level
  within 3 dB (±1 field, above −30 dB, Paula's 6-bit volume) on ≥ 95% of
  fields, pitch within 10 cents on ≥ 99% of measurable fields; effect runs
  98.1-98.6% and 100% (worst 5.5 cents), 69-88 renders in 40 s; title music
  93.2%, not gated (reprogramming within a field).
- Paula backend: `src/platform/amiga/Audio.cpp`. `fm_field` in
  `plat_service` (main program, once a vertical blank); the vertical blank
  stages the commands: DMA on, silence volume 0, loop changes latched at
  the loop's end, a key-on restarts its channel (DMA off, the outgoing
  period's countdown waited out, ≤ 16 lines; Revs, Rescue on Fractalus);
  volume 0 in I/O windows. Voices 0, 3 left, 1, 2 right. Alt-S, Alt-E and
  pause are SPAZ's own key-offs. Cost (68020 A1200 model, demo flight, 100
  fields): 4.8% (≈ 13,600 cycles a field). Soak 68030, 68040 to field 1500:
  sound live, no stop.
- Key-on edges: `rt_opl_keyon` (`rt_out8`). Oracle in every host run
  (`check_opl`): AdLib writes per port and value = the reference's
  `ports.csv`; `rt_opl`, `rt_opl_keyon` = a recount of the host's writes;
  sabotage `keyon`.

- TFH mode: argument `TFH` loads `sfx.rsc` from the game directory; missing,
  invalid or unallocatable samples log a fallback to FM. Sample ownership
  masks all three OPL channels of a slot, including the fourth FM voice;
  song starts clear ownership. `make t-tfh` checks routing, segments,
  envelopes, restarts, engine pitch and all 512 FM masks; sabotage covers
  masking, routing, restarts and volume. Music-hook flags/registers and
  sound-log ticks have separate tests and a reset sabotage. `t-audio` checks
  the production backend's sample merge, zero-volume attack/repeat commands
  and Chip release; its sabotage restores the dropped silent restart.
- TFH A1200/68020, 8 MiB Fast soak (2026-10-15): 1,500 fields, 195 audio
  restarts, 55 FM renders; 107,298 sample Chip bytes, 1,771,224 free Chip
  (largest block 1,771,120). `amiga/milestone.gdb.in` reports free Chip.
  m4 meter against `tmp/fm/meter-sfx.json`: unchanged model cycles,
  instructions, executed bytes and memory accesses; runtime code +24 bytes.

References: `make sound-reference` ([pc-reference-loop.md](pc-reference-loop.md)):
`opl.csv`, `probe.csv`, Nuked OPL WAVs in `tmp/sound/`; `make sound-fm`: the
re-hoster's Paula WAVs beside them (`NAME-paula.wav`). `make sound-tfh` runs
c6/c12/c13 with `--sound-log` and renders `tmp/sound/NAME-tfh.wav` using
`TFH_RSC` (default `tmp/tfh/TheirFinestHour&Missions/data/sfx.rsc`). The log
records posted IRQ0 counts: `tick,o,reg,value`, `tick,s,slot,id`,
`tick,m,0,0`.

## Decisions

- Music: skipped in SPAZ play (HLE `music_skip`, user 2026-10-14;
  translator-design.md). Default off while the plan is developed (user
  2026-10-15): music plays through the re-hoster; `MUSIC` keeps it off.
- Effects, two modes behind one toggle, one Paula backend:
  - **FM**: OPL register re-hoster (default; user's SWOTL files only).
  - **TFH** (hybrid, user 2026-10-15): TFH samples where SWOTL's effect has
    a counterpart, FM for the rest (jet 3, rocket 4, rockets fired 19,
    unplayed 5, 6, 22, 27, 33, 36). One observe-only HLE hook at SPAZ's
    effect start (+0516: slot, id; the guest code always runs) routes each
    slot's Paula voice to the sample or the re-hoster; engine period from
    the slot's F-number. Near/far volumes from the variants' FM levels.
    The user's TFH `sfx.rsc`, copied by the installer, parsed at startup;
    never committed. Replaces the 2026-10-14 plan to replace SPAZ's entries.
- Rejected: real-time software OPL (15–35% CPU); whole-effect pre-renders
  (Chip; kept as a per-effect fallback for FM).

## Steps

2. **Close.** Listening on the user's machine (FM/music, TFH WAVs and Amiga
   TFH mode); music skip
   default back on (`rt_music_skip`, ports.c) unless the user decides
   otherwise; D10 settled in `translator-design.md`; open-work 17 replaced
   by what remains (music method).
