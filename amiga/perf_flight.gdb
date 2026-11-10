# In-game flight speed check (docs/speed-plan.md §4, flight period): the key
# script of ab_runs.py flight (play_walk.sh's: US, flight school, P-47,
# gunnery, start) marks `shot` once the cockpit is up; from then the PAL field
# at each of 61 drawn frames at the frame loop R_044E2, level flight without
# input. ab_runs.py flight reports fields per frame over frames 10-60.
set pagination off
set confirm off
break amiga_script_mark
continue
printf "FLIGHT_START field %d\n", amiga_frames
delete breakpoints
break R_044E2
set $n = 0
while $n < 61
  continue
  printf "FRAME %d field %d\n", $n, amiga_frames
  set $n = $n + 1
end
detach
quit
