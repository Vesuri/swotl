"""Amiga file handles: c27's create -> attributes sequence, and kickfs.

The unchanged c27 DOSBox replay supplies the end-to-end oracle for sharing.
These controls compile the production handle code against a modelled DOS:
a disk filesystem (MODE_NEWFILE exclusive, SetFileSize) and WHDLoad's kickfs,
which has no ACTION_CHANGE_MODE or ACTION_SET_FILE_SIZE (an unknown packet
crashes it; here it aborts). Creates and the C library's O_TRUNC (a 0-byte
write at position 0) must use neither. Includes failure cleanup.
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
#include <stdlib.h>
#include <string.h>
typedef long LONG;
typedef long BPTR;
typedef const char *CONST_STRPTR;
#define MAX_FILES 16
#define PATH_BYTES 128
#define MODE_NEWFILE 1006
#define MODE_OLDFILE 1005
#define OFFSET_CURRENT 0
static BPTR files[MAX_FILES];
static char file_paths[MAX_FILES][PATH_BYTES];
static uint8_t file_stamped[MAX_FILES], file_modified[MAX_FILES];
/* One file "X": size, live handles (one exclusive at most), positions. */
static int kickfs, opens, closes, live, exclusive, reject_open, size, sets;
static long pos[64];
static BPTR Open(CONST_STRPTR path, LONG mode) {
    assert(!strcmp(path, "X")); ++opens;
    if (reject_open || (!kickfs && (exclusive || (mode == MODE_NEWFILE && live)))) return 0;
    if (mode == MODE_NEWFILE) { size = 0; exclusive = !kickfs; }
    ++live;
    BPTR f = 10 + opens; pos[f] = 0;
    return f;
}
static void Close(BPTR f) { assert(f > 10 && live > 0); ++closes; --live; exclusive = 0; pos[f] = -1; }
static LONG Seek(BPTR f, LONG offset, LONG mode) {
    assert(f > 10 && pos[f] >= 0 && mode == OFFSET_CURRENT && offset == 0);
    return pos[f];
}
static LONG SetFileSize(BPTR f, LONG offset, LONG mode) {
    if (kickfs) abort();
    assert(f > 10 && pos[f] >= 0 && mode == OFFSET_CURRENT && offset == 0);
    ++sets; size = pos[f];
    return size;
}
'''

MAIN = r'''
int main(void) {
    for (kickfs = 0; kickfs < 2; ++kickfs) {
        memset(files, 0, sizeof files);
        live = exclusive = sets = 0;
        size = 9;
        file_stamped[0] = 1;
        assert(open_as("X", MODE_NEWFILE) == 0);
        assert(files[0] && size == 0 && live == 1 && !exclusive);
        assert(file_modified[0] == 1 && file_stamped[0] == 0);
        /* Attribute query opens the same file while the create handle is live. */
        assert(open_as("X", MODE_OLDFILE) == 1 && file_modified[1] == 0);
        Close(files[1]); files[1] = 0;
        /* O_TRUNC: a 0-byte write at position 0 of a reopened file. */
        Close(files[0]); files[0] = 0;
        size = 9;
        assert(open_as("X", MODE_OLDFILE) == 0 && size == 9);
        assert(truncate_at(0) == 0 && files[0] && size == 0 && sets == 0);
        assert(live == 1 && !exclusive && !strcmp(file_paths[0], "X"));
        /* Another handle holds it: a disk filesystem refuses MODE_NEWFILE. */
        size = 9;
        assert(open_as("X", MODE_OLDFILE) == 1);
        assert(truncate_at(0) == 0 && files[0] && size == 0 && live == 2);
        assert(sets == !kickfs);
        Close(files[1]); files[1] = 0;
        if (!kickfs) {
            /* Past the start only SetFileSize truncates. */
            pos[files[0]] = 5; size = 9;
            assert(truncate_at(0) == 0 && size == 5 && sets == 2);
            pos[files[0]] = 0;
        }
        /* A reopen that fails leaves no handle. */
        reject_open = 1;
        assert(truncate_at(0) == -1 && !files[0] && live == 0);
        assert(open_as("X", MODE_NEWFILE) == -1 && !files[0] && live == 0);
        reject_open = 0;
        file_stamped[0] = 1; file_modified[0] = 7;
        char longer[PATH_BYTES + 1];
        memset(longer, 'X', PATH_BYTES); longer[PATH_BYTES] = 0;
        int old_opens = opens;
        assert(open_as(longer, MODE_OLDFILE) == -1 && opens == old_opens);
        assert(file_stamped[0] == 1 && file_modified[0] == 7);
        for (int k = 0; k < MAX_FILES; ++k) files[k] = 42;
        assert(open_as("X", MODE_NEWFILE) == -1 && opens == old_opens);
    }
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
    body = source[source.index('static BPTR open_new('):source.index('/* MODE_OLDFILE')]
    assert run(body) == 0, 'create sharing / truncation / failure cleanup mismatch'
    print('Amiga file sharing: create, query, O_TRUNC, held file, kickfs, API failures, full table passed')
    if args.sabotage:
        for old, new in [('    Close(f);\n', '    (void)f;\n'),
                         ('if (Seek(files[handle], 0, OFFSET_CURRENT) != 0)', 'if (1)'),
                         ('    if (files[handle]) {\n        return 0;', '    if (0) {\n        return 0;'),
                         ('if (path[n]) {', 'if (0) {'),
                         ('return !files[handle] ? -1 :', 'return')]:
            assert old in body
            assert run(body.replace(old, new, 1)) != 0, f'plant escaped: {old}'
            print('caught:', old)


if __name__ == '__main__':
    main()
