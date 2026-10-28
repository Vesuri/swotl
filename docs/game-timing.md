# Game timing

How SWOTL 2.2 keeps real-time speed on any CPU. Read from the IR; sites in
[irq-plan.md](irq-plan.md) (handler footprint) and [sound-plan.md](sound-plan.md).

- **Clock.** SPAZ reprograms PIT channel 0 to 236.7 Hz (`+0283..+028C`); its IRQ0
  handler (`+07CC`) chains every 13th tick to the BIOS, so the DOS clock keeps time.
  Each tick increments game counters, among them `[813C]`. The tick runs with sound
  off: it is the game clock, not only the music timer.
- **Flight frame: one variable step per rendered frame.** FLIGHT `+0122A..01245`
  spins until `[813C]` is nonzero, stores it as the frame's elapsed ticks (`[88F8]`),
  sets `[88B0] = 0xEC / ticks` (236: frames per second) and clears the counter. The
  world advances by the measured time; simulation and rendering are not decoupled.
  - Slow CPU: more ticks per frame, larger steps, same world speed, lower frame rate
    (DOSBox reference: demo 9 ticks per frame, opening view 18).
  - Fast CPU: the spin guarantees one tick per frame, capping the rate at 236.7 fps;
    the elapsed count is never 0 (no divide by zero, no zero step).
- **Waits.** Menu and timeout waits count ticks (SWOTL `+3682` 200 ticks, `+0180`,
  `+3F94`), not loop passes.
- **SPAZ calibration.** At init SPAZ counts spin passes in one tick (8,956 in the
  reference; `RT_BENCH_POLLS`) and sizes its OPL register-write delays from it.
- **CPU-dependent.** The joystick read times a loop (root `+04442..+044A6`, `cli` at
  `+4469`); hence the calibration screen.
- **What 2.2 changed** for faster processors is unknown: no earlier version is in
  `ref/`. The one-tick minimum and the calibrated delays are candidates, unverified.
- **Port.** The Amiga delivers the 236.7 Hz tick from a CIA timer (irq-plan RC6), so
  the world runs at real-time speed on any Amiga; a faster CPU only adds frames.
  At 290–300 ms per frame on the 68020 a frame spans about 70 ticks.
