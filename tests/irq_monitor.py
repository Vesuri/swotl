"""IRQ0 footprint monitor (docs/irq-plan.md I3) for tests/host_run.py.

Checks every guest memory access of a host run against I2's footprint
(build/gen/irq-footprint.csv):
- inside a delivered IRQ0 handler (deliver_guest from rt_irq to rt_irq_back),
  every access, generated or runtime, lies in the footprint for its kind: the
  fixed classes (paragraphs at run time: SPAZ's link paragraphs + the load
  segment, G = the word at 188A:0162, BDA), a song segment of G's table (S,
  reads), or the interrupted stack from the frame down by the proved depth (K);
- in main code, an access that meets the footprint (a read of a handler-written
  byte, a write of a handler-accessed byte) comes from a sync instruction whose
  row covers the address, runs with guest IF clear, or from a runtime service
  (recorded: the services that must mask the tick, I6); any other generated or
  runtime access fails;
- song buffers: per song table entry, the handler's reads give the buffer's
  extent and the ticks it was read in; a main or service write into an extent
  between its first and last read fails (a generated one) or is recorded (a
  service).
Records the sync sites hit, IF-clear accesses, services, song buffers and EMS
use (song segments in the E000h page frame) in tmp/test/irq-monitor-<run>.json.
"""
from __future__ import annotations

import bisect
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOOTPRINT = REPO / "build/gen/irq-footprint.csv"
GAME_DS_SLOT = (0x188A, 0x162)     # translator/irq.py
SONG_TABLE, SONGS = 0x613C, 0x27   # G: far pointers (offset, segment)
EMS_FRAME = 0xE000                 # src/runtime/ems.c
WRITTEN, ACCESSED, READ_OK, WRITE_OK, LAYOUT = 1, 2, 4, 8, 16
LIMIT = 20
# Runtime code that runs as an interrupt handler, not main code: the BIOS tick
# (IRQ0 while IVT 08h is the BIOS's, and the end of SPAZ's chain)
INTERRUPT_SIDE = {"bios_tick"}


