# Sound (D10)

Music stays enabled through the FM re-hoster in both effect modes.

## Facts (2026-10-21)

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
  rate, step, level, +28 sustain (60 Hz fields, FFFFh forever; PAL ×5/6, NTSC as is),
  +30 release. Samples 2001–2013: signed 8-bit PCM. Envelope once a field:
  acc += rate, over 255 one step. Engine period 800 → 320 with airspeed.
- Effects use 2-op FM only (never additive), waveforms 0-3, feedback 7 in
  most noise patches; SPAZ ramps carrier TL itself on its 236.7 Hz tick
  (fast decays) and slides F-numbers (engines, sweeps).
- FM re-hoster: `src/platform/amiga/fm_paula.c` (per field: OPL registers +
  key-on counts → 4 voice commands). Period loops ≤ 4096 bytes rendered on
  demand (0.75 dB modulator steps without hysteresis, up to four renders a
  field, per-voice memo: a pitch change is a new period only) in a
  64 KB Chip pool of 256-byte pages. Feedback 6-7 is chaotic only with a
  strong modulator (fb 7 < 10.5 dB, fb 6 < 4.5 dB down): two 4 KB noise
  tables built at `fm_init`, played at the modulator's pitch. An odd synthesis
  F-number avoids short feedback cycles; the moving average retains one
  byte per OPL sample. Tonal loops retain canonical synthesis phase across
  timbre changes. All four free voices can play music; continuing selected
  notes keep their physical voice. Exact lookup tables use 24 KiB ordinary
  RAM. No software mixing: each selected voice has its own Paula channel.
- Check `make t-fm` (`tools/fm_check.cpp`, vs Nuked per channel): level
  within 3 dB (±1 field, above −30 dB, Paula's 6-bit volume) on ≥ 95% of
  fields, pitch within 10 cents on ≥ 99% of measurable fields; effect runs
  98.1–98.3% and 100% (worst 8.3 cents), 410–476 renders per reference; title
  music 93.8%, not gated (reprogramming within a field). `t-fm-quality` and
  its sabotage check low-note/noise playback rates, short noise repetition,
  canonical loop phase and pitch-change overflow. `t-fm-render`, `t-fm-phase`,
  `t-fm-envelope` and `t-fm-allocation` (each with a plant) check exact operator
  samples, bounds, ≤ 0.375 dB rounding error, voice continuity and TFH
  reservations; `t-fm-cache` (plants) checks loop-cache slots and pages
  against a model of the original rule. `make gates-audio` runs every sound
  check and plant.
- Paula backend: `src/platform/amiga/Audio.cpp`. `fm_field` in
  `plat_service` (the field task, once a vertical blank, on an OPL snapshot); the vertical blank
  stages the commands: DMA on, silence volume 0, loop changes latched at
  the loop's end, a key-on restarts its channel (DMA off for two outgoing
  periods, Paula's idle point, ≤ 16 lines, a VHPOSR wait the link audits;
  Revs, Rescue on Fractalus);
  volume 0 in I/O windows. Voices 0, 3 left, 1, 2 right. Alt-S, Alt-E and
  pause are SPAZ's own key-offs. Cost before R34 (68020 A1200 model, demo
  flight, 100 fields, one capture per build): about 5.0% with short loops and
  8.5% with the longer loops (+48 KB Chip). This samples audio cost, not a
  fixed-work frame-rate comparison.
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
- TFH A1200/68020, 8 MiB Fast soak (2026-10-15): 1,500 fields, 199 audio
  restarts, 86 FM renders; 107,298 sample Chip bytes, 1,722,072 free Chip
  (largest block 1,721,968). `amiga/milestone.gdb.in` reports free Chip.

References: `make sound-reference` ([pc-reference-loop.md](pc-reference-loop.md)):
`opl.csv`, `probe.csv`, Nuked OPL WAVs in `tmp/sound/`; `make sound-fm`: the
re-hoster's Paula WAVs beside them (`NAME-paula.wav`). `make sound-tfh` runs
c6/c12/c13 with `--sound-log` and renders `tmp/sound/NAME-tfh.wav` using
`TFH_RSC` (default `tmp/tfh/TheirFinestHour&Missions/data/sfx.rsc`). The log
records posted IRQ0 counts: `tick,o,reg,value`, `tick,s,slot,id`,
`tick,m,0,0`.

## Decisions

- Music: enabled by default through the FM re-hoster (user 2026-10-15).
  `rt_music_skip` stays 0; `MUSIC` also selects music enabled.
- Quality budget: the user accepts the longer-loop audio at about +3.5 CPU
  percentage points in the sampled window and +48 KB Chip (2026-10-15).
- R34 quality tradeoff (user 2026-10-21): accepted canonical phase and
  0.75 dB steps, +0.0453% opening-bench median and +24 KiB ordinary RAM;
  no additional Chip.
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
- Rejected: real-time software OPL (15–35% CPU). Whole-effect pre-renders,
  first rejected for Chip, are now the plan below (user 2026-10-29).

## Prerendered effects (plan, user 2026-10-29)

Why: the live re-hoster renders a 4 KB loop per 0.75 dB modulator step; id 13
(own heavy gun) renders 192,512 bytes per 0.88 s shot (id 7: 768), about
19 M cycles: ~40% of a 50 MHz 68030, more than a 68020 (`tmp/fmcost`,
fm_check with a byte counter). Every play of an effect id is the same SPAZ
script, so each is rendered once at startup and played as a sample.

