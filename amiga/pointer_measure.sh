#!/usr/bin/env bash
# Pointer census on the A1200 model (docs/pointer-plan.md P1): in the main menu,
# the mouse moved every field for MOVE fields (steps of 4 counts, right, then
# up), then at rest for REST mouse reads. Per window: fields (amiga_frames),
# hide-show pairs (0320:0CAC then 0CD2), frames shown (amiga_display_count),
# and pairs with a present between hide and show (the hide's row marks already
# taken at the show: rt_vram_top 200), split into moves (hide called from the
# tracker 0D1A) and menu redraws. The guest position (ds:9C1A, 9CBA) at the last
# show is printed at the marks. Only cold paths are stopped on, and each count
# is a state change: a breakpoint on the guest's polls (thousands per field)
# distorts the model's timing, and a stop with an interrupt pending is
# reported again after it.
# SWOTL_ELF and SWOTL_EXE (absolute) select another build.
set -euo pipefail
cd "$(dirname "$0")/.."
. amiga/env.sh
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/pointer-measure.XXXXXX")
export FSUAE_RUN="../tmp/${run##*/}/run" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=none JOY1=none
export SWOTL_ELF="${SWOTL_ELF:-$PWD/amiga/out/Swotl.elf}"
move=${MOVE:-24}
steps=
for d in mx+4 my-4; do
  for _ in $(seq 1 $((move / 2))); do steps+=",p0:$d"; done
done
export SWOTL_ARGS="KEYS=300:enter,p300:enter,p200:shot${steps},p0:shot,p${REST:-5000}:quit"
{
  cat <<'EOF'
set pagination off
set confirm off
set $w = -1
set $hides = 0
set $shows = 0
set $shown0 = 0
set $offin = 0
set $offout = 0
set $off = 0
set $f0 = 0
set $x = -1
set $y = -1
break *rt_stop
commands
  silent
  printf "POINTER_FAIL rt_stop\n"
  detach
  quit 1
end
define report
  printf "POINTER window=%d fields=%u hides=%u shows=%u shown=%u off_tracker=%u off_menu=%u\n", $w, amiga_frames - $f0, $hides, $shows, amiga_display_count - $shown0, $offin, $offout
        set $hides = 0
  set $shows = 0
  set $refreshes = 0
  set $offin = 0
  set $offout = 0
  set $f0 = amiga_frames
end
break *amiga_script_mark
commands
  silent
  printf "POINTER mark=%d x=%d y=%d\n", $w + 1, $x, $y
  if $w >= 0
    report
  end
  set $w = $w + 1
  set $f0 = amiga_frames
  set $shown0 = amiga_display_count
  if *(int *)($sp + 4)
    printf "POINTER_OK\n"
    detach
    quit 0
  end
  continue
end
break *R_03EAC
commands
  silent
  if !$off
    set $hides = $hides + 1
    set $off = 1
    if *(unsigned int *)$sp >= (unsigned int)&R_03F1A && *(unsigned int *)$sp <= (unsigned int)&R_04211
      set $off = 2
    end
  end
  continue
end
break *R_03ED2
commands
  silent
  if $off
    set $shows = $shows + 1
    if rt_vram_top == 200 && $off == 2
      set $offin = $offin + 1
    end
    if rt_vram_top == 200 && $off == 1
      set $offout = $offout + 1
    end
    set $off = 0
  end
  set $x = *(unsigned char *)($a3 + 0x7fff - 0x9c1a) | *(unsigned char *)($a3 + 0x7fff - 0x9c1b) << 8
  set $y = *(unsigned char *)($a3 + 0x7fff - 0x9cba) | *(unsigned char *)($a3 + 0x7fff - 0x9cbb) << 8
  continue
end
continue
EOF
} > "$run/measure.gdb"
printf 'Diagnostic logs: %s\n' "$run"
bash amiga/debug.sh "" "$run/measure.gdb" "${SWOTL_EXE:-out/Swotl.exe}" > "$run/measure.log" 2>&1 || true
grep '^POINTER' "$run/measure.log"
grep -q '^POINTER_OK$' "$run/measure.log"
