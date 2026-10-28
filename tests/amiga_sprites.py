"""The Amiga pointer sprites (src/platform/amiga/Pointer.cpp) over a shown frame,
from their dumped words: sprite 4 then sprite 6, 36 words each (position,
control, 16 rows of DATA/DATB, end), BPLCON4 bank F, so sprite 4 shows entries
F8h + colour and sprite 6 FCh + colour; sprite 4 covers sprite 6. Beam
position of pixel (0, 0): HSTART $80, VSTART $38 (DIWSTRT $3881); the display
window clips. Sprite 4's colour 1 (F9h) holds the stolen colour: composed as
that colour's index."""
import struct

SPRITE_WORDS = 36
SPRITE_X, SPRITE_Y = 0x80, 0x38
STOLEN = 0xF9


def decode(words: bytes) -> dict[int, int]:
    """{screen offset: colour entry} of the visible sprite pixels."""
    w = struct.unpack(f">{2 * SPRITE_WORDS}H", words[:4 * SPRITE_WORDS])
    out = {}
    for k, base in ((1, 0xFC), (0, 0xF8)):     # sprite 6 first: sprite 4 covers it
        pos, ctl = w[k * SPRITE_WORDS], w[k * SPRITE_WORDS + 1]
        vstart = (pos >> 8) | ((ctl >> 2) & 1) << 8
        vstop = (ctl >> 8) | ((ctl >> 1) & 1) << 8
        hstart = (pos & 0xFF) << 1 | (ctl & 1)
        for r in range(max(0, min(vstop - vstart, 16))):
            a, b = w[k * SPRITE_WORDS + 2 + 2 * r], w[k * SPRITE_WORDS + 3 + 2 * r]
            for c in range(16):
                colour = (a >> (15 - c) & 1) | (b >> (15 - c) & 1) << 1
                x, y = hstart - SPRITE_X + c, vstart - SPRITE_Y + r
                if colour and 0 <= x < 320 and 0 <= y < 200:
                    out[y * 320 + x] = base + colour
    return out


def compose(shown: bytes, words: bytes, stolen: int) -> tuple[bytes, list[str]]:
    """The frame with the sprites over it, F9h pixels as `stolen`; problems: a
    sprite pixel in an entry other than F9h (with a stolen colour) or FEh."""
    out, problems = bytearray(shown), []
    pixels = decode(words)
    for o, entry in pixels.items():
        if entry == STOLEN and stolen >= 0:
            out[o] = stolen
        elif entry == 0xFE:
            out[o] = entry
        else:
            problems.append(f"sprite pixel x={o % 320} y={o // 320} in entry {entry:02x}"
                            f"{'' if stolen >= 0 else ' with no stolen colour'}")
            break
    return bytes(out), problems


def visible(words: bytes) -> bool:
    w = struct.unpack(f">{2 * SPRITE_WORDS}H", words[:4 * SPRITE_WORDS])
    return bool(w[SPRITE_WORDS] or w[SPRITE_WORDS + 1])
