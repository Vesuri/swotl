#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/display-audit.XXXXXX")
relative="../tmp/${run##*/}"
export FSUAE_RUN="$relative/run" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=none JOY1=none
unset SWOTL_ARGS
# Before the first published guest frame both allocated bitmaps are black.
dd if=/dev/zero of="$run/latest.bin" bs=64000 count=1 2>/dev/null
sed "s|@OUT@|$relative|g" amiga/display_audit.gdb > "$run/audit.gdb"
printf 'Diagnostic logs: %s\n' "$run"
bash amiga/debug.sh "" "$run/audit.gdb" > "$run/check.log" 2>&1
grep '^AUDIT\|^HANDOFF\|^DISPLAY_AUDIT' "$run/check.log"
grep -q '^DISPLAY_AUDIT_OK captures=40 ' "$run/check.log"
python3 tests/display_audit.py "$run" "$run/check.log"
