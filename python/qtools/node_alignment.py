"""Preview and apply straight vertical or horizontal node chains."""

import contextlib

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


IGNORED_CLASSES = {"BackdropNode", "Viewer"}
_dialog = None


def _node_key(node):
    try:
        return node.fullName()
    except Exception:
        return node.name()


def _node_size(node):
    try:
        return max(1, node.screenWidth()), max(1, node.screenHeight())
    except Exception:
        return 80, 20


def _selected_nodes():
    return [
        node for node in nuke.selectedNodes()
        if node.Class() not in IGNORED_CLASSES
    ]


def capture_positions(nodes):
    """Capture immutable position and display-size data for selected nodes."""
    result = {}
    for node in nodes:
        width, height = _node_size(node)
        result[_node_key(node)] = {
            "node": node,
            "x": int(node.xpos()),
            "y": int(node.ypos()),
            "width": int(width),
            "height": int(height),
        }
    return result


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
            result.append(input_node)
    return result


def _directional_graph(snapshot, orientation):
    """Build adjacency and directed degrees for matching selected connections."""
    keys = set(snapshot)
    neighbours = {key: set() for key in keys}
    incoming = {key: 0 for key in keys}
    outgoing = {key: 0 for key in keys}
    for key, item in snapshot.items():
        for input_node in _input_nodes(item["node"]):
            input_key = _node_key(input_node)
            if input_key not in keys:
                continue
            input_item = snapshot[input_key]
            source_x = item["x"] + item["width"] / 2.0
            source_y = item["y"] + item["height"] / 2.0
            input_x = input_item["x"] + input_item["width"] / 2.0
            input_y = input_item["y"] + input_item["height"] / 2.0
            horizontal_distance = abs(source_x - input_x)
            vertical_distance = abs(source_y - input_y)
            edge_orientation = (
                "horizontal"
                if horizontal_distance > vertical_distance
                else "vertical"
            )
            if edge_orientation != orientation:
                continue
            neighbours[key].add(input_key)
            neighbours[input_key].add(key)
            incoming[key] += 1
            outgoing[input_key] += 1
    return neighbours, incoming, outgoing


def _graph_components(neighbours, allowed):
    """Return connected components restricted to an allowed key set."""
    components = []
    unseen = set(allowed)
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


def directional_chains(snapshot, orientation):
    """Group selected nodes using only connections matching an orientation."""
    neighbours, _incoming, _outgoing = _directional_graph(
        snapshot, orientation
    )
    connected = {key for key in snapshot if neighbours[key]}
    return _graph_components(neighbours, connected)


def movable_chain_sections(snapshot, orientation):
    """Return rigid chain sections, excluding shared branch/merge junctions."""
    neighbours, incoming, outgoing = _directional_graph(
        snapshot, orientation
    )
    connected = {key for key in snapshot if neighbours[key]}
    junctions = {
        key for key in connected
        if incoming[key] > 1 or outgoing[key] > 1
    }
    sections = _graph_components(neighbours, connected - junctions)
    return [section for section in sections if section]


def spacing_units(snapshot, orientation):
    """Return target chains plus consecutive perpendicular rigid blocks."""
    perpendicular = (
        "horizontal" if orientation == "vertical" else "vertical"
    )
    target_chains = directional_chains(snapshot, orientation)
    target_keys = set().union(*target_chains) if target_chains else set()
    candidates = [
        {"keys": set(section), "kind": "target"}
        for section in target_chains
    ]
    perpendicular_graph, _incoming, _outgoing = _directional_graph(
        snapshot, perpendicular
    )
    perpendicular_keys = {
        key for key in snapshot
        if perpendicular_graph[key] and key not in target_keys
    }
    candidates.extend(
        {"keys": set(section), "kind": "perpendicular"}
        for section in _graph_components(
            perpendicular_graph, perpendicular_keys
        )
    )

    axis = 0 if orientation == "vertical" else 1
    candidates.sort(
        key=lambda candidate: (
            _section_bounds(snapshot, candidate["keys"])[axis],
            _section_bounds(snapshot, candidate["keys"])[axis + 2],
        )
    )
    units = []
    for candidate in candidates:
        if (
            candidate["kind"] == "perpendicular"
            and units
            and units[-1]["kind"] == "perpendicular"
        ):
            units[-1]["keys"].update(candidate["keys"])
        else:
            units.append(candidate)
    return [unit["keys"] for unit in units]


