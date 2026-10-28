#!/usr/bin/env python3
"""Display audit (D9): each capture of amiga/display_audit.gdb, taken right
after a queued frame becomes visible, must equal the frame presented at that
publication (the guest may have advanced since then), and that frame the guest
A0000h snapshot, except under the guest's pointer while it is masked
(rt_pointer shown, docs/pointer-plan.md): there the shown frame with the
pointer sprites over it (tests/amiga_sprites.py) must equal the snapshot once
the sprite is shown (it follows a state held for a field). Palette: the
guest DAC, entry F9h holding the stolen colour.
Planes: bit k of a pixel in plane k, MSB first, BytesPerRow from the log;
the chunky dump is reversed (guest RAM lies reversed below rt_guest).

  display_audit.py tmp/display-audit GDB_LOG
"""
import re
import struct
import sys
from pathlib import Path

import amiga_sprites as S


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
    stolen = [int(v) for v in re.findall(r"^HANDOFF .* stolen=(-?\d+)$", log, re.M)]
    counts = {"pointer": 0, "composed": 0, "debounce": 0}
    if len(caps) != 40:
        print(f"expected 40 captures, got {len(caps)}")
        return 1
    bad = 0
    for k, n, field, bpr in caps:
        k = int(k)
        planes = [(d / f"{k:02d}-plane{i}.bin").read_bytes() for i in range(8)]
        want = (d / f"{k:02d}-chunky.bin").read_bytes()[::-1]
        if len(want) != 64000 or any(len(p) != int(bpr) * 200 for p in planes):
            raise ValueError("short display capture")
        got = shown(planes, int(bpr))
        frame = (d / f"{k:02d}-frame.bin").read_bytes()
        pointer = (d / f"{k:02d}-pointer.bin").read_bytes()
        sprites = (d / f"{k:02d}-sprites.bin").read_bytes()
        dac = bytearray((d / f"{k:02d}-dac.bin").read_bytes())
        if stolen[k] >= 0:
            dac[0xF9 * 3:0xF9 * 3 + 3] = dac[stolen[k] * 3:stolen[k] * 3 + 3]
        colours = (d / f"{k:02d}-colours.bin").read_bytes()
        expected = struct.pack(">770I", 256 << 16,
                               *[(v & 63) * 0x04104104 for v in dac], 0)
        palette_bad = colours != expected
        problems = []
        masked = set()
        if pointer[0]:
            counts["pointer"] += 1
            w, h = pointer[1], pointer[2]
            x0, y0 = struct.unpack(">hh", pointer[4:8])
            masked = {(y0 + r) * 320 + x0 + c for r in range(h) for c in range(w)
                      if pointer[18 + r * 16 + c] != 0xFD and 0 <= x0 + c < 320 and 0 <= y0 + r < 200}
            if stolen[k] not in (-1, pointer[3]):
                problems.append(f"stolen colour {stolen[k]}, the pointer's {pointer[3]:02x}")
        diff = [o for o in range(64000) if got[o] != frame[o]]
        if diff:
            problems.append(f"{len(diff)} pixels differ from the presented frame, "
                            f"first x={diff[0] % 320} y={diff[0] // 320}")
        diff = [o for o in range(64000) if frame[o] != want[o] and o not in masked]
        if diff:
            problems.append(f"{len(diff)} presented pixels differ from A0000h, "
                            f"first x={diff[0] % 320} y={diff[0] // 320}")
        if pointer[0] and S.visible(sprites):
            counts["composed"] += 1
            composed, bad = S.compose(got, sprites, stolen[k])
            problems += bad
            diff = [o for o in range(64000) if composed[o] != want[o]]
            if diff:
                problems.append(f"shown + sprites: {len(diff)} pixels differ from A0000h, "
                                f"first x={diff[0] % 320} y={diff[0] // 320}")
        elif pointer[0]:
            counts["debounce"] += 1
        state = "ok" if not problems else "; ".join(problems)
        print(f"capture {k:2d} (present {n}, field {field}): {state}")
        if palette_bad:
            print("  palette differs from queued guest DAC")
        bad += bool(problems) or palette_bad
    print(f"pointer: {counts['pointer']} captures with it, {counts['composed']} composed with the sprites, "
          f"{counts['debounce']} in the sprite's first field")
    print(f"display audit: {len(caps)} captures, {'ok' if not bad else f'{bad} FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
