"""Folder-based production notes in a dockable Nuke panel."""

import datetime
import json
import os
import re
import uuid

import nuke
import nukescripts

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


PANEL_ID = "com.qtools.ShotNotes"
PANEL_TITLE = "Shot Notes"
NOTES_FILENAME = ".qtools_shot_notes.json"
WIDGET_EXPRESSION = (
    "__import__('qtools.shot_notes', "
    "fromlist=['ShotNotesWidget']).ShotNotesWidget"
)
_PANEL_REGISTERED = False


def _script_path():
    """Return the current saved Nuke script path."""
    try:
        path = str(nuke.root()["name"].value() or "")
    except Exception:
        return ""

    if not path or path == "Root":
        return ""

    return os.path.abspath(path)


def _notes_path():
    """Return the notes file belonging to the current script folder."""
    script_path = _script_path()

    if not script_path:
        return ""

    return os.path.join(
        os.path.dirname(script_path),
        NOTES_FILENAME
    )


def _empty_data():
    """Return a new notes document."""
    return {
        "version": 1,
        "notes": [],
        "archives": [],
    }


def _parse_note_text(value):
    """Return clean notes, removing leading dash and asterisk bullets."""
    notes = []

    for line in str(value or "").splitlines():
        text = re.sub(r"^\s*[-*]\s*", "", line).strip()

        if text:
            notes.append(text)

    return notes


def _today():
    """Return today's date in the format used by Shot Notes."""
    return datetime.datetime.now().strftime("%d/%m/%y")


def _note_tooltip(note, include_script=True):
    """Return the recorded lifecycle details for a note."""
    created = note.get("created_date") or "Not recorded"
    completed = note.get("completed_date") or "Not completed"
    lines = ["Created: {}".format(created)]

    if include_script:
        script = note.get("script") or "Not completed"
        lines.append("File: {}".format(script))

    lines.append("Completed: {}".format(completed))
    return "\n".join(lines)


def _load_data(path):
    """Load notes from path, returning an empty document when absent."""
    if not path or not os.path.exists(path):
        return _empty_data()

    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except Exception as error:
        nuke.message(
            "Shot Notes could not read:\n\n{}\n\n{}".format(path, error)
        )
        return _empty_data()

    if not isinstance(data, dict):
        return _empty_data()

    data.setdefault("version", 1)
    data.setdefault("notes", [])
    data.setdefault("archives", [])
    return data


def _save_data(path, data):
    """Save notes atomically beside the current Nuke script."""
    if not path:
        return False

    temporary_path = "{}.tmp".format(path)

    try:
        with open(temporary_path, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary_path, path)
    except Exception as error:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except Exception:
            pass

        nuke.message(
            "Shot Notes could not save:\n\n{}\n\n{}".format(path, error)
        )
        return False

    return True


class NoteEditDialog(QtWidgets.QDialog):
    """Comfortable multiline editor for one existing note."""

    def __init__(self, text, parent=None):
        super(NoteEditDialog, self).__init__(parent)
        self.setWindowTitle("Edit note")
        self.resize(700, 360)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Note:"))
        self.editor = QtWidgets.QPlainTextEdit(text)
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.editor, 1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.editor.selectAll()
        self.editor.setFocus()

    def text(self):
        return self.editor.toPlainText()


class NoteRow(QtWidgets.QWidget):
    """One checkable note with a compact remove button."""

    changed = QtCore.Signal()
    edit_requested = QtCore.Signal(str)
    remove_requested = QtCore.Signal(str)

    def __init__(self, note, parent=None):
        super(NoteRow, self).__init__(parent)
        self.note_id = note["id"]

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setChecked(bool(note.get("done", False)))
        self.checkbox.setToolTip(_note_tooltip(note))
        layout.addWidget(self.checkbox)

        self.text_label = QtWidgets.QLabel(note["text"])
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.text_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self.text_label.setToolTip(_note_tooltip(note))
        self.text_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred
        )
        layout.addWidget(self.text_label, 1)

        edit_button = QtWidgets.QToolButton()
        edit_button.setText("Edit")
        edit_button.setToolTip("Edit this note")
        edit_button.setAutoRaise(True)
        layout.addWidget(edit_button)

        remove_button = QtWidgets.QToolButton()
        remove_button.setText("×")
        remove_button.setToolTip("Delete this note")
        remove_button.setAutoRaise(True)
        layout.addWidget(remove_button)

        self.checkbox.toggled.connect(self._checked_changed)
        edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.note_id)
        )
        remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.note_id)
        )
        self._update_done_style()

    def _checked_changed(self):
        self._update_done_style()
        self.changed.emit()

    def _update_done_style(self):
        font = self.text_label.font()
        font.setStrikeOut(False)
        self.text_label.setFont(font)
        self.text_label.setStyleSheet(
            "color: #888888;" if self.checkbox.isChecked() else ""
        )

    def row_size_hint(self, width):
        """Return a row height that accommodates the wrapped note text."""
        layout = self.layout()
        available = max(80, int(width) - 105)
        text_height = self.text_label.heightForWidth(available)
        control_height = max(
            layout.itemAt(index).widget().sizeHint().height()
            for index in range(layout.count())
            if layout.itemAt(index).widget() is not None
        )
        height = max(text_height, control_height) + 8
        return QtCore.QSize(max(0, int(width)), int(height))


