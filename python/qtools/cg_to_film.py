"""Create CG To Film as a self-contained Group node."""

import os

import nuke


_GROUP_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "groups", "CGTOFILM.nk")
)


def create_group():
    """Paste the bundled Group into the current script."""
    if not os.path.isfile(_GROUP_PATH):
        nuke.message("CG To Film group file was not found:\n{}".format(_GROUP_PATH))
        return None

    return nuke.nodePaste(_GROUP_PATH)
