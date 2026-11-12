"""Persistent batch view for the AYON Read representation switcher."""

import traceback

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from . import ayon_read_swap as swap


class ReadSwapWindow(QtWidgets.QDialog):
    def __init__(self, reads):
        super().__init__(QtWidgets.QApplication.activeWindow())
        self.setWindowTitle(swap.TITLE)
        self.setModal(False)
        self.resize(1160, 430)
        self.setMinimumSize(850, 300)
        self.rows = []
        self._busy = False
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel("EXR ↔ MOV · AYON representations")
        font = heading.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        self.instructions = QtWidgets.QLabel(
            "Check the Reads to process. Choose an output where several are available."
        )
        layout.addWidget(self.instructions)
        self.single = QtWidgets.QWidget()
        single_layout = QtWidgets.QVBoxLayout(self.single)
        single_layout.setContentsMargins(0, 0, 0, 0)
        self.product_label = QtWidgets.QLabel()
        self.product_label.setWordWrap(True)
        self.source_label = QtWidgets.QLabel()
        single_layout.addWidget(self.product_label)
        single_layout.addWidget(self.source_label)
        single_layout.addWidget(QtWidgets.QLabel("Representation to load:"))
        self.single_choice = QtWidgets.QVBoxLayout()
        single_layout.addLayout(self.single_choice)
        self.loaded_label = QtWidgets.QLabel()
        self.result_label = QtWidgets.QLabel()
        self.result_label.setWordWrap(True)
        single_layout.addWidget(self.loaded_label)
        single_layout.addWidget(self.result_label)
        layout.addWidget(self.single)
        self.table = QtWidgets.QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Use", "Product", "Source Read", "Load representation",
            "EXR in scene", "MOV in scene", "Version", "Result",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        for column, width in enumerate((44, 260, 145, 230, 100, 100, 70, 200)):
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(7, QtWidgets.QHeaderView.Stretch)
        self.table.itemChanged.connect(self._check_changed)
        layout.addWidget(self.table)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        tools = QtWidgets.QHBoxLayout()
        layout.addLayout(tools)
        self.selection_button = QtWidgets.QPushButton("Reload from selection")
        self.selection_button.clicked.connect(self._reload_selection)
        self.refresh_button = QtWidgets.QPushButton("Refresh loaded status")
        self.refresh_button.clicked.connect(self._render)
        tools.addWidget(self.selection_button)
        tools.addWidget(self.refresh_button)
        tools.addStretch()
        actions = QtWidgets.QHBoxLayout()
        layout.addLayout(actions)
        self.replace_button = QtWidgets.QPushButton("Replace selected Reads")
        self.alongside_button = QtWidgets.QPushButton("Load alongside")
        self.replace_button.clicked.connect(lambda: self._run(True))
        self.alongside_button.clicked.connect(lambda: self._run(False))
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.close)
        for button in (self.replace_button, self.alongside_button, close_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self._set_reads(reads)

    def _set_reads(self, reads):
        self.rows = [swap.BatchRow(node) for node in reads]
        single = len(self.rows) == 1
        self.single.setVisible(single)
        self.table.setVisible(not single)
        self.instructions.setVisible(not single)
        self.replace_button.setText("Replace selected Read" if single else "Replace selected Reads")
        self.setMinimumSize(500, 280) if single else self.setMinimumSize(850, 300)
        self.resize(560, 310) if single else self.resize(1160, 430)
        self._render()

    def _reload_selection(self):
        reads = [node for node in nuke.selectedNodes() if node.Class() == "Read"]
        if reads:
            self._set_reads(reads)
        else:
            self.summary.setText("Select one or more Reads in the graph, then reload.")

    def _item(self, row, column, text, tooltip="", color=None):
        item = QtWidgets.QTableWidgetItem(text)
        item.setToolTip(tooltip or text)
        if color:
            item.setForeground(QtGui.QColor(color))
        self.table.setItem(row, column, item)
        return item

    def _render(self):
        nodes = swap.scene_reads()
        if len(self.rows) == 1:
            self._render_single(self.rows[0], nodes)
            self._update_actions()
            return
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        try:
            for index, row in enumerate(self.rows):
                alive = row.node in nodes
                if not alive:
                    row.checked = False
                context = row.context
                check = self._item(index, 0, "")
                check.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                check.setCheckState(QtCore.Qt.Checked if row.checked else QtCore.Qt.Unchecked)
                if row.error or not alive:
                    check.setFlags(QtCore.Qt.NoItemFlags)
                product = context["product"]["name"] if context else "Unavailable"
                tooltip = ("{} · {}".format(context["project"]["name"],
                           context["folder"]["path"]) if context else row.error)
                self._item(index, 1, product, tooltip)
                self._item(index, 2, row.node.name() if alive else "Read deleted")
                if len(row.candidates) > 1:
                    combo = QtWidgets.QComboBox()
                    for candidate in row.candidates:
                        combo.addItem("{} ({})".format(
                            candidate["name"], swap._extension(candidate).upper()
                        ), candidate["id"])
                    choice = combo.findData(row.target_id)
                    combo.setCurrentIndex(max(0, choice))
                    combo.setEnabled(alive and not row.error)
                    combo.currentIndexChanged.connect(
                        lambda unused, r=row, widget=combo: self._choose(r, widget)
                    )
                    self.table.setCellWidget(index, 3, combo)
                else:
                    text = "{} ({})".format(
                        row.candidates[0]["name"], swap._extension(row.candidates[0]).upper()
                    ) if row.candidates else "Unavailable"
                    self._item(index, 3, text)
                loaded = swap.loaded_formats(context, row.representations, nodes) if context else {}
                both = bool(loaded.get("exr") and loaded.get("mov"))
                for column, extension in ((4, "exr"), (5, "mov")):
                    matching = loaded.get(extension, [])
                    self._item(index, column,
                               "Loaded ({})".format(len(matching)) if matching else "—",
                               "\n".join(node.fullName() for node in matching),
                               "#8dce9b" if matching else None)
                version = context["version"]["version"] if context else None
                self._item(index, 6, "—" if version is None else (
                    "hero" if version < 0 else "v{:03d}".format(version)
                ))
                status = row.error or ("Source Read deleted; reload selection." if not alive else row.status)
                if both and not row.error and alive:
                    status = "Both formats loaded" + (" · " + status if status else "")
                self._item(index, 7, status or "Ready",
                           color="#ec9b8d" if row.error or not alive or row.status.startswith("Failed:") else (
                               "#8dce9b" if both or row.status else None))
        finally:
            self.table.blockSignals(False)
        self._update_actions()

    def _render_single(self, row, nodes):
        alive = row.node in nodes
        row.checked = alive and not row.error
        context = row.context
        product = context["product"]["name"] if context else "Unavailable"
        self.product_label.setText(product)
        self.source_label.setText("Read: {}".format(row.node.name()) if alive else "Read deleted")
        while self.single_choice.count():
            item = self.single_choice.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if len(row.candidates) > 1:
            widget = QtWidgets.QComboBox()
            for candidate in row.candidates:
                widget.addItem("{} ({})".format(
                    candidate["name"], swap._extension(candidate).upper()
                ), candidate["id"])
            widget.setCurrentIndex(max(0, widget.findData(row.target_id)))
            widget.currentIndexChanged.connect(
                lambda unused, r=row, combo=widget: self._choose(r, combo)
            )
            widget.setEnabled(row.checked)
        else:
            candidate = row.candidates[0] if row.candidates else None
            widget = QtWidgets.QLabel("{} ({})".format(
                candidate["name"], swap._extension(candidate).upper()
            ) if candidate else "Unavailable")
        self.single_choice.addWidget(widget)
        loaded = swap.loaded_formats(context, row.representations, nodes) if context else {}
        self.loaded_label.setText("   ·   ".join(
            "{}: {}".format(extension.upper(), "Loaded ({})".format(len(loaded[extension]))
                           if loaded.get(extension) else "Not loaded")
            for extension in ("exr", "mov")
        ))
        both = bool(loaded.get("exr") and loaded.get("mov"))
        status = row.error or (row.status if alive else "Source Read deleted; reload selection.")
        if both:
            status = "Both formats loaded" + (" · " + status if status else "")
        self.result_label.setText(status)

    def _choose(self, row, combo):
        row.target_id = combo.currentData()
        self._update_actions()

    def _check_changed(self, item):
        if item.column() == 0:
            self.rows[item.row()].checked = item.checkState() == QtCore.Qt.Checked
            self._update_actions()

    def _update_actions(self):
        checked = [row for row in self.rows if row.checked and not row.error]
        missing = sum(row.target_id is None for row in checked)
        enabled = bool(checked) and not missing and not self._busy
        self.replace_button.setEnabled(enabled)
        self.alongside_button.setEnabled(enabled)
        if len(self.rows) == 1:
            self.summary.setText(
                "Replace keeps the Read's name, position and connections.\n"
                "Load alongside places a new Read above it."
            )
            return
        self.summary.setText(
            "{} of {} Reads checked{}".format(
                len(checked), len(self.rows),
                " · Choose a representation for {} checked row(s).".format(missing)
                if missing else " · Successful rows are unchecked; the window stays open."
            )
        )

    def _run(self, replace):
        if self._busy:
            return
        checked = [row for row in self.rows if row.checked and not row.error]
        if not checked or any(row.target_id is None for row in checked):
            return
        self._busy = True
        self.table.setEnabled(False)
        self.single.setEnabled(False)
        self.selection_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self._update_actions()
        completed, failed = 0, 0
        try:
            with nuke.Undo():
                nuke.Undo.name(swap.TITLE)
                for row in checked:
                    try:
                        # Validate handles again: users can edit the scene while
                        # this modeless window is open.
                        if row.node not in swap.scene_reads():
                            raise RuntimeError("Source Read was deleted; reload the selection.")
                        path = row.node.fullName().rpartition(".")[0]
                        parent = nuke.toNode(path) if path else nuke.root()
                        with parent:
                            row.apply(replace)
                        completed += 1
                    except Exception as error:
                        row.status = "Failed: {}".format(error)
                        nuke.tprint(traceback.format_exc())
                        failed += 1
        finally:
            self._busy = False
            self.table.setEnabled(True)
            self.single.setEnabled(True)
            self.selection_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self._render()
            if len(self.rows) > 1:
                self.summary.setText("{} completed · {} failed. {}".format(
                    completed, failed,
                    "See each row's result; failed rows stay checked." if failed else
                    "Loaded status updated. Check rows again to run another action."
                ))
