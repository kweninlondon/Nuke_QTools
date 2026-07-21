"""Consolidate labels on hidden PostageStamp-to-Dot connections."""

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


FROM_LABEL_WRAP_LENGTH = 20


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


def _from_label(name):
    """Format a Dot source label, wrapping long names after From."""
    name = _clean_text(name)
    separator = "\n" if len(name) > FROM_LABEL_WRAP_LENGTH else " "
    return "From{}{}".format(separator, name)


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

    HEADERS = ["Update", "Change", "Conflict resolution"]

    def __init__(self, safe, conflicts, parent=None):
        super(ConnectorCleanupDialog, self).__init__(parent)

        self._rows = []
        self.setWindowTitle("Connector Label clean up")
        self.resize(850, 600)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Choose the connector groups to normalize. Expand a row only "
            "when you need to inspect its current labels."
        ))

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(len(self.HEADERS))
        self.tree.setHeaderLabels(self.HEADERS)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.tree)

        safe_group = QtWidgets.QTreeWidgetItem(
            self.tree,
            ["Safe ({})".format(len(safe))]
        )
        safe_group.setFirstColumnSpanned(True)
        safe_group.setExpanded(True)
        self._add_rows(safe_group, safe, safe=True)

        conflict_group = QtWidgets.QTreeWidgetItem(
            self.tree,
            ["Conflicts ({}) — choose a name".format(len(conflicts))]
        )
        conflict_group.setFirstColumnSpanned(True)
        conflict_group.setExpanded(True)
        self._add_rows(conflict_group, conflicts, safe=False)

        header = self.tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)

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

    def _add_rows(self, parent, candidates, safe):
        """Add compact candidate rows beneath a status group."""
        for candidate in candidates:
            preferred_name = candidate["preferred_name"]
            dot_name = _connector_name(
                candidate["dot"]["label"].value()
            )
            current_names = _unique_names([dot_name, preferred_name])
            current_text = (
                " / ".join(current_names)
                if safe
                else "Multiple"
            )
            item = QtWidgets.QTreeWidgetItem(
                parent,
                ["", current_text, ""]
            )
            item.setFlags(
                item.flags()
                | QtCore.Qt.ItemIsUserCheckable
            )
            item.setCheckState(
                0,
                QtCore.Qt.Checked if safe else QtCore.Qt.Unchecked
            )

            name_combo = None

            if not safe:
                name_combo = QtWidgets.QComboBox()
                name_combo.setEditable(True)
                name_combo.addItems(candidate["choices"])
                name_combo.setCurrentText(preferred_name)
                self.tree.setItemWidget(item, 2, name_combo)

            detail_item = QtWidgets.QTreeWidgetItem(item)
            detail_item.setFirstColumnSpanned(True)
            dot_label = _clean_text(candidate["dot"]["label"].value())
            stamp_labels = ", ".join(
                _clean_text(stamp["label"].value())
                for stamp, _name in candidate["connections"]
            )
            detail_item.setText(
                0,
                "Current — Dot: {}  |  PostageStamps: {}".format(
                    dot_label,
                    stamp_labels
                )
            )
            detail_item.setFlags(QtCore.Qt.ItemIsEnabled)

            result_detail_item = QtWidgets.QTreeWidgetItem(item)
            result_detail_item.setFirstColumnSpanned(True)
            result_detail_item.setFlags(QtCore.Qt.ItemIsEnabled)

            row_data = {
                "candidate": candidate,
                "item": item,
                "name_combo": name_combo,
                "current_text": current_text,
                "result_detail_item": result_detail_item,
                "safe": safe,
            }
            self._rows.append(row_data)

            if name_combo is not None:
                name_combo.currentTextChanged.connect(
                    lambda _text, data=row_data: self._update_preview(data)
                )

            self._update_preview(row_data)

    def _update_preview(self, row_data):
        """Update one row's proposed From/To labels."""
        if row_data["name_combo"] is None:
            name = row_data["candidate"]["preferred_name"]
        else:
            name = _clean_text(row_data["name_combo"].currentText())

        row_data["item"].setText(
            1,
            "{} → To {}".format(row_data["current_text"], name)
        )
        row_data["result_detail_item"].setText(
            0,
            "Result — Dot: {}  |  PostageStamps: To {}".format(
                _clean_text(_from_label(name)),
                name
            )
        )

    def _set_checked(self, predicate):
        """Set row checkboxes according to predicate."""
        for row_data in self._rows:
            row_data["item"].setCheckState(
                0,
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
            if row_data["item"].checkState(0) != QtCore.Qt.Checked:
                continue

            if row_data["name_combo"] is None:
                name = row_data["candidate"]["preferred_name"]
            else:
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
            _from_label(canonical_name)
        )

        for stamp, _stamp_name in candidate["connections"]:
            stamp["label"].setValue(
                "To {}".format(canonical_name)
            )
            updated_stamps += 1

    return updated_stamps
