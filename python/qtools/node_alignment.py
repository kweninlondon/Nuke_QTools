"""Interactive, reversible node-graph alignment tools for Foundry Nuke."""

from __future__ import division

import contextlib

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "NodeAlignment"
IGNORED_CLASSES = {"BackdropNode", "Viewer"}
_dialog = None


def _settings():
    return QtCore.QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def _setting_bool(key, default):
    value = _settings().value(key, default)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _node_size(node):
    """Return displayed DAG size, tolerating incomplete node geometry."""
    try:
        return max(1, int(node.screenWidth())), max(1, int(node.screenHeight()))
    except Exception:
        return 80, 20


def _node_key(node):
    try:
        return node.fullName()
    except Exception:
        return node.name()


def _capture(nodes):
    snapshot = {}
    for node in nodes:
        width, height = _node_size(node)
        snapshot[_node_key(node)] = {
            "node": node,
            "x": float(node.xpos()),
            "y": float(node.ypos()),
            "w": float(width),
            "h": float(height),
        }
    return snapshot


def _copy_positions(snapshot):
    return {key: (item["x"], item["y"]) for key, item in snapshot.items()}


def _bounds(keys, snapshot, positions):
    left = min(positions[key][0] for key in keys)
    top = min(positions[key][1] for key in keys)
    right = max(positions[key][0] + snapshot[key]["w"] for key in keys)
    bottom = max(positions[key][1] + snapshot[key]["h"] for key in keys)
    return left, top, right, bottom


def _round_positions(positions):
    return {
        key: (int(round(value[0])), int(round(value[1])))
        for key, value in positions.items()
    }


def _selected_nodes():
    return [
        node for node in nuke.selectedNodes()
        if node.Class() not in IGNORED_CLASSES
    ]


def _input_nodes(node):
    result = []
    try:
        count = int(node.inputs())
    except Exception:
        count = 0
    for index in range(count):
        try:
            input_node = node.input(index)
        except Exception:
            input_node = None
        if input_node is not None:
            result.append((index, input_node))
    return result


def connected_components(snapshot):
    """Return selected components without traversing outside the selection."""
    keys = set(snapshot)
    neighbours = {key: set() for key in keys}
    for key, item in snapshot.items():
        for _index, input_node in _input_nodes(item["node"]):
            input_key = _node_key(input_node)
            if input_key in keys:
                neighbours[key].add(input_key)
                neighbours[input_key].add(key)

    components = []
    unseen = set(keys)
    while unseen:
        start = unseen.pop()
        component = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            additions = neighbours[current] & unseen
            unseen.difference_update(additions)
            component.update(additions)
            stack.extend(additions)
        components.append(component)
    return components


def align_positions(snapshot, mode):
    """Align selected node edges or centres from the original snapshot."""
    positions = _copy_positions(snapshot)
    keys = list(snapshot)
    if len(keys) < 2:
        return _round_positions(positions)
    left, top, right, bottom = _bounds(keys, snapshot, positions)
    centre_x = (left + right) / 2.0
    centre_y = (top + bottom) / 2.0
    for key, item in snapshot.items():
        x, y = positions[key]
        if mode == "left":
            x = left
        elif mode == "hcentre":
            x = centre_x - item["w"] / 2.0
        elif mode == "right":
            x = right - item["w"]
        elif mode == "top":
            y = top
        elif mode == "vcentre":
            y = centre_y - item["h"] / 2.0
        elif mode == "bottom":
            y = bottom - item["h"]
        positions[key] = (x, y)
    return _round_positions(positions)


