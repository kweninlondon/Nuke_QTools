"""Create QTools menus when Nuke's graphical interface starts."""

import nuke

qtools_menu = nuke.menu("Nuke").addMenu("QTools")

gizmos_menu = qtools_menu.addMenu("Gizmos")

gizmos_menu.addCommand(
    "CG To Film",
    "nuke.createNode('CGTOFILM')",
)

nodes_qtools_menu = nuke.menu("Nodes").addMenu("QTools")

nodes_qtools_menu.addCommand(
    "CG To Film",
    "nuke.createNode('CGTOFILM')",
)

from qtools import shot_notes
from qtools import wired_copy


shot_notes.register_panel()

qtools_menu.addCommand(
    "Shot Notes",
    "from qtools import shot_notes; shot_notes.show_shot_notes()",
    "Ctrl+Alt+N",
)

qtools_menu.addCommand(
    "Postage Stamp Connector",
    "from qtools import postage_stamp_creator; "
    "postage_stamp_creator.create_or_retarget_postage_stamp()",
    "Alt+Y",
)

wired_copy_menu = qtools_menu.addMenu("Wired Copy")

wired_copy_menu.addCommand(
    "Copy with Inputs",
    "from qtools import wired_copy; wired_copy.copy_with_inputs()",
    "Ctrl+C",
)

wired_copy_menu.addCommand(
    "Paste with Inputs",
    "from qtools import wired_copy; wired_copy.paste_with_inputs()",
    "Ctrl+Shift+V",
)

wired_copy_menu.addCommand(
    "Duplicate with Inputs",
    "from qtools import wired_copy; wired_copy.duplicate_with_inputs()",
    "Ctrl+Shift+D",
)

utilities_menu = qtools_menu.addMenu("Utilities")

utilities_menu.addCommand(
    "Create Layer Shuffles",
    "from qtools import layer_shuffles; "
    "layer_shuffles.create_layer_shuffles()",
)

utilities_menu.addCommand(
    "Copy Asset Report",
    "from qtools import asset_report; asset_report.show_asset_report()",
)

script_cleanup_menu = qtools_menu.addMenu("Script Cleanup")

script_cleanup_menu.addCommand(
    "Dot Note clean up",
    "from qtools import dot_note_cleanup; "
    "dot_note_cleanup.clean_up_selected_dots()",
)

script_cleanup_menu.addCommand(
    "Connector Label clean up",
    "from qtools import connector_label_cleanup; "
    "connector_label_cleanup.clean_up_connector_labels()",
)