class ShotNotesWidget(QtWidgets.QWidget):
    """Dockable notes UI stored once per script folder."""

    def __init__(self, parent=None):
        super(ShotNotesWidget, self).__init__(parent)
        self._path = ""
        self._data = _empty_data()
        self._rows = {}
        self._row_items = {}

        self._build_ui()
        self._switch_folder(force=True)

        self._folder_timer = QtCore.QTimer(self)
        self._folder_timer.setInterval(1500)
        self._folder_timer.timeout.connect(self._switch_folder)
        self._folder_timer.start()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.location_label = QtWidgets.QLabel()
        self.location_label.setToolTip(
            "Notes are shared by every Nuke script saved in this folder."
        )
        layout.addWidget(self.location_label)

        self.single_note_input = QtWidgets.QLineEdit()
        self.single_note_input.setPlaceholderText(
            "Add a note and press Enter…"
        )
        self.single_note_input.setToolTip(
            "Type one note and press Enter to add it immediately."
        )
        self.single_note_input.returnPressed.connect(
            self._add_single_note
        )
        layout.addWidget(self.single_note_input)

        add_notes_header = QtWidgets.QHBoxLayout()
        self.add_notes_toggle = QtWidgets.QToolButton()
        self.add_notes_toggle.setText("MULTILINE EDITOR")
        self.add_notes_toggle.setCheckable(True)
        self.add_notes_toggle.setChecked(False)
        self.add_notes_toggle.setArrowType(QtCore.Qt.RightArrow)
        self.add_notes_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonTextBesideIcon
        )
        self.add_notes_toggle.setToolTip(
            "Show or hide the editor for adding several notes at once."
        )
        add_notes_header.addWidget(self.add_notes_toggle)
        add_notes_header.addStretch()

        self.clipboard_button = QtWidgets.QPushButton(
            "Add Notes from Clipboard"
        )
        self.clipboard_button.setToolTip(
            "Create notes from clipboard lines and remove - or * bullets."
        )
        self.clipboard_button.clicked.connect(
            self._add_notes_from_clipboard
        )
        add_notes_header.addWidget(self.clipboard_button)
        layout.addLayout(add_notes_header)

        self.add_notes_widget = QtWidgets.QWidget()
        add_notes_layout = QtWidgets.QVBoxLayout(self.add_notes_widget)
        add_notes_layout.setContentsMargins(0, 0, 0, 0)
        add_notes_layout.setSpacing(6)

        self.note_input = QtWidgets.QPlainTextEdit()
        self.note_input.setPlaceholderText(
            "Add a note…\nPaste multiple lines to create multiple notes."
        )
        self.note_input.setMaximumHeight(90)
        self.note_input.setToolTip(
            "Enter one note per line. Leading - and * bullets are removed."
        )
        add_notes_layout.addWidget(self.note_input)

        self.add_button = QtWidgets.QPushButton("Add Notes")
        self.add_button.setToolTip(
            "Create one checklist item from each non-empty line."
        )
        self.add_button.clicked.connect(self._add_notes)
        add_notes_layout.addWidget(self.add_button)
        self.add_notes_widget.setVisible(False)
        layout.addWidget(self.add_notes_widget)
        self.add_notes_toggle.toggled.connect(
            self._set_add_notes_expanded
        )

        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.setAlternatingRowColors(True)
        self.notes_list.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        self.notes_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        layout.addWidget(self.notes_list, 1)

        actions = QtWidgets.QHBoxLayout()
        self.copy_done_button = QtWidgets.QPushButton("Copy Done")
        self.copy_done_button.setToolTip(
            "Copy all checked notes to the clipboard."
        )
        self.copy_done_button.clicked.connect(self._copy_done)
        actions.addWidget(self.copy_done_button)

        self.copy_all_button = QtWidgets.QPushButton("Copy All")
        self.copy_all_button.setToolTip(
            "Copy separate DONE and LEFT TO DO note lists."
        )
        self.copy_all_button.clicked.connect(self._copy_all)
        actions.addWidget(self.copy_all_button)

        self.archive_done_button = QtWidgets.QPushButton("Archive Done")
        self.archive_done_button.setToolTip(
            "Move checked notes into a dated archive."
        )
        self.archive_done_button.clicked.connect(self._archive_done)
        actions.addWidget(self.archive_done_button)
        layout.addLayout(actions)

        self.archives = QtWidgets.QTreeWidget()
        self.archives.setColumnCount(3)
        self.archives.setHeaderHidden(True)
        self.archives.setRootIsDecorated(True)
        self.archives.setAlternatingRowColors(True)
        self.archives.setWordWrap(True)
        archive_header = self.archives.header()
        archive_header.setStretchLastSection(False)
        archive_header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        archive_header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        archive_header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.Fixed
        )
        self.archives.setColumnWidth(2, 24)
        self.archives.setToolTip(
            "Expand an archive to see each completed note and its script version."
        )
        self.archives_toggle = QtWidgets.QToolButton()
        self.archives_toggle.setText("ARCHIVES")
        self.archives_toggle.setCheckable(True)
        self.archives_toggle.setChecked(True)
        self.archives_toggle.setArrowType(QtCore.Qt.DownArrow)
        self.archives_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonTextBesideIcon
        )
        self.archives_toggle.setToolTip(
            "Show or hide archived completed notes."
        )
        self.archives_toggle.toggled.connect(
            self._set_archives_expanded
        )
        layout.addWidget(self.archives_toggle)
        layout.addWidget(self.archives, 1)

    def _switch_folder(self, force=False):
        """Reload when the current script changes to another folder."""
        path = _notes_path()

        if not force and path == self._path:
            return

        self._path = path
        self._data = _load_data(path)
        self._refresh()

    def _refresh(self):
        """Rebuild the visible checklist and archive history."""
        self.notes_list.clear()
        self._rows = {}
        self._row_items = {}

        for note in self._data["notes"]:
            if "id" not in note:
                note["id"] = uuid.uuid4().hex

            item = QtWidgets.QListWidgetItem()
            row = NoteRow(note, self.notes_list)
            self.notes_list.addItem(item)
            self.notes_list.setItemWidget(item, row)
            self._rows[note["id"]] = row
            self._row_items[note["id"]] = item
            row.changed.connect(self._note_state_changed)
            row.edit_requested.connect(self._edit_note)
            row.remove_requested.connect(self._remove_note)

        self._update_note_row_sizes()

        self.archives.clear()

        for archive_index in range(len(self._data["archives"]) - 1, -1, -1):
            archive = self._data["archives"][archive_index]
            parent = QtWidgets.QTreeWidgetItem([
                archive.get("date", ""),
                "",
                "",
            ])
            parent.setFirstColumnSpanned(True)
            self.archives.addTopLevelItem(parent)

            for note_index, note in enumerate(archive.get("notes", [])):
                if isinstance(note, dict):
                    text = note.get("text", "")
                    script = note.get("script", "")
                else:
                    # Archives written by older versions stored the script on
                    # the date group and each note as a plain string.
                    text = note
                    script = archive.get("script", "")

                child = QtWidgets.QTreeWidgetItem(parent, [text, script, ""])
                child.setTextAlignment(1, QtCore.Qt.AlignRight)
                if isinstance(note, dict):
                    tooltip = _note_tooltip(note, include_script=False)
                else:
                    tooltip = (
                        "Created: Not recorded\nCompleted: Not recorded"
                    )
                child.setToolTip(0, tooltip)
                child.setToolTip(1, tooltip)

                remove_button = QtWidgets.QToolButton(self.archives)
                remove_button.setText("×")
                remove_button.setToolTip("Delete this archived note")
                remove_button.setAutoRaise(True)
                remove_button.clicked.connect(
                    lambda checked=False, archive_index=archive_index,
                    note_index=note_index: self._remove_archived_note(
                        archive_index, note_index
                    )
                )
                self.archives.setItemWidget(child, 2, remove_button)

        self.archives_toggle.setText(
            "ARCHIVES ({})".format(len(self._data["archives"]))
        )
        folder = os.path.dirname(self._path) if self._path else ""
        self.location_label.setText(
            folder if folder else "Save the Nuke script to enable Shot Notes."
        )
        enabled = bool(self._path)
        self.single_note_input.setEnabled(enabled)
        self.note_input.setEnabled(enabled)
        self.add_button.setEnabled(enabled)
        self.clipboard_button.setEnabled(enabled)
        self._update_action_buttons()

    def _update_action_buttons(self):
        """Enable completed-note actions only when they can do something."""
        has_notes = bool(self._path) and bool(self._data["notes"])
        has_done = bool(self._path) and any(
            note.get("done", False)
            for note in self._data["notes"]
        )
        self.copy_done_button.setEnabled(has_done)
        self.copy_all_button.setEnabled(has_notes)
        self.archive_done_button.setEnabled(has_done)

    def _set_add_notes_expanded(self, expanded):
        """Show or collapse the note-entry controls."""
        self.add_notes_widget.setVisible(expanded)
        self.add_notes_toggle.setArrowType(
            QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow
        )

        if expanded:
            self.note_input.setFocus()

    def _set_archives_expanded(self, expanded):
        """Show or collapse the archive history."""
        self.archives.setVisible(expanded)
        self.archives_toggle.setArrowType(
            QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow
        )

    def _save(self):
        """Persist the current folder's notes."""
        _save_data(self._path, self._data)

    def resizeEvent(self, event):
        super(ShotNotesWidget, self).resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._update_note_row_sizes)

    def _update_note_row_sizes(self):
        """Resize checklist rows when wrapping changes with panel width."""
        if not hasattr(self, "notes_list"):
            return

        width = max(120, self.notes_list.viewport().width() - 6)

        for note_id, row in self._rows.items():
            item = self._row_items.get(note_id)

            if item is not None:
                item.setSizeHint(row.row_size_hint(width))

    def _add_single_note(self):
        """Add the always-visible single-line note when Enter is pressed."""
        if not self._path:
            nuke.message("Save the Nuke script before adding Shot Notes.")
            return

        texts = _parse_note_text(self.single_note_input.text())

        if not texts:
            return

        self._append_notes(texts)
        self.single_note_input.clear()
        self.single_note_input.setFocus()

    def _add_notes(self):
        """Turn every non-empty input line into a checklist item."""
        if not self._path:
            nuke.message("Save the Nuke script before adding Shot Notes.")
            return

        texts = _parse_note_text(self.note_input.toPlainText())

        if not texts:
            return

        self._append_notes(texts)
        self.note_input.clear()
        self.note_input.setFocus()

    def _add_notes_from_clipboard(self):
        """Create checklist items from the current clipboard text."""
        if not self._path:
            nuke.message("Save the Nuke script before adding Shot Notes.")
            return

        texts = _parse_note_text(
            QtWidgets.QApplication.clipboard().text()
        )

        if texts:
            self._append_notes(texts)

    def _append_notes(self, texts):
        """Append note strings and persist them."""
        for text in texts:
            self._data["notes"].append({
                "id": uuid.uuid4().hex,
                "text": text,
                "done": False,
                "created_date": _today(),
            })

        self._save()
        self._refresh()

    def _note_state_changed(self):
        """Copy checkbox states back into the stored data."""
        for note in self._data["notes"]:
            row = self._rows.get(note["id"])

            if row is not None:
                was_done = bool(note.get("done", False))
                is_done = row.checkbox.isChecked()
                note["done"] = is_done

                if is_done and not was_done:
                    note["script"] = os.path.basename(_script_path())
                    note["completed_date"] = _today()
                elif not is_done:
                    note.pop("script", None)
                    note.pop("completed_date", None)

                tooltip = _note_tooltip(note)
                row.checkbox.setToolTip(tooltip)
                row.text_label.setToolTip(tooltip)

        self._save()
        self._update_action_buttons()

    def _edit_note(self, note_id):
        """Edit an existing active note without changing its lifecycle data."""
        note = next(
            (
                candidate for candidate in self._data["notes"]
                if candidate.get("id") == note_id
            ),
            None
        )

        if note is None:
            return

        dialog = NoteEditDialog(
            note.get("text", ""),
            parent=self
        )

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return

        text = " ".join(str(dialog.text() or "").split())

        if not text:
            nuke.message("A note cannot be empty.")
            return

        note["text"] = text
        self._save()
        self._refresh()

    def _remove_note(self, note_id):
        """Delete one checklist item."""
        self._data["notes"] = [
            note
            for note in self._data["notes"]
            if note.get("id") != note_id
        ]
        self._save()
        self._refresh()

    def _remove_archived_note(self, archive_index, note_index):
        """Delete one archived note and discard its group when empty."""
        try:
            archive = self._data["archives"][archive_index]
            del archive["notes"][note_index]
        except (IndexError, KeyError, TypeError):
            return

        if not archive["notes"]:
            del self._data["archives"][archive_index]

        self._save()
        self._refresh()

    def _done_texts(self):
        """Return checked note text in checklist order."""
        return [
            note["text"]
            for note in self._data["notes"]
            if note.get("done", False)
        ]

    def _copy_done(self):
        """Copy completed notes as a simple bullet list."""
        texts = self._done_texts()

        if not texts:
            return

        QtWidgets.QApplication.clipboard().setText(
            "DONE:\n{}".format(
                "\n".join("- {}".format(text) for text in texts)
            )
        )

    def _copy_all(self):
        """Copy all notes in separate completed and remaining sections."""
        done = self._done_texts()
        remaining = [
            note["text"]
            for note in self._data["notes"]
            if not note.get("done", False)
        ]

        def section(title, texts):
            lines = [title]
            lines.extend(
                "- {}".format(text)
                for text in texts
            )

            if not texts:
                lines.append("- None")

            return "\n".join(lines)

        QtWidgets.QApplication.clipboard().setText(
            "{}\n\n{}".format(
                section("DONE:", done),
                section("LEFT TO DO:", remaining)
            )
        )

    def _archive_done(self):
        """Archive completed notes under the current date."""
        completed_notes = [
            {
                "text": note["text"],
                "script": note.get("script", ""),
                "created_date": note.get("created_date", ""),
                "completed_date": note.get("completed_date", ""),
            }
            for note in self._data["notes"]
            if note.get("done", False)
        ]

        if not completed_notes:
            return

        self._data["archives"].append({
            "date": _today(),
            "notes": completed_notes,
        })
        self._data["notes"] = [
            note
            for note in self._data["notes"]
            if not note.get("done", False)
        ]
        self._save()
        self._refresh()


