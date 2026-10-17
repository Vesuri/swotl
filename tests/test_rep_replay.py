"""REP slices: exact counters/registers, nested records, zero count and rejection."""
import argparse
import os
import subprocess
from pathlib import Path
import tempfile
from dataclasses import replace
import rep_replay as R
import test_replay_events as C


def check_builds(source, expect_failure=False):
    data = C.DATA
    rep = '''
#define REPLAY_REPS 1u
struct replay_rep { uint32_t point, service, hits, cx, si, di, end_cx, end_si, end_di, restart, repeat; };
static const struct replay_rep replay_reps[] = {{0,0,0,1,0,0,0,1,1,0,1}};
'''
    compiler = Path(os.environ.get('AMIGA_TOOLCHAIN', Path.home() / '.local/opt')) / 'bin/m68k-amiga-elf-gcc'
    with tempfile.TemporaryDirectory(prefix='swotl-replay-build-') as tmp:
        p = Path(tmp)
        (p / 'amiga_replay.c').write_text(source)
        for metadata in ('', rep):
            (p / 'replay_data.h').write_text(data.replace('SERVICE_HASH', '0') + metadata)
            result = subprocess.run([str(compiler), '-m68020', '-msoft-float', '-O2',
                '-ffreestanding', '-Wall', '-Wextra', '-Werror', '-I' + str(R.ROOT / 'src/runtime'),
                '-c', str(p / 'amiga_replay.c'), '-o', str(p / 'check.o')], capture_output=True, text=True)
            if expect_failure and not metadata:
                assert result.returncode and 'unused-variable' in result.stderr, result.stderr
            else:
                assert result.returncode == 0, result.stderr


def check_scheduler(broken=False):
    chunks = [R.Chunk('L',0,0,(4,65534,20),(2,2,24),True),
              R.Chunk('N',1,0,(1,30,40),(0,28,38),False),
              R.Chunk('L',2,0,(2,2,24),(1,4,26),False),
              R.Chunk('L',2,1,(0,4,26),(0,4,26),False)]
    r=R.Replay(chunks)
    assert not r.checkpoint(0,(4,65534,20),0,1,False)
    assert not r.checkpoint(0,(3,0,22),0,1,False)
    if broken:
        r.chunks[0]=replace(r.chunks[0],end=(1,4,26))
    assert r.checkpoint(0,(2,2,24),0,1,False)
    assert not r.checkpoint(1,(1,30,40),1,1,False)
    assert not r.checkpoint(1,(0,28,38),1,1,True)
    assert not r.checkpoint(0,(2,2,24),2,1,False)
    assert not r.checkpoint(0,(1,4,26),2,1,True)
    assert not r.checkpoint(0,(0,4,26),2,2,False)
    assert not r.checkpoint(0,(0,4,26),2,2,True)
    r.complete()
    for point,regs,svc,visits,done in [(1,chunks[0].start,0,1,False),
        (0,(3,0,22),0,1,False),(0,chunks[0].start,1,1,False),
        (0,chunks[0].start,0,2,False),(0,chunks[0].start,0,1,True)]:
        try:R.Replay(chunks).checkpoint(point,regs,svc,visits,done)
        except ValueError:pass
        else:raise AssertionError('bad slice accepted')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'rep.csv'
        assert R.read(Path(tmp)) == []
        try:R.read(Path(tmp), required=True)
        except ValueError:pass
        else:raise AssertionError('missing required REP metadata accepted')
        p.write_text(','.join(R.FIELDS)+'\n')
        try:R.read(Path(tmp), required=True)
        except ValueError:pass
        else:raise AssertionError('empty required REP metadata accepted')
        p.write_text(','.join(R.FIELDS)+'\nSWOTL.EXE,0x10,0,0,4,65534,20,2,2,24,1\n')
        assert R.read(Path(tmp))[0].end==(2,2,24)
        p.write_text(p.read_text().replace(',2,2,24,1',',5,2,24,1'))
        try:R.read(Path(tmp))
        except ValueError:pass
        else:raise AssertionError('increasing REP count accepted')


