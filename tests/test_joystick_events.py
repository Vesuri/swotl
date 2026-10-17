from pathlib import Path
import sys

import test_replay_events as C
p=Path(__file__).resolve().parent
source=(p/'amiga_replay.c').read_text()
data=C.DATA.replace('#define REPLAY_IRQS 3u','#define REPLAY_IRQS 0u').replace('#define REPLAY_SERVICES 1u','#define REPLAY_SERVICES 0u').replace('#define REPLAY_STEPS 1u','#define REPLAY_STEPS 4u').replace('{{2,1,0,0,0}}','{{2,2,5,-1000,0},{2,1,5,1000,0},{2,3,5,3,0},{2,1,0,0,0}}')
harness=C.HARNESS[:C.HARNESS.index('int main(void)')]+r'''
int main(void) {
    G_IF=1;
    mouse_x=17; mouse_y=-19; mouse_buttons=4;
    assert(replay_point(2)==0 && replay_steps==0);
    assert(replay_point(2)==0 && replay_steps==1);
    assert(replay_point(2)==0 && replay_steps==2);
    assert(replay_point(2)==0 && replay_steps==2);
    assert(replay_point(2)==0 && replay_steps==2);
    assert(replay_point(2)==0 && replay_steps==3);
    assert(!rt_key_tail && !rt_irq_tail && !replay_interrupts && !release_at);
    assert(mouse_x==17 && mouse_y==-19 && mouse_buttons==4);
    assert(replay_point(2)==-1 && replay_steps==4);
    return 0;
}
'''
C.check(source,False,data,harness,(0,),(0,))
for replacement in ([] if '--sabotage' not in sys.argv else ['case 5: mouse_buttons=step->value; break;', 'case 5: release_at=1; break;']):
    C.check(source.replace('case 5: break;',replacement),True,data,harness,(0,),(0,))
print('Joystick action scheduler: exact visits and no key/IRQ/mouse effects pass' + ('; both plants caught' if '--sabotage' in sys.argv else ''))
