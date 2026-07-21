"""Create QTools menus when Nuke's graphical interface starts."""

import nuke


qtools_menu = nuke.menu("Nuke").addMenu("QTools")

qtools_menu.addCommand(
    "Postage Stamp Connector",
    "from qtools import postage_stamp_creator; "
    "postage_stamp_creator.create_or_retarget_postage_stamp()",
    "Alt+Y",
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
