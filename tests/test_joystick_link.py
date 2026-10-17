from pathlib import Path
import os,subprocess,struct,sys,tempfile
sys.path.insert(0,str(Path.cwd()/'tests'))
import host_run as H
import joystick_replay as J
p=Path(__file__).resolve().parent
cc=str(Path(os.environ.get('AMIGA_TOOLCHAIN',Path.home()/'.local/opt'))/'bin/m68k-amiga-elf-gcc')
with tempfile.TemporaryDirectory(prefix='swotl-joy-link-') as tmp:
    out=Path(tmp)
    (out/'joystick_data.h').write_text(J.c_header([J.Run(0,1,1,0,1),J.Run(0,0,1,255,2),J.Run(0,0,1,252,1),J.Run(1,0,1,236,1)]))
    (out/'ports.c').write_text('''#include "runtime.h"
uint32_t rt_port_in(uint32_t port, uint32_t width) { return port==0x21 && width==8 ? 0xf8 : 0; }
void rt_port_out(uint32_t port,uint32_t value,uint32_t width) { (void)port; (void)value; (void)width; }
''')
    (out/'main.c').write_text('''#include "runtime.h"
volatile uint32_t replay_services;
extern void replay_joystick_complete(void);
extern uint32_t rt_port_in(uint32_t port,uint32_t width);
extern void rt_port_out(uint32_t port,uint32_t value,uint32_t width);
void test_stop(void) { for (;;) {} }
void rt_unsupported(const char *s,uint16_t a,uint16_t b,uint16_t c) {
 (void)s;(void)a;(void)b;(void)c;__asm__("moveq #2,%d0; jmp test_stop");__builtin_unreachable(); }
int main(void) {
 if(rt_port_in(0x21,8)!=0xf8) return 3;
 rt_port_out(0x201,0,8);
 if(rt_port_in(0x201,8)!=255 || rt_port_in(0x201,8)!=255 || rt_port_in(0x201,8)!=252) return 4;
 replay_services=1;
 if(rt_port_in(0x201,8)!=236) return 5;
 replay_joystick_complete();return 0;
}
''')
    common=[cc,'-m68020','-msoft-float','-O2','-ffreestanding','-Wall','-Wextra','-Werror','-I'+str(Path.cwd()/'src/runtime'),'-I'+str(out)]
    objects=[]
    for i,source in enumerate((out/'main.c',out/'ports.c',p/'joystick_replay.c')):
        obj=out/f'{i}.o';objects.append(obj)
        subprocess.run([*common,'-c',str(source),'-o',str(obj)],check=True)
    elf=out/'test.elf'
    for wrap,want in ([(True,0),(False,4)] if '--sabotage' in sys.argv else [(True,0)]):
        flags=['-Wl,--wrap=rt_port_in,--wrap=rt_port_out'] if wrap else ['-Wl,--defsym=__real_rt_port_in=rt_port_in,--defsym=__real_rt_port_out=rt_port_out']
        subprocess.run([cc,'-m68020','-nostdlib','-Wl,-Ttext=0x10000,-e,main',*flags,*map(str,objects),'-o',str(elf)],check=True)
        entry,segs,symbols=H.elf_load(elf)
        e=H.U.Engine(H.U.ARCH_M68K,H.U.MODE_BIG_ENDIAN,H.U.CPU_M68K_M68020)
        e.map(0,0x40000)
        for addr,data,size in segs:e.write(addr,data+bytes(size-len(data)))
        e.reg_write(H.U.M68K['sr'],0x2700);e.reg_write(H.U.M68K['a7'],0x3f000)
        e.write(0x3f000,struct.pack('>I',symbols['test_stop']))
        error=e.start(entry,symbols['test_stop'],timeout_us=1000000)
        assert not error,error
        assert e.reg_read(H.U.M68K['d0'])==want
print('68020 separate-object link dispatch passes' + ('; missing linker wrappers plant caught' if '--sabotage' in sys.argv else ''))
