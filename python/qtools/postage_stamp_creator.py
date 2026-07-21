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
#
# After choosing a source, creates a new PostageStamp connected to it.
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


import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


SUPPORTED_TARGET_CLASSES = {
    "Dot",
    "PostageStamp",
}


def _clean_text(value):
    """Return trimmed, single-line text."""
    if value is None:
        return ""

    return " ".join(str(value).split())


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


def _create_postage_stamp(source):
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

    target_x = stamp.xpos()
    target_y = stamp.ypos()

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


class SourceSelectionDialog(QtWidgets.QDialog):
    """
    Searchable source-selection window.

    Displays:
      - Viewer
      - Every labelled Dot

    Target nodes can be excluded to prevent self-connections.
    """

    def __init__(self, excluded_nodes=None, parent=None):
        super(SourceSelectionDialog, self).__init__(parent)

        self._excluded_nodes = set(excluded_nodes or [])
        self._entries = []

        self.setWindowTitle("Select Source")
        self.resize(460, 520)

        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel(
            "Select the source:"
        )
        layout.addWidget(title)

        self.search_field = QtWidgets.QLineEdit()
        self.search_field.setPlaceholderText(
            "Search Viewer or labelled Dots..."
        )
        self.search_field.setClearButtonEnabled(True)
        layout.addWidget(self.search_field)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.create_button = QtWidgets.QPushButton("Select")

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
            self.accept
        )

    def _accept_selected_item(self, _item):
        """Accept the dialog when a valid item is double-clicked."""
        if self.selected_source() is not None:
            self.accept()

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

        for dot in _labelled_dots(
            excluded_nodes=self._excluded_nodes
        ):
            dot_label = _clean_text(
                dot["label"].value()
            )

            self._add_entry(
                dot_label,
                dot
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


def _choose_source(excluded_nodes=None):
    """
    Open the source-selection window and return the chosen node.
    """
    dialog = SourceSelectionDialog(
        excluded_nodes=excluded_nodes,
        parent=_nuke_main_window()
    )

    result = dialog.exec()

    if result != QtWidgets.QDialog.Accepted:
        return None

    return dialog.selected_source()


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
        source = _choose_source(
            excluded_nodes=selected_nodes
        )

        if source is None:
            return None

        return _retarget_nodes(
            targets=selected_nodes,
            source=source
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

    source = _choose_source()

    if source is None:
        return None

    reconnected = _reconnect_matching_disconnected_targets(source)

    if reconnected:
        return reconnected

    return _create_postage_stamp(source)


# Backwards-compatible function name.
def create_postage_stamp():
    return create_or_retarget_postage_stamp()


# Run directly when executed in Nuke's Script Editor, but not when imported by
# the QTools menu.
if __name__ == "__main__":
    create_or_retarget_postage_stamp()
