#!/usr/bin/env python3
"""Measurement regressions must catch false bitfield reads and missing helpers."""
import inspect
import io
import unittest
from unittest.mock import patch

import test_cost_meter as T


def check(case, broken):
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
    result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    assert result.wasSuccessful() != broken, 'cost-tool plant escaped or baseline failed'


check(T.BitfieldOperands, False)
check(T.RuntimeLabels, False)
source = inspect.getsource(T.M.accesses)
bad = source.replace('ops = [ops[0], ops[-1]]', 'ops = ops[:-2]')
assert bad != source
scope = dict(T.M.__dict__)
exec(bad, scope)
with patch.object(T.M, 'accesses', scope['accesses']):
    check(T.BitfieldOperands, True)
print('cost meter: bitfield offset as memory plant caught')
original = T.A.label_cycles
with patch.object(T.A, 'label_cycles', lambda capture, syms, extra=(): original(capture, syms)):
    check(T.RuntimeLabels, True)
print('label A/B: omitted explicit helper plant caught')

check(T.ChangedLabels, False)
with patch.object(T.A, 'changed_labels', lambda weights, before, after:
                  {k for k in weights if before.get(k) != after.get(k) or k + '_bp' in after}):
    check(T.ChangedLabels, True)
print('label A/B: unchanged guarded-copy plant caught')

check(T.RegisterAliases, False)
source = inspect.getsource(T.M.reglist_size)
bad = source.replace('operand = operand.replace("fp", "a6").replace("sp", "a7")', 'operand = operand')
assert bad != source
scope = dict(T.M.__dict__)
exec(bad, scope)
with patch.object(T.M, 'reglist_size', scope['reglist_size']):
    check(T.RegisterAliases, True)
print('cost meter: omitted register-alias normalization plant caught')

check(T.StringLayoutLabels, False)
with patch.object(T.A, 'canon', lambda name: name.removesuffix('_bp')):
    check(T.StringLayoutLabels, True)
print('label A/B: omitted cold string cycles plant caught')

check(T.InstructionMix, False)
source = inspect.getsource(T.A.instruction_cycles)
bad = source.replace('n * cycles / executions', 'cycles')
assert bad != source
scope = dict(T.A.__dict__)
exec(bad, scope)
with patch.object(T.A, 'instruction_cycles', scope['instruction_cycles']):
    check(T.InstructionMix, True)
print('instruction A/B: capture REP length used as host work plant caught')

check(T.LayoutAliases, False)
with patch.object(T.A, 'expand_aliases', lambda changed, *tables: set(changed)):
    check(T.LayoutAliases, True)
print('instruction A/B: omitted alias-neighbor work plant caught')

check(T.ExecutedLoops, False)
source = inspect.getsource(T.M.Program.set_loops)
import textwrap
source = textwrap.dedent(source)
bad = source.replace(' or taken.get(a, 0) <= 0', '')
assert bad != source
scope = dict(T.M.__dict__)
exec(bad, scope)
with patch.object(T.M.Program, 'set_loops', scope['set_loops']):
    check(T.ExecutedLoops, True)
print('cost meter: untaken backward branch discounts code plant caught')

source = inspect.getsource(T.M.capture_counts)
for old, new, name in (
        ('seq = np.concatenate(([previous], pcs)) if previous is not None else pcs',
         'seq = pcs', 'lost cross-field taken branch'),
        (' & ((bt < 0) | (dst == bt))', '', 'interrupt counted as direct branch')):
    bad = source.replace(old, new)
    assert bad != source
    scope = dict(T.M.__dict__)
    exec(bad, scope)
    with patch.object(T.M, 'capture_counts', scope['capture_counts']):
        check(T.ExecutedLoops, True)
    print(f'cost meter: {name} plant caught')

check(T.LongArithmetic, False)
with patch.object(T.M, 'cost_features', lambda feat: list(feat)):
    check(T.LongArithmetic, True)
print('cost meter: double-charged long arithmetic fetch/multiply plant caught')
