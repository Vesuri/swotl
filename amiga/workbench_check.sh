#!/usr/bin/env bash
# Workbench start (docs/amiga-lessons.md L84, L86): the program's result at
# start.c's reply seam, from its icon and from the Shell.
#   icon   tool types MUSIC and the menu exit as KEYS: the game reads its data
#          from the icon's drawer, exits through its own menu with the state
#          restored, then result 0 with the WBStartup message held for the reply
#   bench  tool type BENCH, which the production image refuses: result 20
#   shell  argument BENCH from the Shell: result 20, no message
# Shell arguments through ReadArgs (open-work 44), stopped at rt_start once parsed:
#   lower  tfh keys=1:shot in lower case: TFH chosen, the key script set
#   prompt `?`, then tfh read from the Shell input (SWOTL_INPUT)
#   bad    an unknown argument: ReadArgs fails with IoErr 118 (wrong number of
#          arguments) for PrintFault, result 20
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/workbench-check.XXXXXX")
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=none JOY1=none FSUAE_CLAIM_STRICT=1
printf 'Diagnostic logs: %s\n' "$run"
exit_keys='KEYS=300:enter,p300:enter,p200:u,p200:e,p200:y,1500:shot'

# $1 case, $2 expected result, $3 1 if a Workbench message is expected,
# $4 1 if the game must run and restore first.
fixture() {
  {
    echo 'set pagination off'
    echo 'set confirm off'
    printf 'break *rt_stop\ncommands\n  silent\n  printf "SWOTL_WB_STOP\\n"\n  detach\n  quit 1\nend\n'
    printf 'break *amiga_script_mark\ncommands\n  silent\n  printf "SWOTL_WB_TIMEOUT fields=%%u\\n", amiga_frames\n  detach\n  quit 1\nend\n'
    if [ "$4" = 1 ]; then
      echo 'break Swotl::handBack'
      echo 'continue'
      echo 'finish'
      echo 'printf "SWOTL_WB_RESTORE status=%u fields=%u music_skip=%u\n", amiga_restore_status, amiga_frames, rt_music_skip'
      printf 'if amiga_restore_status != 127 || rt_music_skip != 0\n  detach\n  quit 1\nend\n'
    fi
    echo 'break amiga_start_return'
    echo 'continue'
    echo 'printf "SWOTL_WB_RESULT case='"$1"' result=%d message=%d\n", result, amiga_wb_startup != 0'
    printf 'if result != %s || (amiga_wb_startup != 0) != %s\n  detach\n  quit 1\nend\n' "$2" "$3"
    echo 'printf "SWOTL_WB_OK\n"'
    echo 'detach'
    echo 'quit 0'
  } > "$run/$1.gdb"
}

# $1 case, $2 gdb condition at rt_start ($tfh: TFH chosen, the sample file opened
# whether or not ref/ holds it).
options() {
  local line
  line=$(grep -n '"sfx.rsc"' src/platform/amiga/amiga_platform.c | cut -d: -f1)
  {
    echo 'set pagination off'
    echo 'set confirm off'
    printf 'set $tfh = 0\nbreak amiga_platform.c:%s\ncommands\n  silent\n  set $tfh = 1\n  continue\nend\n' "$line"
    printf 'break amiga_start_return\ncommands\n  silent\n  printf "SWOTL_WB_RESULT case=%s result=%%d\\n", result\n  detach\n  quit 1\nend\n' "$1"
    echo 'break rt_start'
    echo 'continue'
    printf 'printf "SWOTL_WB_ARGS case=%s tfh=%%d music_skip=%%u bench=%%u keys=%%d\\n", $tfh, rt_music_skip, rt_bench, key_script != 0\n' "$1"
    printf 'if !(%s)\n  detach\n  quit 1\nend\n' "$2"
    echo 'printf "SWOTL_WB_OK\n"'
    echo 'detach'
    echo 'quit 0'
  } > "$run/$1.gdb"
}

# $1 case, $2 the IoErr (pr_Result2) at the PrintFault call.
fault() {
  local line
  line=$(grep -n 'PrintFault' src/platform/amiga/amiga_platform.c | cut -d: -f1)
  {
    echo 'set pagination off'
    echo 'set confirm off'
    echo 'break rt_start'
    printf 'commands\n  silent\n  printf "SWOTL_WB_PARSED\\n"\n  detach\n  quit 1\nend\n'
    echo "break amiga_platform.c:$line"
    echo 'continue'
    echo 'set $err = *(long *)(*(long *)(*(long *)4 + 276) + 148)'
    printf 'printf "SWOTL_WB_FAULT case=%s ioerr=%%d\\n", $err\n' "$1"
    printf 'if $err != %s\n  detach\n  quit 1\nend\n' "$2"
    # The PrintFault line has more than one location.
    echo 'delete'
    echo 'break amiga_start_return'
    echo 'continue'
    printf 'printf "SWOTL_WB_RESULT case=%s result=%%d\\n", result\n' "$1"
    printf 'if result != 20\n  detach\n  quit 1\nend\n'
    echo 'printf "SWOTL_WB_OK\n"'
    echo 'detach'
    echo 'quit 0'
  } > "$run/$1.gdb"
}

check() {
  local name=$1
  FSUAE_RUN="../tmp/${run##*/}/$name" bash amiga/debug.sh "" "$run/$name.gdb" > "$run/$name.log" 2>&1 || true
  cat "$run/$name.log"
  # A disconnected debugger or an exhausted command file is not a pass.
  grep -q '^SWOTL_WB_OK$' "$run/$name.log" || { echo "FAIL: $name"; exit 1; }
}

fixture icon 0 1 1
SWOTL_WORKBENCH=1 SWOTL_TOOLTYPES="MUSIC $exit_keys" check icon
fixture bench 20 1 0
SWOTL_WORKBENCH=1 SWOTL_TOOLTYPES=BENCH check bench
fixture shell 20 0 0
SWOTL_ARGS=BENCH check shell
options lower '$tfh == 1 && rt_music_skip == 0 && key_script != 0 && *key_script == 0x31'
SWOTL_ARGS='tfh keys=1:shot' check lower
options prompt '$tfh == 1'
SWOTL_INPUT=tfh SWOTL_ARGS='?' check prompt
fault bad 118
SWOTL_ARGS=foo check bad
echo 'PASS: Workbench and Shell starts return their results; Shell arguments parse'
