# Postage Stamp and Dot Connector for Foundry Nuke
#
# Behaviour
# =========
#
# NORMAL NODE SELECTED
# --------------------
# Creates a new PostageStamp:
#   - Connected to the selected node
#   - Input pipe hidden
#   - Label: To NodeName
#
# If the selected source is a labelled Dot:
#   - Label: To Dot Label
#
#
# NOTHING SELECTED
# ----------------
# Opens a searchable menu containing:
#   - Viewer
#   - Every labelled Dot
#   - Read nodes, when enabled in the persistent menu options
#
# After choosing a source, creates a new PostageStamp connected to it, or a
# named Dot for a Read when that persistent option is enabled.
#
#
# DOTS OR POSTAGESTAMPS SELECTED
# -----------------------------
# If every selected node is either a Dot or PostageStamp:
#   - Opens the same Viewer / labelled-Dot menu
#   - Connects every selected node to the chosen source
#   - Updates every selected node label to: To Source
#   - Hides the input pipe on selected PostageStamps
#
# Selected target nodes are excluded from the source menu to avoid
# connecting a node to itself.
#
#
# Save as:
#
#     postage_stamp_creator.py
#
# Then call:
#
#     import postage_stamp_creator
#     postage_stamp_creator.create_or_retarget_postage_stamp()
#
# To reload while developing:
#
#     import importlib
#     import postage_stamp_creator
#     importlib.reload(postage_stamp_creator)
#     postage_stamp_creator.create_or_retarget_postage_stamp()


import os
import re

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


SUPPORTED_TARGET_CLASSES = {
    "Dot",
    "PostageStamp",
}

SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "PostageStampCreator"
SETTING_HIDE_TO = "hide_to_dots"
SETTING_SHOW_ONLY_FROM = "show_only_from_dots_v2"
SETTING_SHOW = "show_sources"
SETTING_CREATE_DOT = "create_dot_for_read"
SETTING_FIX_DOT_NAME = "fix_dot_name"
FROM_LABEL_WRAP_LENGTH = 20
READ_DOT_SEARCH_DEPTH = 6
READ_DOT_COLLISION_PADDING = 20
READ_DOT_MAX_UPWARD_SHIFT = 4000
_source_dialog = None


def _clean_text(value):
    """Return trimmed, single-line text."""
    if value is None:
        return ""

    return " ".join(str(value).split())


def _from_label(name):
    """Format a Dot source label, wrapping long names after From."""
    name = _clean_text(name)
    separator = "\n" if len(name) > FROM_LABEL_WRAP_LENGTH else " "
    return "From{}{}".format(separator, name)


def _settings():
    """Return the persistent settings for this tool."""
    return QtCore.QSettings(
        SETTINGS_ORGANISATION,
        SETTINGS_APPLICATION
    )


def _setting_bool(key, default):
    """Return a persistent boolean setting."""
    value = _settings().value(key, default)

    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}

    return bool(value)


def _read_frame_name(node):
    """Return the filename stem without its frame-number token."""
    if node is None or "file" not in node.knobs():
        return ""

    file_path = str(node["file"].value() or "")
    filename = os.path.basename(file_path.replace("\\", "/"))
    stem, _extension = os.path.splitext(filename)

    return re.sub(
        r"[\W_]*(?:#+|%0?\d*d|\$F\d*)$",
        "",
        stem
    )


def _read_display_text(node):
    """Return the source-menu display text for a Read node."""
    node_name = node.name()

    if re.fullmatch(r"Read\d*", node_name):
        return _read_frame_name(node) or node_name

    return node_name


def _upstream_read(node):
    """Return a Read reached through an input chain of Dots."""
    visited = set()
    current = node

    while current is not None and current not in visited:
        visited.add(current)

        if current.Class() == "Read":
            return current

        if current.Class() != "Dot":
            return None

        try:
            current = current.input(0)
        except Exception:
            return None

    return None


def _node_display_text(node):
    """
    Return the source text used in labels.

    Labelled Dots use their visible label.
    All other nodes use their node name.
    """
    if node is None:
        return ""

    if node.Class() == "Dot" and "label" in node.knobs():
        dot_label = _clean_text(node["label"].value())

        # Avoid repeatedly producing labels such as:
        # To To Source
        if dot_label.lower().startswith("to "):
            dot_label = dot_label[3:].strip()
        elif dot_label.lower().startswith("from "):
            dot_label = dot_label[5:].strip()

        if dot_label:
            return dot_label

    return node.name()


def _connection_label(source):
    """Build the final label for a target node."""
    return "To {}".format(_node_display_text(source))


def _normalised_label(value):
    """Return label text normalized for matching."""
    return _clean_text(value).lower()


def _node_has_no_input(node):
    """Return True when input 0 is disconnected."""
    try:
        return node.input(0) is None
    except Exception:
        return False


def _target_matches_source_label(target, source):
    """Return True when target is labelled as a connector to source."""
    if "label" not in target.knobs():
        return False

    return (
        _normalised_label(target["label"].value())
        == _normalised_label(_connection_label(source))
    )


