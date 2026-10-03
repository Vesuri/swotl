"""Minimal ctypes binding to the Unicorn C library (2.1.x, Homebrew), as Slicks.

Only what the differentials use. Enum values are from unicorn.h 2.1.4
(printed by a C probe); `check_abi()` re-reads the library version.
"""

from __future__ import annotations

import ctypes as C
import os

LIB = os.environ.get("UNICORN_LIB", "/opt/homebrew/lib/libunicorn.2.dylib")
uc = C.CDLL(LIB)

ARCH_X86, MODE_16 = 4, 2
ARCH_M68K, MODE_BIG_ENDIAN, CPU_M68K_M68020 = 7, 1 << 30, 2
CTL_CPU_MODEL, CTL_TB_FLUSH = 7, 10
PROT_ALL = 7
HOOK_INTR, HOOK_INSN, HOOK_CODE, HOOK_MEM_READ, HOOK_MEM_WRITE = 1, 2, 4, 1 << 10, 1 << 11
X86_INS_IN, X86_INS_OUT = 218, 500
M68K = {**{f"a{k}": 1 + k for k in range(8)}, **{f"d{k}": 9 + k for k in range(8)},
        "sr": 17, "pc": 18}
X86 = {"ax": 3, "bx": 8, "cx": 12, "dx": 18, "sp": 47, "bp": 6, "si": 45, "di": 14,
       "es": 28, "cs": 11, "ss": 49, "ds": 17, "ip": 34, "flags": 252}

uc.uc_version.restype = C.c_uint
uc.uc_open.argtypes = [C.c_int, C.c_int, C.POINTER(C.c_void_p)]
uc.uc_close.argtypes = [C.c_void_p]
uc.uc_mem_map.argtypes = [C.c_void_p, C.c_uint64, C.c_size_t, C.c_uint32]
uc.uc_mem_write.argtypes = [C.c_void_p, C.c_uint64, C.c_char_p, C.c_size_t]
uc.uc_mem_read.argtypes = [C.c_void_p, C.c_uint64, C.c_void_p, C.c_size_t]
uc.uc_reg_write.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
uc.uc_reg_read.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
uc.uc_emu_start.argtypes = [C.c_void_p, C.c_uint64, C.c_uint64, C.c_uint64, C.c_size_t]
uc.uc_emu_stop.argtypes = [C.c_void_p]
uc.uc_hook_add.argtypes = [C.c_void_p, C.POINTER(C.c_size_t), C.c_int, C.c_void_p, C.c_void_p,
                           C.c_uint64, C.c_uint64]
uc.uc_hook_del.argtypes = [C.c_void_p, C.c_size_t]
uc.uc_strerror.argtypes = [C.c_int]
uc.uc_strerror.restype = C.c_char_p
uc.uc_ctl.argtypes = [C.c_void_p, C.c_int]

INTR_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32, C.c_void_p)
IN_CB = C.CFUNCTYPE(C.c_uint32, C.c_void_p, C.c_uint32, C.c_int, C.c_void_p)
OUT_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32, C.c_int, C.c_uint32, C.c_void_p)
MEM_CB = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_int, C.c_uint64, C.c_int, C.c_int64, C.c_void_p)
CODE_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint64, C.c_uint32, C.c_void_p)


class UcError(Exception):
    pass


def check(err: int, what: str) -> None:
    if err:
        raise UcError(f"{what}: {uc.uc_strerror(err).decode()} ({err})")


def check_abi() -> None:
    v = uc.uc_version(None, None)
    if (v >> 24, (v >> 16) & 0xFF) != (2, 1):
        raise UcError(f"Unicorn {v:08x}: binding written for 2.1")


class Engine:
    def __init__(self, arch: int, mode: int, cpu_model: int | None = None):
        check_abi()
        self.h = C.c_void_p()
        check(uc.uc_open(arch, mode, C.byref(self.h)), "uc_open")
        if cpu_model is not None:
            ctl = CTL_CPU_MODEL | (1 << 26) | (1 << 30)  # UC_CTL_WRITE(UC_CTL_CPU_MODEL, 1)
            check(uc.uc_ctl(self.h, ctl, C.c_int(cpu_model)), "uc_ctl cpu model")
        self.hooks = []  # keep callbacks alive

    def map(self, addr: int, size: int) -> None:
        check(uc.uc_mem_map(self.h, addr, size, PROT_ALL), "uc_mem_map")

    def write(self, addr: int, data: bytes) -> None:
        check(uc.uc_mem_write(self.h, addr, data, len(data)), "uc_mem_write")

    def read(self, addr: int, size: int) -> bytes:
        buf = C.create_string_buffer(size)
        check(uc.uc_mem_read(self.h, addr, buf, size), "uc_mem_read")
        return buf.raw

    def reg_write(self, reg: int, value: int) -> None:
        v = C.c_uint64(value)
        check(uc.uc_reg_write(self.h, reg, C.byref(v)), "uc_reg_write")

    def reg_read(self, reg: int) -> int:
        v = C.c_uint64(0)
        check(uc.uc_reg_read(self.h, reg, C.byref(v)), "uc_reg_read")
        return v.value

    def hook(self, kind: int, cb, *extra) -> int:
        hh = C.c_size_t()
        args = [C.c_int(x) for x in extra]
        check(uc.uc_hook_add(self.h, C.byref(hh), kind, C.cast(cb, C.c_void_p), None,
                             C.c_uint64(1), C.c_uint64(0), *args), "uc_hook_add")
        self.hooks.append(cb)
        return hh.value

    def hook_range(self, kind: int, cb, begin: int, end: int) -> int:
        """Hook on [begin, end] only (code and memory hooks)."""
        hh = C.c_size_t()
        check(uc.uc_hook_add(self.h, C.byref(hh), kind, C.cast(cb, C.c_void_p), None,
                             C.c_uint64(begin), C.c_uint64(end)), "uc_hook_add")
        self.hooks.append(cb)
        return hh.value

    def unhook(self, hh: int) -> None:
        check(uc.uc_hook_del(self.h, hh), "uc_hook_del")

    def flush(self) -> None:
        """Drop translated blocks; uc_mem_write does not invalidate them."""
        check(uc.uc_ctl(self.h, CTL_TB_FLUSH | (1 << 30)), "uc_ctl tb flush")

    def start(self, begin: int, until: int, count: int = 0) -> int:
        return uc.uc_emu_start(self.h, begin, until, 0, count)

    def stop(self) -> None:
        uc.uc_emu_stop(self.h)
