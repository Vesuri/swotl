#!/usr/bin/env python3
"""Display audit (D9): each capture of amiga/display_audit.gdb, taken right
after a present returned, must show exactly the guest's A0000h frame.
Planes: bit k of a pixel in plane k, MSB first, BytesPerRow from the log;
the chunky dump is reversed (guest RAM lies reversed below rt_guest).

  display_audit.py tmp/display-audit GDB_LOG
"""
import re
import sys
from pathlib import Path


def shown(planes: list[bytes], bpr: int) -> bytes:
    out = bytearray(64000)
    for y in range(200):
        for xb in range(40):
            bits = [p[y * bpr + xb] for p in planes]
            for b in range(8):
                out[y * 320 + xb * 8 + b] = sum(((bits[k] >> (7 - b)) & 1) << k for k in range(8))
    return bytes(out)


def main() -> int:
    d, log = Path(sys.argv[1]), Path(sys.argv[2]).read_text()
    caps = re.findall(r"^AUDIT (\d+) present (\d+) field (\d+) bpr (\d+)$", log, re.M)
    if not caps:
        print("no captures")
        return 1
    bad = 0
    for k, n, field, bpr in caps:
        k = int(k)
        planes = [(d / f"{k:02d}-plane{i}.bin").read_bytes() for i in range(8)]
        want = (d / f"{k:02d}-chunky.bin").read_bytes()[::-1]
        got = shown(planes, int(bpr))
        diff = [o for o in range(64000) if got[o] != want[o]]
        state = "ok" if not diff else \
            f"{len(diff)} pixels differ, first x={diff[0] % 320} y={diff[0] // 320}"
        print(f"capture {k:2d} (present {n}, field {field}): {state}")
        bad += bool(diff)
    print(f"display audit: {len(caps)} captures, {'ok' if not bad else f'{bad} FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
