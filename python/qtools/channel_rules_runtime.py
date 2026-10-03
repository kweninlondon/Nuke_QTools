"""Self-contained runtime embedded in Channel Rules Groups when created.

Only Python's standard library and Nuke are required, including for updates.
"""
import fnmatch

import nuke


def patterns(text):
    return [part.strip() for part in text.replace('\r', ',').replace('\n', ',').split(',') if part.strip()]


def matches(channel, rules):
    layer = channel.split('.', 1)[0]
    return any(fnmatch.fnmatchcase(channel, rule) or fnmatch.fnmatchcase(layer, rule)
               for rule in rules)


def resolve(channels, remove_text, keep_text):
    """Keep is a final allowlist when supplied, overriding earlier removals."""
    available = set(channels)
    remove_rules, keep_rules = patterns(remove_text), patterns(keep_text)
    retained = {c for c in available if not matches(c, remove_rules)}
    if keep_rules:
        retained = {c for c in available if matches(c, keep_rules)}
    return sorted(retained), sorted(available - retained)


def removal_masks(channels, removed):
    """Use whole-layer masks where possible; otherwise individual channels."""
    layers = {}
    for channel in set(channels):
        layers.setdefault(channel.split('.', 1)[0], set()).add(channel)
    removed = set(removed)
    masks = []
    for layer, members in sorted(layers.items()):
        if members <= removed:
            masks.append(layer)
        else:
            masks.extend(sorted(members & removed))
    return [masks[i:i + 4] for i in range(0, len(masks), 4)]


def apply_rules(group):
    source = group.input(0)
    if source is None:
        raise ValueError('Connect the Group input before applying rules.')
    channels = list(source.channels())
    if not channels:
        raise ValueError('The input has no channels to inspect.')
    remove_text = group['remove_rules'].value()
    keep_text = group['keep_rules'].value()
    retained, removed = resolve(channels, remove_text, keep_text)
    batches = removal_masks(channels, removed)
    undo = nuke.Undo()
    undo.begin('Apply Channel Rules')
    group.begin()
    created = []
    try:
        children = list(group.nodes())
        inputs = [node for node in children if node.Class() == 'Input']
        outputs = [node for node in children if node.Class() == 'Output']
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError('Channel Rules needs exactly one internal Input and Output.')
        previous = [node for node in children
                    if node.Class() == 'Remove' and node.knob('qtools_rule_node') is not None]
        tail = inputs[0]
        for index, batch in enumerate(batches):
            node = nuke.nodes.Remove(name='RuleRemove', inputs=[tail])
            created.append(node)
            marker = nuke.Boolean_Knob('qtools_rule_node', '')
            marker.setVisible(False)
            node.addKnob(marker)
            node['operation'].setValue('remove')
            for knob, value in zip(('channels', 'channels2', 'channels3', 'channels4'),
                                   batch + ['none'] * (4 - len(batch))):
                node[knob].setValue(value)
            node.setXYpos(0, 80 * (index + 1))
            tail = node
        # Do not replace the working graph until the new graph is validated.
        if set(tail.channels()) != set(retained):
            raise RuntimeError('Native Remove output differs from the requested rules; previous graph preserved.')
        outputs[0].setInput(0, tail)
        outputs[0].setXYpos(0, 80 * (len(batches) + 1))
        for node in previous:
            nuke.delete(node)
        created = []
        group['removed_channels'].setValue(
            '\n'.join('- ' + mask for batch in batches for mask in batch) or '(none)')
        group['rules_applied'].setValue(True)
        group['apply_rules'].setLabel('Update')
    except Exception:
        for node in reversed(created):
            nuke.delete(node)
        raise
    finally:
        group.end()
        undo.end()


def run_button():
    try:
        apply_rules(nuke.thisNode())
    except Exception as error:
        nuke.message('Channel Rules: {}'.format(error))
