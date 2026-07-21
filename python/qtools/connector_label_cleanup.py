"""Consolidate labels on hidden PostageStamp-to-Dot connections."""

import nuke


def _clean_text(value):
    """Return trimmed, single-line text."""
    if value is None:
        return ""

    return " ".join(str(value).split())


def _connector_name(label):
    """Return a connector label without a leading To or From."""
    label = _clean_text(label)
    lower_label = label.lower()

    if lower_label.startswith("to "):
        return label[3:].strip()

    if lower_label.startswith("from "):
        return label[5:].strip()

    return label


def _has_hidden_input(node):
    """Return True only when the node's input pipe is hidden."""
    try:
        return bool(node["hide_input"].value())
    except Exception:
        return False


def clean_up_connector_labels():
    """Normalize safe PostageStamp and source-Dot label pairs."""
    connections_by_dot = {}

    for stamp in nuke.allNodes("PostageStamp"):
        if not _has_hidden_input(stamp):
            continue

        if "label" not in stamp.knobs():
            continue

        stamp_name = _connector_name(stamp["label"].value())

        if not stamp_name:
            continue

        try:
            dot = stamp.input(0)
        except Exception:
            continue

        if dot is None or dot.Class() != "Dot":
            continue

        if "label" not in dot.knobs() or not _clean_text(
            dot["label"].value()
        ):
            continue

        connections_by_dot.setdefault(dot, []).append(
            (stamp, stamp_name)
        )

    safe_connections = []
    conflicting_dots = []

    for dot, connections in connections_by_dot.items():
        names = {
            name.lower()
            for _stamp, name in connections
        }

        if len(names) != 1:
            conflicting_dots.append(dot)
            continue

        canonical_name = connections[0][1]
        safe_connections.append(
            (dot, connections, canonical_name)
        )

    stamp_count = sum(
        len(connections)
        for _dot, connections, _name in safe_connections
    )

    if not stamp_count:
        message = "No safe PostageStamp-to-Dot labels were found."

        if conflicting_dots:
            message += "\n\n{} conflicting Dot(s) were skipped.".format(
                len(conflicting_dots)
            )

        nuke.message(message)
        return 0

    prompt = (
        "Normalize {stamp_count} hidden PostageStamp connection(s) "
        "across {dot_count} Dot(s)?"
    ).format(
        stamp_count=stamp_count,
        dot_count=len(safe_connections)
    )

    if conflicting_dots:
        prompt += "\n\n{} conflicting Dot(s) will be skipped.".format(
            len(conflicting_dots)
        )

    if not nuke.ask(prompt):
        return 0

    for dot, connections, canonical_name in safe_connections:
        dot["label"].setValue("From {}".format(canonical_name))

        for stamp, _stamp_name in connections:
            stamp["label"].setValue("To {}".format(canonical_name))

    message = "Normalized {} PostageStamp connection(s).".format(
        stamp_count
    )

    if conflicting_dots:
        message += "\n{} conflicting Dot(s) were skipped.".format(
            len(conflicting_dots)
        )

    nuke.message(message)
    return stamp_count
