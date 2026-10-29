# Frame cap (runtime.h rt_frame_cap): over the first 200 frame-end polls
# (R_044E2: the attract screens' input loops, faster than a field) and 300
# frames of the attract demo flight, the polls that return in the field of
# the previous one (0 when capped), the fields they span and the CIA ticks,
# of them those run at once (none held behind a capped wait).
#   AMIGA_SETUP=a1200-060 ./debug.sh "" frame_pace.gdb
set pagination off
set confirm off
define pace
  set $fields0 = (unsigned) amiga_frames
  set $ticks0 = (unsigned) amiga_ticks
  set $async0 = (unsigned) amiga_ticks_async
  set $prev = (unsigned) amiga_frames
  set $same = 0
  set $n = 0
  while $n < $arg1
    continue
    if (unsigned) amiga_frames == $prev
      set $same = $same + 1
    end
    set $prev = (unsigned) amiga_frames
    set $n = $n + 1
  end
  set $fields = (unsigned) amiga_frames - $fields0
  set $ticks = (unsigned) amiga_ticks - $ticks0
  set $async = (unsigned) amiga_ticks_async - $async0
  printf "FRAME_PACE %s frames %u fields %u same_field %u ticks %u async %u\n", $arg0, $n, $fields, $same, $ticks, $async
end
break R_044E2
continue
pace "attract" 200
delete breakpoints
break RPL_031E6
continue
delete breakpoints
break R_044E2
continue
pace "demo" 300
detach
quit
