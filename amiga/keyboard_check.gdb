# Filled in by keyboard_check.sh. Left Shift (raw 60, scan 2A/AA) changes no
# game state. Phase 0: toggled as an I/O window opens after the takeover, one
# edge outstanding, until the windows' VERTB server has read a make and a break
# itself; fails at field 500. Phase 1, taken over: held 60 fields (make,
# typematic repeats after 25 fields at 10.9/s), then released.
set pagination off
set confirm off
set $phase = 0
set $inserver = 0
set $servers = 0
set $serverkeys = 0
set $down = 0
set $toggles = 0
set $reads = 0
set $presents = 0
break *rt_stop
commands
  silent
  x/s *(char **)($sp+4)
  printf "KEYBOARD_FAIL rt_stop\n"
  detach
  quit 1
end
break *'_ZL16ioKeyboardServerv'
commands
  silent
  set $inserver = 1
  set $servers = $servers + 1
  continue
end
break *amiga_io_begin
commands
  silent
  if $phase == 0 && $reads == $toggles && 'Swotl::active'
    set $down = !$down
    set $toggles = $toggles + 1
    if $down
      monitor key 60 1
    else
      monitor key 60 0
    end
  end
  continue
end
break *((char *)'_ZL16ioKeyboardServerv' + @SERVER_BACK@)
commands
  silent
  set $inserver = 0
  continue
end
break *'_ZN5Input3keyEhb'
commands
  silent
  if *(unsigned char *)($sp + 7) == 0x60
    set $reads = $reads + 1
  end
  if $inserver && *(unsigned char *)($sp + 7) == 0x60
    set $serverkeys = $serverkeys + 1
    if $serverkeys == 2 && $phase == 0
      printf "KEYBOARD window fields=%u servers=%u toggles=%u edges=%u\n", amiga_frames, $servers, $toggles, $serverkeys
      set $phase = 1
      delete $field
    end
  end
  continue
end
# Phase 0 ends by field 500 (the game may wait on a static screen).
break *'_ZL12fieldHandlerv'
set $field = $bpnum
commands
  silent
  if amiga_frames >= 500
    printf "KEYBOARD_FAIL fields=%u servers=%u toggles=%u read %u, %u in the server\n", amiga_frames, $servers, $toggles, $reads, $serverkeys
    detach
    quit 1
  end
  continue
end
break *plat_present
commands
  silent
  set $presents = $presents + 1
  if $phase == 1 && $presents >= 100
    disable
    if $down
      monitor key 60 0
      monitor fields 5
    end
    set $t = rt_key_tail
    set $f = amiga_frames
    monitor key 60 1
    monitor fields 60
    maintenance flush dcache
    set $makes = (unsigned char)(rt_key_tail - $t)
    set $i = 0
    while $i < $makes
      if rt_key_ring[($t + $i) % 16] != 0x2a
        printf "KEYBOARD_FAIL held: entry %u is %x\n", $i, rt_key_ring[($t + $i) % 16]
        detach
        quit 1
      end
      set $i = $i + 1
    end
    monitor key 60 0
    monitor fields 5
    maintenance flush dcache
    set $all = (unsigned char)(rt_key_tail - $t)
    printf "KEYBOARD held fields=%u makes=%u then %u (%x)\n", amiga_frames - $f, $makes, $all - $makes, rt_key_ring[($t + $makes) % 16]
    if $makes < 5 || $makes > 9 || $all != $makes + 1 || rt_key_ring[($t + $makes) % 16] != 0xaa
      printf "KEYBOARD_FAIL typematic\n"
      detach
      quit 1
    end
    printf "KEYBOARD_OK servers=%u server_edges=%u makes=%u\n", $servers, $serverkeys, $makes
    detach
    quit 0
  end
  continue
end
continue
