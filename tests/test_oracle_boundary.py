"""Instruction completion controls, including Unicorn's code-page store retry."""
import argparse
import x86_diff as X


def check():
    regs = dict(ax=0x9565, bx=0x7407, cx=0x2b, dx=0x9baa, sp=0x4ce4,
                bp=0x2a, si=0x151c, di=0xc6e1, es=0xb51c, cs=0x369f,
                ss=0x36bd, ds=0xab68)
    # The original executes this exact FLIGHT+11090 case: IP 01F4, byte
    # 36BE4 = 01, every other byte unchanged (live DOSBox debugger proof).
    cases = [
        ('flight store', 'c646ea01', {}, 0x1f4, {0x36be4: 1}, {}),
        ('same-value store', 'c646ea36', {}, 0x1f4, {0x36be4: 0x36}, {}),
        ('word store', 'c746ea3412', {}, 0x1f5, {0x36be4: 0x34, 0x36be5: 0x12}, {}),
        ('increment store', 'fe46ea', {}, 0x1f3, {0x36be4: 0x37}, {}),
        ('xor store changes flags', '8076ea80', {}, 0x1f4, {0x36be4: 0xb6}, {}),
        ('self jump', 'ebfe', {}, 0x1f0, {}, {}),
        ('self conditional jump', '75fe', {}, 0x1f0, {}, {}),
        ('self call', 'e8fdff', {}, 0x1f0,
         {0x3b8b2: 0xf3, 0x3b8b3: 1}, {'sp': 0x4ce2}),
        ('self call with code-page stack', 'e8fdff', {'sp': 0x16}, 0x1f0,
         {0x36be4: 0xf3, 0x36be5: 1}, {'sp': 0x14}),
        ('self indirect call', 'ffd0', {'ax': 0x1f0}, 0x1f0,
         {0x3b8b2: 0xf2, 0x3b8b3: 1}, {'sp': 0x4ce2}),
        ('ordinary store', 'c646ea01', {'ss': 0x6000}, 0x1f4, {0x60014: 1}, {}),
        ('rep store', 'f3aa', {'cx': 3, 'es': 0x6000, 'di': 0x100}, 0x1f2,
         {0x60100: 0x65, 0x60101: 0x65, 0x60102: 0x65}, {'cx': 0, 'di': 0x103}),
        ('exchange store', '8646ea', {}, 0x1f3, {0x36be4: 0x65}, {'ax': 0x9536}),
        ('pop store', '8f46ea', {}, 0x1f3, {0x36be4: 0x36, 0x36be5: 0x36}, {'sp': 0x4ce6}),
    ]
    for name, hexcode, inputs, ip, writes, changes in cases:
        r = dict(regs, **inputs)
        o = X.Oracle(bytes([0x36]) * X.RAM)
        visits = []
        original_code = o.callbacks[0][1]

        @X.U.CODE_CB
        def counted(h, addr, size, user):
            visits.append(addr)
            original_code(h, addr, size, user)

        o.callbacks = ((X.U.HOOK_CODE, counted),) + o.callbacks[1:]
        o.open()
        original_start = o.e.start
        # A bad boundary must fail, not hang on a self-loop.
        o.e.start = lambda begin, until: original_start(begin, until, timeout_us=1000000)
        code = bytes.fromhex(hexcode)
        initial = bytearray(o.bg)
        initial[0x36be0:0x36be0+len(code)] = code
        try:
            err, out, flags, mem, ints, ports, touched = o.run(
                (r, {f: 0 for f in X.FLAGS}, 0, 0x1f0, [(0x36be0, code)]), 1)
            assert not err and not ints and not ports, (name, err, ints, ports)
            if name in ('self jump', 'self conditional jump'):
                assert visits == [0x36be0, 0x36be0], (name, 'boundary hook visits', len(visits))
            assert out == dict(r, ip=ip, **changes), (name, out)
            assert flags == (0x82 if name == 'xor store changes flags' else 2), (name, flags)
            assert mem == writes and touched == set(writes), (name, mem, touched)
            for a, b in writes.items():
                initial[a] = b
            assert o.e.read(0, X.RAM) == initial, (name, 'full memory')
        finally:
            X.U.uc.uc_close(o.e.h)
    print(f'oracle boundaries: {len(cases)} register, flag, full-memory and write-set controls pass')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    if args.sabotage:
        check()
        saved = X.store_retry
        X.store_retry = lambda *args: False
        try:
            try:
                check()
            except AssertionError as exc:
                assert exc.args[0][0] == 'flight store', exc
            else:
                raise AssertionError('premature completion escaped')
        finally:
            X.store_retry = saved
        print('sabotage: premature code-page store completion caught')
        X.store_retry = lambda addr, previous, *args: addr == previous
        try:
            try:
                check()
            except AssertionError as exc:
                assert exc.args[0][:2] == ('self jump', 'boundary hook visits'), exc
            else:
                raise AssertionError('real self-jump mistaken for retry')
        finally:
            X.store_retry = saved
        print('sabotage: real self-jump mistaken for retry caught')
    else:
        check()
