# Flyby profile (docs/speed-plan.md §1 F0; supplementary, user decision U9):
# from drawn frame 12 of the attract demo, five consecutive 100-field
# instruction profiles (500 fields, distant fighters to close B-17s) into
# ../tmp/prof/flyby-K.bin, with the guest view and DAC at each window start
# (flyby-K.vram, reversed guest bytes; flyby-K.dac) for tools/profile_tree.py.
#   AMIGA_CPU unset (68020): ./debug.sh "" perf_flyby.gdb
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
set $k = 0
while $k < 5
  set $g = *(unsigned char **)&rt_guest - 0xa0000
  eval "dump binary memory ../tmp/prof/flyby-%d.vram %u %u", $k, $g-63999, $g+1
  eval "dump binary memory ../tmp/prof/flyby-%d.dac %u %u", $k, &rt_dac, (char *)&rt_dac+768
  printf "WINDOW %d field %d\n", $k, amiga_frames
  eval "monitor profile 100 \"\" \"../tmp/prof/flyby-%d.bin\"", $k
  set $k = $k + 1
end
printf "WINDOW_END field %d\n", amiga_frames
detach
quit
