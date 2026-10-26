"""IRQ0 stress mode (docs/irq-plan.md I6) for tests/host_run.py.

A recorded IRQ0 whose group is that one guest tick is not posted at its poll
visit: it is armed there and injected through rt_irq_interrupt (the CIA tick's
async entry) after a random number (seeded) of 68k instructions, generated or
runtime, as an interrupt frame on the 68k stack. It is injected earlier, before the
next event a tick does not commute with (I2): a sync access (build/gen/
irq-footprint.csv, ports included), CLI or POPF, a runtime entry (services,
faults, other IRQs, host stubs), a script step or the next recorded interrupt.
Not ready at the visit (a main OPL index/data pair): posted as without stress.
Not ready at the drawn point (runtime mask): it waits; not ready at an event:
fails. The run then must match the reference at every service and
snapshot, as without stress.

Unicorn (2.x): a PC write from a hook, or a read of SR through the API, loses
the lazily kept condition codes; a stop in a code hook leaves before the
instruction and keeps them. So the hook stops, host_run's run loop calls
resume() and restarts at the stub, which saves CCR itself; arming restarts at
the visited instruction (blocks translated before the counter hook skip it).
Every code hook of an instruction runs, in registration order, also after one
stopped, and again when the instruction runs after the handler: every host code
hook goes through guarded(), so the first one stops and the rest of that pass,
and its rerun, are skipped once.
"""
from __future__ import annotations

import csv
import random
import re
import struct

import uc as U

REACH = 400          # instructions after the visit at most (1..REACH, uniform)
STUB = 0x00FF1000    # above host_run.STACK_TOP: the tick's 68k entry
IF_OPS = re.compile(r"^(\w+):\t; [0-9A-F]{4}:[0-9A-F]{4} (cli|popf)\b")


