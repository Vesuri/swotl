#!/usr/bin/env bash
# A1200 steep-bank regression; use AMIGA_CPU=68030 or 68040.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/play-walk.XXXXXX")
export FSUAE_RUN="../tmp/${run##*/}" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=none JOY1=none
export SWOTL_ARGS='KEYS=300:enter,p300:enter,p200:u,p200:f,p200:1,p200:1,p200:s,3000:s,3500:shot'
for ((i=0; i<30; i++)); do SWOTL_ARGS+=',p1:mx+100'; done
SWOTL_ARGS+=',p1:quit'
printf 'Diagnostic logs: %s\n' "$run"
exec bash amiga/debug.sh "" "$PWD/amiga/play_walk.gdb"
