"""Consolidate labels on hidden PostageStamp-to-Dot connections."""

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


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


def _nuke_main_window():
    """Return Nuke's main window when available."""
    application = QtWidgets.QApplication.instance()

    if application is None:
        return None

    for widget in application.topLevelWidgets():
        try:
            if (
                widget.inherits("QMainWindow")
                and widget.metaObject().className()
                == "Foundry::UI::DockMainWindow"
            ):
                return widget
        except Exception:
            continue

    return None


def _unique_names(names):
    """Return non-empty names without case-insensitive duplicates."""
    unique = []
    seen = set()

    for name in names:
        name = _connector_name(name)
        key = name.lower()

        if not name or key in seen:
            continue

        seen.add(key)
        unique.append(name)

    return unique


def _collect_candidates():
    """Collect eligible connections, grouped by their source Dot."""
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

    safe = []
    conflicts = []

    for dot, connections in connections_by_dot.items():
        stamp_names = _unique_names(
            name
            for _stamp, name in connections
        )
        dot_name = _connector_name(dot["label"].value())
        choices = _unique_names(stamp_names + [dot_name])
        candidate = {
            "dot": dot,
            "connections": connections,
            "choices": choices,
            "preferred_name": stamp_names[0],
        }

        if len(stamp_names) == 1:
            safe.append(candidate)
        else:
            conflicts.append(candidate)

    sort_key = lambda candidate: candidate["dot"].name().lower()
    return sorted(safe, key=sort_key), sorted(conflicts, key=sort_key)


