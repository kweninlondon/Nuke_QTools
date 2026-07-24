"""Copy and paste partial node trees while preserving external inputs."""

import base64
import json

import nuke

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets


CONNECTION_PREFIX = "# QTOOLS_WIRED_COPY: "
METADATA_PREFIX = "# QTOOLS_WIRED_COPY_DATA: "


def _clipboard():
    """Return the application clipboard."""
    application = QtWidgets.QApplication.instance()
    return application.clipboard() if application is not None else None


def _node_full_name(node):
    """Return a node path that can be resolved from the Root context."""
    try:
        return node.fullName()
    except Exception:
        return node.name()


def _copy_metadata(selected_nodes):
    """Return readable connection lines and machine-readable metadata."""
    selected_set = set(selected_nodes)
    origin_x = min(node.xpos() for node in selected_nodes)
    origin_y = min(node.ypos() for node in selected_nodes)
    connections = []
    readable_lines = []

    for node in selected_nodes:
        try:
            input_count = node.inputs()
        except Exception:
            continue

        for input_index in range(input_count):
            try:
                source = node.input(input_index)
            except Exception:
                continue

            if source is None or source in selected_set:
                continue

            connections.append({
                "node": node.name(),
                "class": node.Class(),
                "x": node.xpos() - origin_x,
                "y": node.ypos() - origin_y,
                "input": input_index,
                "source": _node_full_name(source),
                "source_name": source.name(),
            })
            readable_lines.append(
                "{}{}.input{} = {}".format(
                    CONNECTION_PREFIX,
                    node.name(),
                    input_index,
                    source.name()
                )
            )

    metadata = {
        "version": 1,
        "connections": connections,
    }
    encoded_metadata = base64.urlsafe_b64encode(
        json.dumps(
            metadata,
            separators=(",", ":")
        ).encode("utf-8")
    ).decode("ascii")
    return readable_lines, encoded_metadata


def copy_with_inputs():
    """Copy selected nodes with external-input data in clipboard comments."""
    selected_nodes = list(nuke.selectedNodes())

    if not selected_nodes:
        return False

    nuke.nodeCopy("%clipboard%")
    clipboard = _clipboard()

    if clipboard is None:
        return False

    node_text = clipboard.text()
    readable_lines, encoded_metadata = _copy_metadata(selected_nodes)
    headers = readable_lines + [
        "{}{}".format(METADATA_PREFIX, encoded_metadata)
    ]
    clipboard.setText("{}\n{}".format(
        "\n".join(headers),
        node_text
    ))
    return True


def _metadata_from_text(text):
    """Decode Wired Copy metadata from clipboard text."""
    for line in str(text or "").splitlines():
        if not line.startswith(METADATA_PREFIX):
            continue

        encoded_metadata = line[len(METADATA_PREFIX):].strip()

        try:
            decoded = base64.urlsafe_b64decode(
                encoded_metadata.encode("ascii")
            ).decode("utf-8")
            metadata = json.loads(decoded)
        except Exception:
            return None

        if (
            isinstance(metadata, dict)
            and metadata.get("version") == 1
            and isinstance(metadata.get("connections"), list)
        ):
            return metadata

    return None


def _find_source(connection):
    """Resolve the saved external source in the current script."""
    source = nuke.toNode(connection.get("source", ""))

    if source is None:
        source = nuke.toNode(connection.get("source_name", ""))

    return source


def _match_pasted_node(connection, pasted_nodes, origin_x, origin_y):
    """Match saved relative position and class to one pasted node."""
    expected_x = origin_x + int(connection.get("x", 0))
    expected_y = origin_y + int(connection.get("y", 0))
    expected_class = connection.get("class", "")
    candidates = [
        node
        for node in pasted_nodes
        if (
            node.Class() == expected_class
            and node.xpos() == expected_x
            and node.ypos() == expected_y
        )
    ]

    if len(candidates) == 1:
        return candidates[0]

    original_name = connection.get("node", "")
    named_candidates = [
        node
        for node in pasted_nodes
        if (
            node.Class() == expected_class
            and (
                node.name() == original_name
                or (
                    node.name().startswith(original_name)
                    and node.name()[len(original_name):].isdigit()
                )
            )
        )
    ]

    return named_candidates[0] if len(named_candidates) == 1 else None


def _restore_connections(metadata, pasted_nodes):
    """Restore saved external inputs and return unresolved descriptions."""
    if not pasted_nodes:
        return []

    origin_x = min(node.xpos() for node in pasted_nodes)
    origin_y = min(node.ypos() for node in pasted_nodes)
    unresolved = []

    for connection in metadata["connections"]:
        node = _match_pasted_node(
            connection,
            pasted_nodes,
            origin_x,
            origin_y
        )
        source = _find_source(connection)
        input_index = int(connection.get("input", -1))

        if node is None or source is None or input_index < 0:
            unresolved.append(
                "{}.input{} = {}".format(
                    connection.get("node", "?"),
                    connection.get("input", "?"),
                    connection.get("source_name", "?")
                )
            )
            continue

        try:
            if node.input(input_index) is None:
                node.setInput(input_index, source)
        except Exception:
            unresolved.append(
                "{}.input{} = {}".format(
                    connection.get("node", "?"),
                    input_index,
                    connection.get("source_name", "?")
                )
            )

    return unresolved


def paste_with_inputs():
    """Paste clipboard nodes and restore connections recorded by Wired Copy."""
    clipboard = _clipboard()

    if clipboard is None:
        return []

    metadata = _metadata_from_text(clipboard.text())

    if metadata is None:
        nuke.message(
            "Connection information was not found.\n\n"
            "Use Copy with Inputs before Paste with Inputs."
        )
        return []

    for node in nuke.selectedNodes():
        node.setSelected(False)

    undo = nuke.Undo()
    undo.begin("Paste with Inputs")

    try:
        nuke.nodePaste("%clipboard%")
        pasted_nodes = list(nuke.selectedNodes())
        unresolved = _restore_connections(metadata, pasted_nodes)
    finally:
        undo.end()

    if unresolved:
        nuke.message(
            "{} external connection(s) could not be restored:\n\n{}".format(
                len(unresolved),
                "\n".join(unresolved)
            )
        )

    return pasted_nodes


def duplicate_with_inputs():
    """Copy and immediately paste selected nodes with external inputs."""
    if not copy_with_inputs():
        return []

    return paste_with_inputs()
