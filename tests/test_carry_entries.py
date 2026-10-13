"""A block entry must consume memory flags even when the incoming X is wrong."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import m68k_diff as D


def main(sabotage=False):
    real_plan, real_case = D.F.plan, D.lower_case

    def entry_plan(insns, lives, leaders, ctx_for, program=False):
        return real_plan(insns, lives, set(leaders) | (set() if sabotage else {1}), ctx_for, program)

    def poison_x(insns, cs, tag, end_ip):
        lines, stats = real_case(insns, cs, tag, end_ip)
        # Arbitrary predecessor hardware X; guest CF remains in the state block.
        at = lines.index(f"{tag}_1:")
        lines.insert(at, "\tandi.b #$ef,ccr")
        return lines, stats

    D.F.plan, D.lower_case = entry_plan, poison_x
    try:
        D.Harness.keep_failing = not sabotage   # planted mismatches: no batch is kept
        h = D.Harness(1)
        for code in ("01d811ca", "29d819ca", "d1e0d1d2", "d1e8d1da"):
            for ax in (0, 1, 0x8000, 0xffff):
                for cf in (0, 1):
                    h.case(bytes.fromhex(code), "carry-entry", n=2, block=True,
                           overrides={"regs": {"ax": ax, "bx": 1, "dx": 0,
                                      "cx": 0}, "flags": {"CF": cf}})
        h.flush()
        print(f"carry entries: {sum(h.count.values())} cases, {len(h.bad)} mismatches")
        for bad in h.bad[:3]:
            print(bad)
        return bool(h.bad) != sabotage
    finally:
        D.F.plan, D.lower_case = real_plan, real_case


if __name__ == "__main__":
    sys.exit(main("--sabotage" in sys.argv))