def space_positions(snapshot, axis, spacing, even_gaps=False):
    """Space nodes along an axis while preserving the outer anchors."""
    positions = _copy_positions(snapshot)
    keys = list(snapshot)
    if len(keys) < 2:
        return _round_positions(positions)
    dimension = "w" if axis == "x" else "h"
    coordinate = 0 if axis == "x" else 1
    ordered = sorted(
        keys,
        key=lambda key: positions[key][coordinate]
        + snapshot[key][dimension] / 2.0,
    )
    first = ordered[0]
    last = ordered[-1]
    first_start = positions[first][coordinate]
    last_end = positions[last][coordinate] + snapshot[last][dimension]

    if even_gaps:
        total_size = sum(snapshot[key][dimension] for key in ordered)
        available = last_end - first_start - total_size
        gap = max(float(spacing), available / float(len(ordered) - 1))
        cursor = first_start
        for key in ordered:
            value = list(positions[key])
            value[coordinate] = cursor
            positions[key] = tuple(value)
            cursor += snapshot[key][dimension] + gap
    else:
        first_centre = first_start + snapshot[first][dimension] / 2.0
        last_centre = last_end - snapshot[last][dimension] / 2.0
        required = float(spacing) * (len(ordered) - 1)
        extent = max(last_centre - first_centre, required)
        step = extent / float(len(ordered) - 1)
        for index, key in enumerate(ordered):
            value = list(positions[key])
            value[coordinate] = (
                first_centre + index * step - snapshot[key][dimension] / 2.0
            )
            positions[key] = tuple(value)
    return _round_positions(positions)


def _primary_chains(snapshot):
    """Group nodes connected through input zero into main-flow chains."""
    keys = set(snapshot)
    adjacency = {key: set() for key in keys}
    for key, item in snapshot.items():
        for input_index, input_node in _input_nodes(item["node"]):
            input_key = _node_key(input_node)
            if input_index == 0 and input_key in keys:
                adjacency[key].add(input_key)
                adjacency[input_key].add(key)
                break
    chains = []
    unseen = set(keys)
    while unseen:
        start = unseen.pop()
        chain = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            additions = adjacency[current] & unseen
            unseen.difference_update(additions)
            chain.update(additions)
            stack.extend(additions)
        chains.append(chain)
    return chains