Decisions (user 2026-10-29): render at startup from the user's own files,
silently, before the title; every non-engine effect (ids 5–38; engines 0–4
and music stay live FM); in TFH mode only the ids TFH lacks; SPAZ's own
code runs out of the game's flow for it (approved); 0.91 waits for it.

- **R1 capture** (done: `src/runtime/sfx.c`, `t-sfx-capture`; SPAZ steps
  effects on every second tick, countdown `[176]`, 3 at init; 27 ids, 7,901
  writes).
  Observe-only HLE row at SPAZ init's return (`+02ED`,
  `retf`): the runtime holds the tick (game time pauses), saves the state
  SPAZ, its timer and the BIOS chain touch (SPAZ data, game counters, BDA,
  OPL shadow, PIC/PIT), then per id: stop all (`+0666`), play(id·4)
  (`+03D5`), SPAZ's INT 08h handler (`+07CC`) per tick through a guest far
  call/interrupt with a sentinel return (as `deliver_guest`), OPL writes to
  a capture buffer, not `rt_opl`; until SPAZ ends it (count DS:6564+id back
  to 0) or 8 s. Then restore. Oracle:
  the capture equals `tools/sfx_levels.py` (original SPAZ under Unicorn)
  write for write and tick for tick; host milestones still match the
  reference with the prerender on (restore complete).
- **R2 render** (done: `fm_effect` in `fm_paula.c`, `t-fm-effect`; 27 ids,
  28.1 s, 464,974 bytes at 16,572 Hz with the end below). Per id, the captured stream through
  the re-hoster's operator model, updated per tick, synthesised directly at
  the output rate in one pass (phase continuous; a same-tick key-off/on
  retriggers, as on the bus; one signed table lookup an operator), the
  effect's channels mixed in 16 bits, then one signed 8-bit sample
  normalised to its peak; `*level` the peak in OPL units (a full-scale voice
  is one channel at 0 dB, 4095). A channel is silent 42 dB under the peak so
  far (the scaled sample's 8-bit floor). The end: SPAZ fades many effects
  slowly before its key-off (cannon 13: 1.43 s; TFH's cannon 0.54 s), so an
  effect ends `FM_EFFECT_FADE` (0.2 s) after its last 20 ms window within
  `FM_EFFECT_END_DB` (30) of its loudest, faded out linearly (fm_paula.h,
  tunable; bump `FM_EFFECT_VERSION`); 36.2 s uncut. Trailing zeros are cut. Oracle
  `tools/fm_effect_check.cpp` vs Nuked sampled every third chip sample (the
  same waveform): AC level per 20 ms within 3 dB on >= 90% and 6 dB on all,
  pitch within 10 cents where the reference is tonal (ids 20, 32, 38;
  feedback noise and sub-audio rumble have none); the fade not compared.
  The end: the reference (to the last write and its release) has no window
  within 27 dB of its loudest after ours ends; where it still sounds within
  40 dB there, ours ends faded (last window 36 dB under; 7 ids). Plants:
  pitch, level, end (cut at half), fade (undone). `t-sab-sfx-capture`'s
  plants write their own captures (tmp/sfx-capture.csv stays the real one).
  Known: direct synthesis aliases partials above 8.3 kHz (mult 15
  modulators, feedback 7): ids 19, 30, 31 are up to 5 dB louder than the
  chip output band-limited by a 3-sample average.
- **R3 play** (done: `tfh_paula.c`, `Audio.cpp`, `t-sfx-play`, `t-audio`).
  Production (`rt_sfx_prerender_on`, not the sync image) renders the ids
  `tfh_effect_wanted` names (without TFH the 27, with TFH id 19) into one
  Chip block each at SPAZ init. A slot whose id has a sample (TFH's first)
  plays it once on the slot's voice, slot channels muted, period 214 PAL /
  216 NTSC, volume from the peak (64 at most: twelve ids peak above one
  channel, up to +9.4 dB, id 13; the live re-hoster gives a slot one
  voice); a new start restarts. Samples over one Paula loop (id 20, 72 KB)
  play in equal chunks, each latched a field after the one before starts.
- **R4 Amiga** (done: `fm_effect_run.s`, `t-fm-effect-asm`; the cache in
  `Audio.cpp`, `t-audio`, `test-whdload`). Each capture ends when SPAZ ends
  the effect (R1). The render's channel loop is hand-written 68020
  (`FM_EFFECT_ASM`, four variants: feedback x connection); oracle: fm_effect
  with it on the Unicorn 68020 core equals the C build on the 27 captured
  ids and one synthetic effect per variant, byte for byte. Plants: index
  mask, feedback, modulator history. The samples go to `sfx.cache` (game
  drawer), keyed on `FM_EFFECT_VERSION`, PAL/NTSC, the start registers and
  each wanted id's writes; written in one `Write` (under WHDLoad each write
  is a save and a write delay), refused whole if anything differs or is cut,
  then rendered and rewritten. Measured (`SWOTL_EFFECTS`, m2-choose-side;
  the end of R2 included), A1200 model 68020: capture 140 fields, render 654
  and cache write 7 at the first start (16 s), from the cache 6 (3 s with the
  capture); 68030: capture 40, render 285, write 1 (6.5 s), cached 4 (0.9 s);
  464,994 Chip bytes, file 465,226 (TFH: id 19 alone, 39,368). The end saves
  Chip, not render time: the effect is synthesised whole before its cut.