def register_panel():
    """Register Shot Notes in Nuke's Pane menu and workspace system."""
    global _PANEL_REGISTERED

    if _PANEL_REGISTERED:
        return

    nukescripts.panels.registerWidgetAsPanel(
        WIDGET_EXPRESSION,
        PANEL_TITLE,
        PANEL_ID
    )
    _PANEL_REGISTERED = True


def _shot_notes_widgets():
    """Return currently instantiated Shot Notes panel widgets."""
    application = QtWidgets.QApplication.instance()

    if application is None:
        return []

    return [
        widget
        for widget in application.allWidgets()
        if isinstance(widget, ShotNotesWidget)
    ]


def _activate_panel_widget(widget):
    """Make every stacked parent containing widget show its Shot Notes page."""
    child = widget
    parent = child.parentWidget()

    while parent is not None:
        if isinstance(parent, QtWidgets.QStackedWidget):
            index = parent.indexOf(child)

            if index >= 0:
                parent.setCurrentIndex(index)

        child = parent
        parent = child.parentWidget()

    widget.single_note_input.setFocus()


def _activate_properties_tab():
    """Activate a Properties tab in the pane currently showing Shot Notes."""
    application = QtWidgets.QApplication.instance()

    if application is None:
        return False

    for tab_bar in application.allWidgets():
        if not isinstance(tab_bar, QtWidgets.QTabBar):
            continue

        shot_notes_index = -1
        properties_index = -1

        for index in range(tab_bar.count()):
            tab_text = str(tab_bar.tabText(index)).replace("&", "").strip()

            if tab_text == PANEL_TITLE:
                shot_notes_index = index
            elif tab_text == "Properties":
                properties_index = index

        if (
            shot_notes_index >= 0
            and properties_index >= 0
            and tab_bar.currentIndex() == shot_notes_index
        ):
            tab_bar.setCurrentIndex(properties_index)
            return True

    return False


def show_shot_notes():
    """Toggle between Shot Notes and Properties in its docked pane."""
    register_panel()
    widgets = _shot_notes_widgets()

    if widgets:
        widget = widgets[0]

        if widget.isVisible() and _activate_properties_tab():
            return widget

        _activate_panel_widget(widget)
        return widget

    pane = (
        nuke.getPaneFor("Properties.1")
        or nuke.getPaneFor("Scene Graph")
    )
    panel = nukescripts.panels.registerWidgetAsPanel(
        WIDGET_EXPRESSION,
        PANEL_TITLE,
        PANEL_ID,
        True
    )
    panel.addToPane(pane)
    QtCore.QTimer.singleShot(
        0,
        lambda: [
            _activate_panel_widget(widget)
            for widget in _shot_notes_widgets()
        ]
    )
    return panel