def _target_source_text(target):
    """Return source text from a target label such as "To CAMERA"."""
    if "label" not in target.knobs():
        return ""

    label = _clean_text(target["label"].value())

    if not label.lower().startswith("to "):
        return ""

    return label[3:].strip()


def _source_dot_matching_text(source_text, excluded_nodes=None):
    """Return a labelled Dot matching source_text."""
    source_text = _normalised_label(source_text)

    if not source_text:
        return None

    for dot in _labelled_dots(excluded_nodes=excluded_nodes):
        if _normalised_label(_node_display_text(dot)) == source_text:
            return dot

    return None


def _deselect_all():
    """Deselect every currently selected node."""
    for node in nuke.selectedNodes():
        try:
            node.setSelected(False)
        except Exception:
            pass


def _all_selected_are_retargetable(selected_nodes):
    """
    Return True when one or more nodes are selected and every selected node
    is either a Dot or PostageStamp.
    """
    return bool(selected_nodes) and all(
        node.Class() in SUPPORTED_TARGET_CLASSES
        for node in selected_nodes
    )


def _active_viewer_source():
    """
    Return the node connected to the active input of the active Viewer.
    """
    try:
        active_viewer = nuke.activeViewer()
    except Exception:
        return None

    if active_viewer is None:
        return None

    try:
        viewer_node = active_viewer.node()
        active_input = active_viewer.activeInput()
    except Exception:
        return None

    if viewer_node is None:
        return None

    try:
        return viewer_node.input(active_input)
    except Exception:
        return None


def _labelled_dots(excluded_nodes=None):
    """
    Return every labelled Dot except nodes included in excluded_nodes.
    """
    excluded_nodes = set(excluded_nodes or [])
    dots = []

    for node in nuke.allNodes("Dot"):
        if node in excluded_nodes:
            continue

        if "label" not in node.knobs():
            continue

        label = _clean_text(node["label"].value())

        if not label:
            continue

        dots.append(node)

    return sorted(
        dots,
        key=lambda node: (
            _clean_text(node["label"].value()).lower(),
            node.name().lower(),
        )
    )


def _read_nodes(excluded_nodes=None):
    """Return every Read node except nodes included in excluded_nodes."""
    excluded_nodes = set(excluded_nodes or [])

    return sorted(
        (
            node
            for node in nuke.allNodes("Read")
            if node not in excluded_nodes
        ),
        key=lambda node: (
            _read_display_text(node).lower(),
            node.name().lower(),
        )
    )


def _direct_dependents(node):
    """Return nodes whose inputs are directly connected to node."""
    dependents = []

    for candidate in nuke.allNodes():
        try:
            input_count = candidate.inputs()
        except Exception:
            continue

        for input_index in range(input_count):
            try:
                if candidate.input(input_index) is node:
                    dependents.append(candidate)
                    break
            except Exception:
                continue

    return sorted(
        dependents,
        key=lambda candidate: candidate.name().lower()
    )


def _connected_input_count(node):
    """Return the number of currently connected inputs on node."""
    count = 0

    try:
        input_count = node.inputs()
    except Exception:
        return 0

    for input_index in range(input_count):
        try:
            if node.input(input_index) is not None:
                count += 1
        except Exception:
            continue

    return count


def _outgoing_connections(node):
    """Return every node input directly connected to node."""
    connections = []

    for dependent in nuke.allNodes():
        try:
            input_count = dependent.inputs()
        except Exception:
            continue

        for input_index in range(input_count):
            try:
                if dependent.input(input_index) is node:
                    connections.append((dependent, input_index))
            except Exception:
                continue

    return connections


def _rectangles_overlap(first, second, padding=0):
    """Return True when two Node Graph rectangles overlap."""
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second

    return not (
        first_x + first_width + padding <= second_x
        or second_x + second_width + padding <= first_x
        or first_y + first_height + padding <= second_y
        or second_y + second_height + padding <= first_y
    )


def _placement_is_clear(rectangle, ignored_nodes):
    """Return True when rectangle does not overlap another graph node."""
    ignored_nodes = set(ignored_nodes)

    for node in nuke.allNodes():
        if node in ignored_nodes or node.Class() == "BackdropNode":
            continue

        node_rectangle = (
            node.xpos(),
            node.ypos(),
            node.screenWidth(),
            node.screenHeight(),
        )

        if _rectangles_overlap(
            rectangle,
            node_rectangle,
            READ_DOT_COLLISION_PADDING
        ):
            return False

    return True


def _read_dot_upward_shift(source, dot, target_x, target_y):
    """Return an upward shift that clears both the Read and new Dot."""
    dot_rectangle = (
        target_x,
        target_y,
        dot.screenWidth(),
        dot.screenHeight(),
    )
    ignored_nodes = {source, dot}

    if _placement_is_clear(dot_rectangle, ignored_nodes):
        return 0

    for shift in range(
        READ_DOT_COLLISION_PADDING,
        READ_DOT_MAX_UPWARD_SHIFT + READ_DOT_COLLISION_PADDING,
        READ_DOT_COLLISION_PADDING
    ):
        shifted_dot_rectangle = (
            target_x,
            target_y - shift,
            dot.screenWidth(),
            dot.screenHeight(),
        )
        shifted_source_rectangle = (
            source.xpos(),
            source.ypos() - shift,
            source.screenWidth(),
            source.screenHeight(),
        )

        if (
            _placement_is_clear(shifted_dot_rectangle, ignored_nodes)
            and _placement_is_clear(shifted_source_rectangle, ignored_nodes)
        ):
            return shift

    return 0


