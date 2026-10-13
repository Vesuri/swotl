# Scripted steep-bank regression: require the reported entry to return.
set pagination off
set confirm off
set $walk_calls = 0
set $walk_returns = 0
set $walk_pending = 0
break *R_0EC17
commands
  silent
  if ($d2 & 0xffff) == 0x2bde
    set $walk_calls = $walk_calls + 1
    set $walk_pending = 1
  end
  continue
end
break *R_0EC19
commands
  silent
  if $walk_pending
    set $walk_returns = $walk_returns + 1
    set $walk_pending = 0
  end
  continue
end
break *rt_stop
commands
  silent
  printf "SWOTL_PLAY_STOP fields=%u calls=%u returns=%u\n", amiga_frames, $walk_calls, $walk_returns
  x/s *(char **)($sp+4)
  printf "args=%x %x\n", *(unsigned int *)($sp+8), *(unsigned int *)($sp+12)
  detach
  quit 1
end
break *amiga_script_mark
commands
  silent
  printf "SWOTL_PLAY_MARK fields=%u reads=%u calls=%u returns=%u\n", amiga_frames, amiga_mouse_reads, $walk_calls, $walk_returns
  if *(unsigned int *)($sp+4)
    if $walk_calls > 0 && $walk_calls == $walk_returns
      printf "SWOTL_PLAY_OK\n"
      detach
      quit 0
    end
    detach
    quit 1
  end
  continue
end
continue