class Stress:
    def __init__(self, host, seed: int):
        self.h = host
        self.rng = random.Random(seed)
        self.seed = seed
        self.left = None          # instructions before the armed tick, None: none armed
        self.skip = None          # the instruction whose hooks the injection cut short
        self.free: set[int] = set()   # hooks that do not end a window (counters, polls)
        self.counter = None
        self.last = None
        self.restart = None       # (kind, addr) for resume() after a stop
        self.problem: str | None = None
        self.armed = self.drawn = self.early = self.waited = self.posted = 0
        self.hook_range = host.e.hook_range
        host.e.hook_range = self.guarded

    def setup(self, footprint, gen_dir) -> None:
        """Window ends and the entry stub; after the symbols and code are loaded."""
        from translator import emit
        h, syms = self.h, self.h.syms
        names = set()
        for r in csv.DictReader(footprint.open()):
            if r["kind"] == "sync":
                mod, off = r["where"].split("+")
                names.add(emit.label(mod, int(off, 16)))
        for p in gen_dir.glob("*.s"):
            with p.open() as f:
                names.update(m.group(1) for line in f if (m := IF_OPS.match(line)))
        # _np: past a sync build's poll test at the event itself (irq-plan I8), where a
        # tick armed at that poll is due before the access, CLI or POPF
        self.bound = {syms[n + s] for n in names
                      for s in ("", "_np", "_bp", "_bp_np") if n + s in syms}
        self.bound |= {syms[n] for n in ("rt_int", "rt_fault", "rt_irq") if n in syms}
        # move.w ccr,-(a7); movem.l d0-d1/a0-a1,-(a7); jsr rt_irq_interrupt;
        # movem.l (a7)+,d0-d1/a0-a1; move.w (a7)+,ccr; rts (Unicorn has no RTR)
        code = bytes.fromhex("42e748e7c0c04eb9") + struct.pack(">I", syms["rt_irq_interrupt"]) \
            + bytes.fromhex("4cdf030344df4e75")
        h.e.write(STUB, code)

        @U.CODE_CB
        def entered(uh, addr, size, user):
            self.skip = None
        self.hook_range(U.HOOK_CODE, entered, STUB, STUB)

        @U.CODE_CB
        def count(uh, addr, size, user):
            if self.skip is not None:
                if self.skip == addr:
                    return
                self.skip = None
            if self.left is None:
                return
            if not h.state(11, 1):   # IF cleared by the previous instruction: an event missed
                return self.fail(f"stress: guest IF cleared under an armed tick at "
                                 f"{h.irq.symbol(self.last)}")
            self.last = addr
            if self.left == 0 or addr in self.bound:
                self.inject(addr, addr in self.bound)
            else:
                self.left -= 1
        self.count = count

    def guarded(self, kind, cb, begin, end):
        if kind != U.HOOK_CODE:
            return self.hook_range(kind, cb, begin, end)
        inner, free = cb, id(cb) in self.free

        @U.CODE_CB
        def hook(uh, addr, size, user):
            if self.skip == addr:
                return
            if self.left is not None and (not free or self.left == 0 or addr in self.bound):
                if self.inject(addr, not free or addr in self.bound):
                    return
            inner(uh, addr, size, user)
        return self.hook_range(kind, hook, begin, end)

    # -- from host_run's replay --------------------------------------------
    def eligible(self, irqs, i) -> bool:
        """irqs[i] is one guest IRQ0 alone in its (svc, label, hits) group, and the
        CIA tick could run it here (else production holds it, the reference did
        not: inside a main OPL index/data pair, posted as without stress)."""
        if irqs[i][3] != 8 or not (i + 1 == len(irqs) or irqs[i + 1][:3] != irqs[i][:3]):
            return False
        if not self.ready():
            self.posted += 1
            return False
        return True

    def arm(self, addr: int) -> None:
        """At the visited instruction addr, which runs first: stop and restart
        there (the running block would run its rest uncounted)."""
        self.left = self.rng.randint(1, REACH)
        self.armed += 1
        self.stop("arm", addr)

    def stop(self, kind: str, addr: int) -> None:
        self.restart, self.skip = (kind, addr), addr   # addr's hooks have run: skip once
        self.h.e.stop()

    def resume(self) -> int | None:
        """After the emulator returned: where to restart, None if it stopped otherwise."""
        if self.restart is None or self.h.halted:
            return None
        (kind, addr), self.restart = self.restart, None
        h = self.h
        if h.r("pc") != addr:
            raise AssertionError(f"stress: stopped at {h.r('pc'):x}, not {addr:x}")
        if kind == "arm":   # hooks are bound at translation: flush with the counter
            self.counter = self.hook_range(U.HOOK_CODE, self.count, 0, STUB - 1)
            h.e.flush()
            return addr
        h.e.unhook(self.counter)   # blocks translated with it keep calling into the list
        h.e.flush()
        a7 = h.r("a7") - 4
        h.e.write(a7, struct.pack(">I", addr))
        h.e.reg_write(U.M68K["a7"], a7)
        return STUB

    def pending(self, addr) -> bool:
        """The next recorded interrupt is due at addr: inject the armed tick first."""
        return self.left is not None and self.inject(addr, True)

    # -- injection ------------------------------------------------------------
    def ready(self) -> bool:
        """machine.c rt_irq0_ready."""
        h, s = self.h, self.h.syms
        b = lambda n: h.mem(s[n], 1)[0]
        return bool(h.state(11, 1)) and not b("rt_irq0_running") and not b("rt_irq_mask") \
            and not b("rt_opl_pair") and b("irq_head") == b("rt_irq_tail") and not b("rt_bench") \
            and h.guest_vector(8)

    def inject(self, addr: int, event: bool) -> bool:
        h = self.h
        if not self.ready():
            if event:
                self.fail(f"stress: armed tick not deliverable before the event at {h.irq.symbol(addr)}")
            elif self.left == 0:
                self.waited += 1
            return False
        if event:
            self.early += 1
        else:
            self.drawn += 1
        self.left = None
        h.sound_tick += 1
        self.stop("inject", addr)
        return True

    def fail(self, text: str) -> None:
        if not self.problem:
            self.problem = text
        self.left = None
        self.h.halted = True
        self.h.e.stop()

    def summary(self) -> str:
        return (f"irq stress seed {self.seed}: {self.armed} ticks armed, {self.drawn} injected at the "
                f"drawn instruction, {self.early} before an event, {self.waited} waits, {self.posted} posted "
                f"(not ready at the visit)")
