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


def directional_chains(snapshot, orientation):
    """Group selected nodes using only connections matching an orientation."""
    keys = set(snapshot)
    neighbours = {key: set() for key in keys}
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

    chains = []
    unseen = {key for key in keys if neighbours[key]}
    while unseen:
        start = unseen.pop()
        chain = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            additions = neighbours[current] & unseen
            unseen.difference_update(additions)
            chain.update(additions)
            stack.extend(additions)
        chains.append(chain)
    return chains


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
        horizontal_node_width = 14
        for index, offset in enumerate(offsets):
            y = size / 2.0 - node_height / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(
                    4 + index * 18,
                    y,
                    horizontal_node_width,
                    node_height,
                ),
                2,
                2,
            )
    painter.end()
    return QtGui.QIcon(pixmap)


class StraightenChainDialog(QtWidgets.QDialog):
    """Small modeless preview panel containing only Straighten Chain."""

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

        button_layout = QtWidgets.QHBoxLayout()
        self.vertical_button = self._make_chain_button(
            "Vertical chain", "vertical"
        )
        self.horizontal_button = self._make_chain_button(
            "Horizontal chain", "horizontal"
        )
        button_layout.addWidget(self.vertical_button)
        button_layout.addWidget(self.horizontal_button)
        layout.addLayout(button_layout)

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

    def _set_button_icon(self, button, aligned):
        button.setIcon(
            _chain_icon(
                button.property("orientation"), aligned, self.palette()
            )
        )

    def _toggle(self, orientation, checked):
        button = (
            self.vertical_button
            if orientation == "vertical"
            else self.horizontal_button
        )
        self._set_button_icon(button, checked)
        orientations = {
            name
            for name, toggle in (
                ("vertical", self.vertical_button),
                ("horizontal", self.horizontal_button),
            )
            if toggle.isChecked()
        }
        self._preview = smart_straightened_positions(
            self._snapshot, orientations
        )
        set_positions(self._snapshot, self._preview)
        self._dirty = self._preview != original_positions(self._snapshot)
        moved = sum(
            self._preview[key] != original_positions(self._snapshot)[key]
            for key in self._preview
        )
        self.status_label.setText(
            "{} node{} moved in preview."
            .format(moved, "" if moved == 1 else "s")
            if orientations else "Preview off."
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
        self.apply_button.setEnabled(self._dirty)
        self.reset_button.setEnabled(
            self.vertical_button.isChecked()
            or self.horizontal_button.isChecked()
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
            nuke.Undo.begin("Straighten Chain")
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
        self.status_label.setText("Straightened chain applied.")
        self._update_state()
        self._closing = True
        self.accept()

    def reset_changes(self):
        self.vertical_button.setChecked(False)
        self.horizontal_button.setChecked(False)
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
            "Apply the previewed alignment before closing?",
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
