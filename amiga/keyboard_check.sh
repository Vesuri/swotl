#!/usr/bin/env bash
# Keyboard at the vertical blank (docs/irq-plan.md I7): emulated key presses,
# from FS-UAE's `monitor key`, reach rt_key_ring in I/O windows (the VERTB
# server) and with the machine taken over, with typematic repeat.
# SWOTL_ELF and SWOTL_EXE (absolute) select another build, as for sabotage.
set -euo pipefail
cd "$(dirname "$0")/.."
. amiga/env.sh
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/keyboard-check.XXXXXX")
relative="../tmp/${run##*/}"
export FSUAE_RUN="$relative/run" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=none JOY1=none
unset SWOTL_ARGS
export SWOTL_ELF="${SWOTL_ELF:-$PWD/amiga/out/Swotl.elf}"
# Symbols, not link addresses: the stub relocates the program.
# The offset of the instruction after the server's call into Input::keyboard.
back=$(m68k-amiga-elf-objdump -d --disassemble=_ZL16ioKeyboardServerv "$SWOTL_ELF" |
  python3 -c 'import re, sys
d = sys.stdin.read()
base = int(re.search(r"^([0-9a-f]+) <_ZL16ioKeyboardServerv>:", d, re.M)[1], 16)
ins = re.findall(r"^\s*([0-9a-f]+):\s+(?:[0-9a-f]{4}\s+)+(\S.*)$", d, re.M)
calls = [i for i, (_, op) in enumerate(ins) if "<_ZN5Input8keyboardEv>" in op]
assert len(calls) == 1, d
print(int(ins[calls[0] + 1][0], 16) - base)')
[ -n "$back" ]
sed -e "s|@SERVER_BACK@|$back|" \
  amiga/keyboard_check.gdb > "$run/check.gdb"
printf 'Diagnostic logs: %s\n' "$run"
bash amiga/debug.sh "" "$run/check.gdb" "${SWOTL_EXE:-out/Swotl.exe}" > "$run/check.log" 2>&1 || true
grep '^KEYBOARD' "$run/check.log"
grep -q '^KEYBOARD_OK ' "$run/check.log"
