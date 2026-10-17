from pathlib import Path
import subprocess
import tempfile
import sys
p=Path(__file__).resolve().parent
source=(p.parent/'tools/vendor/dosbox-x/src/misc/swotl_trace.cpp').read_text()
state=source[source.index('FILE *joystick_ports = nullptr;'):source.index('/* OPL log')]
start=source.index('    if (joystick_ports && port == 0x201)')
body=source[start:source.index('\n\tif (opl && write',start)]
harness=r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <string>
void E_Exit(const char *) { std::abort(); }
uint64_t service_events;
STATE
void Record(bool write,uint8_t width,unsigned port,uint32_t value) {
BODY
}
int main() {
    Record(false,1,0x201,255);
    assert(joystick_run.count==0);
    joystick_ports=tmpfile(); assert(joystick_ports);
    Record(true,1,0x201,0);
    for(int i=0;i!=3;++i)Record(false,1,0x201,255);
    Record(false,1,0x201,252);
    service_events=1;
    Record(false,1,0x201,252); Record(false,1,0x201,252);
    Record(true,1,0x201,1);
    Record(false,1,0x21,248);
    Record(false,2,0x201,65535); Record(false,2,0x201,65535);
    FlushJoystickPorts(); FlushJoystickPorts();
    rewind(joystick_ports);
    std::string got; char buf[128];
    while(fgets(buf,sizeof buf,joystick_ports))got+=buf;
    assert(got=="0,1,1,0,1\n0,0,1,255,3\n0,0,1,252,1\n1,0,1,252,2\n1,1,1,1,1\n1,0,2,65535,2\n");
    fclose(joystick_ports);
}
'''.replace('STATE',state).replace('BODY',body)
variants={'normal':harness,'merged-service':harness.replace('joystick_run.service != service_events ||',''),
          'extra-repeat':harness.replace('++joystick_run.count;','joystick_run.count += 2;')}
with tempfile.TemporaryDirectory(prefix='swotl-joystick-recorder-') as tmp:
    p=Path(tmp)
    for name,text in variants.items():
        if name != 'normal' and '--sabotage' not in sys.argv: continue
        cpp=p/(name+'-recorder.cpp');exe=p/(name+'-recorder');cpp.write_text(text)
        subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
        r=subprocess.run([str(exe)],capture_output=True,text=True)
        if name=='normal':assert r.returncode==0,r.stderr
        else:assert r.returncode != 0 and 'Assertion' in r.stderr,(name,r.returncode,r.stderr)
print('Exact recorder compression passes' + ('; merged-service and extra-repeat plants caught' if '--sabotage' in sys.argv else ''))

INPUT_HARNESS = '#include "swotl_joystick_input.h"\n#include <cassert>\nint main() {\n    for (char axis : {\'x\', \'y\'}) {\n        for (int v : {0, 1, 999, 1000}) {\n            for (char sign : {\'+\', \'-\'}) {\n                const auto r = SwotlParseJoystick(std::string("j") + axis + sign + std::to_string(v));\n                assert(r.kind == axis && r.value == (sign == \'-\' ? -v : v));\n            }\n        }\n    }\n    for (int mask = 0; mask != 4; ++mask) {\n        const auto r = SwotlParseJoystick("jb" + std::to_string(mask));\n        assert(r.kind == \'b\' && r.value == mask);\n    }\n    for (const auto s : {"", "j", "jx", "jx+", "jx100", "jx+1001", "jy-1001",\n                        "jx+99999999999999999999", "jx+-1", "jx+1x", "jz+1", "jb4",\n                        "jb-1", "jb00", "JX+1", "jx+ 1", "jx+1\\n", "enter", "mx+1"})\n        assert(!SwotlParseJoystick(s).kind);\n}\n'
header=(Path(__file__).resolve().parents[1]/'tools/vendor/dosbox-x/include/swotl_joystick_input.h').read_text()
with tempfile.TemporaryDirectory(prefix='swotl-joystick-input-') as tmp:
    out=Path(tmp)
    (out/'input.cpp').write_text(INPUT_HARNESS)
    variants=[('normal',header)]
    if '--sabotage' in sys.argv:
        assert 'value > 1000' in header
        variants.append(('wide-axis',header.replace('value > 1000','value > 2000')))
    for name,text in variants:
        (out/'swotl_joystick_input.h').write_text(text)
        subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',str(out/'input.cpp'),'-o',str(out/'input')],check=True)
        r=subprocess.run([str(out/'input')],capture_output=True,text=True)
        if name=='normal': assert r.returncode==0,r.stderr
        else: assert r.returncode and 'Assertion' in r.stderr,r.stderr
print('Recorder axes/buttons parser boundaries pass')
