import importlib.util, os, sys, tempfile, subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'tools'))
p=Path(__file__).resolve().parent
source=p.parent/'tools/pc_run.py'
spec=importlib.util.spec_from_file_location('joy_pc_run',source)
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
if '--broken' in sys.argv:
    exec(compile(source.read_text().replace("    env.pop('SWOTL_JOYSTICK', None)\n", ''), str(source), 'exec'), M.__dict__)
seen=[]
def prepare(run):
    (run/'root').mkdir(parents=True)
    (run/'trace').mkdir()
    return run/'root'
def run(command,**kwargs):
    seen.append(kwargs['env'])
    (kwargs['cwd']/'trace/exit.txt').write_text('done')
    return SimpleNamespace(returncode=0)
with tempfile.TemporaryDirectory(prefix='swotl-joy-cli-') as tmp:
    M.REPO=Path(tmp)
    with patch.object(M,'prepare',prepare), patch.object(M.subprocess,'run',run), patch.dict(os.environ,{'SWOTL_JOYSTICK':'1'}):
        for args in (['plain'],['enabled','--joystick']):
            with patch.object(sys,'argv',[str(source),*args]):
                assert M.main()==0
assert 'SWOTL_JOYSTICK' not in seen[0]
assert seen[1]['SWOTL_JOYSTICK']=='1'
for key in ('SWOTL_FIXED_FILE_CLOCK','SWOTL_KEYS','SWOTL_SNAPSHOTS'):
    assert seen[0][key]==seen[1][key]
print('Recorder CLI: explicit opt-in; inherited joystick cleared; other capture inputs unchanged')

if '--sabotage' in sys.argv:
    r=subprocess.run([sys.executable,__file__,'--broken'],capture_output=True,text=True)
    assert r.returncode and "assert 'SWOTL_JOYSTICK' not in seen[0]" in r.stderr,r.stderr
    print('Inherited joystick environment plant caught')
