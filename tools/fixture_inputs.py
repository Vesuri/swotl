"""Explicit filesystem inputs for original-game coverage fixtures.
"""
from __future__ import annotations
import json
import re
from pathlib import Path


def missing_files(value: str) -> tuple[str, ...]:
    """Canonical relative DOS paths; reject traversal and ambiguous aliases."""
    paths = []
    for raw in value.split():
        parts = raw.replace('\\', '/').split('/')
        if any(part in ('', '.', '..') or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?', part)
               for part in parts):
            raise ValueError(f'invalid missing-file fixture path: {raw!r}')
        path = '/'.join(parts).upper()
        if path in paths:
            raise ValueError(f'duplicate missing-file fixture path: {raw!r}')
        paths.append(path)
    return tuple(paths)


def stage_missing(root: Path, paths: tuple[str, ...]) -> None:
    """Remove only named files from the fresh disposable fixture root."""
    root = root.resolve()
    selected = []
    for name in paths:
        path = root
        for part in name.split('/'):
            matches = [p for p in path.iterdir() if p.name.upper() == part]
            if len(matches) != 1:
                raise ValueError(f'missing-file fixture source not unique: {name}')
            path = matches[0]
            if path.is_symlink():
                raise ValueError(f'symlink in missing-file fixture source: {name}')
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'missing-file fixture source is not a regular file: {name}')
        selected.append(path)
    for path in selected:
        path.unlink()


def record(run: Path, paths: tuple[str, ...]) -> None:
    if paths:
        (run / 'fixture-inputs.json').write_text(json.dumps({'missing_files': list(paths)}, indent=2) + '\n')


def verify(run: Path, paths: tuple[str, ...]) -> None:
    source = run / 'fixture-inputs.json'
    if not source.exists():
        if paths:
            raise ValueError('reference lacks its declared missing-file inputs')
        return
    expected = {'missing_files': list(paths)}
    if json.loads(source.read_text()) != expected:
        raise ValueError('reference filesystem inputs differ from the fixture definition')