def straighten_positions(snapshot, flow, spacing):
    """Straighten primary connections and enforce minimum flow spacing."""
    positions = _copy_positions(snapshot)
    cross_axis = 0 if flow == "vertical" else 1
    flow_axis = 1 - cross_axis
    cross_size = "w" if cross_axis == 0 else "h"
    flow_size = "h" if flow_axis == 1 else "w"
    for chain in _primary_chains(snapshot):
        centres = sorted(
            positions[key][cross_axis] + snapshot[key][cross_size] / 2.0
            for key in chain
        )
        anchor = centres[len(centres) // 2]
        ordered = sorted(
            chain,
            key=lambda key: positions[key][flow_axis]
            + snapshot[key][flow_size] / 2.0,
        )
        previous_end = None
        for key in ordered:
            value = list(positions[key])
            value[cross_axis] = anchor - snapshot[key][cross_size] / 2.0
            if previous_end is not None:
                value[flow_axis] = max(
                    value[flow_axis], previous_end + float(spacing)
                )
            previous_end = value[flow_axis] + snapshot[key][flow_size]
            positions[key] = tuple(value)
    return _round_positions(positions)


def distribute_tree_positions(snapshot, axis, spacing, even_gaps=False):
    """Distribute connected components as rigid tree units."""
    positions = _copy_positions(snapshot)
    components = connected_components(snapshot)
    if len(components) < 2:
        return _round_positions(positions)
    coordinate = 0 if axis == "x" else 1
    records = []
    for component in components:
        bounds = _bounds(component, snapshot, positions)
        start = bounds[coordinate]
        end = bounds[coordinate + 2]
        records.append((component, start, end, (start + end) / 2.0))
    records.sort(key=lambda record: record[3])
    first_start = records[0][1]
    last_end = records[-1][2]

    if even_gaps:
        total_size = sum(record[2] - record[1] for record in records)
        available = last_end - first_start - total_size
        gap = max(float(spacing), available / float(len(records) - 1))
        targets = []
        cursor = first_start
        for record in records:
            targets.append(cursor)
            cursor += record[2] - record[1] + gap
    else:
        first_centre = records[0][3]
        last_centre = records[-1][3]
        minimum = float(spacing) * (len(records) - 1)
        step = max(last_centre - first_centre, minimum) / float(
            len(records) - 1
        )
        targets = [
            first_centre + index * step - (record[2] - record[1]) / 2.0
            for index, record in enumerate(records)
        ]
    for record, target in zip(records, targets):
        shift = target - record[1]
        for key in record[0]:
            value = list(positions[key])
            value[coordinate] += shift
            positions[key] = tuple(value)
    return _round_positions(positions)


def tidy_tree_positions(snapshot, flow, spacing, even_gaps=False):
    """Straighten and independently space every selected tree."""
    straightened = straighten_positions(snapshot, flow, spacing)
    working = {}
    for key, item in snapshot.items():
        working[key] = dict(item)
        working[key]["x"], working[key]["y"] = straightened[key]
    result = dict(straightened)
    axis = "y" if flow == "vertical" else "x"
    for component in connected_components(snapshot):
        component_snapshot = {key: working[key] for key in component}
        result.update(
            space_positions(component_snapshot, axis, spacing, even_gaps)
        )
    return _round_positions(result)


def _guide_coordinates(node, axis):
    width, height = _node_size(node)
    if axis == "x":
        start, size = float(node.xpos()), float(width)
    else:
        start, size = float(node.ypos()), float(height)
    return start, start + size / 2.0, start + size


def snap_positions(snapshot, snap_x, snap_y, tolerance):
    """Snap each selected component rigidly to unselected guide lines."""
    positions = _copy_positions(snapshot)
    selected_keys = set(snapshot)
    external = [
        node for node in nuke.allNodes()
        if _node_key(node) not in selected_keys
        and node.Class() not in IGNORED_CLASSES
    ]
    components = connected_components(snapshot)
    for axis, enabled in (("x", snap_x), ("y", snap_y)):
        if not enabled:
            continue
        coordinate = 0 if axis == "x" else 1
        guides = [
            guide for node in external for guide in _guide_coordinates(node, axis)
        ]
        if not guides:
            continue
        for component in components:
            bounds = _bounds(component, snapshot, positions)
            candidates = (
                bounds[coordinate],
                (bounds[coordinate] + bounds[coordinate + 2]) / 2.0,
                bounds[coordinate + 2],
            )
            deltas = [guide - value for guide in guides for value in candidates]
            shift = min(deltas, key=lambda delta: abs(delta))
            if abs(shift) > float(tolerance):
                continue
            for key in component:
                value = list(positions[key])
                value[coordinate] += shift
                positions[key] = tuple(value)
    return _round_positions(positions)


@contextlib.contextmanager
def _undo_suppressed():
    disabled = False
    try:
        nuke.Undo.disable()
        disabled = True
    except Exception:
        pass
    try:
        yield
    finally:
        if disabled:
            try:
                nuke.Undo.enable()
            except Exception:
                pass


def _set_positions(snapshot, positions, suppress_undo=True):
    manager = _undo_suppressed() if suppress_undo else contextlib.nullcontext()
    with manager:
        for key, position in positions.items():
            item = snapshot.get(key)
            if item is None:
                continue
            try:
                item["node"].setXYpos(int(position[0]), int(position[1]))
            except Exception:
                pass


class NodeAlignmentDialog(QtWidgets.QDialog):
    """Modeless live-preview panel for selected nodes."""

    def __init__(self, parent=None):
        super(NodeAlignmentDialog, self).__init__(parent)
        self.setWindowTitle("Q Align Nodes")
        self.setMinimumWidth(390)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self._snapshot = {}
        self._positions = {}
        self._operation = None
        self._dirty = False
        self._closing_action = False
        self._build_ui()
        self._restore_settings()
        self.refresh_selection(initial=True)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        selection_row = QtWidgets.QHBoxLayout()
        self.selection_label = QtWidgets.QLabel()
        self.refresh_button = QtWidgets.QPushButton("Refresh selection")
        selection_row.addWidget(self.selection_label, 1)
        selection_row.addWidget(self.refresh_button)
        root.addLayout(selection_row)

        align_group = QtWidgets.QGroupBox("Align selection")
        align_layout = QtWidgets.QGridLayout(align_group)
        buttons = [
            ("Left", "left", 0, 0), ("Centre X", "hcentre", 0, 1),
            ("Right", "right", 0, 2), ("Top", "top", 1, 0),
            ("Centre Y", "vcentre", 1, 1), ("Bottom", "bottom", 1, 2),
        ]
        self.align_buttons = []
        for label, mode, row, column in buttons:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=mode: self.set_operation(
                    "align", value
                )
            )
            align_layout.addWidget(button, row, column)
            self.align_buttons.append(button)
        root.addWidget(align_group)

        tree_group = QtWidgets.QGroupBox("Tree layout")
        tree_layout = QtWidgets.QGridLayout(tree_group)
        self.flow_combo = QtWidgets.QComboBox()
        self.flow_combo.addItem("Vertical flow", "vertical")
        self.flow_combo.addItem("Horizontal flow", "horizontal")
        self.straighten_button = QtWidgets.QPushButton("Straighten connections")
        self.tidy_button = QtWidgets.QPushButton("Tidy selected trees")
        self.tree_x_button = QtWidgets.QPushButton("Distribute trees X")
        self.tree_y_button = QtWidgets.QPushButton("Distribute trees Y")
        tree_layout.addWidget(self.flow_combo, 0, 0, 1, 2)
        tree_layout.addWidget(self.straighten_button, 1, 0, 1, 2)
        tree_layout.addWidget(self.tidy_button, 2, 0, 1, 2)
        tree_layout.addWidget(self.tree_x_button, 3, 0)
        tree_layout.addWidget(self.tree_y_button, 3, 1)
        root.addWidget(tree_group)

        spacing_group = QtWidgets.QGroupBox("Spacing")
        spacing_layout = QtWidgets.QGridLayout(spacing_group)
        self.spacing_spin = QtWidgets.QSpinBox()
        self.spacing_spin.setRange(0, 1000)
        self.spacing_spin.setSuffix(" px")
        self.spacing_spin.setSingleStep(10)
        self.spacing_mode = QtWidgets.QComboBox()
        self.spacing_mode.addItem("Even visible gaps", True)
        self.spacing_mode.addItem("Even centres", False)
        self.space_x_button = QtWidgets.QPushButton("Space nodes X")
        self.space_y_button = QtWidgets.QPushButton("Space nodes Y")
        spacing_layout.addWidget(QtWidgets.QLabel("Minimum:"), 0, 0)
        spacing_layout.addWidget(self.spacing_spin, 0, 1)
        spacing_layout.addWidget(self.spacing_mode, 1, 0, 1, 2)
        spacing_layout.addWidget(self.space_x_button, 2, 0)
        spacing_layout.addWidget(self.space_y_button, 2, 1)
        root.addWidget(spacing_group)

        snap_group = QtWidgets.QGroupBox("Global snap to unselected nodes")
        snap_layout = QtWidgets.QGridLayout(snap_group)
        self.snap_x = QtWidgets.QCheckBox("X lines")
        self.snap_y = QtWidgets.QCheckBox("Y lines")
        self.snap_tolerance = QtWidgets.QSpinBox()
        self.snap_tolerance.setRange(1, 250)
        self.snap_tolerance.setSuffix(" px")
        self.snap_button = QtWidgets.QPushButton("Snap trees as units")
        snap_layout.addWidget(self.snap_x, 0, 0)
        snap_layout.addWidget(self.snap_y, 0, 1)
        snap_layout.addWidget(QtWidgets.QLabel("Tolerance:"), 1, 0)
        snap_layout.addWidget(self.snap_tolerance, 1, 1)
        snap_layout.addWidget(self.snap_button, 2, 0, 1, 2)
        root.addWidget(snap_group)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setDefault(True)
        footer.addWidget(self.reset_button)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.apply_button)
        root.addLayout(footer)

        self.refresh_button.clicked.connect(self.refresh_selection)
        self.straighten_button.clicked.connect(
            lambda: self.set_operation("straighten", self.flow_combo.currentData())
        )
        self.tidy_button.clicked.connect(
            lambda: self.set_operation("tidy", self.flow_combo.currentData())
        )
        self.tree_x_button.clicked.connect(
            lambda: self.set_operation("trees", "x")
        )
        self.tree_y_button.clicked.connect(
            lambda: self.set_operation("trees", "y")
        )
        self.space_x_button.clicked.connect(
            lambda: self.set_operation("space", "x")
        )
        self.space_y_button.clicked.connect(
            lambda: self.set_operation("space", "y")
        )
        self.snap_button.clicked.connect(lambda: self.set_operation("snap", None))
        self.reset_button.clicked.connect(self.reset_preview)
        self.cancel_button.clicked.connect(self.cancel_changes)
        self.apply_button.clicked.connect(self.apply_changes)
        self.spacing_spin.valueChanged.connect(self._controls_changed)
        self.spacing_mode.currentIndexChanged.connect(self._controls_changed)
        self.flow_combo.currentIndexChanged.connect(self._flow_changed)
        self.snap_x.toggled.connect(self._controls_changed)
        self.snap_y.toggled.connect(self._controls_changed)
        self.snap_tolerance.valueChanged.connect(self._controls_changed)

    def _restore_settings(self):
        settings = _settings()
        self.spacing_spin.setValue(int(settings.value("spacing", 50)))
        index = self.spacing_mode.findData(_setting_bool("even_gaps", True))
        self.spacing_mode.setCurrentIndex(max(0, index))
        index = self.flow_combo.findData(str(settings.value("flow", "vertical")))
        self.flow_combo.setCurrentIndex(max(0, index))
        self.snap_x.setChecked(_setting_bool("snap_x", True))
        self.snap_y.setChecked(_setting_bool("snap_y", True))
        self.snap_tolerance.setValue(int(settings.value("snap_tolerance", 25)))

    def _save_settings(self):
        settings = _settings()
        settings.setValue("spacing", self.spacing_spin.value())
        settings.setValue("even_gaps", bool(self.spacing_mode.currentData()))
        settings.setValue("flow", self.flow_combo.currentData())
        settings.setValue("snap_x", self.snap_x.isChecked())
        settings.setValue("snap_y", self.snap_y.isChecked())
        settings.setValue("snap_tolerance", self.snap_tolerance.value())

    def refresh_selection(self, _checked=False, initial=False):
        if self._dirty and not initial:
            answer = QtWidgets.QMessageBox.question(
                self, "Refresh selection",
                "Discard the current preview and use the new selection?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        if self._snapshot:
            _set_positions(self._snapshot, _copy_positions(self._snapshot))
        nodes = _selected_nodes()
        self._snapshot = _capture(nodes)
        self._positions = _copy_positions(self._snapshot)
        self._operation = None
        self._dirty = False
        components = connected_components(self._snapshot) if self._snapshot else []
        self.selection_label.setText(
            "{} node{} · {} tree{}".format(
                len(nodes), "" if len(nodes) == 1 else "s",
                len(components), "" if len(components) == 1 else "s",
            )
        )
        self.status_label.setText(
            "Choose an operation to preview it in the Node Graph."
            if nodes else "Select nodes, then refresh the selection."
        )
        self._update_enabled_state()

    def _update_enabled_state(self):
        enough = len(self._snapshot) >= 2
        self.apply_button.setEnabled(self._dirty)
        self.reset_button.setEnabled(self._dirty)
        for widget in self.align_buttons + [
            self.straighten_button, self.tidy_button,
            self.tree_x_button, self.tree_y_button,
            self.space_x_button, self.space_y_button,
        ]:
            widget.setEnabled(enough)
        self.snap_button.setEnabled(bool(self._snapshot))

    def set_operation(self, operation, argument):
        if self._snapshot:
            self._operation = (operation, argument)
            self._update_preview()

    def _controls_changed(self, *_args):
        if self._operation is not None:
            self._update_preview()

    def _flow_changed(self, *_args):
        if self._operation and self._operation[0] in {"straighten", "tidy"}:
            self._operation = (
                self._operation[0], self.flow_combo.currentData()
            )
            self._update_preview()

    def _update_preview(self):
        operation, argument = self._operation
        spacing = self.spacing_spin.value()
        even_gaps = bool(self.spacing_mode.currentData())
        if operation == "align":
            positions = align_positions(self._snapshot, argument)
            description = "Aligned selection: {}".format(argument)
        elif operation == "space":
            positions = space_positions(self._snapshot, argument, spacing, even_gaps)
            description = "Spaced nodes on {}".format(argument.upper())
        elif operation == "straighten":
            positions = straighten_positions(self._snapshot, argument, spacing)
            description = "Straightened {} primary connections".format(argument)
        elif operation == "tidy":
            positions = tidy_tree_positions(
                self._snapshot, argument, spacing, even_gaps
            )
            description = "Tidied each selected {} tree".format(argument)
        elif operation == "trees":
            positions = distribute_tree_positions(
                self._snapshot, argument, spacing, even_gaps
            )
            description = "Distributed trees on {}".format(argument.upper())
        elif operation == "snap":
            if not self.snap_x.isChecked() and not self.snap_y.isChecked():
                self.status_label.setText("Enable X lines, Y lines, or both.")
                return
            positions = snap_positions(
                self._snapshot, self.snap_x.isChecked(), self.snap_y.isChecked(),
                self.snap_tolerance.value(),
            )
            description = "Snapped trees to nearby global lines"
        else:
            return
        self._positions = positions
        _set_positions(self._snapshot, positions)
        originals = _round_positions(_copy_positions(self._snapshot))
        self._dirty = positions != originals
        moved = sum(1 for key in positions if positions[key] != originals[key])
        self.status_label.setText(
            "{} · {} node{} moved".format(
                description, moved, "" if moved == 1 else "s"
            )
        )
        self._update_enabled_state()

    def reset_preview(self):
        self._positions = _round_positions(_copy_positions(self._snapshot))
        _set_positions(self._snapshot, self._positions)
        self._operation = None
        self._dirty = False
        self.status_label.setText("Preview reset to the opening positions.")
        self._update_enabled_state()

    def apply_changes(self):
        if not self._snapshot or not self._dirty:
            return
        final_positions = dict(self._positions)
        _set_positions(self._snapshot, _round_positions(_copy_positions(self._snapshot)))
        try:
            nuke.Undo.begin("Q Align Nodes")
            _set_positions(self._snapshot, final_positions, suppress_undo=False)
        finally:
            try:
                nuke.Undo.end()
            except Exception:
                pass
        self._save_settings()
        self._snapshot = _capture(
            [item["node"] for item in self._snapshot.values()]
        )
        self._positions = _copy_positions(self._snapshot)
        self._operation = None
        self._dirty = False
        self.status_label.setText("Changes applied as one Nuke Undo step.")
        self._update_enabled_state()

    def cancel_changes(self):
        if self._snapshot:
            _set_positions(self._snapshot, _copy_positions(self._snapshot))
        self._closing_action = True
        self.reject()

    def closeEvent(self, event):
        if self._closing_action or not self._dirty:
            self._save_settings()
            event.accept()
            return
        message = QtWidgets.QMessageBox(self)
        message.setWindowTitle("Close Q Align Nodes")
        message.setText("Apply the previewed node positions before closing?")
        apply_button = message.addButton("Apply", QtWidgets.QMessageBox.AcceptRole)
        discard_button = message.addButton(
            "Discard", QtWidgets.QMessageBox.DestructiveRole
        )
        message.addButton("Keep editing", QtWidgets.QMessageBox.RejectRole)
        execute = getattr(message, "exec", None) or message.exec_
        execute()
        clicked = message.clickedButton()
        if clicked is apply_button:
            self.apply_changes()
            self._closing_action = True
            event.accept()
        elif clicked is discard_button:
            _set_positions(self._snapshot, _copy_positions(self._snapshot))
            self._closing_action = True
            event.accept()
        else:
            event.ignore()


def show_dialog():
    """Show or focus the retained modeless alignment dialog."""
    global _dialog
    if _dialog is not None:
        try:
            if not _dialog._dirty:
                _dialog.refresh_selection()
            _dialog.show()
            _dialog.raise_()
            _dialog.activateWindow()
            return _dialog
        except Exception:
            _dialog = None
    _dialog = NodeAlignmentDialog()
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _dialog.destroyed.connect(_clear_dialog_reference)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def _clear_dialog_reference(*_args):
    global _dialog
    _dialog = None