def _snapshot_at_positions(snapshot, positions):
    result = {}
    for key, item in snapshot.items():
        result[key] = dict(item)
        result[key]["x"], result[key]["y"] = positions[key]
    return result


def _section_bounds(snapshot, section):
    left = min(snapshot[key]["x"] for key in section)
    top = min(snapshot[key]["y"] for key in section)
    right = max(
        snapshot[key]["x"] + snapshot[key]["width"] for key in section
    )
    bottom = max(
        snapshot[key]["y"] + snapshot[key]["height"] for key in section
    )
    return left, top, right, bottom


def spaced_chain_positions(snapshot, orientation, minimum_gap, anchor):
    """Space rigid parallel chain sections while preserving larger gaps."""
    result = original_positions(snapshot)
    sections = spacing_units(snapshot, orientation)
    if len(sections) < 2:
        return result

    axis = 0 if orientation == "vertical" else 1
    records = []
    for section in sections:
        bounds = _section_bounds(snapshot, section)
        start = bounds[axis]
        end = bounds[axis + 2]
        records.append({
            "keys": section,
            "start": float(start),
            "end": float(end),
            "size": float(end - start),
        })
    records.sort(key=lambda record: (record["start"], record["end"]))

    relative_starts = [0.0]
    for previous, current in zip(records, records[1:]):
        original_gap = current["start"] - previous["end"]
        preserved_gap = max(float(minimum_gap), original_gap)
        relative_starts.append(
            relative_starts[-1] + previous["size"] + preserved_gap
        )
    new_span = relative_starts[-1] + records[-1]["size"]
    original_start = records[0]["start"]
    original_end = records[-1]["end"]
    if anchor in {"left", "top"}:
        target_start = original_start
    elif anchor in {"right", "bottom"}:
        target_start = original_end - new_span
    elif anchor in {"center", "middle"}:
        target_start = (original_start + original_end - new_span) / 2.0
    else:
        raise ValueError("Unknown spacing anchor: {}".format(anchor))

    for record, relative_start in zip(records, relative_starts):
        shift = target_start + relative_start - record["start"]
        for key in record["keys"]:
            x, y = result[key]
            if axis == 0:
                x += shift
            else:
                y += shift
            result[key] = (int(round(x)), int(round(y)))
    return result


def straightened_positions(snapshot, orientation):
    """Align node centres to the median vertical or horizontal centre line."""
    result = {
        key: (item["x"], item["y"])
        for key, item in snapshot.items()
    }
    if len(snapshot) < 2:
        return result

    def median(values):
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2.0

    if orientation == "vertical":
        centres = sorted(
            item["x"] + item["width"] / 2.0
            for item in snapshot.values()
        )
        anchor = median(centres)
        for key, item in snapshot.items():
            result[key] = (
                int(round(anchor - item["width"] / 2.0)),
                item["y"],
            )
    elif orientation == "horizontal":
        centres = sorted(
            item["y"] + item["height"] / 2.0
            for item in snapshot.values()
        )
        anchor = median(centres)
        for key, item in snapshot.items():
            result[key] = (
                item["x"],
                int(round(anchor - item["height"] / 2.0)),
            )
    else:
        raise ValueError("Unknown chain orientation: {}".format(orientation))
    return result


