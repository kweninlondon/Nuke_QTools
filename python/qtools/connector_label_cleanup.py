"""Consolidate labels on hidden PostageStamp-to-Dot connections."""

import os
import re

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


FROM_LABEL_WRAP_LENGTH = 20
_ACTIVE_DIALOG = None


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


def _unique_texts(values):
    """Return clean text values without case-insensitive duplicates."""
    unique = []
    seen = set()

    for value in values:
        value = _clean_text(value)
        key = value.lower()

        if not value or key in seen:
            continue

        seen.add(key)
        unique.append(value)

    return unique


def _read_frame_name(node):
    """Return a Read filename stem without its frame-number token."""
    if node is None or node.Class() != "Read" or "file" not in node.knobs():
        return ""

    file_path = str(node["file"].value() or "")
    filename = os.path.basename(file_path.replace("\\", "/"))
    stem, _extension = os.path.splitext(filename)

    return re.sub(
        r"[\W_]*(?:#+|%0?\d*d|\$F\d*)$",
        "",
        stem
    )


def _duplicate_preferred_name(candidate):
    """Prefer a distinct PostageStamp name over its duplicated Dot name."""
    dot_name = _connector_name(candidate["dot"]["label"].value())
    alternatives = [
        (name, count)
        for name, count in candidate["stamp_name_counts"]
        if name.lower() != dot_name.lower()
    ]

    if not alternatives:
        return ""

    alternatives.sort(key=lambda item: -item[1])
    return alternatives[0][0]


def _numbered_duplicate_name(base_name, candidate, index, used_names):
    """Return a stable unique name for a duplicated connector Dot."""
    upstream = candidate["dot"].input(0)
    frame_name = _read_frame_name(upstream)
    suffix = frame_name or str(index)
    proposed = "{} ({})".format(base_name, suffix)
    attempt = 2

    while proposed.lower() in used_names:
        proposed = "{} ({}) ({})".format(
            base_name,
            suffix,
            attempt
        )
        attempt += 1

    return proposed


