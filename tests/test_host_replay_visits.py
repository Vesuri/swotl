"""Exercise Host.run's actual replay hooks with nested guest handlers."""
import argparse
import inspect
import textwrap
import host_run as H


def scenario(run, same_point, changed_epoch=False):
    h = object.__new__(H.Host)
    h.services, h.music_skip, h.entry = [], False, 0
    h.syms = dict(A=100, A_bp=110, A_np=120, A_bp_np=130,
                  B=200, B_np=220, rt_irq_back=300)
    h.stack, posted = 1000, []
    h.r = lambda name: h.stack
    h.post = posted.append
    h.guest_vector = lambda vector: True

    class Engine:
        def __init__(self):
            self.hooks = {}

        def hook_range(self, kind, callback, first, last):
            assert first == last
            self.hooks.setdefault(first, []).append(callback)

        def reg_write(self, *args):
            pass

        def start(self, *args, **kwargs):
            def visit(address):
                for hook in self.hooks.get(address, []):
                    hook(None, address, 2, None)
                assert not h.irq_lost, h.irq_lost
            visit(110)  # outer guarded entry interrupted before execution
            assert posted == [8] and h.visits.get('A', 0) == 0
            if not same_point:
                h.stack = 800
                visit(200)
                assert posted == [8, 8]
                h.stack = 788
                visit(300); visit(220)
                h.stack = 988
                visit(300)
                assert posted == [8, 8, 8]  # outer group survives nesting
                visit(300); visit(120)
                assert h.visits == {'A': 1, 'B': 1} and not h.groups
                return 0
            h.stack = 800
            visit(100); visit(120)  # same point executed inside handler
            assert h.visits['A'] == 1
            visit(200)  # nested interrupt at another point
            assert posted == [8, 8]
            h.stack = 600
            visit(100)
            assert posted == [8, 8, 8]
            h.stack = 588
            visit(300); visit(120)
            assert h.visits['A'] == 2
            h.stack = 788
            visit(300); visit(220)
            h.stack = 988
            if changed_epoch:
                h.services.append('handler service')
            visit(300)
            assert posted == [8, 8, 8, 8]
            visit(300)
            h.services.append('new epoch inside handler')
            visit(120)  # guarded IRQ return resumes exact continuation
            assert h.visits == {'A': 1}
            visit(110); visit(130)  # un-interrupted guarded execution
            assert h.visits == {'A': 2}
            assert not h.groups
            return 0

    h.e = Engine()
    run(h, dict(keys=[], snapshots=[], releases=[], irqs=[
        (0, 'A', 0, 8), (0, 'B', 0, 8),
        (0, 'A', 1 if same_point else 0, 8)] +
        ([(1 if changed_epoch else 0, 'A', 0 if changed_epoch else 2, 8)] if same_point else [])), 1)
    assert h.irq_i == (4 if same_point else 3)


def check(run=H.Host.run):
    for same_point in (True, False):
        scenario(run, same_point)
    scenario(run, True, True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    check()
    print('host replay: nested groups, same-point visits, epochs and guarded continuations pass')
    if args.sabotage:
        source = textwrap.dedent(inspect.getsource(H.Host.run))
        old = 'here = canon[addr]'
        assert old in source
        source = source.replace(old, old + '\n        self.visits[here] = self.visits.get(here, 0) + 1')
        namespace = dict(vars(H))
        exec(source, namespace)
        try:
            check(namespace['run'])
        except AssertionError:
            print('host replay: early-counting fault caught')
        else:
            raise AssertionError('early-counting fault survived')
