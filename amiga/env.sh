#!/usr/bin/env bash
# Source this for the shared Amiga environment that AmigaXDev installs (~/.local/share/amiga):
# the cross-toolchain and FS-UAE on PATH, the Kickstart, SetPatch and the FS-UAE helpers.
# Every variable can be overridden from the environment.
#   . amiga/env.sh
# or, from amiga/:
#   . env.sh
. "${AMIGA_ENV:-$HOME/.local/share/amiga/env.sh}"
# Emulator: the shared native arm64 FS-UAE (harness commands: exact `monitor fields`,
# gapless chained `monitor profile`). Measurements compare one binary only (speed-plan §4).
export FSUAE="${FSUAE:-$FSUAE_ARM}"