def smart_straightened_positions(snapshot, orientations):
    """Straighten independent directional chains without collapsing branches."""
    result = original_positions(snapshot)
    for orientation in ("vertical", "horizontal"):
        if orientation not in orientations:
            continue
        for chain in directional_chains(snapshot, orientation):
            chain_snapshot = {key: snapshot[key] for key in chain}
            aligned = straightened_positions(chain_snapshot, orientation)
            for key in chain:
                if orientation == "vertical":
                    result[key] = (aligned[key][0], result[key][1])
                else:
                    result[key] = (result[key][0], aligned[key][1])
    return result


@contextlib.contextmanager
def _undo_suppressed():
    nuke.Undo.disable()
    try:
        yield
    finally:
        nuke.Undo.enable()


def set_positions(snapshot, positions, preview=True):
    manager = _undo_suppressed() if preview else contextlib.nullcontext()
    with manager:
        for key, position in positions.items():
            snapshot[key]["node"].setXYpos(*position)


def original_positions(snapshot):
    return {
        key: (item["x"], item["y"])
        for key, item in snapshot.items()
    }


def _nuke_main_window():
    """Find Nuke's main window so the tool stays above the Node Graph."""
    application = QtWidgets.QApplication.instance()
    active = application.activeWindow()
    while active is not None and active.parentWidget() is not None:
        active = active.parentWidget()
    if isinstance(active, QtWidgets.QMainWindow):
        return active
    for widget in application.topLevelWidgets():
        if isinstance(widget, QtWidgets.QMainWindow) and widget.isVisible():
            return widget
    return None


def _chain_icon(orientation, aligned, palette, size=58):
    """Draw an original icon so no external icon package is required."""
    ratio = QtWidgets.QApplication.instance().devicePixelRatio()
    pixmap = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    foreground = palette.color(QtGui.QPalette.ButtonText)
    guide = palette.color(QtGui.QPalette.Highlight)
    guide.setAlpha(230)
    pen = QtGui.QPen(guide, 3.0)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    if aligned:
        painter.setPen(pen)
        if orientation == "vertical":
            painter.drawLine(
                QtCore.QLineF(size / 2.0, 5, size / 2.0, size - 5)
            )
        else:
            painter.drawLine(
                QtCore.QLineF(5, size / 2.0, size - 5, size / 2.0)
            )

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(foreground)
    node_width = 26
    node_height = 10
    if orientation == "vertical":
        offsets = (0, 0, 0) if aligned else (-8, 7, -4)
        for index, offset in enumerate(offsets):
            x = size / 2.0 - node_width / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(
                    x, 8 + index * 17, node_width, node_height
                ),
                2,
                2,
            )
    else:
        offsets = (0, 0, 0) if aligned else (-8, 7, -4)
        horizontal_node_width = 17.5
        for index, offset in enumerate(offsets):
            y = size / 2.0 - node_height / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(
                    1 + index * 19.25,
                    y,
                    horizontal_node_width,
                    node_height,
                ),
                2,
                2,
            )
    painter.end()
    return QtGui.QIcon(pixmap)


def _between_icon(orientation, active, palette, size=58):
    """Draw three connected chains changing from irregular to regular gaps."""
    ratio = QtWidgets.QApplication.instance().devicePixelRatio()
    pixmap = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    foreground = palette.color(QtGui.QPalette.ButtonText)
    connector = (
        palette.color(QtGui.QPalette.Highlight)
        if active else palette.color(QtGui.QPalette.Mid)
    )
    connector.setAlpha(230 if active else 210)
    painter.setPen(QtGui.QPen(connector, 1.5))
    if orientation == "vertical":
        chain_positions = (7, 25, 43) if active else (5, 20, 45)
        for x in chain_positions:
            painter.drawLine(QtCore.QLineF(x + 4, 5, x + 4, 53))
    else:
        chain_positions = (7, 25, 43) if active else (5, 20, 45)
        for y in chain_positions:
            painter.drawLine(QtCore.QLineF(5, y + 4, 53, y + 4))

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(foreground)
    if orientation == "vertical":
        for x in chain_positions:
            for y in (3, 25, 47):
                painter.drawRoundedRect(QtCore.QRectF(x, y, 8, 7), 1.5, 1.5)
    else:
        for y in chain_positions:
            for x in (3, 25, 47):
                painter.drawRoundedRect(QtCore.QRectF(x, y, 7, 8), 1.5, 1.5)
    painter.end()
    return QtGui.QIcon(pixmap)


