#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. amiga/env.sh
: "${FSUAE_INPUT:?Set FSUAE_INPUT to a Lua-enabled Barto emulator; see docs/headless-fsuae.md}"
export FSUAE="$FSUAE_INPUT"
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/hardware-input.XXXXXX")
relative="../tmp/${run##*/}"
export FSUAE_RUN="$relative/run" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=mouse JOY1=none
# UAE synthesizes early key releases in warp mode. Keep the scripted edges.
export WARP=0
# Only the timeout mark uses KEYS; all key and mouse events come from Lua.
export SWOTL_ARGS='KEYS=3500:shot'
cp amiga/hardware_input.lua "$run/input.lua"
export EXTRA_ARGS="--uae_lua=$relative/input.lua ${EXTRA_ARGS:-}"
printf 'Diagnostic logs: %s\n' "$run"
python3 - "$run/input.gdb" <<'PYGDB'
from pathlib import Path
import re
import subprocess
import sys
# Observe the CPU register immediately after the actual hardware load. The
# Barto stub refuses CIA memory reads. Derive offsets from this build, and
# fail if the expected unique load no longer exists.
def load_site(symbol, address):
    dis = subprocess.check_output(['m68k-amiga-elf-objdump', '-d',
        '--disassemble=' + symbol, 'amiga/out/Swotl.elf'], text=True)
    base = int(re.search(r'^([0-9a-f]+) <' + symbol + r'>:', dis, re.M)[1], 16)
    ins = re.findall(r'^\s*([0-9a-f]+):\s+(?:[0-9a-f]{4}\s+)+(\S.*)$', dis, re.M)
    hits = [(i, re.search(r'move\.[bw] ' + address + r' .*?,(d[0-7])$', op))
            for i, (_, op) in enumerate(ins)]
    hits = [(i, m) for i, m in hits if m]
    assert len(hits) == 1, dis
    i, match = hits[0]
    return str(int(ins[i+1][0], 16)-base), '$' + match[1]
text = Path('amiga/hardware_input.gdb.in').read_text()
for prefix, symbol, address in [('SDR', '_ZN5Input8keyboardEv', 'bfec01'),
                                ('JOY', '_ZN5Input6sampleEv', 'dff00a')]:
    offset, register = load_site(symbol, address)
    text = text.replace('@' + prefix + '_OFFSET@', offset)
    text = text.replace('@' + prefix + '_REGISTER@', register)
lines = text.splitlines(True)
out = []
while lines:
    line = lines.pop(0)
    if line.startswith('# REPEAT '):
        count = int(line.split()[2])
        block = []
        while lines[0].strip() != '# END REPEAT':
            block.append(lines.pop(0))
        lines.pop(0)
        out.extend(block * count)
    else:
        out.append(line)
Path(sys.argv[1]).write_text(''.join(out))
PYGDB
bash amiga/debug.sh "" "$run/input.gdb" > "$run/check.log" 2>&1
grep '^HARDWARE_\|^SWOTL_HARDWARE' "$run/check.log"
grep -q '^SWOTL_HARDWARE_INPUT_OK ' "$run/check.log"
