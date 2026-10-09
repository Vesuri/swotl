# Display audit (D9, docs/speed-plan.md S1): after a present returns no
# graphics driver call runs and every published change has been converted,
# so the shown bitplanes must equal guest A0000h. Every 20th present of the
# attract sequence (logo, title, demo flight), 40 captures, into
# ../tmp/display-audit/ for tests/display_audit.py.
#   AMIGA_CPU=68030 ./debug.sh "" display_audit.gdb
set pagination off
set confirm off
break plat_present
set $n = 0
set $k = 0
while $k < 40
  continue
  set $n = $n + 1
  if $n % 20 == 0
    finish
    set $bm = &amiga_bitmap
    set $q = $bm->BytesPerRow * 200
    set $g = *(unsigned char **)&rt_guest - 0xa0000
    eval "dump binary memory ../tmp/display-audit/%02d-chunky.bin %u %u", $k, $g - 63999, $g + 1
    set $i = 0
    while $i < 8
      set $p = (unsigned char *)$bm->Planes[$i]
      eval "dump binary memory ../tmp/display-audit/%02d-plane%d.bin %u %u", $k, $i, $p, $p + $q
      set $i = $i + 1
    end
    printf "AUDIT %d present %d field %d bpr %d\n", $k, $n, amiga_frames, $bm->BytesPerRow
    set $k = $k + 1
  end
end
detach
quit