def _collect_candidates():
    """Collect eligible connections, grouped by their source Dot."""
    connections_by_dot = {}

    for stamp in nuke.allNodes("PostageStamp"):
        if "label" not in stamp.knobs():
            continue

        stamp_name = _connector_name(stamp["label"].value())

        try:
            dot = stamp.input(0)
        except Exception:
            continue

        if dot is None or dot.Class() != "Dot":
            continue

        if "label" not in dot.knobs():
            continue

        connections_by_dot.setdefault(dot, []).append(
            (stamp, stamp_name)
        )

    candidates = []
    unnamed = []

    for dot, connections in connections_by_dot.items():
        stamp_names = _unique_names(
            name
            for _stamp, name in connections
        )
        stamp_name_counts = []

        for stamp_name in stamp_names:
            count = sum(
                1
                for _stamp, name in connections
                if name.lower() == stamp_name.lower()
            )
            stamp_name_counts.append((stamp_name, count))

        raw_stamp_labels = _unique_texts(
            _clean_text(stamp["label"].value())
            for stamp, _name in connections
        )
        raw_stamp_label_counts = []

        for raw_label in raw_stamp_labels:
            count = sum(
                1
                for stamp, _name in connections
                if _clean_text(stamp["label"].value()).lower()
                == raw_label.lower()
            )
            raw_stamp_label_counts.append((raw_label, count))

        dot_name = _connector_name(dot["label"].value())
        choices = _unique_names(stamp_names + [dot_name])
        visible_input_count = sum(
            1
            for stamp, _name in connections
            if not _has_hidden_input(stamp)
        )

        if not choices:
            unnamed_candidate = {
                "dot": dot,
                "connections": connections,
                "choices": [],
                "stamp_name_counts": [],
                "raw_stamp_label_counts": raw_stamp_label_counts,
                "visible_input_count": visible_input_count,
                "preferred_name": "",
            }
            unnamed.append(unnamed_candidate)
            continue

        count_by_name = {
            name.lower(): count
            for name, count in stamp_name_counts
        }
        choices.sort(
            key=lambda name: (
                -(
                    count_by_name.get(name.lower(), 0)
                    + (1 if name.lower() == dot_name.lower() else 0)
                ),
                0 if name.lower() == dot_name.lower() else 1,
            )
        )
        candidate = {
            "dot": dot,
            "connections": connections,
            "choices": choices,
            "stamp_name_counts": stamp_name_counts,
            "raw_stamp_label_counts": raw_stamp_label_counts,
            "visible_input_count": visible_input_count,
            "preferred_name": choices[0],
            "dot_name": dot_name,
            "healthy": False,
        }

        if len(choices) == 1:
            expected_dot_label = _clean_text(
                _from_label(candidate["preferred_name"])
            ).lower()
            expected_stamp_label = "to {}".format(
                candidate["preferred_name"]
            ).lower()
            dot_is_healthy = (
                _clean_text(dot["label"].value()).lower()
                == expected_dot_label
            )
            stamps_are_healthy = all(
                _clean_text(stamp["label"].value()).lower()
                == expected_stamp_label
                for stamp, _name in connections
            )
            inputs_are_healthy = all(
                _has_hidden_input(stamp)
                for stamp, _name in connections
            )

            candidate["healthy"] = (
                dot_is_healthy
                and stamps_are_healthy
                and inputs_are_healthy
            )

        candidates.append(candidate)

    candidates_by_name = {}

    for candidate in candidates:
        candidates_by_name.setdefault(
            candidate["dot_name"].lower(),
            []
        ).append(candidate)

    duplicate_keys = {
        key
        for key, grouped_candidates in candidates_by_name.items()
        if len(grouped_candidates) > 1
    }
    used_names = {
        candidate["dot_name"].lower()
        for candidate in candidates
        if candidate["dot_name"].lower() not in duplicate_keys
    }
    duplicates = []

    for key in sorted(duplicate_keys):
        grouped_candidates = sorted(
            candidates_by_name[key],
            key=lambda candidate: candidate["dot"].name().lower()
        )
        base_name = grouped_candidates[0]["dot_name"]

        for index, candidate in enumerate(grouped_candidates):
            preferred_name = _duplicate_preferred_name(candidate)

            if preferred_name and preferred_name.lower() not in used_names:
                suggested_name = preferred_name
            elif base_name.lower() not in used_names:
                suggested_name = base_name
            else:
                suggested_name = _numbered_duplicate_name(
                    base_name,
                    candidate,
                    index,
                    used_names
                )

            candidate["duplicate_name"] = suggested_name
            used_names.add(suggested_name.lower())
            duplicates.append(candidate)

    remaining = [
        candidate
        for candidate in candidates
        if candidate["dot_name"].lower() not in duplicate_keys
    ]
    safe = [
        candidate
        for candidate in remaining
        if len(candidate["choices"]) == 1 and not candidate["healthy"]
    ]
    conflicts = [
        candidate
        for candidate in remaining
        if len(candidate["choices"]) > 1
    ]

    sort_key = lambda candidate: candidate["dot"].name().lower()
    return (
        sorted(safe, key=sort_key),
        sorted(conflicts, key=sort_key),
        sorted(duplicates, key=sort_key),
        sorted(unnamed, key=sort_key),
    )


def _choice_count(candidate, option_name):
    """Return the PostageStamp count for one resolution choice."""
    return next(
        (
            count
            for name, count in candidate["stamp_name_counts"]
            if name.lower() == option_name.lower()
        ),
        0
    )


def _choice_text(candidate, option_name):
    """Return compact dropdown text for one resolution choice."""
    count = _choice_count(candidate, option_name)

    if count:
        return "{} ({})".format(option_name, count)

    return "{} (Dot)".format(option_name)