def _nearby_from_dot(read_node):
    """
    Find the nearest downstream From Dot on a simple Read branch.

    Traversal is limited and stops at nodes that combine multiple inputs.
    """
    pending = [(read_node, 0)]
    visited = {read_node}

    while pending:
        current, depth = pending.pop(0)

        if depth >= READ_DOT_SEARCH_DEPTH:
            continue

        for dependent in _direct_dependents(current):
            if dependent in visited:
                continue

            visited.add(dependent)
            next_depth = depth + 1

            if dependent.Class() == "Dot":
                label = (
                    _clean_text(dependent["label"].value())
                    if "label" in dependent.knobs()
                    else ""
                )

                if label.lower().startswith("from "):
                    return dependent

                if label:
                    continue

            if dependent.Class() in {"Viewer", "PostageStamp"}:
                continue

            if _connected_input_count(dependent) > 1:
                continue

            pending.append((dependent, next_depth))

    return None

def _set_target_label(target, source):
    """Update the target label and hide its input connection."""
    if "label" in target.knobs():
        target["label"].setValue(
            _connection_label(source)
        )

    if "hide_input" in target.knobs():
        target["hide_input"].setValue(True)

def _configure_postage_stamp(stamp, source):
    """Apply PostageStamp-specific settings."""
    if "hide_input" in stamp.knobs():
        stamp["hide_input"].setValue(True)

    _set_target_label(stamp, source)


def _create_postage_stamp(source, target_position=None, frame_new=True):
    """
    Create a PostageStamp using Nuke's native node placement.

    The initial position is saved before connecting the source and restored
    afterwards because Nuke may reposition a connected node near its input.
    """
    if source is None:
        nuke.message("No valid source node was found.")
        return None

    _deselect_all()

    stamp = nuke.createNode(
        "PostageStamp",
        inpanel=False
    )

    if not stamp.canSetInput(0, source):
        nuke.delete(stamp)
        stamp = nuke.createNode(
            "Dot",
            inpanel=False
        )

    if target_position is None:
        target_x = stamp.xpos()
        target_y = stamp.ypos()
    else:
        target_x = int(target_position[0] - stamp.screenWidth() / 2)
        target_y = int(target_position[1] - stamp.screenHeight() / 2)

    try:
        stamp.setInput(0, source)
    except Exception as error:
        try:
            nuke.delete(stamp)
        except Exception:
            pass

        nuke.message(
            "The PostageStamp could not be connected.\n\n{}".format(
                error
            )
        )
        return None

    _configure_postage_stamp(stamp, source)

    # Restore the position after connecting the source.
    stamp.setXYpos(target_x, target_y)
    stamp.setSelected(True)

    if frame_new:
        nuke.zoomToFitSelected()

    return stamp


def _disconnected_targets_matching_source(source, excluded_nodes=None):
    """
    Return disconnected Dot/PostageStamp nodes labelled as connectors to source.
    """
    if source is None:
        return []

    excluded_nodes = set(excluded_nodes or [])
    targets = []

    for node_class in sorted(SUPPORTED_TARGET_CLASSES):
        for node in nuke.allNodes(node_class):
            if node is source or node in excluded_nodes:
                continue

            if not _node_has_no_input(node):
                continue

            if not _target_matches_source_label(node, source):
                continue

            targets.append(node)

    return sorted(
        targets,
        key=lambda node: (
            node.ypos(),
            node.xpos(),
            node.name().lower(),
        )
    )


def _reconnect_matching_disconnected_targets(source, excluded_nodes=None):
    """
    Reconnect disconnected targets whose labels still point to source.

    Returns the number of successfully reconnected nodes.
    """
    targets = _disconnected_targets_matching_source(
        source,
        excluded_nodes=excluded_nodes
    )

    if not targets:
        return 0

    return _retarget_nodes(
        targets=targets,
        source=source
    )


def _ask_to_reconnect_targets(source, targets):
    """Ask whether matching disconnected targets should be reconnected."""
    if not targets:
        return False

    count = len(targets)
    plural = "s" if count != 1 else ""

    return nuke.ask(
        "Found {count} disconnected connector{plural} labelled {label}.\n\n"
        "Reconnect instead of creating a new PostageStamp?".format(
            count=count,
            plural=plural,
            label=_connection_label(source)
        )
    )


def _reconnect_source_dot_targets_if_confirmed(source, excluded_nodes=None):
    """Reconnect targets matching source only when the user confirms."""
    targets = _disconnected_targets_matching_source(
        source,
        excluded_nodes=excluded_nodes
    )

    if not _ask_to_reconnect_targets(source, targets):
        return 0

    return _retarget_nodes(
        targets=targets,
        source=source
    )