class ConnectorCleanupDialog(QtWidgets.QDialog):
    """Preview and choose connector-label cleanup operations."""

    HEADERS = [
        "Update",
        "Dot",
        "Current labels",
        "Resolve as",
        "Preview",
    ]

    def __init__(self, safe, conflicts, parent=None):
        super(ConnectorCleanupDialog, self).__init__(parent)

        self._rows = []
        self.setWindowTitle("Connector Label clean up")
        self.resize(1050, 650)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Review hidden-input PostageStamp connections. "
            "Each checked row updates its Dot and all listed PostageStamps."
        ))

        safe_group = QtWidgets.QGroupBox(
            "Safe — PostageStamp names agree ({})".format(len(safe))
        )
        safe_layout = QtWidgets.QVBoxLayout(safe_group)
        safe_layout.addWidget(self._build_table(safe, checked=True))
        layout.addWidget(safe_group)

        conflict_group = QtWidgets.QGroupBox(
            "Conflicts — choose the correct name ({})".format(
                len(conflicts)
            )
        )
        conflict_layout = QtWidgets.QVBoxLayout(conflict_group)
        conflict_layout.addWidget(
            self._build_table(conflicts, checked=False)
        )
        layout.addWidget(conflict_group)

        button_layout = QtWidgets.QHBoxLayout()
        select_all_button = QtWidgets.QPushButton("Select All")
        select_safe_button = QtWidgets.QPushButton("Select Safe")
        select_conflicts_button = QtWidgets.QPushButton(
            "Select Conflicts"
        )
        clear_button = QtWidgets.QPushButton("Clear Selection")
        button_layout.addWidget(select_all_button)
        button_layout.addWidget(select_safe_button)
        button_layout.addWidget(select_conflicts_button)
        button_layout.addWidget(clear_button)
        button_layout.addStretch()

        cancel_button = QtWidgets.QPushButton("Cancel")
        apply_button = QtWidgets.QPushButton("Apply Selected")
        apply_button.setDefault(True)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(apply_button)
        layout.addLayout(button_layout)

        select_all_button.clicked.connect(self._select_all)
        select_safe_button.clicked.connect(self._select_safe)
        select_conflicts_button.clicked.connect(self._select_conflicts)
        clear_button.clicked.connect(self._clear_selection)
        cancel_button.clicked.connect(self.reject)
        apply_button.clicked.connect(self.accept)

    def _build_table(self, candidates, checked):
        """Build a preview table for one candidate group."""
        table = QtWidgets.QTableWidget(len(candidates), len(self.HEADERS))
        table.setHorizontalHeaderLabels(self.HEADERS)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)

        for row, candidate in enumerate(candidates):
            check_item = QtWidgets.QTableWidgetItem()
            check_item.setFlags(
                QtCore.Qt.ItemIsEnabled
                | QtCore.Qt.ItemIsUserCheckable
            )
            check_item.setCheckState(
                QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
            )
            table.setItem(row, 0, check_item)

            dot = candidate["dot"]
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(dot.name()))

            stamp_labels = ", ".join(
                _clean_text(stamp["label"].value())
                for stamp, _name in candidate["connections"]
            )
            current_text = "Dot: {}\nPostageStamps: {}".format(
                _clean_text(dot["label"].value()),
                stamp_labels
            )
            table.setItem(
                row,
                2,
                QtWidgets.QTableWidgetItem(current_text)
            )

            name_combo = QtWidgets.QComboBox()
            name_combo.setEditable(True)
            name_combo.addItems(candidate["choices"])
            name_combo.setCurrentText(candidate["preferred_name"])
            table.setCellWidget(row, 3, name_combo)

            preview_item = QtWidgets.QTableWidgetItem()
            table.setItem(row, 4, preview_item)

            row_data = {
                "candidate": candidate,
                "check_item": check_item,
                "name_combo": name_combo,
                "preview_item": preview_item,
                "safe": checked,
            }
            self._rows.append(row_data)
            name_combo.currentTextChanged.connect(
                lambda _text, data=row_data: self._update_preview(data)
            )
            self._update_preview(row_data)

        table.resizeRowsToContents()
        table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            4,
            QtWidgets.QHeaderView.Stretch
        )
        return table

    def _update_preview(self, row_data):
        """Update one row's proposed From/To labels."""
        name = _clean_text(row_data["name_combo"].currentText())
        stamp_count = len(row_data["candidate"]["connections"])
        row_data["preview_item"].setText(
            "Dot: From {name} | {count} PostageStamp(s): To {name}".format(
                name=name,
                count=stamp_count
            )
        )

    def _set_checked(self, predicate):
        """Set row checkboxes according to predicate."""
        for row_data in self._rows:
            row_data["check_item"].setCheckState(
                QtCore.Qt.Checked
                if predicate(row_data)
                else QtCore.Qt.Unchecked
            )

    def _select_all(self):
        self._set_checked(lambda _row: True)

    def _select_safe(self):
        self._set_checked(lambda row: row["safe"])

    def _select_conflicts(self):
        self._set_checked(lambda row: not row["safe"])

    def _clear_selection(self):
        self._set_checked(lambda _row: False)

    def selected_resolutions(self):
        """Return checked candidates with their selected canonical names."""
        resolutions = []

        for row_data in self._rows:
            if row_data["check_item"].checkState() != QtCore.Qt.Checked:
                continue

            name = _clean_text(row_data["name_combo"].currentText())

            if name:
                resolutions.append((row_data["candidate"], name))

        return resolutions


def clean_up_connector_labels():
    """Review and normalize PostageStamp and source-Dot label pairs."""
    safe, conflicts = _collect_candidates()

    if not safe and not conflicts:
        nuke.message(
            "No labelled, hidden-input PostageStamp-to-Dot "
            "connections were found."
        )
        return 0

    dialog = ConnectorCleanupDialog(
        safe,
        conflicts,
        parent=_nuke_main_window()
    )

    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return 0

    resolutions = dialog.selected_resolutions()
    updated_stamps = 0

    for candidate, canonical_name in resolutions:
        candidate["dot"]["label"].setValue(
            "From {}".format(canonical_name)
        )

        for stamp, _stamp_name in candidate["connections"]:
            stamp["label"].setValue(
                "To {}".format(canonical_name)
            )
            updated_stamps += 1

    return updated_stamps
