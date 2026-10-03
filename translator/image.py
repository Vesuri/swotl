"""Proved module images and annotations (gate 1 layout: tools/swotl_model.py)."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import swotl_model as M  # noqa: E402

ANNOTATIONS = REPO / "annotations"
SCOPE = M.SCOPE


def load(ref: Path = M.REF) -> dict[str, M.Module]:
    return M.load_modules(ref)


def rows(name: str) -> list[dict]:
    with (ANNOTATIONS / name).open() as f:
        return list(csv.DictReader(f))


def smc_regions() -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r in rows("self-modifying.csv"):
        span = (int(r["first"], 16), int(r["last"], 16))
        if span not in out[r["module"]]:
            out[r["module"]].append(span)
    return out


def runtime_bytes(traces: list[Path]) -> dict[str, bytes]:
    """Module images as found in the first snapshot holding each self-modified region."""
    out = {}
    mods = load()
    for name, spans in smc_regions().items():
        for t in traces:
            for snap in sorted(t.glob("snap-*")):
                res = M.residency(snap / "residency.csv")
                img = bytearray(mods[name].data)
                ram = (snap / "ram.bin").read_bytes()
                covered = set()
                for lo, hi, mod, off in res:
                    if mod == name:
                        n = min(hi - lo, len(img) - off)
                        img[off:off + n] = ram[lo:lo + n]
                        covered.update(range(off, off + n))
                if all(a in covered for lo, hi in spans for a in (lo, hi)):
                    out[name] = bytes(img)
                    break
            if name in out:
                break
    return out
