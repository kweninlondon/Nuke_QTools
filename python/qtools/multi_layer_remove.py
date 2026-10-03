"""Create portable Channel Rules Groups using only native Nuke processing nodes."""
import os

import nuke


_DIRTY_CALLBACK = '''import nuke
node = nuke.thisNode()
knob = nuke.thisKnob()
if knob.name() in ('remove_rules', 'keep_rules', 'inputChange'):
    button = node.knob('apply_rules')
    applied = node.knob('rules_applied')
    if button is not None and applied is not None:
        text = 'Update' if applied.value() else 'Apply'
        button.setLabel('<font color="#f0a030">' + text + '</font>')
'''


def create_group():
    selected = nuke.selectedNodes()
    if len(selected) > 1:
        nuke.message('Select one input node, or deselect everything to create an unconnected Group.')
        return None
    source = selected[0] if selected else None
    runtime_path = os.path.join(os.path.dirname(__file__), 'channel_rules_runtime.py')
    with open(runtime_path, encoding='utf-8') as stream:
        button_script = stream.read() + '\nrun_button()\n'
    undo = nuke.Undo()
    undo.begin('Create Channel Rules')
    group = None
    try:
        group = nuke.nodes.Group(name='ChannelRules')
        group.addKnob(nuke.Tab_Knob('channel_rules', 'Channel Rules'))
        for name, label in (('remove_rules', 'Remove'), ('keep_rules', 'Keep')):
            knob = nuke.String_Knob(name, label)
            knob.setTooltip('Comma-separated, case-sensitive wildcards matching layers or channels. '
                            'Keep, when nonempty, is the final allowlist and overrides Remove.')
            group.addKnob(knob)
        applied = nuke.Boolean_Knob('rules_applied', '')
        applied.setVisible(False)
        group.addKnob(applied)
        button = nuke.PyScript_Knob('apply_rules', '<font color="#f0a030">Apply</font>')
        button.setValue(button_script)
        group.addKnob(button)
        result = nuke.Multiline_Eval_String_Knob('removed_channels', 'Channels Removed')
        result.setValue('Not applied yet.')
        result.setEnabled(False)
        group.addKnob(result)
        group.addKnob(nuke.Text_Knob('rules_help', '',
            'Blank Keep preserves channels not removed. Nonempty Keep selects only matching channels.\n'
            'Update after changing upstream channels. The graph is baked when you apply.'))
        group.begin()
        try:
            input_node = nuke.nodes.Input(name='Input1')
            output = nuke.nodes.Output(name='Output1', inputs=[input_node])
            output.setXYpos(0, 80)
        finally:
            group.end()
        group['knobChanged'].setValue(_DIRTY_CALLBACK)
        if source is not None:
            group.setInput(0, source)
            group.setXYpos(source.xpos(), source.ypos() + source.screenHeight() + 50)
        if nuke.env.get("gui", False):
            group.showControlPanel()
        return group
    except Exception:
        if group is not None:
            nuke.delete(group)
        raise
    finally:
        undo.end()


def show_dialog():
    """Compatibility entry point for older QTools menu registrations."""
    return create_group()
