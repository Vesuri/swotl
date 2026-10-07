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
        print(f"byteorder entries: {total} cases, {bad} mismatches")
        return bool(bad)
    finally:
        D.F.plan = real_plan


if __name__ == "__main__":
    sys.exit(main())