class Monitor:
    def __init__(self, host, size: int, footprint: Path = FOOTPRINT):
        from translator import emit
        self.h = host
        self.size = size
        self.mem, self.sync = [], defaultdict(list)
        self.depth = None
        for r in csv.DictReader(footprint.open()):
            if r["kind"] == "mem":
                self.mem.append((r["class"], int(r["first"], 16), int(r["last"], 16), r["access"]))
            elif r["kind"] == "stack":
                self.depth = -int(r["first"], 16)
            elif r["kind"] == "sync" and r["class"] != "port":
                mod, off = r["where"].split("+")
                self.sync[(mod, int(off, 16))].append(
                    (r["class"], int(r["first"], 16), int(r["last"], 16)))
        if self.depth is None:
            raise ValueError(f"{footprint}: no stack row")
        tags = {t: m for m, t in emit.TAG.items()}
        pat = re.compile(r"^(%s)_([0-9A-F]{5})(_bp)?$" % "|".join(tags))
        labels = sorted((a, (tags[m.group(1)], int(m.group(2), 16)))
                        for n, a in host.syms.items() if (m := pat.match(n)))
        self.label_at = [a for a, _ in labels]
        self.label_node = [n for _, n in labels]
        named = sorted((a, n) for n, a in host.syms.items())
        self.sym_at = [a for a, _ in named]
        self.sym_name = [n for _, n in named]
        self.back = host.syms["rt_irq_back"]
        self.loadseg = None
        self.g = None
        self.mask = None
        self.dirty = True
        self.songs: dict[int, list] = {}      # table index -> [linear, lo, hi, first tick, last tick]
        self.song_span = (1, 0)               # all extents: quick reject
        self.windows: list[tuple[int, int, int]] = []
        self.in_handler = False
        self.k = (0, -1)
        self.tick = 0
        self.entries = Counter()
        self.found = Counter()
        self.masked = Counter()
        self.services = Counter()
        self.song_writes: list[tuple[int, int, str, bool, int]] = []
        self.problems: list[str] = []

    # -- layout --------------------------------------------------------------
    def para(self, cls: str):
        if re.fullmatch(r"[0-9A-F]{4}", cls):
            return int(cls, 16) + self.loadseg
        return {"BDA": 0x40, "G": self.g}.get(cls)

    def word(self, lin: int) -> int:
        return int.from_bytes(self.h.gmem(lin, 2), "little")

    def layout(self):
        """Class paragraphs, the masks and the song windows from guest memory."""
        if self.loadseg is None:
            self.loadseg = self.h.u32(self.h.syms["load_segment"]) & 0xFFFF
        self.g = self.word((GAME_DS_SLOT[0] + self.loadseg) * 16 + GAME_DS_SLOT[1]) or None
        mask = bytearray(self.size)
        for cls, lo, hi, access in self.mem:
            p = self.para(cls)
            if p is None:
                continue
            bits = (WRITTEN | ACCESSED | WRITE_OK) if access == "w" else (ACCESSED | READ_OK)
            for a in range(p * 16 + lo, min(p * 16 + hi + 1, len(mask))):
                mask[a] |= bits
        # words whose change moves the layout: the G slot, the song table
        slot = (GAME_DS_SLOT[0] + self.loadseg) * 16 + GAME_DS_SLOT[1]
        for a in range(slot, slot + 2):
            mask[a] |= LAYOUT
        self.windows = []
        if self.g:
            for a in range(self.g * 16 + SONG_TABLE, self.g * 16 + SONG_TABLE + 4 * SONGS):
                mask[a] |= LAYOUT
            for k in range(SONGS):
                off, seg = (self.word(self.g * 16 + SONG_TABLE + 4 * k + j) for j in (0, 2))
                if seg:
                    self.windows.append((seg * 16, seg * 16 + 0xFFFF, seg * 16 + off, k))
                    self.songs.setdefault(k, [seg * 16 + off, None, None, None, None])
        self.mask = mask
        self.dirty = False

    # -- sites -----------------------------------------------------------------
    def node(self, pc: int):
        k = bisect.bisect_right(self.label_at, pc) - 1
        return self.label_node[k] if k >= 0 else None

    def symbol(self, pc: int) -> str:
        k = bisect.bisect_right(self.sym_at, pc) - 1
        return self.sym_name[k] if k >= 0 else f"{pc:x}"

    @staticmethod
    def site(n) -> str:
        return f"{n[0]}+{n[1]:05X}"

    def fail(self, text: str):
        if len(self.problems) < LIMIT:
            self.problems.append(f"irq monitor: {text}")

    # -- events from host_run -------------------------------------------------
    def deliver(self):
        """deliver_guest reached: an IRQ0 delivery when it returns to rt_irq_back."""
        if self.h.u32(self.h.r("a7")) != self.back:
            return
        if self.dirty:
            self.layout()
        g = self.h.guest_regs(8)
        top = g["ss"] * 16 + g["sp"]
        self.k = (top - self.depth, top + 5)
        cs, ip = (int.from_bytes(self.h.mem(self.h.syms[n], 2), "big")
                  for n in ("rt_deliver_cs", "rt_deliver_ip"))
        self.entries[f"{cs:04X}:{ip:04X}"] += 1
        self.in_handler = True

    def returned(self):
        if self.in_handler:
            self.in_handler = False
            self.tick += 1

    def read(self, lin: int, size: int):
        m = self.mask
        if self.in_handler or self.dirty or m is None:
            return self.access(False, lin, size)
        if m[lin] & WRITTEN or m[lin + size - 1] & WRITTEN or size == 4 and (m[lin + 1] | m[lin + 2]) & WRITTEN:
            self.main_access(False, lin, size)

    def write(self, lin: int, size: int):
        m = self.mask
        if self.in_handler or self.dirty or m is None:
            return self.access(True, lin, size)
        hot = ACCESSED | LAYOUT
        if m[lin] & hot or m[lin + size - 1] & hot or size == 4 and (m[lin + 1] | m[lin + 2]) & hot \
                or self.song_span[0] <= lin + size - 1 and lin <= self.song_span[1]:
            self.main_access(True, lin, size)

    def access(self, write: bool, lin: int, size: int):
        if self.mask is None or (self.dirty and not self.in_handler):
            self.layout()
        if self.in_handler:
            self.handler_access(write, lin, size)
        else:
            self.main_access(write, lin, size)

    def handler_access(self, write: bool, lin: int, size: int):
        need = WRITE_OK if write else READ_OK
        for a in range(lin, lin + size):
            if self.k[0] <= a <= self.k[1] or self.mask[a] & need:
                continue
            song = None if write else self.song_of(a)
            if song is not None:
                s = self.songs[song]
                s[1] = a if s[1] is None else min(s[1], a)
                s[2] = a if s[2] is None else max(s[2], a)
                s[3] = self.tick if s[3] is None else s[3]
                s[4] = self.tick
                lo, hi = self.song_span
                self.song_span = (a, a) if lo > hi else (min(lo, a), max(hi, a))
                continue
            pc = self.h.r("pc")
            where = self.site(self.node(pc)) if self.h.code[0] <= pc < self.h.code[1] else self.symbol(pc)
            self.fail(f"handler {'write' if write else 'read'} of {a:05X} outside the footprint "
                      f"at {where} (tick {self.tick})")
            return

    def main_access(self, write: bool, lin: int, size: int):
        bits = 0
        for a in range(lin, lin + size):
            bits |= self.mask[a]
        if write and bits & LAYOUT:
            self.dirty = True
        hit = bits & (ACCESSED if write else WRITTEN)
        song = write and self.song_span[0] <= lin + size - 1 and lin <= self.song_span[1] and \
            any(s[1] is not None and s[1] <= lin + size - 1 and lin <= s[2] for s in self.songs.values())
        if not hit and not song:
            return
        pc = self.h.r("pc")
        generated = self.h.code[0] <= pc < self.h.code[1]
        if self.h.in_service:
            who = f"service {self.h.pending_vec[-1]:02X}h" if self.h.pending_vec else "service"
        elif generated:
            who = self.site(self.node(pc))
        else:
            who = self.symbol(pc)
        if song:
            self.song_writes.append((lin, size, who, generated and not self.h.in_service, self.tick))
        if not hit:
            return
        if self.h.in_service or (not generated and who in INTERRUPT_SIDE):
            self.services[f"{who} {self.cls_of(lin)}"] += 1
        elif not generated:
            self.fail(f"runtime {'write' if write else 'read'} of {lin:05X} meets the footprint "
                      f"at {who}")
        elif self.h.state(11, 1) == 0:
            self.masked[who] += 1
        elif self.covered(self.node(pc), lin, size):
            self.found[who] += 1
        else:
            self.fail(f"main {'write' if write else 'read'} of {lin:05X} meets the footprint at "
                      f"{who}, not a sync access for it")

    def song_of(self, a: int):
        """The song table entry whose segment holds a: the greatest pointer at or
        below a, else the lowest (song segments overlap)."""
        hits = [(ptr, k) for lo, hi, ptr, k in self.windows if lo <= a <= hi]
        if not hits:
            return None
        below = [h for h in hits if h[0] <= a]
        return max(below)[1] if below else min(hits)[1]

    def cls_of(self, lin: int) -> str:
        for cls, lo, hi, _ in self.mem:
            p = self.para(cls)
            if p is not None and p * 16 + lo <= lin <= p * 16 + hi:
                return f"{cls}:{lin - p * 16:04X}"
        return f"{lin:05X}"

    def covered(self, node, lin: int, size: int) -> bool:
        for cls, lo, hi in self.sync.get(node, ()):
            p = self.para(cls)
            if p is not None and p * 16 + lo <= lin and lin + size - 1 <= p * 16 + hi:
                return True
        return False

    # -- result ----------------------------------------------------------------
    def finish(self, out: Path | None) -> list[str]:
        problems = list(self.problems)
        played = {k: s for k, s in self.songs.items() if s[1] is not None}
        for lin, size, who, generated, tick in self.song_writes:
            for k, s in played.items():
                if generated and s[1] <= lin + size - 1 and lin <= s[2] and s[3] <= tick <= s[4]:
                    problems.append(f"irq monitor: main write of {lin:05X} into song {k}'s buffer "
                                    f"at {who} (tick {tick}, read in ticks {s[3]}-{s[4]})")
        ems = sorted(k for k, s in played.items() if EMS_FRAME * 16 <= s[0] < EMS_FRAME * 16 + 0x10000)
        record = dict(ticks=self.tick, handler_entries=dict(self.entries), g=self.g and f"{self.g:04X}",
                      sync_sites=dict(sorted(self.found.items())),
                      if_clear=dict(sorted(self.masked.items())),
                      services=dict(sorted(self.services.items())),
                      songs={k: dict(pointer=f"{s[0]:05X}", first=f"{s[1]:05X}", last=f"{s[2]:05X}",
                                     ticks=[s[3], s[4]]) for k, s in sorted(played.items())},
                      ems_songs=ems,
                      service_song_writes=sorted({w for _, _, w, g, _ in self.song_writes if not g}))
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, indent=1) + "\n")
        print(f"irq monitor: {self.tick} ticks, {len(self.found)} sync sites hit, "
              f"{sum(self.masked.values())} IF-clear and {sum(self.services.values())} service accesses, "
              f"{len(played)} song buffers{' (EMS)' if ems else ''}, {len(problems)} problems")
        return problems
