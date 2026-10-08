"""T3: every internal leader is a native-order entry and exit boundary."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import m68k_diff as D


def main():
    real_plan = D.F.plan
    try:
        total = bad = 0
        for leader in (1, 2, 3):
            def entry_plan(insns, lives, leaders, ctx_for, program=False):
                return real_plan(insns, lives, set(leaders) | {leader}, ctx_for, program)
            D.F.plan = entry_plan
            h = D.Harness(1)
            for code in ("8b0789058905b80000", "585050b80000", "8b0789c28915ba0000"):
                for bx in (0, 1, 0xfffe, 0xffff):
                    h.case(bytes.fromhex(code), "byteorder-entry", n=4, block=True,
                           overrides={"regs": {"cs": 0x2000, "ds": 0x5000,
                                      "ss": 0x7000, "bx": bx, "di": bx, "sp": bx}, "ip": 0x100})
            h.flush()
            total += sum(h.count.values())
            bad += len(h.bad)
            for failure in h.bad[:3]:
                print(failure)
        # T11: append independent-arithmetic and exposed-register boundaries.
        for leader in (1, 2, 3):
            def entry_plan(insns, lives, leaders, ctx_for, program=False):
                return real_plan(insns, lives, set(leaders) | {leader}, ctx_for, program)
            D.F.plan = entry_plan
            h = D.Harness(37)
            for code, count in (("8b07 83c101 8905 b80000", 4),
                                ("8b07 8b17 83c001 8915 8905", 5),
                                ("8b07 43 8905 83fb01 7402", 5)):
                for edge in (0, 1, 0xfffe, 0xffff):
                    h.case(bytes.fromhex(code), "broad-byteorder-entry", n=count,
                           block=True, overrides={"regs": dict(cs=0x2000,
                           ds=0x5000, ss=0x7000, bx=edge, di=edge,
                           sp=edge, cx=1), "ip": 0x100})
            h.flush()
            total += sum(h.count.values())
            bad += len(h.bad)
            for failure in h.bad[:3]:
                print(failure)
        # T12: an internal entry cannot inherit the predecessor's offset fact.
        for leader in (1, 2):
            def entry_plan(insns, lives, leaders, ctx_for, program=False):
                return real_plan(insns, lives, set(leaders) | {leader}, ctx_for, program)
            D.F.plan = entry_plan
            h = D.Harness(43)
            for rm in range(8):
                for edge in (0, 1, 0x7fff, 0x8000, 0xfffe, 0xffff):
                    code = b"".join(bytes((0x8b, 0x80 | rm | reg << 3, 0xff, 0xff))
                                    for reg in (0, 1, 2))
                    h.case(code, "offset-reuse-entry", n=3, block=True,
                           overrides={"regs": dict(cs=0x2000, ds=0x5000,
                           ss=0x7000, bx=edge, bp=edge, si=1, di=0xffff), "ip": 0x100})
            h.flush()
            total += sum(h.count.values())
            bad += len(h.bad)
            for failure in h.bad[:3]:
                print(failure)
        # T13: raw address-register groups end at every possible entry.
        for leader in (1, 2, 3):
            def entry_plan(insns, lives, leaders, ctx_for, program=False):
                return real_plan(insns, lives, set(leaders) | {leader}, ctx_for, program)
            D.F.plan = entry_plan
            h = D.Harness(53)
            for reg in (6, 7):
                for value in (0, 1, 0x8000, 0xffff):
                    code = bytes((0x8b, 0x06 | reg << 3, 0, 4))
                    code += b"".join(bytes((0x89, 0x06 | reg << 3, at, 4))
                                     for at in (0x20, 0x22, 0x24))
                    h.case(code, "address-byteorder-entry", n=4, block=True,
                           overrides={"regs": dict(cs=0x2000, ds=0x5000,
                           ss=0x7000, sp=0xfffe), "ip": 0x100,
                           "mem": [(0x50400, value.to_bytes(2, "little"))]})
            h.flush()
            total += sum(h.count.values())
            bad += len(h.bad)
            for failure in h.bad[:3]:
                print(failure)
        print(f"byteorder entries: {total} cases, {bad} mismatches")
        return bool(bad)
    finally:
        D.F.plan = real_plan


if __name__ == "__main__":
    sys.exit(main())
