#!/usr/bin/env python3
"""Music entry clears sample ownership without changing the skip decision."""
import io
import sys
import host_run as H


def check(plant=False):
    h = H.Host(H.image.M.REF)
    assert h.mem(h.syms['rt_sfx_id'], 3) == b'\xff' * 3
    ret = h.syms['plat_exit']
    entry = h.syms['rt_hle_music_skip']
    if plant:
        # First absolute byte store is eight bytes; skip its ownership clear.
        h.e.write(entry, bytes.fromhex('4e71') * 4)
    for skip in (0, 1, 2, 255):
        h.e.write(h.syms['rt_music_skip'], bytes([skip]))
        h.e.write(h.syms['rt_sfx_id'], bytes([0, 7, 23]))
        h.e.write(h.syms['rt_sfx_starts'], bytes([9, 255, 2]))
        h.e.reg_write(H.U.M68K['sr'], 0x2700)
        h.e.reg_write(H.U.M68K['a7'], H.STACK_TOP - 4)
        h.e.write(H.STACK_TOP - 4, ret.to_bytes(4, 'big'))
        for reg in ('d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6'):
            h.e.reg_write(H.U.M68K[reg], 0x12345678)
        h.e.start(entry, ret, timeout_us=1_000_000)
        assert h.r('pc') == ret
        assert h.mem(h.syms['rt_sfx_id'], 3) == b'\xff' * 3
        assert h.mem(h.syms['rt_sfx_starts'], 3) == bytes([9, 255, 2])
        # Unicorn exposes lazy flags through a CCR store, not an SR read.
        probe = H.STACK_TOP + 0x100
        h.e.write(probe, bytes.fromhex('42f9') + (probe + 0x100).to_bytes(4, 'big'))
        h.e.start(probe, probe + 6, timeout_us=1_000_000)
        ccr = int.from_bytes(h.mem(probe + 0x100, 2), 'big')
        assert bool(ccr & 4) == (skip == 0)
        for reg in ('d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6'):
            assert h.r(reg) == 0x12345678
    log = h.sound_log = io.StringIO()
    h.post(9)
    h.sound_event('s', 1, 7)
    h.post(8)
    h.sound_event('o', 176, 32)
    h.e.reg_write(H.U.M68K['a7'], H.STACK_TOP - 4)
    h.e.start(entry, ret, timeout_us=1_000_000)
    assert log.getvalue() == '0,s,1,7\n1,o,176,32\n1,m,0,0\n'


if __name__ == '__main__':
    plant = '--sabotage' in sys.argv
    try:
        check(plant)
    except AssertionError:
        if not plant:
            raise
        print('music ownership sabotage: caught')
    else:
        assert not plant, 'missed music ownership sabotage'
        print('music ownership, skip flags, registers, sound-log ticks: ok')
