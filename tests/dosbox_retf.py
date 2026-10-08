"""Live DOSBox-X oracle for the documented Unicorn 16-bit RETF wrap bug.

The existing, unmodified heavy-debug binary executes one instruction. The
caller supplies its current registers, instruction bytes and stack bytes;
no translated/interpreted result enters this oracle. Debugger single-step
runs the CPU directly, without advancing devices or delivering hardware IRQs.
All registers/flags are read back and the 1 MiB physical memory window is
compared before/after. Instruction and stack inputs must be conventional RAM. No saved reference or expected CS calculation is used.
"""
from __future__ import annotations

import atexit
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parent.parent
NAMES = ('eax', 'ebx', 'ecx', 'edx', 'esp', 'ebp', 'esi', 'edi',
         'es', 'cs', 'ss', 'ds', 'eip', 'eflags')
INSTANCE = None


class Debugger:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='swotl-retf-')
        self.path = Path(self.tmp.name)
        self.log = self.path / 'debug.log'
        self.offset = 0
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 120, 0, 0))
        # Separate test configuration: never edit the game/reference fixture.
        conf = self.path / 'oracle.conf'
        conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmemsize=4\n'
                        '[cpu]\ncore=normal\ncputype=386\ncycles=fixed 12000\n'
                        '[mixer]\nnosound=true\n[log]\nlogfile=debug.log\n')
        env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', TERM='xterm')
        try:
            self.proc = subprocess.Popen([
                str(ROOT / 'tools/vendor/dosbox-x/src/dosbox-x'), '-conf', str(conf),
                '-nogui', '-nomenu', '-silent', '-fastlaunch', '-break-start'],
                cwd=self.path, env=env, stdin=slave, stdout=slave, stderr=slave)
        finally:
            os.close(slave)
        atexit.register(self.close)
        self.wait('TYPE HELP')
        self.sequence = 0

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()  # only the subprocess owned by this oracle
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.master is not None:
            os.close(self.master)
            self.master = None
        self.tmp.cleanup()

    def wait(self, marker):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f'DOSBox oracle exited {self.proc.returncode}')
            if self.log.exists():
                data = self.log.read_text(errors='replace')[self.offset:]
                if marker in data:
                    self.offset += len(data)
                    return data
            ready, _, _ = select.select([self.master], [], [], .01)
            if ready:
                os.read(self.master, 65536)  # drain curses; parse only the plain log
        raise RuntimeError(f'DOSBox oracle timeout waiting for {marker!r}')

    def command(self, command):
        self.sequence += 1
        marker = f'ORACLE_DONE_{self.sequence}'
        os.write(self.master, (command + '\nADDLOG ' + marker + '\n').encode())
        result = self.wait('NOTICE: ' + marker)
        if 'failure' in result.lower() or 'error' in result.lower():
            raise RuntimeError(result)
        return result

    def registers(self):
        result = self.command('EV ' + ' '.join(NAMES))
        found = re.search(r"EV of '[^']+' is:\n([0-9a-f ]+)\n", result)
        if not found:
            raise RuntimeError(f'Missing DOSBox registers: {result}')
        values = [int(x, 16) for x in found[1].split()]
        if len(values) != len(NAMES):
            raise RuntimeError(f'Incomplete DOSBox registers: {result}')
        return dict(zip(NAMES, values))

    def memory(self):
        # Debugger MEMDUMPBIN wraps its offset at 64 KiB. Dump each segment
        # separately, covering the complete 1 MiB physical address space.
        chunks = []
        for segment in range(0, 0x10000, 0x1000):
            result = self.command(f'MEMDUMPBIN {segment:x}:0 10000')
            if 'Memory dump binary success.' not in result:
                raise RuntimeError(result)
            data = (self.path / 'MEMDUMP.BIN').read_bytes()
            if len(data) != 0x10000:
                raise RuntimeError('Incomplete DOSBox memory dump')
            chunks.append(data)
        return b''.join(chunks)

    def run(self, registers, flags, code, stack):
        if flags & 0x100:
            raise RuntimeError('DOSBox RETF oracle requires TF clear')
        desired = {('e' + r if r in ('ax','bx','cx','dx','sp','bp','si','di','ip') else r): v
                   for r, v in registers.items()}
        desired['eflags'] = flags
        # Full 32-bit writes eliminate debugger startup state in upper words.
        for name in NAMES:
            self.command(f'SR {name} {desired[name]:x}')
        for address, data in stack + [(registers['cs'] * 16 + registers['ip'], code)]:
            if address + len(data) > 0xa0000:
                raise RuntimeError('DOSBox RETF input must be in conventional RAM')
            self.command(f'SM {address >> 4:x}:{address & 15:x} ' + data.hex(' '))
        before_regs = self.registers()
        if before_regs != desired:
            raise RuntimeError(f'DOSBox state initialization mismatch: {before_regs} != {desired}')
        before = self.memory()
        for address, data in stack + [(registers['cs'] * 16 + registers['ip'], code)]:
            if before[address:address + len(data)] != data:
                raise RuntimeError(f'DOSBox memory initialization mismatch at {address:x}: {before[address:address + len(data)].hex()} != {data.hex()}')
        # xterm F11: execute exactly one instruction in the normal CPU core.
        self.command('\x1b[23~')
        after_regs = self.registers()
        after = self.memory()
        if before != after:
            raise RuntimeError('DOSBox RETF unexpectedly wrote memory')
        out = {r: after_regs['e' + r] for r in ('ax','bx','cx','dx','sp','bp','si','di','ip')}
        out.update({r: after_regs[r] for r in ('es','cs','ss','ds')})
        return out, after_regs['eflags']


def run(registers, flags, code, read):
    global INSTANCE
    if INSTANCE is None:
        INSTANCE = Debugger()
    ss, sp = registers['ss'] * 16, registers['sp']
    # Include both sides of the wrap and the unwrapped alternative. Read
    # bytes from the live x86 state, not from the IR or 68k result.
    stack = [(ss + sp, read(ss + sp, 6)), (ss, read(ss, 6))]
    return INSTANCE.run(registers, flags, code, stack)
