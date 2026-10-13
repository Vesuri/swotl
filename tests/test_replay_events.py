#!/usr/bin/env python3
"""Replay scheduler boundaries: per-service visits, groups, IF and completion."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import struct
import host_run as H

ROOT = Path(__file__).resolve().parents[1]
DATA = '''
#define REPLAY_POINTS 3u
#define REPLAY_IRQS 3u
#define REPLAY_SERVICES 1u
#define REPLAY_STEPS 1u
struct replay_point_info { uint32_t cs, ip; };
struct replay_irq { uint32_t service, point, hits, vector; };
struct replay_step { uint32_t point, hits, kind; int32_t value; uint32_t release; };
static const struct replay_point_info replay_points[] = {{1,2},{3,4},{5,6}};
static const struct replay_irq replay_irqs[] = {{0,0,1,8},{0,0,1,8},{1,1,0,9}};
static const struct replay_step replay_script[] = {{2,1,0,0,0}};
static const uint32_t replay_service_hashes[] = {SERVICE_HASH};
'''
HARNESS = '''
#define assert(x) do { if (!(x)) return 1; } while (0)
#include "amiga_replay.c"
static uint8_t memory[32];
uint8_t *rt_guest = memory;
volatile uint8_t rt_irq_ring[RT_IRQ_RING], rt_irq_tail, rt_irq_pending;
volatile uint16_t rt_key_ring[RT_KEY_RING];
volatile uint8_t rt_key_tail;
uint32_t test_case;
void test_stop(void) { for (;;) {} }
void rt_unsupported(const char *what, uint16_t a, uint16_t b, uint16_t c)
{ (void)what; (void)a; (void)b; (void)c; __asm__("moveq #2,%d0; jmp test_stop"); __builtin_unreachable(); }
int main(void) {
    G_IF = 1;
    if (test_case == 3 || test_case == 4) {
        static uint32_t r[20];
        r[4] = r[5] = 0x7fff; r[6] = 0x21;
        if (test_case == 4) r[0] = 1;
        *(uint32_t *)((uint8_t *)r + 66) = 0x12345678;
        replay_enter(r);
        assert(replay_services == 1 && depth == 1);
        return 0;
    }
    if (test_case == 1) { replay_services = 1; replay_point(0); return 3; }
    if (test_case == 2) { G_IF = 0; replay_point(0); replay_point(0); return 3; }
    assert(replay_point(0) == 0);
    assert(replay_point(0) == 1);
    assert(replay_interrupts == 1 && rt_irq_ring[0] == 8);
    assert(replay_next(1) == 1 && replay_interrupts == 2);
    assert(replay_next(1) == 0 && replay_interrupts == 2);
    replay_services = 1;
    assert(replay_point(1) == 3 && replay_interrupts == 3 && rt_irq_ring[2] == 9);
    assert(replay_cs == 3 && replay_ip == 4);
    assert(replay_next(3) == 0);
    assert(replay_point(2) == -1 && replay_steps == 1);
    return 0;
}
'''


def check(source, broken=False):
    with tempfile.TemporaryDirectory(prefix='swotl-replay-events-') as tmp:
        p = Path(tmp)
        (p / 'amiga_replay.c').write_text(source)
        digest = 2166136261
        for byte in struct.pack('>14H', *([0] * 11 + [0x21, 0x200, 0])):
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        (p / 'replay_data.h').write_text(DATA.replace('SERVICE_HASH', str(digest)))
        (p / 'test.c').write_text(HARNESS)
        subprocess.run([str(Path(os.environ.get('AMIGA_TOOLCHAIN', Path.home() / '.local/opt')) / 'bin/m68k-amiga-elf-gcc'), '-m68020', '-O2', '-nostdlib', '-ffreestanding', '-fno-builtin',
                        '-I' + str(ROOT / 'src/runtime'), str(p / 'test.c'),
                        '-Wl,-Ttext=0x10000,-e,main', '-o', str(p / 'test.elf')], check=True)
        entry, segments, symbols = H.elf_load(p / 'test.elf')
        def run(case):
            e = H.U.Engine(H.U.ARCH_M68K, H.U.MODE_BIG_ENDIAN, H.U.CPU_M68K_M68020)
            e.map(0, 0x40000)
            for address, data, size in segments:
                e.write(address, data + bytes(size - len(data)))
            e.write(symbols['test_case'], struct.pack('>I', case))
            e.reg_write(H.U.M68K['sr'], 0x2700)
            e.reg_write(H.U.M68K['a7'], 0x3f000)
            e.write(0x3f000, struct.pack('>I', symbols['test_stop']))
            error = e.start(entry, symbols['test_stop'], timeout_us=1_000_000)
            assert not error, error
            return e.reg_read(H.U.M68K['d0'])
        actual = [run(case) for case in range(5)]
        expected = [0, 2, 2, 0, 2]
        assert (actual == expected) != broken, (actual, expected, broken)
    print('replay events: planted fault caught' if broken else 'replay events: visits, groups, IF and completion checked')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    source = (ROOT / 'tests/amiga_replay.c').read_text()
    check(source)
    if args.sabotage:
        for old, new in [('irq->hits + 1', 'irq->hits + 2'),
                         ('a->point == b->point', 'a->point != b->point'),
                         ('replay_services != REPLAY_SERVICES', 'replay_services == REPLAY_SERVICES'),
                         ('if (!G_IF)', 'if (0 && !G_IF)'),
                         ('service_hash != replay_service_hashes[replay_services]', '0')]:
            assert old in source
            check(source.replace(old, new), True)
