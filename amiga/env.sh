#!/usr/bin/env bash
# Source this to expose the shared Amiga cross-toolchain and FS-UAE.
#   . amiga/env.sh
# or, from amiga/:
#   . env.sh
SWOTL_TC="$HOME/.local"
export PATH="$SWOTL_TC/opt/bin:$SWOTL_TC:$SWOTL_TC/fs-uae:$PATH"
export KICKSTART="${KICKSTART:-$HOME/Documents/RetroPie/BIOS/kick31.rom}"
