#!/usr/bin/env python3
"""Give a gate its own emulator files and a strictly claimed debugger port."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main(argv):
    (ROOT / 'tmp').mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='gate-run.', dir=ROOT / 'tmp'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    # As in amiga_replay: if another process takes this port before launch,
    # strict claim fails instead of reclaiming somebody else's emulator.
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED='1',
               FSUAE_CLAIM_STRICT='1', FSUAE_RUN=os.path.relpath(run, ROOT / 'amiga'))
    print(f'Gate emulator files: {run}', flush=True)
    return subprocess.run(argv, env=env).returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
