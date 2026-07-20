"""Bootstrap QTools from a QTools link inside the Nuke user directory."""

import os

import nuke


nuke.pluginAddPath(os.path.join(os.path.dirname(__file__), "QTools"))
