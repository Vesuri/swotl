#!/usr/bin/env bash
# Standalone 68020/Fast RAM costs. Never rebuilds or runs the game.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
. amiga/env.sh
# Pin the normal speed-fixture machine; reject external overrides.
for setting in AMIGA_CPU CPU AMIGA_SETUP EXTRA_ARGS; do
    if [ -n "${!setting:-}" ]; then echo "unset $setting for the 68020 probe" >&2; exit 1; fi
done
RUN=$(mktemp -d "$ROOT/tmp/cost-probe.XXXXXX")
export FSUAE_RUN="${RUN#"$ROOT/"}/emulator" FSUAE_CLAIM_STRICT=1
. "$FSUAE_COMMON"
cleanup() {
    fsuae_stop
    rm -f "$RUN/capture.bin"
}
trap cleanup EXIT
mkdir -p "$RUN/dh0/c" "$RUN/dh0/s" "$RUN/dh1" "$RUN/gdbhome" "$RUN/state"
python3 tools/m68k_cost_probe.py "$RUN" ${COST_PROBE_PLANT:+--plant}
vasmm68k_mot -m68020 -Felf -quiet -x -no-opt -o "$RUN/probe.o" "$RUN/probe.s"
m68k-amiga-elf-gcc -m68020 -nostdlib -Wl,--emit-relocs,-Ttext=0 -o "$RUN/probe.elf" "$RUN/probe.o"
elf2hunk "$RUN/probe.elf" "$RUN/dh1/CostProbe"
m68k-amiga-elf-objdump -d "$RUN/probe.elf" > "$RUN/probe.dis"
cp "$SETPATCH" "$RUN/dh0/c/SetPatch"
printf 'C:SetPatch QUIET\ncd dh1:\nCostProbe\n' > "$RUN/dh0/s/startup-sequence"
AMIGA_MODEL=A1200 CHIP_KB=2048 FAST_KB=8192 WARP=0 DEBUG=1 NTSC=0
fsuae_claim_port
fsuae_options
printf '%s\n' "${FSUAE_ARGS[@]}" > "$RUN/options.txt"
shasum -a 256 "$RUN/probe.elf" "$(command -v "${FSUAE:-fs-uae}")" > "$RUN/hashes.txt"
echo "Probe artifacts: $RUN"
for pass in 1 2 3; do
    fsuae_launch --hard_drive_0="$RUN/dh0" --hard_drive_1="$RUN/dh1" \
        --remote_debugger_trigger=CostProbe --state_dir="$RUN/state"
    for i in $(seq 1 60); do
        kill -0 "$FSUAE_PID" || exit 1
        if lsof -nP -iTCP:"$DEBUG_PORT" -sTCP:LISTEN >/dev/null 2>&1; then break; fi
        sleep 1
    done
    cat > "$RUN/probe.gdb" <<EOF
set pagination off
set confirm off
set remotetimeout 90
target remote 127.0.0.1:$DEBUG_PORT
break probe_ready
continue
if (unsigned int)&probe_ready < 0x200000 || (unsigned int)&probe_ready >= 0xa00000
  echo code not in Fast RAM\n
  quit 1
end
if ((unsigned int)&probe_buffer & 3) != 0
  echo buffer not aligned\n
  quit 1
end
printf "PROBE_BASE code=%x data=%x\n", &probe_ready, &probe_buffer
delete breakpoints
monitor profile 50 "" "$RUN/capture.bin"
maintenance flush register-cache
if \$d7 != 0
  echo PROBE_ARITHMETIC_FAILURE\n
  quit 1
end
echo COST_PROBE_OK\n
detach
quit
EOF
    env HOME="$RUN/gdbhome" XDG_CACHE_HOME="$RUN/gdbhome" \
        m68k-amiga-elf-gdb -q -batch -x "$RUN/probe.gdb" "$RUN/probe.elf" > "$RUN/pass-$pass.log" 2>&1
    fsuae_stop
    FSUAE_PID=""
    grep -q COST_PROBE_OK "$RUN/pass-$pass.log"
    python3 tools/m68k_cost_probe.py "$RUN" --capture "$RUN/capture.bin" \
        --output "$RUN/pass-$pass.json" | tee "$RUN/pass-$pass.txt"
    rm "$RUN/capture.bin"
done
