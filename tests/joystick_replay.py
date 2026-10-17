"""Strict reader for original gameport events; no device approximations."""
import csv
from dataclasses import dataclass
from pathlib import Path

FIELDS = ('service', 'write', 'width', 'value', 'repeat')

@dataclass(frozen=True)
class Run:
    service: int
    write: int
    width: int
    value: int
    repeat: int

def read(path: Path, required=False):
    if not path.exists():
        if required:
            raise ValueError('missing required joystick port recording')
        return []
    with path.open(newline='') as f:
        rows = csv.DictReader(f)
        if tuple(rows.fieldnames or ()) != FIELDS:
            raise ValueError('invalid joystick header')
        result = []
        for row in rows:
            if set(row) != set(FIELDS) or any(not isinstance(v, str) or not v or
                    any(c not in '0123456789' for c in v) for v in row.values()):
                raise ValueError('invalid joystick numeric record')
            r = Run(*(int(row[k]) for k in FIELDS))
            if (r.service > 0xffffffff or r.write not in (0, 1) or r.width not in (1, 2, 4) or
                    r.value >= 1 << (r.width * 8) or not 1 <= r.repeat <= 0xffffffff):
                raise ValueError('joystick record out of range')
            if result and r.service < result[-1].service:
                raise ValueError('joystick service count moved backwards')
            result.append(r)
    if required and not result:
        raise ValueError('empty required joystick port recording')
    return result

class Replay:
    def __init__(self, runs):
        self.runs = runs
        self.index = self.used = 0

    def step(self, write, width, service, value=None):
        if self.index == len(self.runs):
            raise ValueError('unexpected gameport access after recording')
        r = self.runs[self.index]
        if (write, width, service) != (r.write, r.width, r.service):
            raise ValueError('gameport direction, width or service mismatch')
        if write and value != r.value:
            raise ValueError('gameport write value mismatch')
        self.used += 1
        if self.used == r.repeat:
            self.index += 1
            self.used = 0
        return r.value

    def complete(self):
        if self.index != len(self.runs) or self.used:
            raise ValueError('unconsumed gameport records')

def c_header(runs):
    """Local-only metadata for the diagnostic wrapper; omit wrapper when absent."""
    if not runs:
        raise ValueError('cannot build joystick wrapper without recorded accesses')
    lines = ['/* Generated original-game input metadata: do not commit. */',
             f'#define REPLAY_JOYSTICK_RECORDS {len(runs)}u',
             'struct replay_joystick { uint32_t service, write, width, value, repeat; };',
             'static const struct replay_joystick replay_joystick[] = {']
    lines += [' {' + ','.join(f'{getattr(r, k)}u' for k in FIELDS) + '},' for r in runs]
    return '\n'.join(lines + ['};', ''])


def action(key, enabled):
    """Validate an immediate physical action; return False for other inputs."""
    if not isinstance(key, str) or not key.startswith(('jx', 'jy', 'jb')):
        return False
    if not enabled:
        raise ValueError('joystick action without declared joystick recording')
    if key.startswith('jb'):
        valid = len(key) == 3 and key[2] in '0123'
    else:
        valid = (4 <= len(key) <= 7 and key[2] in '+-' and
                 all(c in '0123456789' for c in key[3:]) and int(key[3:]) <= 1000)
    if not valid:
        raise ValueError('invalid joystick action')
    return True
