"""Runtime consumers must check both return words and report the actual pair."""
import argparse
import struct

import host_run as H
from test_mouse_irq import machine, call, write_guest

U = H.U


def returned(h, cs, ip):
    # R33: the expected pair is unchanged; d6 is no longer a return value.
    h.e.reg_write(U.M68K["d7"], cs << 16 | ip)
    h.e.reg_write(U.M68K["d6"], 0x9876ABCD)


def return_pair(h):
    return h.r("d7") >> 16, h.r("d7") & 0xFFFF


def check_bios(corrupt_result=False):
    count = 0
    for cs, ip in ((0, 0), (0xFFFF, 0xFFFF), (0x1234, 0x5678)):
        for flags in (2, 0x7ED7):
            h = machine()
            ss, sp = 0x7000, 0x120
            frame = struct.pack("<HHH", ip, cs, flags)
            write_guest(h, ss * 16 + sp, frame)
            h.e.write(H.TOP + 3, struct.pack(">H", ss))
            h.e.write(h.syms["rt_r"] + 8, struct.pack(">H", sp))
            h.e.reg_write(U.M68K["a6"], H.TOP)
            call(h, "load_regs")
            before = h.guest_regs(0)
            call(h, "rt_bios_int08")
            if corrupt_result:
                returned(h, cs ^ 1, ip)
            assert not h.halted and return_pair(h) == (cs, ip), h.log
            after = h.guest_regs(0)
            for reg in H.REGS + ("es", "ss", "ds"):
                assert after[reg] == (sp + 6 if reg == "sp" else before[reg]), reg
            assert h.gmem(ss * 16 + sp, 6) == frame
            assert call(h, "rt_flags_word") & 0xFFFF == flags
            U.uc.uc_close(h.e.h)
            count += 1
    return count


def check_delivery(corrupt_check=False):
    count = 0
    for cs, ip in ((0, 0), (0xFFFF, 0xFFFF), (0x1234, 0x5678)):
        for wrong in (None, "ip", "cs"):
            h = machine()
            h.e.reg_write(U.M68K["a6"], H.TOP)
            call(h, "load_regs")
            target = 0x00FD0000
            h.e.write(target, bytes.fromhex("4e75"))  # test callback returns
            h.e.write(h.syms["rt_deliver_code"], struct.pack(">I", target))
            h.e.write(h.syms["rt_deliver_cs"], struct.pack(">H", 0x2000))
            h.e.write(h.syms["rt_deliver_ip"], struct.pack(">H", 0x100))
            actual_cs, actual_ip = cs ^ (wrong == "cs"), ip ^ (wrong == "ip")

            @U.CODE_CB
            def callback(e, addr, size, user):
                returned(h, actual_cs, actual_ip)
                if corrupt_check:
                    # Make the saved expected frame match the corrupt return.
                    # The positive controls must still pass; negative ones fail.
                    h.e.write(h.r("a7") + 4, struct.pack(">HH", actual_cs, actual_ip))

            h.e.hook_range(U.HOOK_CODE, callback, target, target)
            h.e.reg_write(U.M68K["d7"], cs << 16 | ip)
            call(h, "deliver_guest")
            if wrong is None:
                assert not h.halted, h.log
            else:
                expected = f"SWOTL_STOP return site reached with IP/CS {actual_ip:04x} {actual_cs:04x}"
                assert h.halted and expected in h.log, (wrong, expected, h.log)
            U.uc.uc_close(h.e.h)
            count += 1
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sabotage", action="store_true")
    args = ap.parse_args()
    print("runtime return protocol:", check_delivery(), "controls pass")
    print("BIOS return protocol:", check_bios(), "controls pass")
    if args.sabotage:
        try:
            check_delivery(True)
        except AssertionError:
            print("runtime return protocol: unchecked return plant caught")
        else:
            raise AssertionError("unchecked return escaped")
        try:
            check_bios(True)
        except AssertionError:
            print("BIOS return protocol: corrupt result plant caught")
        else:
            raise AssertionError("corrupt BIOS return escaped")


if __name__ == "__main__":
    main()
