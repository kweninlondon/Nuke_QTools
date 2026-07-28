"""Create one naturally sorted Shuffle2 branch for every source layer."""

import re

import nuke


HORIZONTAL_SPACING = 130
DOT_DISTANCE_BELOW_SOURCE = 80
SHUFFLE_DISTANCE_BELOW_DOT = 65


def _natural_sort_key(value):
    """Return a key that sorts embedded numbers numerically."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def _source_layers(source):
    """Return the source's unique layer names in natural order."""
    return sorted(
        {
            channel.split(".", 1)[0]
            for channel in source.channels()
        },
        key=_natural_sort_key
    )


def create_layer_shuffles():
    """Create a Dot and Shuffle2 for every layer on the selected node."""
    selected_nodes = list(nuke.selectedNodes())

    if len(selected_nodes) != 1:
        nuke.message(
            "Select exactly one source node before creating layer Shuffles."
        )
        return []

    source = selected_nodes[0]
    layers = _source_layers(source)

    if not layers:
        nuke.message("The selected node does not contain any channels.")
        return []

    undo = nuke.Undo()
    undo.begin("Create Layer Shuffles")
    created_nodes = []

    try:
        source_centre_x = (
            source.xpos() + source.screenWidth() // 2
        )
        dot_y = (
            source.ypos()
            + source.screenHeight()
            + DOT_DISTANCE_BELOW_SOURCE
        )
        previous_pipe_node = source

        for index, layer in enumerate(layers):
            dot_centre_x = (
                source_centre_x + index * HORIZONTAL_SPACING
            )

            dot = nuke.nodes.Dot()
            dot.setInput(0, previous_pipe_node)
            dot.setXYpos(
                int(dot_centre_x - dot.screenWidth() / 2),
                dot_y
            )

            shuffle = nuke.nodes.Shuffle2(
                name="Shuffle_{}".format(layer),
                label=layer
            )
            shuffle.setInput(0, dot)
            shuffle["in1"].setValue(layer)
            shuffle.setXYpos(
                int(dot_centre_x - shuffle.screenWidth() / 2),
                dot_y + SHUFFLE_DISTANCE_BELOW_DOT
            )

            created_nodes.extend((dot, shuffle))
            previous_pipe_node = dot
    finally:
        undo.end()

    return created_nodes
