"""Load the opposite EXR/MOV representation using AYON's Nuke loader.

AYON imports are deliberately lazy: QTools also runs outside AYON sessions.
No filenames are rewritten and no Read nodes are constructed by this tool.
"""

import os
import traceback

import nuke


TITLE = "Switch EXR / MOV"


def _ayon():
    try:
        import ayon_api
        from ayon_core.pipeline import get_current_project_name
        from ayon_core.pipeline import load
        from ayon_nuke.api.pipeline import parse_container
    except ImportError as error:
        raise RuntimeError(
            "AYON is not available. Launch Nuke through AYON to use this tool."
        ) from error
    return ayon_api, load, parse_container, get_current_project_name


def _extension(representation):
    """Use the published extension, not the representation's display name."""
    extension = representation.get("context", {}).get("ext")
    if extension:
        return str(extension).lower().lstrip(".")
    extensions = {
        os.path.splitext(item.get("path", ""))[1].lower().lstrip(".")
        for item in representation.get("files", [])
    } - {""}
    return next(iter(extensions)) if len(extensions) == 1 else ""


def find_counterparts(read_node):
    """Return source context and every opposite-format sibling from AYON."""
    api, load, parse_container, current_project = _ayon()
    container = parse_container(read_node)
    if not container or not container.get("representation"):
        raise RuntimeError(
            "This Read has no AYON representation metadata. "
            "Load the published asset through AYON first."
        )
    project = container.get("project_name") or current_project()
    if not project:
        raise RuntimeError("AYON could not determine the asset's project.")
    context = load.get_representation_context(project, container["representation"])
    source = context["representation"]
    extension = os.path.splitext(read_node["file"].value())[1].lower().lstrip(".")
    if extension not in {"mov", "exr"}:
        raise RuntimeError("Select a Read containing an EXR sequence or MOV file.")
    if _extension(source) != extension:
        raise RuntimeError(
            "The Read's file format differs from its AYON metadata. "
            "Reload the correct representation through AYON first."
        )
    target = "exr" if extension == "mov" else "mov"
    siblings = api.get_representations(project, version_ids={source["versionId"]})
    candidates = sorted(
        (item for item in siblings if _extension(item) == target),
        key=lambda item: (item["name"].lower(), item["id"]),
    )
    if not candidates:
        raise RuntimeError(
            "No {} representation is published on this product version."
            .format(target.upper())
        )
    return context, candidates


def _choose(context, candidates):
    """One dialog; always require a deliberate choice when ambiguous."""
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets

    parent = QtWidgets.QApplication.activeWindow()
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(TITLE)
    dialog.setMinimumWidth(480)
    layout = QtWidgets.QVBoxLayout(dialog)
    version = context["version"]["version"]
    version_label = "hero" if version < 0 else "v{:03d}".format(version)
    label = QtWidgets.QLabel("{} / {} / {}".format(
        context["folder"]["path"], context["product"]["name"], version_label
    ))
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(QtWidgets.QLabel("Representation to load:"))
    representations = QtWidgets.QComboBox()
    if len(candidates) > 1:
        representations.addItem("Choose a representation…", None)
    for item in candidates:
        representations.addItem("{} ({})".format(
            item["name"], _extension(item).upper()
        ), item["id"])
        index = representations.count() - 1
        # Paths help distinguish similar output names; these are display only.
        path = item.get("files", [{}])[0].get("path", "") if item.get("files") else ""
        representations.setItemData(index, path, 3)  # Qt.ToolTipRole
    layout.addWidget(representations)
    explanation = QtWidgets.QLabel(
        "Replace preserves the selected Read's name, position and connections.\n"
        "Load alongside keeps the selected Read and loads a separate node."
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)
    buttons = QtWidgets.QHBoxLayout()
    layout.addLayout(buttons)
    result = []

    def accept(replace):
        result.append((representations.currentData(), replace))
        dialog.accept()

    replace_button = QtWidgets.QPushButton("Replace selected Read")
    alongside_button = QtWidgets.QPushButton("Load alongside")
    cancel_button = QtWidgets.QPushButton("Cancel")
    replace_button.clicked.connect(lambda: accept(True))
    alongside_button.clicked.connect(lambda: accept(False))
    cancel_button.clicked.connect(dialog.reject)
    for button in (replace_button, alongside_button, cancel_button):
        buttons.addWidget(button)

    def update_buttons(*args):
        enabled = representations.currentData() is not None
        replace_button.setEnabled(enabled)
        alongside_button.setEnabled(enabled)

    representations.currentIndexChanged.connect(update_buttons)
    update_buttons()
    execute = getattr(dialog, "exec", None) or dialog.exec_
    execute()
    return result[0] if result else None


