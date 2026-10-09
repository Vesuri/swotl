"""DX liveness proof edges, including every block boundary and fault input."""
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translator.decode import decode
from translator.reglive import dead_dx


def plan(code, leaders=(), runtime=()):
    data=bytes.fromhex(code);ins=[];at=0
    while at<len(data):
        i=decode(data,0x100+at,at);ins.append(i);at+=i.size
    return dead_dx(ins,set(leaders),[SimpleNamespace(vram=k in runtime) for k in range(len(ins))])


def main():
    assert plan('f7e3 ba3412')[0]
    assert not plan('f7e3 ba3412',leaders={1})[0]
    assert not plan('f7e3 89d1 ba3412')[0]
    assert not plan('f7e3 b234')[0]  # DL alone does not overwrite DX.
    assert not plan('f7e3 b634')[0]  # Nor does DH.
    assert plan('f7e3 99')[0]
    assert plan('f7e3 f7e3')[0]  # A nontrapping word multiply overwrites DX.
    assert not plan('f7e3 f7e2')[0]  # MUL DX also consumes it.
    assert not plan('f7e3 f6e6 ba3412')[0]  # Byte MUL DH consumes the high byte.
    assert not plan('f7e3 f6e3')[0]  # MUL BL does not overwrite DX.
    assert not plan('f7e3 f7f1 ba3412')[0]  # DIV can expose input DX on a fault.
    assert not plan('f7e3 90 ba3412',runtime={1})[0]
    assert not plan('f7e3 7400 ba3412')[0]
    assert not plan('f7e3')[0]
    print('DX liveness: reads, partial writes, implicit writes, leaders and fault barriers pass')


if __name__ == '__main__':
    main()
