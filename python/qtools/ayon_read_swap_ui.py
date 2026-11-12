"""Compact selection summary and sequential AYON representation choices."""

import traceback

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from . import ayon_read_swap as swap


class ReadSwapWindow(QtWidgets.QDialog):
    def __init__(self, reads):
        super().__init__(QtWidgets.QApplication.activeWindow())
        self.setWindowTitle(swap.TITLE)
        self.setModal(False)
        self.setMinimumWidth(520)
        self.resize(600, 340)
        self.plan = swap.SelectionPlan([swap.BatchRow(node) for node in reads])
        self._busy = False
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel()
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)
        self.instructions = QtWidgets.QLabel()
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)
        self.automatic_list = QtWidgets.QListWidget()
        self.automatic_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.automatic_list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.automatic_list.setMaximumHeight(180)
        layout.addWidget(self.automatic_list)
        self.detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.product = QtWidgets.QLabel()
        self.product.setTextFormat(QtCore.Qt.PlainText)
        self.product.setWordWrap(True)
        self.source = QtWidgets.QLabel()
        self.source.setTextFormat(QtCore.Qt.PlainText)
        detail_layout.addWidget(self.product)
        detail_layout.addWidget(self.source)
        detail_layout.addWidget(QtWidgets.QLabel("Representation to load:"))
        self.choice_layout = QtWidgets.QVBoxLayout()
        detail_layout.addLayout(self.choice_layout)
        self.loaded = QtWidgets.QLabel()
        detail_layout.addWidget(self.loaded)
        layout.addWidget(self.detail)
        self.result = QtWidgets.QLabel()
        self.result.setTextFormat(QtCore.Qt.PlainText)
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        layout.addWidget(QtWidgets.QLabel(
            "Replace keeps the Read's name, position and connections.\n"
            "Load alongside places each new Read above its source."
        ))
        buttons = QtWidgets.QHBoxLayout()
        layout.addLayout(buttons)
        self.back_button = QtWidgets.QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        self.replace_button = QtWidgets.QPushButton("Replace selected Reads")
        self.replace_button.clicked.connect(lambda: self._start(True))
        self.alongside_button = QtWidgets.QPushButton("Load alongside")
        self.alongside_button.clicked.connect(lambda: self._start(False))
        self.next_button = QtWidgets.QPushButton("Next")
        self.next_button.clicked.connect(self._next)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.back_button, self.replace_button, self.alongside_button,
                       self.next_button, self.cancel_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self._overview()

    @staticmethod
    def _target_text(row):
        target = next(item for item in row.candidates if item["id"] == row.target_id)
        return "{} ({})".format(target["name"], swap._extension(target).upper())

    def _overview(self):
        single = len(self.plan.rows) == 1
        self.heading.setText("Switch representation" if single else
                             "Switch representations for {} Reads".format(len(self.plan.valid)))
        self.automatic_list.clear()
        if not single:
            for row in self.plan.automatic:
                item = QtWidgets.QListWidgetItem("{} · {} → {}".format(
                    row.context["product"]["name"], row.node.name(), self._target_text(row)
                ))
                item.setToolTip(item.text())
                self.automatic_list.addItem(item)
        self.automatic_list.setVisible(not single and bool(self.plan.automatic))
        self.detail.setVisible(single and bool(self.plan.valid))
        if single and self.plan.valid:
            self._show_read(self.plan.valid[0])
        count = len(self.plan.choices)
        self.instructions.setText(
            "Choose the representation and action." if single else
            ("{} Reads have one available target. {} Reads need a choice; "
             "select an action below, then choose their representations one at a time."
             .format(len(self.plan.automatic), count) if count else
             "Each Read has one available target. The chosen action applies to all listed Reads.")
        )
        errors = ["{}: {}".format(row.node.name(), row.error)
                  for row in self.plan.rows if row.error]
        self.result.setText("Skipped:\n" + "\n".join(errors) if errors else "")
        self.back_button.hide()
        self.next_button.hide()
        self.replace_button.show()
        self.replace_button.setText("Replace selected Read" if single else "Replace selected Reads")
        self.alongside_button.show()
        self.replace_button.setEnabled(bool(self.plan.valid))
        self.alongside_button.setEnabled(bool(self.plan.valid))

    def _show_read(self, row):
        self.product.setText(row.context["product"]["name"])
        self.source.setText("Read: {}".format(row.node.name()))
        while self.choice_layout.count():
            widget = self.choice_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        if len(row.candidates) > 1:
            widget = QtWidgets.QComboBox()
            for candidate in row.candidates:
                widget.addItem("{} ({})".format(
                    candidate["name"], swap._extension(candidate).upper()
                ), candidate["id"])
            widget.setCurrentIndex(max(0, widget.findData(row.target_id)))
            widget.currentIndexChanged.connect(
                lambda unused, r=row, combo=widget: setattr(r, "target_id", combo.currentData())
            )
        else:
            widget = QtWidgets.QLabel(self._target_text(row))
        self.choice_layout.addWidget(widget)
        loaded = swap.loaded_formats(row.context, row.representations, swap.scene_reads())
        self.loaded.setText("   ·   ".join(
            "{}: {}".format(ext.upper(), "Loaded ({})".format(len(loaded[ext]))
                           if loaded[ext] else "Not loaded") for ext in ("exr", "mov")
        ))

    def _start(self, replace):
        if self._busy:
            return
        self.plan.start(replace)
        if self.plan.ready:
            self._run()
        else:
            self._review()

    def _review(self):
        row = self.plan.current
        self.heading.setText("Choose representation · {} of {}".format(
            self.plan.choice_index + 1, len(self.plan.choices)
        ))
        self.instructions.setText(
            "The same {} action will apply to all {} Reads after the last choice."
            .format("Replace" if self.plan.replace else "Load alongside", len(self.plan.valid))
        )
        self.automatic_list.hide()
        self.detail.show()
        self._show_read(row)
        self.result.clear()
        self.replace_button.hide()
        self.alongside_button.hide()
        self.back_button.show()
        self.next_button.show()
        last = self.plan.choice_index == len(self.plan.choices) - 1
        self.next_button.setText(
            ("Replace {} Reads" if self.plan.replace else "Load {} Reads alongside")
            .format(len(self.plan.valid)) if last else "Next"
        )

    def _next(self):
        self.plan.advance()
        if self.plan.ready:
            self._run()
        else:
            self._review()

    def _back(self):
        self.plan.back()
        if self.plan.replace is None:
            self._overview()
        else:
            self._review()

    def _run(self):
        if self._busy or not self.plan.ready:
            return
        self._busy = True
        self.setEnabled(False)
        failures = []
        skipped = [row for row in self.plan.rows if row.error]
        completed = 0
        try:
            with nuke.Undo():
                nuke.Undo.name(swap.TITLE)
                for row in self.plan.valid:
                    try:
                        if row.node not in swap.scene_reads():
                            raise RuntimeError("Source Read was deleted.")
                        path = row.node.fullName().rpartition(".")[0]
                        parent = nuke.toNode(path) if path else nuke.root()
                        with parent:
                            row.apply(self.plan.replace)
                        completed += 1
                    except Exception as error:
                        row.status = "{}: {}".format(row.node.name(), error)
                        failures.append(row)
                        nuke.tprint(traceback.format_exc())
        finally:
            self._busy = False
            self.setEnabled(True)
        if not failures and not skipped:
            self.accept()
            return
        # Only failed Reads remain eligible for retry; completed ones never reload.
        self.plan = swap.SelectionPlan(failures + skipped)
        self._overview()
        messages = [row.status for row in failures] + [
            "{}: {}".format(row.node.name(), row.error) for row in skipped
        ]
        self.result.setText("{} completed · {} failed · {} skipped\n{}".format(
            completed, len(failures), len(skipped), "\n".join(messages)
        ))
