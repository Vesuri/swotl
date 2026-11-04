#!/usr/bin/env python3
"""What WHDLoad PreLoad holds: run tools/test_whdload.py (any of its options) and
report which files the game still reads from the host disk after the preload.

    python3 tools/whdload_preload.py --mode run --installed DIR [--fast KiB] [--cpu 68030 --z3 KiB]

Host access times show reads: a file's atime moves only when it is older than
its mtime (macOS), so every fixture file is stamped to 1980 after FS-UAE's own
start-up reads of every hard-drive file have stopped, and only then may WHDLoad
start (the startup-sequence waits for the host file DH0:go). Phase 0 runs from WHDLoad's own read through the
preload burst, until no new file is read for 1.5 s; then everything is stamped
again. Phase 1 lists the files read after that: not in the file cache, each an
OS switch. Only a file's first read in a phase shows. The fixture directory
ends in .noindex so Spotlight stays out. Output: both phases on stdout and
<fixture>/reads.txt.
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_whdload as T  # noqa: E402

OLD = 315532800             # 1980-01-01: older than every mtime
state = {'phases': []}
popen = subprocess.Popen
mkdtemp = tempfile.mkdtemp


def files(game):
    return [p for p in game.rglob('*')
            if p.is_file() and not p.name.startswith('.whdl') and not p.name.endswith('.uaem')]


def stamp(game):
    for p in files(game):
        os.utime(p, ns=(OLD * 10**9, p.stat().st_mtime_ns))


def read(game):
    return {p: p.stat().st_atime_ns for p in files(game) if p.stat().st_atime_ns > (OLD + 1) * 10**9}


def quiet(game, seconds):
    """Wait until no fixture file has been read for `seconds`."""
    last, seen = time.time(), {}
    while time.time() - last < seconds:
        now = read(game)
        if now != seen:
            seen, last = now, time.time()
        time.sleep(.05)


def watch(game, boot):
    stamp(game)
    quiet(game, 3)              # FS-UAE's start-up reads
    stamp(game)
    (boot / 'go').touch()       # WHDLoad may start
    while not read(game).get(game / 'WHDLoad'):
        time.sleep(.01)
    last, seen = time.time(), {}
    while time.time() - last < 1.5:
        now = read(game)
        if len(now) != len(seen):
            seen, last = now, time.time()
        time.sleep(.02)
    state['phases'].append(seen)
    stamp(game)


def emulator(cmd, *args, **kwargs):
    game = Path(next(c for c in cmd if c.startswith('--hard_drive_1=')).split('=', 1)[1])
    boot = Path(next(c for c in cmd if c.startswith('--hard_drive_0=')).split('=', 1)[1])
    startup = boot / 's/startup-sequence'
    text = startup.read_text()
    assert 'CD DH1:\n' in text
    startup.write_text(text.replace('CD DH1:\n', 'CD DH1:\nLab wait\nIf NOT EXISTS DH0:go\n'
                                    'DF0:C/Wait 1\nSkip wait BACK\nEndIf\n'))
    state['game'] = game
    emu = popen(cmd, *args, **kwargs)
    threading.Thread(target=watch, args=(game, boot), daemon=True).start()
    return emu


def main():
    T.subprocess.Popen = emulator
    T.tempfile.mkdtemp = lambda **k: mkdtemp(suffix='.noindex', **k)
    try:
        T.main()
    except SystemExit as e:
        if e.code:
            print('test_whdload:', str(e)[:300])
    game = state['game']
    state['phases'].append(read(game))
    assert len(state['phases']) == 2, 'WHDLoad did not start'
    out = []
    for n, phase in enumerate(state['phases']):
        total = 0
        for p, _ in sorted(phase.items(), key=lambda x: x[1]):
            total += p.stat().st_size
            out.append(f'{n} {p.stat().st_size:9} {total:10} {p.relative_to(game)}')
        print(f'phase {n}: {len(phase)} files, {total:,} bytes')
    for line in out:
        if line.startswith('1 '):
            print(' ', line[2:])
    (game.parent / 'reads.txt').write_text('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
