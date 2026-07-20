"""Create QTools menus when Nuke's graphical interface starts."""

import nuke


qtools_menu = nuke.menu("Nuke").addMenu("QTools")

qtools_menu.addCommand(
    "Postage Stamp Connector",
    "from qtools import postage_stamp_creator; "
    "postage_stamp_creator.create_or_retarget_postage_stamp()",
    "Alt+Y",
)