def _reconnect_selected_disconnected_targets(targets):
    """Reconnect selected disconnected targets based on their existing labels."""
    successful = 0

    for target in targets:
        if target.Class() not in SUPPORTED_TARGET_CLASSES:
            continue

        if not _node_has_no_input(target):
            continue

        source = _source_dot_matching_text(
            _target_source_text(target),
            excluded_nodes=targets
        )

        if source is None:
            continue

        successful += _retarget_nodes(
            targets=[target],
            source=source
        )

    return successful


def _retarget_nodes(targets, source):
    """
    Connect every selected Dot/PostageStamp to source and update its label.

    Returns the number of successfully updated nodes.
    """
    if not targets:
        return 0

    if source is None:
        nuke.message("No valid source node was found.")
        return 0

    successful_targets = []
    failed_targets = []

    for target in targets:
        if target is source:
            failed_targets.append(
                "{}: cannot connect a node to itself".format(
                    target.name()
                )
            )
            continue

        if target.Class() not in SUPPORTED_TARGET_CLASSES:
            failed_targets.append(
                "{}: unsupported node class {}".format(
                    target.name(),
                    target.Class()
                )
            )
            continue

        try:
            target.setInput(0, source)
        except Exception as error:
            failed_targets.append(
                "{}: {}".format(
                    target.name(),
                    error
                )
            )
            continue

        _set_target_label(target, source)


        if "hide_input" in target.knobs():
            target["hide_input"].setValue(True)

        successful_targets.append(target)

    _deselect_all()

    for target in successful_targets:
        try:
            target.setSelected(True)
        except Exception:
            pass

    if failed_targets:
        message = (
            "{} node(s) updated successfully.\n\n"
            "The following node(s) could not be updated:\n\n{}"
        ).format(
            len(successful_targets),
            "\n".join(failed_targets)
        )

        nuke.message(message)

    return len(successful_targets)


