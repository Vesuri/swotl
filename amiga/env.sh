#!/usr/bin/env bash
# Source this for the shared Amiga environment that AmigaXDev installs (~/.local/share/amiga):
# the cross-toolchain and FS-UAE on PATH, the Kickstart, SetPatch and the FS-UAE helpers.
# Every variable can be overridden from the environment.
#   . amiga/env.sh
# or, from amiga/:
#   . env.sh
. "${AMIGA_ENV:-$HOME/.local/share/amiga/env.sh}"
