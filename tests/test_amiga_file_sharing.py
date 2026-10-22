"""Amiga create handles must permit c27's create -> attributes sequence.

The unchanged c27 DOSBox replay supplies the end-to-end oracle. These controls
compile the production handle allocator against the DOS handle API, including
failure cleanup. They do not replace the original-game replay.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/platform/amiga/amiga_platform.c'

PREFIX = r'''
#include <stdint.h>
#include <assert.h>
typedef long LONG;
typedef long BPTR;
typedef const char *CONST_STRPTR;
#define MAX_FILES 16
#define MODE_NEWFILE 1006
#define MODE_OLDFILE 1005
#define CHANGE_FH 1
#define SHARED_LOCK -2
static BPTR files[MAX_FILES];
static uint8_t file_stamped[MAX_FILES], file_modified[MAX_FILES];
static int opens, changes, closes, reject_open, reject_change, exclusive;
static BPTR Open(CONST_STRPTR path, LONG mode) {
    assert(path[0] == 'X'); ++opens;
    if (reject_open || exclusive) return 0;
    if (mode == MODE_NEWFILE) exclusive = 1;
    return 42;
}
static LONG ChangeMode(LONG type, BPTR f, LONG mode) {
    assert(type == CHANGE_FH && f == 42 && mode == SHARED_LOCK);
    ++changes;
    if (reject_change) return 0;
    exclusive = 0;
    return 1;
}
static void Close(BPTR f) { assert(f == 42); ++closes; exclusive = 0; }
'''

MAIN = r'''
int main(void) {
    file_stamped[0] = 1;
    assert(open_as("X", MODE_NEWFILE) == 0);
    assert(changes == 1 && closes == 0 && files[0] == 42);
    assert(file_modified[0] == 1 && file_stamped[0] == 0);
    /* Attribute query opens the same file while the create handle is live. */
    assert(open_as("X", MODE_OLDFILE) == 1);
    assert(changes == 1 && file_modified[1] == 0);
    files[0] = files[1] = 0;
    reject_change = 1;
    file_stamped[0] = 1; file_modified[0] = 7;
    assert(open_as("X", MODE_NEWFILE) == -1);
    assert(closes == 1 && !files[0] && !exclusive);
    assert(file_stamped[0] == 1 && file_modified[0] == 7);
    reject_change = 0; reject_open = 1;
    assert(open_as("X", MODE_NEWFILE) == -1);
    assert(changes == 2 && closes == 1 && !files[0]);
    reject_open = 0;
    assert(open_as("X", MODE_NEWFILE) == 0);
    for (int k = 0; k < MAX_FILES; ++k) files[k] = 42;
    int old_opens = opens;
    assert(open_as("X", MODE_NEWFILE) == -1 && opens == old_opens);
    return 0;
}
'''


def run(body):
    with tempfile.TemporaryDirectory(prefix='file-sharing-', dir=ROOT / 'tmp') as name:
        d = Path(name)
        (d / 'check.c').write_text(PREFIX + body + MAIN)
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-o', str(d / 'check'),
                        str(d / 'check.c')], check=True)
        return subprocess.run([str(d / 'check')], capture_output=True).returncode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sabotage', action='store_true')
    args = p.parse_args()
    source = SOURCE.read_text()
    body = source[source.index('static int32_t open_as('):source.index('/* MODE_OLDFILE')]
    assert run(body) == 0, 'create sharing / failure cleanup mismatch'
    print('Amiga file sharing: create, reopen, metadata, API failures, full table passed')
    if args.sabotage:
        for old, new in [('!ChangeMode(CHANGE_FH, f, SHARED_LOCK)', '0'),
                         ('Close(f);', '(void)f;')]:
            assert old in body
            assert run(body.replace(old, new, 1)) != 0, f'plant escaped: {old}'
            print('caught:', old)


if __name__ == '__main__':
    main()
