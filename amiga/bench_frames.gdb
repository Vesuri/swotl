# Frame bench (docs/speed-plan.md §4): PIT ticks follow guest progress
# (runtime.h rt_bench), so every build does the same guest work. Emulated
# time (field and beam line) at frames 0-12 of the attract demo flight (one
# stop per frame at the frame loop R_044E2), the guest RAM at frame 12
# (reversed, as it lies below rt_guest; its hash proves equal work), then a 100-field profile into
# ../tmp/bench/frames.bin.
#   AMIGA_CPU unset (68020): SWOTL_ARGS=BENCH ./debug.sh "" bench_frames.gdb
# A PAL line is 908 profiler cycles on this 68020 model; VPOSR/VHPOSR at $dff004 give the line.
set pagination off
set confirm off
break RPL_031E6
continue
printf "DEMO_START field %d line %d\n", amiga_frames, (*(unsigned int *)0xdff004 >> 8) & 0x1ff
delete breakpoints
break R_044E2
set $n = 0
while $n < 13
  continue
  printf "FRAME %d field %d line %d\n", $n, amiga_frames, (*(unsigned int *)0xdff004 >> 8) & 0x1ff
  set $n = $n + 1
end
delete breakpoints
set $g = *(unsigned char **)&rt_guest
dump binary memory ../tmp/bench/ram.bin $g-0xfffff $g+1
printf "WINDOW_START field %d\n", amiga_frames
monitor profile 100 "" "../tmp/bench/frames.bin"
printf "WINDOW_END field %d\n", amiga_frames
detach
quit
