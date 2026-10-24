#!/usr/bin/env python3
"""FM loop cache placement: the C loop_for against a model of its rule
(first free run on the pages grid, LRU eviction of earlier fields, first empty
slot); random synthetic traffic, no game data."""
import ctypes as C
from pathlib import Path
import random
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/platform/amiga'
CACHE, PAGE, NOISE_PAGES = 64, 256, 32


class Model:
    """The pre-F4 loop_for, scan for scan."""

    def __init__(self, pool_bytes):
        self.pool_pages = min(pool_bytes // PAGE, 256)
        self.used_page = [i < NOISE_PAGES for i in range(256)]
        self.key = [0] * CACHE
        self.used = [0] * CACHE
        self.page = [0] * CACHE
        self.pages = [0] * CACHE
        self.stamp = 2

    def loop_for(self, key, nbytes, ok):
        pages = (nbytes + PAGE - 1) // PAGE
        slot = -1
        for i in range(CACHE):
            if self.key[i] == key:
                self.used[i] = self.stamp
                return i
            if not self.key[i] and slot < 0:
                slot = i
        if not ok:
            return -1
        while True:
            p = 0
            while p + pages <= self.pool_pages:
                if not any(self.used_page[p:p + pages]):
                    break
                p += pages
            if p + pages <= self.pool_pages and slot >= 0:
                break
            k = CACHE
            for i in range(CACHE):
                if self.key[i] and self.used[i] + 1 < self.stamp and (k == CACHE or self.used[i] < self.used[k]):
                    k = i
            if k == CACHE:
                return -1
            for i in range(self.pages[k]):
                self.used_page[self.page[k] + i] = False
            self.key[k] = 0
            if slot < 0:
                slot = k
        for i in range(pages):
            self.used_page[p + i] = True
        self.key[slot], self.used[slot] = key, self.stamp
        self.page[slot], self.pages[slot] = p, pages
        return slot


def checks(source):
    with tempfile.TemporaryDirectory(prefix='fm-cache-', dir=ROOT/'tmp') as td:
        p = Path(td)
        (p/'fm.c').write_text(source + '''
static int8_t check_pool[70000];
void check_init(uint32_t bytes) { fm_init(check_pool, bytes); }
int check_loop(uint32_t key, uint16_t bytes, int ok) { return loop_for(key, bytes, ok); }
int check_page(int slot) { return cache[slot].page; }
void check_touch(int slot) { cache_used[slot] = stamp; }
void check_tick(void) { ++stamp; }
''')
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall',
                        '-Wextra', '-Werror', '-I'+str(SRC), str(p/'fm.c'),
                        '-o', str(p/'fm.so')], check=True)
        lib = C.CDLL(str(p/'fm.so'))
        lib.check_init.argtypes = [C.c_uint32]
        lib.check_loop.argtypes = [C.c_uint32, C.c_uint16, C.c_int]
        calls = 0
        for seed, pool_bytes in enumerate((65536, 70000, 40000, 16384, 9000)):
            rng = random.Random(seed)
            lib.check_init(pool_bytes)
            model = Model(pool_bytes)
            # Distinct keys; lg in the key fixes the loop length, as in voice_cmd.
            keys = list({rng.randrange(1 << 25) | rng.choice((3, 4, 7, 8, 9, 10, 11, 12)) << 25
                         for _ in range(rng.choice((80, 200, 400)))})
            for field in range(400):
                for _ in range(rng.randrange(9)):
                    key = rng.choice(keys)
                    nbytes, ok = 1 << (key >> 25), int(rng.random() < 0.9)
                    want, got = model.loop_for(key, nbytes, ok), lib.check_loop(key, nbytes, ok)
                    assert got == want, f'slot {got} != {want}, pool {pool_bytes}, field {field}'
                    if got >= 0:
                        assert lib.check_page(got) == model.page[got], \
                            f'page {lib.check_page(got)} != {model.page[got]}, pool {pool_bytes}, field {field}'
                    calls += 1
                # a continuing note refreshes its slot without a lookup
                live = [i for i in range(CACHE) if model.key[i]]
                if live and rng.random() < 0.5:
                    i = rng.choice(live)
                    model.used[i] = model.stamp
                    lib.check_touch(i)
                model.stamp += 1
                lib.check_tick()
        return calls


def main():
    source = (SRC/'fm_paula.c').read_text()
    if '--sabotage' not in sys.argv:
        print('FM loop cache:', checks(source), 'lookups match')
        return
    for name, old, new in (
            ('earlier fit', 'p < a + n ? p : (uint16_t)(a + n)', '(uint16_t)(a + n)'),
            ('freed hint', 'first_free = a;', '(void)a;'),
            ('grid', '(uint16_t)(a - a % pages)', 'a'),
            ('tie', 'cache_used[i] < oldest &&', 'cache_used[i] <= oldest &&'),
            ('last field', 'oldest = stamp - 1;', 'oldest = stamp;'),
            ('first empty', '            slot = (int16_t)i;\n            break;',
             '            slot = (int16_t)i;')):
        assert source.count(old) == 1, name
        try:
            checks(source.replace(old, new))
        except AssertionError as e:
            print(f'caught {name}: {e}')
        else:
            raise AssertionError(f'{name} escaped')


if __name__ == '__main__':
    main()