def _connections(nodes):
    return [(node, index, node.input(index))
            for node in nodes for index in range(node.inputs())]


def _restore_connections(connections):
    for node, index, upstream in connections:
        if node.input(index) != upstream:
            node.setInput(index, upstream)


def load_counterpart(read_node, context, representation, replace):
    """Import with AYON, validate, then optionally replace the source Read.

    The caller must enter the source node's parent group. Existing retime
    nodes remain downstream; do not create a second retime chain on loading.
    """
    _, load, parse_container, _ = _ayon()
    if representation["versionId"] != context["representation"]["versionId"]:
        raise RuntimeError("The target must belong to the source published version.")
    target_context = dict(context, representation=representation)
    loaders = [plugin for plugin in load.discover_loader_plugins()
               if plugin.__name__ == "LoadClip" and getattr(plugin, "enabled", True)
               and load.is_compatible_loader(plugin, target_context)]
    if len(loaders) != 1:
        raise RuntimeError(
            "No unique compatible AYON Load Clip loader is available for {}. "
            "Check this project's AYON Nuke loader settings."
            .format(representation["name"])
        )
    before = list(nuke.allNodes())
    connections = _connections(before)
    selection = [node for node in before if node.isSelected()]
    old_name = read_node.name()
    old_position = read_node.xpos(), read_node.ypos()
    for node in selection:
        node.setSelected(False)
    new_read = None
    try:
        # This entry point takes an explicit project context, including assets
        # loaded from a library project rather than the current work project.
        load.load_with_repre_context(
            loaders[0], target_context,
            options={"add_retime": False, "node_type": "Read",
                     "start_at_workfile": "start at" in read_node["frame_mode"].value()},
        )
        created = [node for node in nuke.allNodes() if node not in before]
        if len(created) != 1 or created[0].Class() != "Read":
            raise RuntimeError("AYON did not load a single Read node; replacement was cancelled.")
        new_read = created[0]
        container = parse_container(new_read)
        if not container or container.get("representation") != representation["id"]:
            raise RuntimeError("AYON did not attach the expected representation metadata.")
        if not new_read["file"].value():
            raise RuntimeError("AYON returned a Read without a file path.")
        # Defend against loader callbacks inserting the new Read in the graph.
        _restore_connections(connections)
        new_read.setXYpos(old_position[0] + (0 if replace else 160), old_position[1])
        if replace:
            for node, index, upstream in connections:
                if upstream == read_node:
                    node.setInput(index, new_read)
    except Exception:
        _restore_connections(connections)
        for node in reversed(nuke.allNodes()):
            if node not in before:
                nuke.delete(node)
        for node in before:
            node.setSelected(node in selection)
        raise

    # Commit only after loading, metadata validation and rewiring succeeded.
    if replace:
        nuke.delete(read_node)
        new_read.setName(old_name)
    for node in nuke.allNodes():
        node.setSelected(node == new_read)
    return new_read


def show_dialog():
    """QTools menu entry point."""
    selected = nuke.selectedNodes()
    if len(selected) != 1 or selected[0].Class() != "Read":
        nuke.message("Select exactly one AYON-loaded EXR or MOV Read node.")
        return
    read_node = selected[0]
    try:
        context, candidates = find_counterparts(read_node)
        choice = _choose(context, candidates)
        if choice is None:
            return
        representation_id, replace = choice
        representation = next(item for item in candidates if item["id"] == representation_id)
        parent_path = read_node.fullName().rpartition(".")[0]
        parent = nuke.toNode(parent_path) if parent_path else nuke.root()
        with parent:
            with nuke.Undo():
                nuke.Undo.name(TITLE)
                load_counterpart(read_node, context, representation, replace)
    except Exception as error:
        nuke.tprint(traceback.format_exc())
        nuke.message("{}:\n\n{}".format(TITLE, error))
