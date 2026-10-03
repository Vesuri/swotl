"""Guardrails G1 (generated files) and G2 (hand-written code), translation-lessons.md.

  python3 -m translator.check gen [--regen]   every build/gen file has a
      valid header whose inputs digest matches the current translator,
      annotations and module image and whose body digest matches the body
      (no hand edits); --regen also regenerates to a temporary directory and
      requires byte-identical output.
  python3 -m translator.check lint [paths]    no guest-address-named symbol
      in hand-written code (default: src/, amiga/).
"""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from pathlib import Path

from . import gen, image

HAND = ("src", "amiga")
SOURCES = {".c", ".cc", ".cpp", ".h", ".hpp", ".s", ".asm", ".i", ".inc"}
MODULES = "|".join(re.escape(m.split(".")[0]) for m in image.SCOPE + image.M.OUT_OF_SCOPE)
# Identifiers that name a guest address: generated-label style, IDA/Ghidra style,
# seg_off pairs, or a module name followed by an offset.
GUEST_NAME = re.compile(
    r"\b(?:g_\w+_[0-9A-Fa-f]{4,6}"
    r"|(?:sub|loc|fn|func|proc|lab|off|byte|word|dword|unk|code)_[0-9A-Fa-f]{4,6}"
    r"|\w*_[0-9A-Fa-f]{4}_[0-9A-Fa-f]{4}"
    rf"|(?i:(?:{MODULES})\w*?)_?(?:0x)?[0-9A-Fa-f]{{4,6}})\b")


def check_gen(regen: bool, out: Path = gen.OUT) -> list[str]:
    bad = []
    files = sorted(list(out.glob("*.ir")) + list(out.glob("*.s")))
    if not files:
        return [f"no generated files in {out}"]
    for f in files:
        data = f.read_bytes()
        lines = data.split(b"\n", 4)
        if len(lines) < 5 or not lines[0].startswith(b"; swotl-gen"):
            bad.append(f"{f.name}: no generator header")
            continue
        module = lines[1].decode().removeprefix("; module ")
        inputs = lines[2].decode().removeprefix("; inputs ")
        body_hash = lines[3].decode().removeprefix("; body ")
        body = lines[4]
        if module not in image.SCOPE and module not in (gen.SUPPORT, gen.PROGRAM):
            bad.append(f"{f.name}: unknown module {module}")
            continue
        if inputs != gen.inputs_digest(module):
            bad.append(f"{f.name}: stale (inputs changed since generation); run make gen")
        if body_hash != hashlib.sha256(body).hexdigest():
            bad.append(f"{f.name}: body does not match its header (edited by hand?)")
    if regen and not bad:
        with tempfile.TemporaryDirectory() as tmp:
            gen.generate(Path(tmp))
            for f in files:
                if (Path(tmp) / f.name).read_bytes() != f.read_bytes():
                    bad.append(f"{f.name}: regeneration is not byte-identical")
    return bad


def lint(paths: list[Path]) -> list[str]:
    bad = []
    for root in paths:
        for f in sorted([root] if root.is_file() else root.rglob("*")):
            shown = f.relative_to(image.REPO) if f.is_relative_to(image.REPO) else f
            if f.suffix.lower() not in SOURCES or "gen" in Path(shown).parts[:2]:
                continue
            for k, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                for m in GUEST_NAME.finditer(line):
                    bad.append(f"{shown}:{k}: guest-address name {m.group(0)}")
    return bad


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("gen", "lint"):
        print(__doc__)
        return 2
    if argv[0] == "gen":
        bad = check_gen("--regen" in argv)
        what = "generated files"
    else:
        paths = [Path(p).resolve() for p in argv[1:]] or [image.REPO / p for p in HAND]
        bad = lint(paths)
        what = "hand-written code"
    for b in bad[:50]:
        print(b)
    print(f"{what}: {len(bad)} violations")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