class DotNameDialog(QtWidgets.QDialog):
    """Ask for the label of a Dot created from a Read node."""

    def __init__(self, source, parent=None):
        super(DotNameDialog, self).__init__(parent)

        self._source = source
        self.setWindowTitle("Enter Dot name")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Enter Dot name:"))

        name_layout = QtWidgets.QHBoxLayout()
        self.name_field = QtWidgets.QLineEdit(
            _read_display_text(source)
        )
        self.name_field.setMinimumWidth(560)
        self.frame_name_button = QtWidgets.QPushButton(
            "Use frame name"
        )
        self.frame_name_button.setToolTip(
            "Replace the Dot name with the Read filename without its frame token."
        )
        name_layout.addWidget(self.name_field)
        name_layout.addWidget(self.frame_name_button)
        layout.addLayout(name_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setToolTip(
            "Create the Dot using the entered name."
        )
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setToolTip(
            "Cancel without creating the Dot or PostageStamp."
        )
        layout.addWidget(buttons)

        self.frame_name_button.clicked.connect(
            self._use_frame_name
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.name_field.selectAll()
        self.name_field.setFocus()

    def _use_frame_name(self):
        """Replace the proposed label with the Read filename stem."""
        self.name_field.setText(
            _read_frame_name(self._source)
        )

    def dot_name(self):
        """Return the entered Dot label."""
        return _clean_text(self.name_field.text())


def _create_named_read_dot(source):
    """Ask for a label, then create a visible-input Dot from source."""
    dialog = DotNameDialog(
        source,
        parent=_nuke_main_window()
    )

    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return None

    dot_name = dialog.dot_name()
    outgoing_connections = _outgoing_connections(source)
    original_source_y = source.ypos()
    _deselect_all()
    dot = nuke.createNode("Dot", inpanel=False)

    if "label" in dot.knobs():
        dot["label"].setValue(_from_label(dot_name))

    source_height = source.screenHeight()
    target_x = source.xpos() + int(
        (source.screenWidth() - dot.screenWidth()) / 2
    )
    target_y = source.ypos() + source_height + int(
        source_height * 1.25
    )
    upward_shift = _read_dot_upward_shift(
        source,
        dot,
        target_x,
        target_y
    )

    if upward_shift:
        source.setYpos(source.ypos() - upward_shift)
        target_y -= upward_shift

    rewired_connections = []

    try:
        dot.setInput(0, source)

        for dependent, input_index in outgoing_connections:
            if dependent is dot:
                continue

            if dependent.input(input_index) is source:
                dependent.setInput(input_index, dot)
                rewired_connections.append((dependent, input_index))
    except Exception as error:
        source.setYpos(original_source_y)

        for dependent, input_index in rewired_connections:
            try:
                dependent.setInput(input_index, source)
            except Exception:
                pass

        try:
            nuke.delete(dot)
        except Exception:
            pass

        nuke.message(
            "The Dot could not be connected.\n\n{}".format(error)
        )
        return None

    if "hide_input" in dot.knobs():
        dot["hide_input"].setValue(False)

    dot.setXYpos(target_x, target_y)
    dot.setSelected(True)

    return dot


class SourceSelectionDialog(QtWidgets.QDialog):
    """
    Searchable source-selection window.

    Displays:
      - Viewer
      - Labelled Dots and/or Read nodes, according to user settings

    Target nodes can be excluded to prevent self-connections.
    """

    def __init__(
        self,
        excluded_nodes=None,
        on_source_selected=None,
        parent=None
    ):
        super(SourceSelectionDialog, self).__init__(parent)

        self._excluded_nodes = set(excluded_nodes or [])
        self._on_source_selected = on_source_selected
        self._entries = []
        self._settings = _settings()
        self._graph_click_position = None
        self._show_was_used = False

        self.setWindowTitle("Select Source")
        self.setWindowModality(QtCore.Qt.NonModal)
        self.resize(460, 520)

        self._build_ui()
        self._populate()

        application = QtWidgets.QApplication.instance()

        if application is not None:
            application.installEventFilter(self)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        title_layout = QtWidgets.QHBoxLayout()
        self.cleanup_button = QtWidgets.QPushButton()
        cleanup_button_size = self.cleanup_button.sizeHint().height()
        self.cleanup_button.setFixedSize(
            cleanup_button_size,
            cleanup_button_size
        )
        broom_icon_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "icons",
                "connector_cleanup.svg"
            )
        )
        self.cleanup_button.setIcon(QtGui.QIcon(broom_icon_path))
        self.cleanup_button.setIconSize(
            QtCore.QSize(
                cleanup_button_size - 8,
                cleanup_button_size - 8
            )
        )
        self.cleanup_button.setToolTip(
            "Close this source picker and open Connector Label clean up."
        )
        self.cleanup_button.setAccessibleName("Open connector cleanup")
        title_layout.addWidget(self.cleanup_button)
        title_layout.addWidget(QtWidgets.QLabel("Select the source:"))
        title_layout.addStretch()
        title_layout.addWidget(QtWidgets.QLabel("Show:"))

        self.hide_to_checkbox = QtWidgets.QCheckBox(
            'Hide "To" Dots'
        )
        self.hide_to_checkbox.setChecked(
            _setting_bool(SETTING_HIDE_TO, True)
        )
        self.hide_to_checkbox.setToolTip(
            'Hide Dot sources whose labels begin with "To ".'
        )

        self.show_only_from_checkbox = QtWidgets.QCheckBox(
            'Show only "From" Dots'
        )
        self.show_only_from_checkbox.setChecked(
            _setting_bool(SETTING_SHOW_ONLY_FROM, True)
        )
        self.show_only_from_checkbox.setToolTip(
            'Show only Dot sources whose labels begin with "From ".'
        )

        self.show_combo = QtWidgets.QComboBox()
        self.show_combo.addItems(["Dots", "Read", "All"])
        saved_show = str(
            self._settings.value(SETTING_SHOW, "Dots")
        )
        show_index = self.show_combo.findText(saved_show)
        self.show_combo.setCurrentIndex(
            show_index if show_index >= 0 else 0
        )
        self.show_combo.setToolTip(
            "Choose whether the source list contains Dots, Reads, or both."
        )
        title_layout.addWidget(self.show_combo)

        self.create_dot_checkbox = QtWidgets.QCheckBox(
            "Create dot"
        )
        self.create_dot_checkbox.setChecked(
            _setting_bool(SETTING_CREATE_DOT, True)
        )
        self.create_dot_checkbox.setToolTip(
            "Create a named Dot from a chosen Read before creating its PostageStamp."
        )

        self.fix_dot_name_checkbox = QtWidgets.QCheckBox(
            "Fix Dot name"
        )
        self.fix_dot_name_checkbox.setChecked(
            _setting_bool(SETTING_FIX_DOT_NAME, True)
        )
        self.fix_dot_name_checkbox.setToolTip(
            'Normalize the chosen Dot label to "From NAME" before connecting.'
        )
        self._update_option_visibility()

        layout.addLayout(title_layout)

        self.search_field = QtWidgets.QLineEdit()
        self.search_field.setPlaceholderText(
            "Search Viewer, labelled Dots, or Reads..."
        )
        self.search_field.setClearButtonEnabled(True)
        self.search_field.installEventFilter(self)
        layout.addWidget(self.search_field)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget)

        button_layout = QtWidgets.QHBoxLayout()
        self.show_node_button = QtWidgets.QPushButton("Show")
        self.show_node_button.setEnabled(False)
        self.show_node_button.setToolTip(
            "Select and frame the highlighted source in the Node Graph."
        )
        button_layout.addWidget(self.show_node_button)
        button_layout.addWidget(self.hide_to_checkbox)
        button_layout.addWidget(self.show_only_from_checkbox)
        button_layout.addWidget(self.create_dot_checkbox)
        button_layout.addWidget(self.fix_dot_name_checkbox)
        button_layout.addStretch()

        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setToolTip(
            "Close this window without creating or connecting anything."
        )
        self.create_button = QtWidgets.QPushButton("Connect")
        self.create_button.setToolTip(
            "Use the highlighted source to create or connect the requested nodes."
        )

        self.create_button.setDefault(True)
        self.create_button.setEnabled(False)

        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.create_button)

        layout.addLayout(button_layout)

        self.search_field.textChanged.connect(
            self._filter_items
        )

        self.list_widget.itemSelectionChanged.connect(
            self._update_create_button
        )

        self.list_widget.itemDoubleClicked.connect(
            self._accept_selected_item
        )

        self.cancel_button.clicked.connect(
            self.reject
        )

        self.create_button.clicked.connect(
            self._connect_selected_source
        )

        self.show_node_button.clicked.connect(
            self._show_selected_node
        )

        self.cleanup_button.clicked.connect(
            self._open_connector_cleanup
        )

        self.hide_to_checkbox.toggled.connect(
            self._save_settings_and_repopulate
        )

        self.show_only_from_checkbox.toggled.connect(
            self._save_settings_and_repopulate
        )

        self.show_combo.currentTextChanged.connect(
            self._save_settings_and_repopulate
        )
        self.show_combo.currentTextChanged.connect(
            self._update_option_visibility
        )

        self.create_dot_checkbox.toggled.connect(
            self._save_settings
        )

        self.fix_dot_name_checkbox.toggled.connect(
            self._save_settings
        )

    def _save_settings(self, _value=None):
        """Save the current source-menu options."""
        self._settings.setValue(
            SETTING_HIDE_TO,
            self.hide_to_checkbox.isChecked()
        )
        self._settings.setValue(
            SETTING_SHOW_ONLY_FROM,
            self.show_only_from_checkbox.isChecked()
        )
        self._settings.setValue(
            SETTING_SHOW,
            self.show_combo.currentText()
        )
        self._settings.setValue(
            SETTING_CREATE_DOT,
            self.create_dot_checkbox.isChecked()
        )
        self._settings.setValue(
            SETTING_FIX_DOT_NAME,
            self.fix_dot_name_checkbox.isChecked()
        )
        self._settings.sync()

    def _update_option_visibility(self, _value=None):
        """Show only options relevant to the selected source types."""
        show_sources = self.show_combo.currentText()
        self.create_dot_checkbox.setVisible(
            show_sources in {"Read", "All"}
        )
        self.fix_dot_name_checkbox.setVisible(
            show_sources in {"Dots", "All"}
        )

    def _save_settings_and_repopulate(self, _value=None):
        """Save source filters and rebuild the visible entries."""
        self._save_settings()
        self._populate()

    def eventFilter(self, watched, event):
        """Handle search keys and remember Node Graph click positions."""
        if event.type() == QtCore.QEvent.MouseButtonPress:
            self._record_graph_click(watched, event)

        if (
            watched is self.search_field
            and event.type() == QtCore.QEvent.KeyPress
        ):
            if event.key() == QtCore.Qt.Key_Up:
                self._move_selection(-1)
                return True

            if event.key() == QtCore.Qt.Key_Down:
                self._move_selection(1)
                return True

        return super(SourceSelectionDialog, self).eventFilter(
            watched,
            event
        )

    def _record_graph_click(self, watched, event):
        """Record a left-click position in Nuke's Node Graph."""
        if event.button() != QtCore.Qt.LeftButton:
            return

        graph_widget = watched

        while graph_widget is not None:
            try:
                class_name = graph_widget.metaObject().className()
                object_name = graph_widget.objectName()
            except Exception:
                class_name = ""
                object_name = ""

            identity = "{} {}".format(
                class_name,
                object_name
            ).lower()

            if "dag" in identity or "nodegraph" in identity:
                break

            graph_widget = graph_widget.parentWidget()

        if graph_widget is None:
            return

        try:
            global_position = event.globalPos()
            local_position = graph_widget.mapFromGlobal(global_position)
            graph_center = nuke.center()
            graph_zoom = nuke.zoom()

            self._graph_click_position = (
                graph_center[0]
                + (local_position.x() - graph_widget.width() / 2)
                / graph_zoom,
                graph_center[1]
                + (local_position.y() - graph_widget.height() / 2)
                / graph_zoom,
            )
        except Exception:
            self._graph_click_position = None

    def _move_selection(self, direction):
        """Move to the next visible, enabled source entry."""
        available_rows = []

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)

            if (
                not item.isHidden()
                and item.flags() & QtCore.Qt.ItemIsEnabled
                and item.data(QtCore.Qt.UserRole) is not None
            ):
                available_rows.append(row)

        if not available_rows:
            return

        current_row = self.list_widget.currentRow()

        try:
            current_index = available_rows.index(current_row)
        except ValueError:
            current_index = -1 if direction > 0 else 0

        next_row = available_rows[
            (current_index + direction) % len(available_rows)
        ]
        self.list_widget.setCurrentRow(next_row)
        self.list_widget.scrollToItem(
            self.list_widget.item(next_row)
        )

    def _show_selected_node(self):
        """Select and frame the menu source in the Node Graph."""
        source = self.selected_source()

        if source is None:
            return

        _deselect_all()
        source.setSelected(True)
        nuke.zoomToFitSelected()
        self._show_was_used = True

        self.search_field.setFocus()

    def _open_connector_cleanup(self):
        """Close this picker, then open the modeless cleanup window."""
        from qtools import connector_label_cleanup

        self.reject()
        QtCore.QTimer.singleShot(
            0,
            lambda: connector_label_cleanup.clean_up_connector_labels(
                on_close=self._reopen
            )
        )

    def _accept_selected_item(self, _item):
        """Connect to a valid item when it is double-clicked."""
        self._connect_selected_source()

    def _connect_selected_source(self):
        """Run the requested connection action for the selected source."""
        source = self.selected_source()

        if source is None:
            return

        if (
            self.fix_dot_name_checkbox.isChecked()
            and source.Class() == "Dot"
            and "label" in source.knobs()
        ):
            current_label = _clean_text(source["label"].value())

            if current_label and not current_label.lower().startswith(
                "from "
            ):
                source["label"].setValue(
                    _from_label(_node_display_text(source))
                )

        self.accept()

        if self._on_source_selected is not None:
            self._on_source_selected(
                source,
                self._graph_click_position,
                self._show_was_used
            )

    def _reopen(self):
        """Reopen this source-selection request after connector cleanup."""
        _choose_source(
            excluded_nodes=self._excluded_nodes,
            on_source_selected=self._on_source_selected
        )

    def _add_entry(
        self,
        visible_text,
        source_node,
        description=""
    ):
        """Add one selectable source entry."""
        item = QtWidgets.QListWidgetItem()

        if description:
            item.setText(
                "{}\n{}".format(
                    visible_text,
                    description
                )
            )
        else:
            item.setText(visible_text)

        item.setData(
            QtCore.Qt.UserRole,
            len(self._entries)
        )

        self._entries.append({
            "search_text": "{} {}".format(
                visible_text,
                description
            ).lower(),
            "node": source_node,
        })

        self.list_widget.addItem(item)

    def _add_disabled_entry(self, text):
        """Add a disabled informational list item."""
        item = QtWidgets.QListWidgetItem(text)

        item.setFlags(
            item.flags() & ~QtCore.Qt.ItemIsEnabled
        )

        self.list_widget.addItem(item)

    def _populate(self):
        """Populate Viewer and labelled-Dot entries."""
        self.list_widget.clear()
        self._entries = []

        viewer_source = _active_viewer_source()

        if (
            viewer_source is not None
            and viewer_source not in self._excluded_nodes
        ):
            self._add_entry(
                "Viewer",
                viewer_source,
                "Currently viewing: {}".format(
                    _node_display_text(viewer_source)
                )
            )
        elif viewer_source in self._excluded_nodes:
            self._add_disabled_entry(
                "Viewer\n"
                "The viewed node is one of the selected targets"
            )
        else:
            self._add_disabled_entry(
                "Viewer\n"
                "No source is connected to the active Viewer"
            )

        show_sources = self.show_combo.currentText()

        if show_sources in {"Dots", "All"}:
            dot_entries = []

            for dot in _labelled_dots(
                excluded_nodes=self._excluded_nodes
            ):
                dot_label = _clean_text(
                    dot["label"].value()
                )

                is_from_label = dot_label.lower().startswith("from ")

                if (
                    self.show_only_from_checkbox.isChecked()
                    and not is_from_label
                ):
                    continue

                if (
                    self.hide_to_checkbox.isChecked()
                    and dot_label.lower().startswith("to ")
                ):
                    continue

                if self.show_only_from_checkbox.isChecked():
                    dot_label = dot_label[5:].strip()

                dot_entries.append((dot, dot_label))

            label_counts = {}

            for _dot, dot_label in dot_entries:
                label_counts[dot_label.lower()] = (
                    label_counts.get(dot_label.lower(), 0) + 1
                )

            label_indexes = {}

            for dot, dot_label in dot_entries:
                label_key = dot_label.lower()
                duplicate_index = label_indexes.get(label_key, 0)
                label_indexes[label_key] = duplicate_index + 1
                display_label = dot_label

                if label_counts[label_key] > 1:
                    frame_name = _read_frame_name(
                        _upstream_read(dot)
                    )

                    if frame_name or duplicate_index:
                        suffix = frame_name or str(duplicate_index)
                        display_label = "{} ({})".format(
                            dot_label,
                            suffix
                        )

                self._add_entry(
                    display_label,
                    dot
                )

        if show_sources in {"Read", "All"}:
            for read in _read_nodes(
                excluded_nodes=self._excluded_nodes
            ):
                display_text = _read_display_text(read)
                frame_name = _read_frame_name(read)

                if frame_name and frame_name != display_text:
                    display_text = "{} ({})".format(
                        display_text,
                        frame_name
                    )

                self._add_entry(
                    display_text,
                    read
                )

        self._select_first_available_item()
        self.search_field.setFocus()

    def _select_first_available_item(self):
        """Select the first visible, enabled source entry."""
        self.list_widget.clearSelection()

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)

            if item.isHidden():
                continue

            if not (
                item.flags() & QtCore.Qt.ItemIsEnabled
            ):
                continue

            if item.data(QtCore.Qt.UserRole) is None:
                continue

            self.list_widget.setCurrentItem(item)
            return

    def _filter_items(self, text):
        """Filter Viewer and labelled-Dot entries."""
        search_text = _clean_text(text).lower()

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            entry_index = item.data(QtCore.Qt.UserRole)

            if entry_index is None:
                item.setHidden(bool(search_text))
                continue

            entry = self._entries[int(entry_index)]

            item.setHidden(
                search_text not in entry["search_text"]
            )

        current_item = self.list_widget.currentItem()

        selection_is_valid = (
            current_item is not None
            and not current_item.isHidden()
            and bool(
                current_item.flags()
                & QtCore.Qt.ItemIsEnabled
            )
            and current_item.data(
                QtCore.Qt.UserRole
            ) is not None
        )

        if not selection_is_valid:
            self._select_first_available_item()

        self._update_create_button()

    def _update_create_button(self):
        """Enable Select only when a valid source is selected."""
        item = self.list_widget.currentItem()

        valid = (
            item is not None
            and not item.isHidden()
            and bool(
                item.flags()
                & QtCore.Qt.ItemIsEnabled
            )
            and item.data(
                QtCore.Qt.UserRole
            ) is not None
        )

        self.create_button.setEnabled(valid)
        self.show_node_button.setEnabled(valid)

    def selected_source(self):
        """Return the source represented by the selected list item."""
        item = self.list_widget.currentItem()

        if item is None:
            return None

        entry_index = item.data(
            QtCore.Qt.UserRole
        )

        if entry_index is None:
            return None

        try:
            return self._entries[
                int(entry_index)
            ]["node"]
        except (
            IndexError,
            TypeError,
            ValueError
        ):
            return None


