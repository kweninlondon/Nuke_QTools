"""Load the opposite EXR/MOV representation using AYON's Nuke loader.

AYON imports are deliberately lazy: QTools also runs outside AYON sessions.
No filenames are rewritten and no Read nodes are constructed by this tool.
"""

import os
import traceback

import nuke


TITLE = "Switch EXR ↔ MOV"
_WINDOW = None


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


def find_product_representations(read_node):
    """Resolve the selected Read and all representations of its exact version."""
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
    siblings = list(api.get_representations(
        project, version_ids={source["versionId"]}
    ))
    return context, siblings


def counterpart_candidates(context, representations):
    target = "exr" if _extension(context["representation"]) == "mov" else "mov"
    return sorted(
        (item for item in representations if _extension(item) == target),
        key=lambda item: (item["name"].lower(), item["id"]),
    )


def find_counterparts(read_node):
    """Return source context and every opposite-format sibling from AYON."""
    context, siblings = find_product_representations(read_node)
    candidates = counterpart_candidates(context, siblings)
    if not candidates:
        target = "EXR" if _extension(context["representation"]) == "mov" else "MOV"
        raise RuntimeError(
            "No {} representation is published on this product version.".format(target)
        )
    return context, candidates


def scene_reads():
    """Include Reads in Groups regardless of which graph is currently open."""
    with nuke.root():
        return list(nuke.allNodes("Read", recurseGroups=True))


def loaded_formats(context, representations, nodes):
    """Report actual scene nodes for this exact project/version only."""
    _, _, parse_container, current_project = _ayon()
    formats = {item["id"]: _extension(item) for item in representations}
    formats[context["representation"]["id"]] = _extension(context["representation"])
    result = {"exr": [], "mov": []}
    for node in nodes:
        container = parse_container(node)
        if not container:
            continue
        project = container.get("project_name") or current_project()
        if project != context["project"]["name"]:
            continue
        extension = formats.get(container.get("representation"))
        actual_extension = os.path.splitext(node["file"].value())[1].lower().lstrip(".")
        if extension in result and actual_extension == extension:
            result[extension].append(node)
    return result


class BatchRow:
    """Persistent row state, separate from Qt so batch behavior can be tested."""

    def __init__(self, node):
        self.node = node
        self.context = None
        self.representations = []
        self.candidates = []
        self.target_id = None
        self.checked = False
        self.error = ""
        self.status = ""
        try:
            self.context, self.representations = find_product_representations(node)
            self._set_candidates()
            self.checked = bool(self.candidates)
        except Exception as error:
            self.error = str(error)

    def _set_candidates(self):
        self.candidates = counterpart_candidates(self.context, self.representations)
        self.target_id = self.candidates[0]["id"] if self.candidates else None
        if not self.candidates:
            self.error = "No opposite-format representation on this version."

    def apply(self, replace):
        if self.error:
            raise RuntimeError(self.error)
        target = next((item for item in self.candidates
                       if item["id"] == self.target_id), None)
        if target is None:
            raise RuntimeError("Choose a representation first.")
        _, _, parse_container, _ = _ayon()
        container = parse_container(self.node)
        if not container or container.get("representation") != self.context["representation"]["id"]:
            raise RuntimeError("The source Read changed. Reload the selection.")
        source_extension = os.path.splitext(self.node["file"].value())[1].lower().lstrip(".")
        if source_extension != _extension(self.context["representation"]):
            raise RuntimeError("The source file format changed. Reload the selection.")
        new_read = load_counterpart(self.node, self.context, target, replace)
        self.checked = False
        self.status = "{} {}".format("Replaced with" if replace else "Loaded", target["name"])
        if replace:
            self.node = new_read
            self.context = dict(self.context, representation=target)
            self._set_candidates()
        return new_read


def _connections(nodes):
    return [(node, index, node.input(index))
            for node in nodes for index in range(node.inputs())]


def _restore_connections(connections):
    for node, index, upstream in connections:
        if node.input(index) != upstream:
            node.setInput(index, upstream)


def _alongside_position(read_node, nodes, new_read=None):
    """Place above the source, leaving 60 pixels between node bounds."""
    def size(node):
        try:
            return max(node.screenWidth(), 80), max(node.screenHeight(), 60)
        except AttributeError:
            return 80, 60

    x = read_node.xpos()
    width, height = size(new_read if new_read is not None else read_node)
    y = read_node.ypos() - height - 60
    # Backdrops enclose nodes rather than occupying their usable space.
    obstacles = [node for node in nodes if node.Class() != "BackdropNode"]
    while True:
        collisions = []
        for node in obstacles:
            other_width, other_height = size(node)
            if (x < node.xpos() + other_width + 20
                    and x + width + 20 > node.xpos()
                    and y < node.ypos() + other_height + 60
                    and y + height + 60 > node.ypos()):
                collisions.append(node.ypos() - height - 60)
        if not collisions:
            return x, y
        y = min(collisions)


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
        position = old_position if replace else _alongside_position(read_node, before, new_read)
        new_read.setXYpos(*position)
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
    """Open a retained, modeless batch window for the selected Reads."""
    global _WINDOW
    reads = [node for node in nuke.selectedNodes() if node.Class() == "Read"]
    if not reads:
        nuke.message("Select one or more AYON-loaded EXR or MOV Read nodes.")
        return
    try:
        from .ayon_read_swap_ui import ReadSwapWindow
        if _WINDOW is not None:
            _WINDOW.close()
        _WINDOW = ReadSwapWindow(reads)
        _WINDOW.show()
        _WINDOW.raise_()
        _WINDOW.activateWindow()
    except Exception as error:
        nuke.tprint(traceback.format_exc())
        nuke.message("{}:\n\n{}".format(TITLE, error))
