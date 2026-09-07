"""Paste the bundled Planar Projection group by Vit Sedlacek and Jed Smith."""

import os

import nuke


_GROUP_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "groups", "PlanarProjection.nk"
    )
)


def create_group():
    """Paste the attributed Planar Projection group into the current script."""
    if not os.path.isfile(_GROUP_PATH):
        nuke.message(
            "Planar Projection group file was not found:\n{}".format(_GROUP_PATH)
        )
        return None
    return nuke.nodePaste(_GROUP_PATH)