def check_c(source, broken=False):
    data=C.DATA+'''
#define REPLAY_REPS 3u
struct replay_rep { uint32_t point, service, hits, cx, si, di, end_cx, end_si, end_di, restart, repeat; };
static const struct replay_rep replay_reps[] = {
 {0,0,0,4,65534,20,2,2,24,1,1},
 {1,1,0,1,30,40,0,28,38,0,1},
 {0,2,0,2,2,24,1,4,26,0,1}};
'''
    harness=C.HARNESS[:C.HARNESS.index('int main(void)')]+'''
int main(void) {
 static uint32_t r[15];
 epochs[0]=1; visits[0]=1;
 r[1]=4; r[12]=65534; r[13]=20;
 assert(replay_rep(0,0,r)==0);
 r[1]=3; r[12]=0; r[13]=22;
 assert(replay_rep(0,0,r)==0);
 r[1]=2; r[12]=2; r[13]=24;
 assert(replay_rep(0,0,r)==1);
 replay_services=1; epochs[1]=2; visits[1]=1;
 r[1]=1; r[12]=30; r[13]=40;
 assert(replay_rep(1,0,r)==0);
 r[1]=0; r[12]=28; r[13]=38;
 assert(replay_rep(1,1,r)==0);
 replay_services=2; epochs[0]=3; visits[0]=1;
 r[1]=2; r[12]=2; r[13]=24;
 assert(replay_rep(0,0,r)==0);
 r[1]=1; r[12]=4; r[13]=26;
 assert(replay_rep(0,1,r)==0);
 assert(replay_rep_index==3 && !replay_rep_active);
 return 0;
}
'''
    C.check(source,broken,data,harness,(0,),(0,))


def check_compact(source):
    chunks = []
    for service, step in ((0, 2), (1, -2)):
        for i in range(3):
            start = (8 - 2*i, (65534 + 2*i*step) & 65535, (2 + 2*i*step) & 65535)
            end = (6 - 2*i, (start[1] + 2*step) & 65535, (start[2] + 2*step) & 65535)
            chunks.append(R.Chunk('L', service, i, start, end, True))
        chunks.append(R.Chunk('L', service, 3, end, (0, end[1], end[2]), False))
    groups = R.compact(chunks)
    assert [n for _, n in groups] == [3, 1, 3, 1]
    expanded = []
    for c, n in groups:
        delta = tuple((y-x) & 65535 for x,y in zip(c.start,c.end))
        for i in range(n):
            expanded.append(replace(c, hits=c.hits+i,
                start=tuple((x+i*d)&65535 for x,d in zip(c.start,delta)),
                end=tuple((x+i*d)&65535 for x,d in zip(c.end,delta))))
    assert expanded == chunks
    data = C.DATA + '''
#define REPLAY_REPS 8u
struct replay_rep { uint32_t service, hits; uint16_t point, cx, si, di, end_cx, end_si, end_di, restart, repeat; };
static const struct replay_rep replay_reps[] = {
''' + ''.join('{' + ','.join(map(str,(c.service,c.hits,0,*c.start,*c.end,int(c.restart),n))) + '},\n'
              for c,n in groups) + '};\n'
    calls = []
    for c in chunks:
        calls.append(f'replay_services={c.service}; epochs[0]={c.service+1}; visits[0]={c.hits+1};')
        for regs, done, expected in ((c.start,0,0),(c.end,int(not c.restart),int(c.restart))):
            calls.append(f'r[1]={regs[0]}; r[12]={regs[1]}; r[13]={regs[2]}; assert(replay_rep(0,{done},r)=={expected});')
    harness = C.HARNESS[:C.HARNESS.index('int main(void)')] + 'int main(void) { static uint32_t r[15];\n' + '\n'.join(calls) + '''
assert(replay_rep_index==8 && replay_rep_record==4 && !replay_rep_offset && !replay_rep_active);
return 0;
}
'''
    C.check(source,False,data,harness,(0,),(0,))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--sabotage',action='store_true');args=ap.parse_args()
    check_scheduler()
    source=(R.ROOT/'tests/amiga_replay.c').read_text()
    check_builds(source)
    check_c(source)
    check_compact(source)
    if args.sabotage:
        guarded = '#if REPLAY_REPS\nstatic uint32_t replay_rep_record, replay_rep_offset;\n#endif'
        assert guarded in source
        check_builds(source.replace(guarded, 'static uint32_t replay_rep_record, replay_rep_offset;'), True)
        try:check_scheduler(True)
        except AssertionError:pass
        else:raise AssertionError('wrong endpoint plant survived')
        old='c->restart && cx == end_cx'
        assert old in source
        check_c(source.replace(old,'c->restart && cx == end_cx - 1'),True)
    print('REP replay controls and rejection checks pass')
