"""Create AYON Write instances from selected Read and native Write nodes."""

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from qtools import ayon_write_rules


ELIGIBLE_CLASSES = {"Read", "Write"}
CREATOR_IDENTIFIERS = {
    "Render": "create_write_render",
    "Prerender": "create_write_prerender",
}


def _source_for(node):
    if node.Class() == "Read":
        return node
    return node.input(0)


def _selected_candidates():
    return [node for node in nuke.selectedNodes() if node.Class() in ELIGIBLE_CLASSES]


def _upstream_read(node):
    """Return the nearest Read upstream, checking inputs from left to right."""
    queue = [node]
    visited = set()
    while queue:
        current = queue.pop(0)
        if current is None or current in visited:
            continue
        visited.add(current)
        if current.Class() == "Read":
            return current
        queue.extend(
            current.input(index)
            for index in range(current.inputs())
            if current.input(index) is not None
        )
    return None


def _read_frame_range(node):
    read = _upstream_read(node)
    if read is None:
        return None
    return int(read["first"].value()), int(read["last"].value())


class PreviewDialog(QtWidgets.QDialog):
    """Preview and edit variants before creating AYON nodes."""

    def __init__(self, candidates, parent=None):
        super(PreviewDialog, self).__init__(parent)
        self.candidates = candidates
        self.setWindowTitle("Create AYON Writes")
        self.resize(1080, max(300, min(650, 175 + len(candidates) * 34)))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Review the proposed render variants. Native Write nodes remain in "
            "place; their AYON Write will use the same input."
        ))
        self.type_combos = []
        self.range_checkboxes = []
        self.table = QtWidgets.QTableWidget(len(candidates), 6)
        self.table.setHorizontalHeaderLabels(
            [
                "Source node", "Filename", "Render variant", "Type",
                "Match range", "Rule",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.Stretch
        )
        for row, item in enumerate(candidates):
            values = (
                item["node"].name(), item["text"], item["variant"],
            )
            for column, value in enumerate(values):
                table_item = QtWidgets.QTableWidgetItem(value)
                if column != 2:
                    table_item.setFlags(table_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(row, column, table_item)

            type_combo = QtWidgets.QComboBox()
            type_combo.addItems(["Render", "Prerender"])
            self.table.setCellWidget(row, 3, type_combo)
            self.type_combos.append(type_combo)

            range_checkbox = QtWidgets.QCheckBox()
            range_checkbox.setToolTip(
                "Copy the nearest upstream Read's first/last frames and enable "
                "Limit to range."
            )
            range_holder = QtWidgets.QWidget()
            range_layout = QtWidgets.QHBoxLayout(range_holder)
            range_layout.setContentsMargins(0, 0, 0, 0)
            range_layout.setAlignment(QtCore.Qt.AlignCenter)
            range_layout.addWidget(range_checkbox)
            self.table.setCellWidget(row, 4, range_holder)
            self.range_checkboxes.append(range_checkbox)

            rule_item = QtWidgets.QTableWidgetItem(
                "Matched" if item["matched"] else "Fallback"
            )
            rule_item.setFlags(rule_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(row, 5, rule_item)
        layout.addWidget(self.table)

        lower = QtWidgets.QHBoxLayout()
        rules_button = QtWidgets.QPushButton("Edit rules...")
        lower.addWidget(rules_button)
        render_all_button = QtWidgets.QPushButton("All Render")
        prerender_all_button = QtWidgets.QPushButton("All Prerender")
        match_all_button = QtWidgets.QPushButton("Match all ranges")
        clear_ranges_button = QtWidgets.QPushButton("Clear ranges")
        lower.addWidget(render_all_button)
        lower.addWidget(prerender_all_button)
        lower.addWidget(match_all_button)
        lower.addWidget(clear_ranges_button)
        lower.addStretch()
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Create")
        lower.addWidget(buttons)
        layout.addLayout(lower)
        rules_button.clicked.connect(self._edit_rules)
        render_all_button.clicked.connect(
            lambda _checked=False: self._set_all_types("Render")
        )
        prerender_all_button.clicked.connect(
            lambda _checked=False: self._set_all_types("Prerender")
        )
        match_all_button.clicked.connect(
            lambda _checked=False: self._set_all_ranges(True)
        )
        clear_ranges_button.clicked.connect(
            lambda _checked=False: self._set_all_ranges(False)
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

    def _edit_rules(self):
        if ayon_write_rules.edit_rules(self) != QtWidgets.QDialog.Accepted:
            return
        for row, candidate in enumerate(self.candidates):
            variant, matched = ayon_write_rules.proposed_variant(candidate["text"])
            self.table.item(row, 2).setText(variant)
            self.table.item(row, 5).setText("Matched" if matched else "Fallback")

    def _set_all_types(self, creator_type):
        for combo in self.type_combos:
            combo.setCurrentText(creator_type)

    def _set_all_ranges(self, enabled):
        for checkbox in self.range_checkboxes:
            checkbox.setChecked(enabled)

    def _accept_if_valid(self):
        empty = [
            row for row in range(self.table.rowCount())
            if not self.table.item(row, 2).text().strip()
        ]
        if empty:
            QtWidgets.QMessageBox.warning(
                self, "Missing variant", "Every row needs a render variant."
            )
            return
        self.accept()

    def creation_options(self):
        return [
            {
                "variant": self.table.item(row, 2).text().strip(),
                "creator_identifier": CREATOR_IDENTIFIERS[
                    self.type_combos[row].currentText()
                ],
                "match_frame_range": self.range_checkboxes[row].isChecked(),
            }
            for row in range(self.table.rowCount())
        ]


def _ayon_api():
    try:
        from ayon_core.pipeline import (
            get_current_folder_path,
            get_current_project_name,
            get_current_task_name,
            registered_host,
        )
        from ayon_core.pipeline.context_tools import (
            get_current_folder_entity,
            get_current_task_entity,
        )
        from ayon_core.pipeline.create import CreateContext
    except ImportError as error:
        raise RuntimeError(
            "AYON's Python modules are unavailable. Launch Nuke through AYON "
            "and try again."
        ) from error
    return {
        "CreateContext": CreateContext,
        "host": registered_host(),
        "project_name": get_current_project_name(),
        "folder_path": get_current_folder_path(),
        "task_name": get_current_task_name(),
        "folder_entity": get_current_folder_entity(),
        "task_entity": get_current_task_entity(),
    }


def _write_creator(context, identifier="create_write_render"):
    # Newer AYON Nuke versions expose separate Render, Prerender and Image
    # creators. Older versions used one generic Write creator.
    identifiers = [identifier]
    if identifier == "create_write_render":
        identifiers.append("create_write")
    for candidate_identifier in identifiers:
        creator = context.creators.get(candidate_identifier)
        if creator is not None:
            return creator

    likely_creators = []
    for candidate in context.creators.values():
        if getattr(candidate, "identifier", "") in identifiers:
            return candidate
        label = str(getattr(candidate, "label", "") or "").lower()
        product_type = str(getattr(candidate, "product_type", "") or "").lower()
        class_name = candidate.__class__.__name__.lower()
        requested_type = (
            "prerender" if identifier == "create_write_prerender" else "render"
        )
        if (
            label == requested_type
            or product_type == requested_type
            or requested_type in class_name
        ):
            likely_creators.append(candidate)

    if len(likely_creators) == 1:
        return likely_creators[0]

    available = []
    for identifier, candidate in context.creators.items():
        available.append("{} ({})".format(
            identifier, getattr(candidate, "label", candidate.__class__.__name__)
        ))
    disabled = sorted(getattr(context, "disabled_creators", {}) or {})
    details = "\n\nDiscovered creators:\n{}".format(
        "\n".join(available) if available else "None"
    )
    if disabled:
        details += "\n\nDisabled creators:\n{}".format("\n".join(disabled))
    if len(likely_creators) > 1:
        details += "\n\nMore than one possible Write creator was found."
    raise RuntimeError(
        "AYON creator '{}' could not be selected in this session.{}".format(
            identifier, details
        )
    )


def _created_node(instance):
    try:
        return instance.transient_data.get("node")
    except Exception:
        return None


def _create_one(creator, api, source_node, variant):
    product_name = creator.get_product_name(
        api["project_name"], api["folder_entity"], api["task_entity"], variant
    )
    for node in nuke.allNodes():
        node.setSelected(node is source_node)
    instance = creator.create(
        product_name=product_name,
        instance_data={
            "folderPath": api["folder_path"],
            "task": api["task_name"],
            "variant": variant,
            "productType": creator.product_type,
        },
        pre_create_data={"use_selection": True},
    )
    return _created_node(instance)


def _set_frame_range(group_node, frame_range):
    """Set range knobs on the AYON group and its internal Write node."""
    first, last = frame_range
    targets = [group_node]
    try:
        targets.extend(nuke.allNodes("Write", group=group_node))
    except Exception:
        pass

    for target in targets:
        knobs = target.knobs()
        if "first" in knobs:
            target["first"].setValue(first)
        if "last" in knobs:
            target["last"].setValue(last)
        if "use_limit" in knobs:
            target["use_limit"].setValue(True)


def create_ayon_writes():
    """Create AYON Write nodes for the selected Reads/native Writes."""
    selected = list(nuke.selectedNodes())
    candidates = []
    invalid_writes = []
    for node in _selected_candidates():
        source = _source_for(node)
        if source is None:
            invalid_writes.append(node.name())
            continue
        text = ayon_write_rules.source_text(node)
        variant, matched = ayon_write_rules.proposed_variant(text)
        candidates.append({
            "node": node,
            "source": source,
            "text": text,
            "variant": variant,
            "matched": matched,
        })

    if not candidates:
        message = "Select at least one Read or native Write node."
        if invalid_writes:
            message += "\n\nThe selected Write nodes have no input."
        nuke.message(message)
        return []

    dialog = PreviewDialog(candidates)
    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return []

    try:
        api = _ayon_api()
        context = api["CreateContext"](
            host=api["host"], headless=True, discover_publish_plugins=False
        )
    except Exception as error:
        nuke.message("Could not initialise AYON Create Write:\n\n{}".format(error))
        return []

    created = []
    errors = []
    creators = {}
    try:
        nuke.Undo.begin("Create AYON Writes")
        for candidate, options in zip(candidates, dialog.creation_options()):
            try:
                identifier = options["creator_identifier"]
                if identifier not in creators:
                    creators[identifier] = _write_creator(context, identifier)
                creator = creators[identifier]
                frame_range = None
                if options["match_frame_range"]:
                    frame_range = _read_frame_range(candidate["source"])
                    if frame_range is None:
                        raise RuntimeError("no upstream Read node was found")
                node = _create_one(
                    creator, api, candidate["source"], options["variant"]
                )
                if node is not None:
                    reference = candidate["node"]
                    node.setXYpos(reference.xpos() + 140, reference.ypos())
                    if frame_range is not None:
                        _set_frame_range(node, frame_range)
                    created.append(node)
            except Exception as error:
                errors.append("{}: {}".format(candidate["node"].name(), error))
    finally:
        nuke.Undo.end()
        for node in nuke.allNodes():
            node.setSelected(node in selected)
        for node in created:
            node.setSelected(True)

    if errors:
        nuke.message(
            "Created {} AYON Write(s).\n\nFailed:\n{}".format(
                len(created), "\n".join(errors)
            )
        )
    return created
