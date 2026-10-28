# Queued-display audit. Filled in by display_audit.sh; @OUT@ is relative
# to amiga/. Expected pixels are captured from guest RAM at plat_present,
# never from the converted bitmap, with the presented frame and the pointer
# state (rt_pointer) for the sprites; palette-only queues keep that snapshot.
set pagination off
set confirm off
set $n = 0
set $last = 0
set $k = 0
set $queued = 0
set $conversions = 0
break *rt_stop
commands
  silent
  x/s *(char **)($sp+4)
  detach
  quit 1
end
break *plat_present
commands
  silent
  set $n = $n + 1
  if $n >= $last + 20
    set $g = *(unsigned char **)&rt_guest - 0xa0000
    dump binary memory @OUT@/latest.bin $g-63999 $g+1
    set $f = *(char **)($sp+4)
    dump binary memory @OUT@/latest-frame.bin $f $f+64000
    set $pt = (char *)amiga_pointer_state
    dump binary memory @OUT@/latest-pointer.bin $pt $pt+amiga_pointer_bytes
  end
  continue
end
break *c2p1x1_8_c5_bm
commands
  silent
  set $target = (struct BitMap *)$a1
  if $target->Planes[0] == amiga_bitmap.Planes[0]
    printf "DISPLAY_AUDIT writing shown bitmap\n"
    detach
    quit 1
  end
  set $conversions = $conversions + 1
  continue
end
break *amiga_display_queued
commands
  silent
  set $queued = *(unsigned int *)($sp+4)
  if $n >= $last + 20
    shell cp @OUT@/latest.bin @OUT@/queued.bin
    shell cp @OUT@/latest-frame.bin @OUT@/queued-frame.bin
    shell cp @OUT@/latest-pointer.bin @OUT@/queued-pointer.bin
    dump binary memory @OUT@/queued.dac rt_dac rt_dac+768
  end
  continue
end
break *amiga_display_shown
commands
  silent
  if *(unsigned int *)($sp+4) != $queued || amiga_display_late || amiga_display_line >= 16 || amiga_sprite_late
    printf "DISPLAY_AUDIT bad handoff serial or beam deadline\n"
    detach
    quit 1
  end
  if $n >= $last + 20
    set $last = $n
    set $bm = &amiga_bitmap
    set $q = $bm->BytesPerRow * 200
    eval "shell cp @OUT@/queued.bin @OUT@/%02d-chunky.bin", $k
    eval "shell cp @OUT@/queued.dac @OUT@/%02d-dac.bin", $k
    eval "shell cp @OUT@/queued-frame.bin @OUT@/%02d-frame.bin", $k
    eval "shell cp @OUT@/queued-pointer.bin @OUT@/%02d-pointer.bin", $k
    set $s = (char *)amiga_sprites
    eval "dump binary memory @OUT@/%02d-sprites.bin %u %u", $k, $s, $s+144
    set $i = 0
    while $i < 8
      set $p = (unsigned char *)$bm->Planes[$i]
      eval "dump binary memory @OUT@/%02d-plane%d.bin %u %u", $k, $i, $p, $p+$q
      set $i = $i + 1
    end
    set $c = (char *)amiga_colours
    eval "dump binary memory @OUT@/%02d-colours.bin %u %u", $k, $c, $c+sizeof(amiga_colours)
    printf "AUDIT %d present %d field %d bpr %d\n", $k, $n, amiga_frames, $bm->BytesPerRow
    printf "HANDOFF serial=%u line=%u late=%u sprite_late=%u stolen=%d\n", $queued, amiga_display_line, amiga_display_late, amiga_sprite_late, amiga_sprite_stolen
    set $k = $k + 1
    if $k == 40
      printf "TICKS posted=%u async=%u runs=%u bios=%u pending=%u\n", amiga_ticks, amiga_ticks_async, rt_irq0_runs, rt_irq0_bios, (unsigned char)(rt_irq_tail - irq_head)
      set $handled = rt_irq0_runs + rt_irq0_bios
      if amiga_ticks < $handled || amiga_ticks > $handled + (unsigned char)(rt_irq_tail - irq_head) || amiga_ticks_async == 0
        printf "DISPLAY_AUDIT_TICKS posted ticks not handled, or none run at once\n"
        detach
        quit 1
      end
      printf "DISPLAY_AUDIT_OK captures=%u conversions=%u\n", $k, $conversions
      detach
      quit 0
    end
  end
  continue
end
continue
