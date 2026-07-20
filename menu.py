"""Create QTools menus when Nuke's graphical interface starts."""

import nuke


qtools_menu = nuke.menu("Nuke").addMenu("QTools")

# Add commands here as tools are created. For example:
# qtools_menu.addCommand("Example", "qtools.example.run()")