class ConnectorCleanupDialog(QtWidgets.QDialog):
    """Preview and choose connector-label cleanup operations."""

    HEADERS = ["Update", "Change", "Conflict resolution"]

    def __init__(
        self,
        safe,
        conflicts,
        duplicates,
        unnamed,
        on_close=None,
        parent=None
    ):
        super(ConnectorCleanupDialog, self).__init__(parent)

        self._rows = []
        self._on_close = on_close
        self._skip_on_close = False
        self.setWindowTitle("Connector Label clean up")
        self.setWindowModality(QtCore.Qt.NonModal)

        screen = (
            parent.screen()
            if parent is not None and hasattr(parent, "screen")
            else QtWidgets.QApplication.primaryScreen()
        )
        maximum_height = int(
            screen.availableGeometry().height() * 0.8
        ) if screen is not None else 800
        row_count = (
            len(safe) + len(conflicts) + len(duplicates) + len(unnamed) + 4
        )
        desired_height = 240 + row_count * 34
        window_height = min(
            maximum_height,
            max(650, desired_height)
        )
        self.resize(1100, window_height)

        conflict_texts = [
            _choice_text(candidate, option_name)
            for candidate in conflicts
            for option_name in candidate["choices"]
        ] + [
            candidate["duplicate_name"]
            for candidate in duplicates
        ] + ["Enter connector name..."]
        conflict_text_width = max(
            self.fontMetrics().horizontalAdvance(text)
            for text in conflict_texts or ["Conflict resolution"]
        )
        self._combo_width = max(
            160,
            conflict_text_width + 45
        )

        layout = QtWidgets.QVBoxLayout(self)
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.addWidget(QtWidgets.QLabel(
            "Choose the connector groups to normalize. Expand a row only "
            "when you need to inspect its current labels."
        ))
        header_layout.addStretch()
        self.reload_button = QtWidgets.QPushButton("Reload")
        self.reload_button.setMinimumWidth(90)
        self.reload_button.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Fixed
        )
        self.reload_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload)
        )
        self.reload_button.setToolTip(
            "Rescan the current comp and rebuild this cleanup review."
        )
        header_layout.addWidget(self.reload_button)
        layout.addLayout(header_layout)
        self.summary_label = QtWidgets.QLabel()
        layout.addWidget(self.summary_label)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(len(self.HEADERS))
        self.tree.setHeaderLabels(self.HEADERS)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        self.tree.setUniformRowHeights(False)
        self.tree.setStyleSheet(
            "QTreeWidget::item { padding-top: 3px; padding-bottom: 3px; }"
        )
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

        duplicate_group = QtWidgets.QTreeWidgetItem(
            self.tree,
            ["Duplicates ({}) — confirm unique names".format(
                len(duplicates)
            )]
        )
        duplicate_group.setFirstColumnSpanned(True)
        duplicate_group.setExpanded(True)
        self._add_rows(
            duplicate_group,
            duplicates,
            safe=False,
            duplicate=True
        )

        unnamed_group = QtWidgets.QTreeWidgetItem(
            self.tree,
            ["Unnamed ({}) — enter a name".format(len(unnamed))]
        )
        unnamed_group.setFirstColumnSpanned(True)
        unnamed_group.setExpanded(True)
        self._add_rows(
            unnamed_group,
            unnamed,
            safe=False,
            unnamed=True
        )

        self.tree.itemChanged.connect(self._item_changed)

        for row_data in self._rows:
            self._update_row_style(row_data)

        self._update_summary()

        header = self.tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.tree.setColumnWidth(1, 430)

        button_layout = QtWidgets.QHBoxLayout()
        select_all_button = QtWidgets.QPushButton("Select All")
        select_all_button.setToolTip(
            "Select every safe, conflicting, and named Unnamed group."
        )
        select_safe_button = QtWidgets.QPushButton("Select Safe")
        select_safe_button.setToolTip(
            "Select only groups with one unambiguous connector name."
        )
        select_conflicts_button = QtWidgets.QPushButton(
            "Select Conflicts"
        )
        select_conflicts_button.setToolTip(
            "Select only groups containing competing PostageStamp names."
        )
        select_duplicates_button = QtWidgets.QPushButton(
            "Select Duplicates"
        )
        select_duplicates_button.setToolTip(
            "Select duplicated connector names using their proposed unique names."
        )
        select_unnamed_button = QtWidgets.QPushButton("Select Unnamed")
        select_unnamed_button.setToolTip(
            "Select Unnamed groups that have a connector name entered."
        )
        clear_button = QtWidgets.QPushButton("Clear Selection")
        clear_button.setToolTip("Uncheck every proposed cleanup operation.")
        button_layout.addWidget(select_all_button)
        button_layout.addWidget(select_safe_button)
        button_layout.addWidget(select_conflicts_button)
        button_layout.addWidget(select_duplicates_button)
        button_layout.addWidget(select_unnamed_button)
        button_layout.addWidget(clear_button)
        button_layout.addStretch()

        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.setToolTip(
            "Close without changing any connector labels or input visibility."
        )
        apply_button = QtWidgets.QPushButton("Apply Selected")
        apply_button.setToolTip(
            "Apply the checked label fixes and hide their PostageStamp inputs."
        )
        apply_button.setDefault(True)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(apply_button)
        layout.addLayout(button_layout)

        select_all_button.clicked.connect(self._select_all)
        select_safe_button.clicked.connect(self._select_safe)
        select_conflicts_button.clicked.connect(self._select_conflicts)
        select_duplicates_button.clicked.connect(self._select_duplicates)
        select_unnamed_button.clicked.connect(self._select_unnamed)
        clear_button.clicked.connect(self._clear_selection)
        cancel_button.clicked.connect(self.reject)
        apply_button.clicked.connect(self._apply_selected)
        self.reload_button.clicked.connect(self._reload)

    def _reload(self):
        """Close this snapshot and rebuild it from the current comp."""
        self._skip_on_close = True
        on_close = self._on_close
        self.close()
        QtCore.QTimer.singleShot(
            0,
            lambda: clean_up_connector_labels(on_close=on_close)
        )

    def _add_rows(
        self,
        parent,
        candidates,
        safe,
        unnamed=False,
        duplicate=False
    ):
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
                else (
                    "Unnamed"
                    if unnamed
                    else (
                        dot_name
                        if duplicate
                        else "Multiple ({})".format(
                            len(candidate["choices"])
                        )
                    )
                )
            )
            affected_count = 1 + len(candidate["connections"])
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
                QtCore.Qt.Checked
                if safe or duplicate
                else QtCore.Qt.Unchecked
            )
            item.setToolTip(
                0,
                "Check this connector group to include it when applying fixes."
            )

            name_combo = None
            name_field = None
            change_label = None

            if not safe:
                if unnamed or duplicate:
                    name_field = QtWidgets.QLineEdit()
                    if duplicate:
                        name_field.setText(candidate["duplicate_name"])
                    else:
                        name_field.setPlaceholderText(
                            "Enter connector name..."
                        )
                    name_field.setToolTip(
                        "Edit the unique shared name to use after From and To."
                        if duplicate
                        else "Enter the shared name to use after From and To."
                    )
                    name_field.setFixedWidth(self._combo_width)
                else:
                    name_combo = QtWidgets.QComboBox()
                    name_combo.setToolTip(
                        "Choose the canonical name for this conflicting group."
                    )

                    for option_name in candidate["choices"]:
                        name_combo.addItem(
                            _choice_text(candidate, option_name),
                            option_name
                        )

                    preferred_index = name_combo.findData(preferred_name)
                    name_combo.setCurrentIndex(
                        preferred_index if preferred_index >= 0 else 0
                    )
                    name_combo.setFixedWidth(self._combo_width)

                resolution_widget = QtWidgets.QWidget()
                resolution_layout = QtWidgets.QHBoxLayout(
                    resolution_widget
                )
                resolution_layout.setContentsMargins(0, 0, 0, 0)
                resolution_layout.setSpacing(4)
                previous_button = QtWidgets.QToolButton()
                previous_button.setText("‹")
                previous_button.setToolTip("Show previous connected node")
                arrow_font = previous_button.font()
                arrow_font.setPointSizeF(
                    arrow_font.pointSizeF() * 1.25
                )
                previous_button.setFont(arrow_font)
                change_widget = QtWidgets.QWidget()
                change_layout = QtWidgets.QHBoxLayout(change_widget)
                change_layout.setContentsMargins(0, 0, 0, 0)
                change_layout.setSpacing(4)
                change_layout.addWidget(QtWidgets.QLabel("Show:"))
                change_layout.addWidget(previous_button)

                next_button = QtWidgets.QToolButton()
                next_button.setText("›")
                next_button.setToolTip("Show next connected node")
                next_button.setFont(arrow_font)
                change_layout.addWidget(next_button)
                change_label = QtWidgets.QLabel()
                change_layout.addWidget(change_label)
                change_layout.addStretch()

                item.setText(1, "")
                item.setSizeHint(1, QtCore.QSize(0, 30))
                self.tree.setItemWidget(item, 1, change_widget)
                resolution_layout.addWidget(
                    name_field if unnamed else name_combo
                )
                resolution_layout.addStretch()

                self.tree.setItemWidget(item, 2, resolution_widget)

            detail_item = QtWidgets.QTreeWidgetItem(item)
            detail_item.setFirstColumnSpanned(True)
            dot_label = (
                _clean_text(candidate["dot"]["label"].value())
                or "(empty)"
            )
            stamp_summary = ", ".join(
                "{} ({})".format(name, count)
                for name, count in candidate["raw_stamp_label_counts"]
            ) or "(empty)"
            visible_input_count = candidate["visible_input_count"]
            input_summary = (
                "{} visible input(s)".format(visible_input_count)
                if visible_input_count
                else "inputs hidden"
            )
            detail_item.setText(
                0,
                "Current — Dot: {}  |  PostageStamps: {}  |  {}".format(
                    dot_label,
                    stamp_summary,
                    input_summary
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
                "name_field": name_field,
                "change_label": change_label,
                "current_text": current_text,
                "affected_count": affected_count,
                "result_detail_item": result_detail_item,
                "view_index": -1,
                "safe": safe,
                "unnamed": unnamed,
                "duplicate": duplicate,
            }
            self._rows.append(row_data)

            if name_combo is not None:
                name_combo.currentIndexChanged.connect(
                    lambda _index, data=row_data: self._update_preview(data)
                )
                previous_button.clicked.connect(
                    lambda _checked=False, data=row_data: (
                        self._show_connected_node(data, -1)
                    )
                )
                next_button.clicked.connect(
                    lambda _checked=False, data=row_data: (
                        self._show_connected_node(data, 1)
                    )
                )

            if name_field is not None:
                name_field.textChanged.connect(
                    lambda _text, data=row_data: (
                        self._editable_name_changed(data)
                    )
                )
                previous_button.clicked.connect(
                    lambda _checked=False, data=row_data: (
                        self._show_connected_node(data, -1)
                    )
                )
                next_button.clicked.connect(
                    lambda _checked=False, data=row_data: (
                        self._show_connected_node(data, 1)
                    )
                )

            self._update_preview(row_data)

    def _editable_name_changed(self, row_data):
        """Select an editable row when it contains a usable name."""
        has_name = bool(
            _clean_text(row_data["name_field"].text())
        )
        row_data["item"].setCheckState(
            0,
            QtCore.Qt.Checked if has_name else QtCore.Qt.Unchecked
        )
        self._update_preview(row_data)

    def _update_preview(self, row_data):
        """Update one row's proposed From/To labels."""
        if row_data["name_field"] is not None:
            name = _clean_text(row_data["name_field"].text())
        elif row_data["name_combo"] is None:
            name = row_data["candidate"]["preferred_name"]
        else:
            name = _clean_text(row_data["name_combo"].currentData())

        if row_data["safe"]:
            change_text = "{} → To {} ({})".format(
                row_data["current_text"],
                name,
                row_data["affected_count"]
            )
        elif row_data["duplicate"]:
            change_text = "{} → To {} ({})".format(
                row_data["current_text"],
                name,
                row_data["affected_count"]
            )
        else:
            change_text = (
                "{} → To {}".format(row_data["current_text"], name)
                if name
                else "Unnamed → enter a name"
            )

        if row_data["change_label"] is None:
            row_data["item"].setText(1, change_text)
        else:
            row_data["change_label"].setText(change_text)
        row_data["result_detail_item"].setText(
            0,
            (
                "Result — Dot: {}  |  PostageStamps: To {}  |  "
                "inputs hidden".format(
                    _clean_text(_from_label(name)),
                    name
                )
                if name
                else "Result — enter a name to preview this fix"
            )
        )

    def _show_connected_node(self, row_data, direction):
        """Cycle through and frame nodes in one conflicting group."""
        candidate = row_data["candidate"]
        nodes = [candidate["dot"]] + [
            stamp
            for stamp, _name in candidate["connections"]
        ]

        if not nodes:
            return

        if row_data["view_index"] < 0:
            row_data["view_index"] = 0 if direction > 0 else len(nodes) - 1
        else:
            row_data["view_index"] = (
                row_data["view_index"] + direction
            ) % len(nodes)
        node = nodes[row_data["view_index"]]

        for selected_node in nuke.selectedNodes():
            selected_node.setSelected(False)

        node.setSelected(True)
        nuke.zoomToFitSelected()

    def _item_changed(self, item, column):
        """Refresh highlighting and totals after a checkbox changes."""
        if column != 0:
            return

        for row_data in self._rows:
            if row_data["item"] is item:
                self._update_row_style(row_data)
                self._update_summary()
                return

    def _update_row_style(self, row_data):
        """Highlight checked connector rows in Nuke-style orange."""
        checked = (
            row_data["item"].checkState(0) == QtCore.Qt.Checked
        )
        brush = (
            QtGui.QBrush(QtGui.QColor("#d9822b"))
            if checked
            else QtGui.QBrush()
        )

        for column in range(1, self.tree.columnCount()):
            row_data["item"].setForeground(column, brush)

        if row_data["change_label"] is not None:
            row_data["change_label"].setStyleSheet(
                "color: #d9822b;" if checked else ""
            )

    def _update_summary(self):
        """Show a live total of all currently checked updates."""
        selected_rows = [
            row_data
            for row_data in self._rows
            if row_data["item"].checkState(0) == QtCore.Qt.Checked
        ]
        dot_count = len(selected_rows)
        stamp_count = sum(
            len(row_data["candidate"]["connections"])
            for row_data in selected_rows
        )
        self.summary_label.setText(
            "Selected: Groups ({groups})  •  Dots ({dots})  •  "
            "PostageStamps ({stamps})  •  Total nodes ({total})".format(
                groups=len(selected_rows),
                dots=dot_count,
                stamps=stamp_count,
                total=dot_count + stamp_count
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
        self._set_checked(
            lambda row: (
                not row["unnamed"]
                or bool(_clean_text(row["name_field"].text()))
            )
        )

    def _select_safe(self):
        self._set_checked(lambda row: row["safe"])

    def _select_conflicts(self):
        self._set_checked(
            lambda row: (
                not row["safe"]
                and not row["unnamed"]
                and not row["duplicate"]
            )
        )

    def _select_duplicates(self):
        self._set_checked(lambda row: row["duplicate"])

    def _select_unnamed(self):
        self._set_checked(
            lambda row: (
                row["unnamed"]
                and bool(_clean_text(row["name_field"].text()))
            )
        )

    def _clear_selection(self):
        self._set_checked(lambda _row: False)

    def selected_resolutions(self):
        """Return checked candidates with their selected canonical names."""
        resolutions = []

        for row_data in self._rows:
            if row_data["item"].checkState(0) != QtCore.Qt.Checked:
                continue

            if row_data["name_field"] is not None:
                name = _clean_text(row_data["name_field"].text())
            elif row_data["name_combo"] is None:
                name = row_data["candidate"]["preferred_name"]
            else:
                name = _clean_text(row_data["name_combo"].currentData())

            if name:
                resolutions.append((row_data["candidate"], name))

        return resolutions

    def _duplicate_resolution_errors(self, resolutions):
        """Return names that would remain duplicated after selected fixes."""
        selected_names = {
            candidate["dot"]: name
            for candidate, name in resolutions
        }
        selected_duplicate_dots = {
            row_data["candidate"]["dot"]
            for row_data in self._rows
            if (
                row_data["duplicate"]
                and row_data["candidate"]["dot"] in selected_names
            )
        }
        connected_dots = set()

        for stamp in nuke.allNodes("PostageStamp"):
            try:
                dot = stamp.input(0)
            except Exception:
                continue

            if (
                dot is not None
                and dot.Class() == "Dot"
                and "label" in dot.knobs()
            ):
                connected_dots.add(dot)

        final_names = {}

        for dot in connected_dots:
            name = selected_names.get(
                dot,
                _connector_name(dot["label"].value())
            )

            if not name:
                continue

            final_names.setdefault(name.lower(), []).append(
                (name, dot)
            )

        errors = []

        for grouped_names in final_names.values():
            if len(grouped_names) < 2:
                continue

            if not any(
                dot in selected_duplicate_dots
                for _name, dot in grouped_names
            ):
                continue

            errors.append(grouped_names[0][0])

        return errors

    def _apply_selected(self):
        """Apply checked resolutions, then close the review window."""
        resolutions = self.selected_resolutions()
        duplicate_errors = self._duplicate_resolution_errors(resolutions)

        if duplicate_errors:
            nuke.message(
                "These connector names would still be duplicated:\n\n{}\n\n"
                "Please give each Duplicate row a unique name.".format(
                    "\n".join(sorted(duplicate_errors, key=str.lower))
                )
            )
            return

        for candidate, canonical_name in resolutions:
            candidate["dot"]["label"].setValue(
                _from_label(canonical_name)
            )

            for stamp, _stamp_name in candidate["connections"]:
                stamp["label"].setValue(
                    "To {}".format(canonical_name)
                )

                if "hide_input" in stamp.knobs():
                    stamp["hide_input"].setValue(True)

        self.accept()


def clean_up_connector_labels(on_close=None):
    """Review and normalize PostageStamp and source-Dot label pairs."""
    global _ACTIVE_DIALOG

    if _ACTIVE_DIALOG is not None and _ACTIVE_DIALOG.isVisible():
        existing_on_close = _ACTIVE_DIALOG._on_close
        _ACTIVE_DIALOG._skip_on_close = True
        _ACTIVE_DIALOG.close()
        _ACTIVE_DIALOG = None

        if on_close is None:
            on_close = existing_on_close

    safe, conflicts, duplicates, unnamed = _collect_candidates()

    if not safe and not conflicts and not duplicates and not unnamed:
        nuke.message(
            "All eligible connector labels are already clean."
        )

        if on_close is not None:
            QtCore.QTimer.singleShot(0, on_close)

        return 0

    _ACTIVE_DIALOG = ConnectorCleanupDialog(
        safe,
        conflicts,
        duplicates,
        unnamed,
        on_close=on_close,
        parent=_nuke_main_window()
    )
    dialog = _ACTIVE_DIALOG
    dialog.finished.connect(
        lambda result, closed_dialog=dialog: _cleanup_dialog_finished(
            closed_dialog,
            result
        )
    )
    _ACTIVE_DIALOG.show()
    return _ACTIVE_DIALOG


def _cleanup_dialog_finished(dialog, _result):
    """Release the cleanup window and run its optional return action."""
    global _ACTIVE_DIALOG

    if _ACTIVE_DIALOG is dialog:
        _ACTIVE_DIALOG = None

    if not dialog._skip_on_close and dialog._on_close is not None:
        QtCore.QTimer.singleShot(0, dialog._on_close)