class StraightenChainDialog(QtWidgets.QDialog):
    """Modeless preview panel for chain alignment and rigid spacing."""

    def __init__(self, parent=None):
        super(StraightenChainDialog, self).__init__(parent)
        self.setWindowTitle("Straighten Chain")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setMinimumWidth(230)
        self._snapshot = capture_positions(_selected_nodes())
        self._preview = original_positions(self._snapshot)
        self._dirty = False
        self._closing = False
        self._build_ui()
        self._update_state()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.selection_label = QtWidgets.QLabel()
        layout.addWidget(self.selection_label)

        chain_group = QtWidgets.QGroupBox("Chain Alignment")
        button_layout = QtWidgets.QHBoxLayout(chain_group)
        self.vertical_button = self._make_chain_button(
            "Vertical chain", "vertical"
        )
        self.horizontal_button = self._make_chain_button(
            "Horizontal chain", "horizontal"
        )
        button_layout.addWidget(self.vertical_button)
        button_layout.addWidget(self.horizontal_button)
        layout.addWidget(chain_group)

        spacing_group = QtWidgets.QGroupBox("Between Chains")
        spacing_layout = QtWidgets.QGridLayout(spacing_group)
        self.space_vertical_button = self._make_spacing_button(
            "Space vertical chains", "vertical"
        )
        self.space_horizontal_button = self._make_spacing_button(
            "Space horizontal chains", "horizontal"
        )
        (
            self.vertical_anchor_widget,
            self.vertical_anchor_group,
            self.vertical_anchor_buttons,
        ) = self._make_anchor_selector(
            (("Left", "left"), ("Center", "center"), ("Right", "right")),
            "center",
        )
        (
            self.horizontal_anchor_widget,
            self.horizontal_anchor_group,
            self.horizontal_anchor_buttons,
        ) = self._make_anchor_selector(
            (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")),
            "middle",
        )
        spacing_layout.addWidget(self.space_vertical_button, 0, 0)
        spacing_layout.addWidget(self.vertical_anchor_widget, 0, 1)
        spacing_layout.addWidget(self.space_horizontal_button, 1, 0)
        spacing_layout.addWidget(self.horizontal_anchor_widget, 1, 1)

        gap_row = QtWidgets.QHBoxLayout()
        self.minimum_gap_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.minimum_gap_slider.setRange(0, 5000)
        self.minimum_gap_slider.setPageStep(100)
        self.minimum_gap_slider.setValue(50)
        self.minimum_gap_spin = QtWidgets.QSpinBox()
        self.minimum_gap_spin.setRange(0, 5000)
        self.minimum_gap_spin.setSingleStep(10)
        self.minimum_gap_spin.setValue(50)
        self.minimum_gap_spin.setSuffix(" px")
        gap_row.addWidget(QtWidgets.QLabel("Minimum gap:"))
        gap_row.addWidget(self.minimum_gap_slider, 1)
        gap_row.addWidget(self.minimum_gap_spin)
        spacing_layout.addLayout(gap_row, 2, 0, 1, 2)
        layout.addWidget(spacing_group)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        footer = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setDefault(True)
        footer.addWidget(self.reset_button)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)

        self.vertical_button.toggled.connect(
            lambda checked: self._toggle("vertical", checked)
        )
        self.horizontal_button.toggled.connect(
            lambda checked: self._toggle("horizontal", checked)
        )
        self.space_vertical_button.toggled.connect(
            lambda checked: self._toggle_spacing("vertical", checked)
        )
        self.space_horizontal_button.toggled.connect(
            lambda checked: self._toggle_spacing("horizontal", checked)
        )
        self.minimum_gap_slider.valueChanged.connect(
            self.minimum_gap_spin.setValue
        )
        self.minimum_gap_spin.valueChanged.connect(
            self.minimum_gap_slider.setValue
        )
        self.minimum_gap_spin.valueChanged.connect(self._recompute_preview)
        for button in list(self.vertical_anchor_buttons.values()) + list(
            self.horizontal_anchor_buttons.values()
        ):
            button.toggled.connect(self._anchor_changed)
        self.reset_button.clicked.connect(self.reset_changes)
        self.cancel_button.clicked.connect(self.cancel_changes)
        self.apply_button.clicked.connect(self.apply_changes)

    def _make_chain_button(self, label, orientation):
        button = QtWidgets.QToolButton()
        button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(58, 58))
        button.setMinimumSize(82, 72)
        button.setIcon(
            _chain_icon(orientation, False, self.palette())
        )
        button.setProperty("orientation", orientation)
        button.setToolTip(
            "{}: straighten each selected {} tree."
            .format(label, orientation)
        )
        return button

    def _make_spacing_button(self, label, orientation):
        button = QtWidgets.QToolButton()
        button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(46, 46))
        button.setFixedSize(62, 56)
        button.setIcon(_between_icon(orientation, False, self.palette()))
        button.setProperty("orientation", orientation)
        direction = "left/right" if orientation == "vertical" else "up/down"
        button.setToolTip(
            "{} {} as rigid units; preserve their internal layout."
            .format(label, direction)
        )
        return button

    def _make_anchor_selector(self, choices, default):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        group = QtWidgets.QButtonGroup(widget)
        group.setExclusive(True)
        buttons = {}
        for label, value in choices:
            button = QtWidgets.QPushButton(label)
            button.setCheckable(True)
            button.setProperty("anchor", value)
            button.setChecked(value == default)
            group.addButton(button)
            layout.addWidget(button)
            buttons[value] = button
        return widget, group, buttons

    def _set_button_icon(self, button, aligned):
        button.setIcon(
            _chain_icon(
                button.property("orientation"), aligned, self.palette()
            )
        )

    def _set_spacing_icon(self, button, active):
        button.setIcon(
            _between_icon(
                button.property("orientation"), active, self.palette()
            )
        )

    def _toggle(self, orientation, checked):
        button = (
            self.vertical_button
            if orientation == "vertical"
            else self.horizontal_button
        )
        self._set_button_icon(button, checked)
        self._recompute_preview()

    def _toggle_spacing(self, orientation, checked):
        button = (
            self.space_vertical_button
            if orientation == "vertical"
            else self.space_horizontal_button
        )
        self._set_spacing_icon(button, checked)
        self._recompute_preview()

    def _anchor_changed(self, checked):
        if checked:
            self._recompute_preview()

    @staticmethod
    def _checked_anchor(buttons):
        for value, button in buttons.items():
            if button.isChecked():
                return value
        raise RuntimeError("Spacing anchor group has no checked button")

    def _recompute_preview(self, *_args):
        orientations = {
            name
            for name, toggle in (
                ("vertical", self.vertical_button),
                ("horizontal", self.horizontal_button),
            )
            if toggle.isChecked()
        }
        positions = smart_straightened_positions(
            self._snapshot, orientations
        )
        aligned_snapshot = _snapshot_at_positions(self._snapshot, positions)
        if self.space_vertical_button.isChecked():
            vertical_positions = spaced_chain_positions(
                aligned_snapshot,
                "vertical",
                self.minimum_gap_spin.value(),
                self._checked_anchor(self.vertical_anchor_buttons),
            )
            positions = {
                key: (vertical_positions[key][0], positions[key][1])
                for key in positions
            }
        if self.space_horizontal_button.isChecked():
            horizontal_positions = spaced_chain_positions(
                aligned_snapshot,
                "horizontal",
                self.minimum_gap_spin.value(),
                self._checked_anchor(self.horizontal_anchor_buttons),
            )
            positions = {
                key: (positions[key][0], horizontal_positions[key][1])
                for key in positions
            }
        self._preview = positions
        set_positions(self._snapshot, positions)
        self._dirty = self._preview != original_positions(self._snapshot)
        moved = sum(
            self._preview[key] != original_positions(self._snapshot)[key]
            for key in self._preview
        )
        self.status_label.setText(
            "{} node{} moved in preview."
            .format(moved, "" if moved == 1 else "s")
            if (
                orientations
                or self.space_vertical_button.isChecked()
                or self.space_horizontal_button.isChecked()
            )
            else "Preview off."
        )
        self._update_state()

    def _update_state(self):
        count = len(self._snapshot)
        self.selection_label.setText(
            "{} selected node{}".format(count, "" if count == 1 else "s")
        )
        enabled = count >= 2
        self.vertical_button.setEnabled(enabled)
        self.horizontal_button.setEnabled(enabled)
        self.space_vertical_button.setEnabled(enabled)
        self.space_horizontal_button.setEnabled(enabled)
        self.vertical_anchor_widget.setEnabled(
            enabled and self.space_vertical_button.isChecked()
        )
        self.horizontal_anchor_widget.setEnabled(
            enabled and self.space_horizontal_button.isChecked()
        )
        self.apply_button.setEnabled(self._dirty)
        self.reset_button.setEnabled(
            self.vertical_button.isChecked()
            or self.horizontal_button.isChecked()
            or self.space_vertical_button.isChecked()
            or self.space_horizontal_button.isChecked()
        )
        if not enabled:
            self.status_label.setText(
                "Select at least two nodes before opening this tool."
            )

    def apply_changes(self):
        if not self._dirty:
            return
        final_positions = dict(self._preview)
        set_positions(self._snapshot, original_positions(self._snapshot))
        try:
            nuke.Undo.begin("Chain Layout")
            set_positions(self._snapshot, final_positions, preview=False)
        finally:
            nuke.Undo.end()
        self._snapshot = capture_positions(
            [item["node"] for item in self._snapshot.values()]
        )
        self._preview = original_positions(self._snapshot)
        self._dirty = False
        self.vertical_button.setChecked(False)
        self.horizontal_button.setChecked(False)
        self.space_vertical_button.setChecked(False)
        self.space_horizontal_button.setChecked(False)
        self.status_label.setText("Chain layout applied.")
        self._update_state()
        self._closing = True
        self.accept()

    def reset_changes(self):
        self.vertical_button.setChecked(False)
        self.horizontal_button.setChecked(False)
        self.space_vertical_button.setChecked(False)
        self.space_horizontal_button.setChecked(False)
        self._preview = original_positions(self._snapshot)
        set_positions(self._snapshot, self._preview)
        self._dirty = False
        self.status_label.setText("Reset to the opening positions.")
        self._update_state()

    def cancel_changes(self):
        set_positions(self._snapshot, original_positions(self._snapshot))
        self._closing = True
        self.reject()

    def closeEvent(self, event):
        if self._closing or not self._dirty:
            event.accept()
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Close Straighten Chain",
            "Apply the previewed node positions before closing?",
            QtWidgets.QMessageBox.Save
            | QtWidgets.QMessageBox.Discard
            | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if answer == QtWidgets.QMessageBox.Save:
            self.apply_changes()
            event.accept()
        elif answer == QtWidgets.QMessageBox.Discard:
            set_positions(self._snapshot, original_positions(self._snapshot))
            event.accept()
        else:
            event.ignore()


def show_dialog():
    """Show a fresh modeless Straighten Chain panel for the selection."""
    global _dialog
    if _dialog is not None:
        try:
            if not _dialog.close():
                return _dialog
        except Exception:
            pass
    _dialog = StraightenChainDialog(parent=_nuke_main_window())
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _dialog.destroyed.connect(_clear_dialog_reference)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def _clear_dialog_reference(*_args):
    global _dialog
    _dialog = None
