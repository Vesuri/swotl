# Speed fixture (docs/speed-plan.md): the PAL field at each of the first 12
# drawn frames of the attract demo flight (one stop per frame at the frame
# loop R_044E2, outside any capture), then a 100-field instruction profile
# into ../tmp/prof/frames.bin for tools/profile_report.py.
#   AMIGA_CPU unset (68020): ./debug.sh "" perf_frames.gdb
set pagination off
set confirm off
break RPL_031E6
continue
printf "DEMO_START field %d\n", amiga_frames
delete breakpoints
break R_044E2
set $n = 0
while $n < 12
  continue
  printf "FRAME %d field %d\n", $n, amiga_frames
  set $n = $n + 1
end
delete breakpoints
printf "WINDOW_START field %d\n", amiga_frames
monitor profile 100 "" "../tmp/prof/frames.bin"
printf "WINDOW_END field %d\n", amiga_frames
detach
quit