def _nuke_main_window():
    """Find Nuke's main Qt window."""
    application = QtWidgets.QApplication.instance()

    if application is None:
        return None

    for widget in application.topLevelWidgets():
        try:
            class_name = widget.metaObject().className()
        except Exception:
            class_name = ""

        if (
            widget.inherits("QMainWindow")
            and class_name
            == "Foundry::UI::DockMainWindow"
        ):
            return widget

    for widget in application.topLevelWidgets():
        try:
            if widget.inherits("QMainWindow"):
                return widget
        except Exception:
            continue

    return None


def _choose_source(excluded_nodes=None, on_source_selected=None):
    """
    Open the modeless source-selection window.
    """
    global _source_dialog

    dialog = SourceSelectionDialog(
        excluded_nodes=excluded_nodes,
        on_source_selected=on_source_selected,
        parent=_nuke_main_window()
    )
    _source_dialog = dialog

    dialog.finished.connect(
        lambda _result: _release_source_dialog(dialog)
    )
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

    return dialog


def _release_source_dialog(dialog):
    """Release the retained source dialog after it closes."""
    global _source_dialog

    application = QtWidgets.QApplication.instance()

    if application is not None:
        application.removeEventFilter(dialog)

    if _source_dialog is dialog:
        _source_dialog = None


