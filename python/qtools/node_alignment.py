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
    if orientation == "vertical":
        offsets = (0, 0, 0) if aligned else (-8, 7, -4)
        widths = (25, 34, 29)
        for index, (offset, width) in enumerate(zip(offsets, widths)):
            x = size / 2.0 - width / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(x, 8 + index * 17, width, 10), 2, 2
            )
    else:
        offsets = (0, 0, 0) if aligned else (-7, 7, -3)
        heights = (19, 25, 21)
        for index, (offset, height) in enumerate(zip(offsets, heights)):
            y = size / 2.0 - height / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(7 + index * 17, y, 10, height), 2, 2
            )
    painter.end()
    return QtGui.QIcon(pixmap)


class StraightenChainDialog(QtWidgets.QDialog):
    """Small modeless preview panel containing only Straighten Chain."""

    def __init__(self, parent=None):
        super(StraightenChainDialog, self).__init__(parent)
        self.setWindowTitle("Straighten Chain")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setMinimumWidth(250)
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

        self.button_group = QtWidgets.QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.button_group.addButton(self.vertical_button)
        self.button_group.addButton(self.horizontal_button)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        footer = QtWidgets.QHBoxLayout()
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setDefault(True)
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
        self.cancel_button.clicked.connect(self.cancel_changes)
        self.apply_button.clicked.connect(self.apply_changes)

    def _make_chain_button(self, label, orientation):
        button = QtWidgets.QToolButton()
        button.setText(label)
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(58, 58))
        button.setMinimumSize(105, 92)
        button.setIcon(
            _chain_icon(orientation, False, self.palette())
        )
        button.setProperty("orientation", orientation)
        button.setToolTip(
            "Align selected node centres into a {} line."
            .format(orientation)
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
        if checked:
            self._preview = straightened_positions(self._snapshot, orientation)
            set_positions(self._snapshot, self._preview)
            self.status_label.setText(
                "Previewing a {} chain using the median node centre."
                .format(orientation)
            )
        elif not self.button_group.checkedButton():
            self._preview = original_positions(self._snapshot)
            set_positions(self._snapshot, self._preview)
            self.status_label.setText("Preview removed.")
        self._dirty = self._preview != original_positions(self._snapshot)
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
        self.button_group.setExclusive(False)
        self.vertical_button.setChecked(False)
        self.horizontal_button.setChecked(False)
        self.button_group.setExclusive(True)
        self.status_label.setText("Straightened chain applied.")
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
    _dialog = StraightenChainDialog()
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _dialog.destroyed.connect(_clear_dialog_reference)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def _clear_dialog_reference(*_args):
    global _dialog
    _dialog = None
