"""Create AYON Write instances from selected Read and native Write nodes."""

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from qtools import ayon_write_rules


ELIGIBLE_CLASSES = {"Read", "Write"}


def _source_for(node):
    if node.Class() == "Read":
        return node
    return node.input(0)


def _selected_candidates():
    return [node for node in nuke.selectedNodes() if node.Class() in ELIGIBLE_CLASSES]


class PreviewDialog(QtWidgets.QDialog):
    """Preview and edit variants before creating AYON nodes."""

    def __init__(self, candidates, parent=None):
        super(PreviewDialog, self).__init__(parent)
        self.candidates = candidates
        self.setWindowTitle("Create AYON Writes")
        self.resize(820, max(300, min(650, 175 + len(candidates) * 34)))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Review the proposed render variants. Native Write nodes remain in "
            "place; their AYON Write will use the same input."
        ))
        self.table = QtWidgets.QTableWidget(len(candidates), 4)
        self.table.setHorizontalHeaderLabels(
            ["Source node", "Filename", "Render variant", "Rule"]
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
                "Matched" if item["matched"] else "Fallback",
            )
            for column, value in enumerate(values):
                table_item = QtWidgets.QTableWidgetItem(value)
                if column != 2:
                    table_item.setFlags(table_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(row, column, table_item)
        layout.addWidget(self.table)

        lower = QtWidgets.QHBoxLayout()
        rules_button = QtWidgets.QPushButton("Edit rules...")
        lower.addWidget(rules_button)
        lower.addStretch()
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Create")
        lower.addWidget(buttons)
        layout.addLayout(lower)
        rules_button.clicked.connect(self._edit_rules)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

    def _edit_rules(self):
        if ayon_write_rules.edit_rules(self) != QtWidgets.QDialog.Accepted:
            return
        for row, candidate in enumerate(self.candidates):
            variant, matched = ayon_write_rules.proposed_variant(candidate["text"])
            self.table.item(row, 2).setText(variant)
            self.table.item(row, 3).setText("Matched" if matched else "Fallback")

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

    def variants(self):
        return [
            self.table.item(row, 2).text().strip()
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


def _write_creator(context):
    creator = context.creators.get("create_write")
    if creator is not None:
        return creator
    for candidate in context.creators.values():
        if getattr(candidate, "identifier", "") == "create_write":
            return candidate
    raise RuntimeError("AYON's Create Write creator is not available in this session.")


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
        },
        pre_create_data={"use_selection": True},
    )
    return _created_node(instance)


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
        creator = _write_creator(context)
    except Exception as error:
        nuke.message("Could not initialise AYON Create Write:\n\n{}".format(error))
        return []

    created = []
    errors = []
    try:
        nuke.Undo.begin("Create AYON Writes")
        for candidate, variant in zip(candidates, dialog.variants()):
            try:
                node = _create_one(creator, api, candidate["source"], variant)
                if node is not None:
                    reference = candidate["node"]
                    node.setXYpos(reference.xpos() + 140, reference.ypos())
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