def _create_from_chosen_source(
    source,
    target_position=None,
    frame_new=False
):
    """Create the requested connector from a menu-selected source."""
    reconnected = _reconnect_matching_disconnected_targets(source)

    if reconnected:
        return reconnected

    if (
        source.Class() == "Read"
        and _setting_bool(SETTING_CREATE_DOT, True)
    ):
        dot = _nearby_from_dot(source)

        if dot is None:
            dot = _create_named_read_dot(source)

        if dot is None:
            return None

        return _create_postage_stamp(
            dot,
            target_position=target_position,
            frame_new=frame_new
        )

    return _create_postage_stamp(
        source,
        target_position=target_position,
        frame_new=frame_new
    )


def create_or_retarget_postage_stamp():
    """
    Main entry point.

    Behaviour:

    1. One or more Dots/PostageStamps selected:
       Open the source selector and reconnect all selected targets.

    2. A normal node selected:
       Create a new PostageStamp connected to the selected node.

    3. Nothing selected:
       Open the source selector and create a new PostageStamp.
    """
    selected_nodes = list(nuke.selectedNodes())

    reconnected = _reconnect_selected_disconnected_targets(selected_nodes)

    if reconnected:
        return reconnected

    if (
        len(selected_nodes) == 1
        and selected_nodes[0].Class() == "Dot"
        and not (
            _node_has_no_input(selected_nodes[0])
            and not _clean_text(selected_nodes[0]["label"].value())
        )
    ):
        reconnected = _reconnect_source_dot_targets_if_confirmed(
            selected_nodes[0],
            excluded_nodes=selected_nodes
        )

        if reconnected:
            return reconnected

        return _create_postage_stamp(selected_nodes[0])

    if _all_selected_are_retargetable(selected_nodes):
        return _choose_source(
            excluded_nodes=selected_nodes,
            on_source_selected=lambda source, _position, _shown: _retarget_nodes(
                targets=selected_nodes,
                source=source
            )
        )

    if selected_nodes:
        try:
            source = nuke.selectedNode()
        except Exception:
            source = selected_nodes[-1]

        reconnected = _reconnect_matching_disconnected_targets(
            source,
            excluded_nodes=selected_nodes
        )

        if reconnected:
            return reconnected

        return _create_postage_stamp(source)

    return _choose_source(
        on_source_selected=_create_from_chosen_source
    )


# Backwards-compatible function name.
def create_postage_stamp():
    return create_or_retarget_postage_stamp()


# Run directly when executed in Nuke's Script Editor, but not when imported by
# the QTools menu.
if __name__ == "__main__":
    create_or_retarget_postage_stamp()
