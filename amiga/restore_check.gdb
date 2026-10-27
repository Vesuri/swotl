# Normal guest menu exit, then inspect readable OS/hardware state.
set pagination off
set confirm off
break *rt_stop
commands
  silent
  printf "SWOTL_RESTORE_STOP\n"
  x/s *(char **)($sp+4)
  detach
  quit 1
end
break *amiga_script_mark
commands
  silent
  printf "SWOTL_RESTORE_TIMEOUT fields=%u\n", amiga_frames
  detach
  quit 1
end
break Swotl::handBack
continue
# finish must be top-level: a resume command ends a breakpoint command list.
finish
printf "SWOTL_RESTORE status=%u fields=%u io_fields=%u\n", amiga_restore_status, amiga_frames, amiga_io_frames
if amiga_restore_status != 127
  detach
  quit 1
end
printf "SWOTL_CHIP free=%u largest=%u\n", amiga_chip_free, amiga_chip_largest
printf "SWOTL_RESTORE_OK\n"
detach
quit 0
