# Additional palette bench (D6): measure intervals 60-67; keep the opening bench.
# Frame bench (docs/speed-plan.md §4): PIT ticks follow guest progress
# (runtime.h rt_bench), so every build does the same guest work. Emulated
# time (field and beam line) at frames 0-68 of the attract demo flight (one
# stop per frame at the frame loop R_044E2), the guest RAM at frame 68
# (reversed, as it lies below rt_guest; its hash proves equal work), then a 100-field profile into
# ../tmp/bench-palette/frames.bin.
#   AMIGA_CPU unset (68020): SWOTL_ARGS=BENCH ./debug.sh "" bench_palette.gdb
# A PAL line is 908 profiler cycles on this 68020 model; VPOSR/VHPOSR at $dff004 give the line.
set pagination off
set confirm off
break RPL_031E6
continue
printf "DEMO_START field %d line %d\n", amiga_frames, (*(unsigned int *)0xdff004 >> 8) & 0x1ff
delete breakpoints
break R_044E2
set $n = 0
while $n < 69
  continue
  printf "FRAME %d field %d line %d\n", $n, amiga_frames, (*(unsigned int *)0xdff004 >> 8) & 0x1ff
  printf "BENCH_META frame %d io_fields %u publications %u\n", $n, amiga_io_frames, amiga_display_count
  set $n = $n + 1
end
delete breakpoints
set $g = *(unsigned char **)&rt_guest
dump binary memory ../tmp/bench-palette/ram.bin $g-0xfffff $g+1
printf "WINDOW_START field %d\n", amiga_frames
monitor profile 100 "" "../tmp/bench-palette/frames.bin"
printf "WINDOW_END field %d\n", amiga_frames
detach
quit
