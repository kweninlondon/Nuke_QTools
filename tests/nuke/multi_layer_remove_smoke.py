"""Fresh licensed Nuke: Nuke -t tests/nuke/multi_layer_remove_smoke.py.

Checks real native graph evaluation and embedded updates without QTools.
"""
import os
from pathlib import Path
import sys
import tempfile

import nuke

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'python'))
from qtools import multi_layer_remove, channel_rules_runtime

source = nuke.nodes.Constant()
for i in range(25):
    layer = 'qtest{}'.format(i)
    nuke.Layer(layer, [layer + '.' + c for c in ('red', 'green', 'blue')])
    source = nuke.nodes.AddChannels(inputs=[source], channels=layer)
for node in nuke.selectedNodes():
    node.setSelected(False)
source.setSelected(True)
group = multi_layer_remove.create_group()
group['remove_rules'].setValue('*')
group['keep_rules'].setValue(','.join('qtest{}'.format(i) for i in range(6)))
channel_rules_runtime.apply_rules(group)
expected = {c for c in source.channels() if c.split('.')[0] in {'qtest{}'.format(i) for i in range(6)}}
assert set(group.channels()) == expected
assert group.Class() == 'Group'
assert len([n for n in group.nodes() if n.Class() == 'Remove']) == 5
assert group['apply_rules'].label() == 'Update'
name = group.name()

with tempfile.TemporaryDirectory() as folder:
    path = os.path.join(folder, 'channel_rules.nk')
    nuke.scriptSaveAs(path, overwrite=1)
    sys.path.pop(0)
    for module in list(sys.modules):
        if module == 'qtools' or module.startswith('qtools.'):
            del sys.modules[module]
    nuke.scriptClear()
    nuke.scriptOpen(path)
    group = nuke.toNode(name)
    assert set(group.channels()) == expected
    assert all(n.Class() in ('Input', 'Remove', 'Output') for n in group.nodes())
    group['keep_rules'].setValue('qtest0.red')
    assert '#f0a030' in group['apply_rules'].label()
    group['apply_rules'].execute()
    assert set(group.channels()) == {'qtest0.red'}
    assert group['apply_rules'].label() == 'Update'
    group['remove_rules'].setValue('')
    group['keep_rules'].setValue('')
    group['apply_rules'].execute()
    assert set(group.channels()) == set(group.input(0).channels())
    assert not any(n.Class() == 'Remove' for n in group.nodes())
print('PASS: rules, native graph, dirty state, and embedded update without QTools.')
