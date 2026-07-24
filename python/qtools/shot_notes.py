"""Folder-based production notes in a dockable Nuke panel."""

import datetime
import json
import os
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


class NoteRow(QtWidgets.QWidget):
    """One checkable note with a compact remove button."""

    changed = QtCore.Signal()
    remove_requested = QtCore.Signal(str)

    def __init__(self, note, parent=None):
        super(NoteRow, self).__init__(parent)
        self.note_id = note["id"]

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        self.checkbox = QtWidgets.QCheckBox(note["text"])
        self.checkbox.setChecked(bool(note.get("done", False)))
        self.checkbox.setToolTip(
            "Mark this note as done. Changes are saved automatically."
        )
        layout.addWidget(self.checkbox, 1)

        remove_button = QtWidgets.QToolButton()
        remove_button.setText("×")
        remove_button.setToolTip("Delete this note")
        remove_button.setAutoRaise(True)
        layout.addWidget(remove_button)

        self.checkbox.toggled.connect(self.changed)
        remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.note_id)
        )


class ShotNotesWidget(QtWidgets.QWidget):
    """Dockable notes UI stored once per script folder."""

    def __init__(self, parent=None):
        super(ShotNotesWidget, self).__init__(parent)
        self._path = ""
        self._data = _empty_data()
        self._rows = {}

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

        self.note_input = QtWidgets.QPlainTextEdit()
        self.note_input.setPlaceholderText(
            "Add a note…\nPaste multiple lines to create multiple notes."
        )
        self.note_input.setMaximumHeight(90)
        self.note_input.setToolTip(
            "Enter one note per line, then click Add Notes."
        )
        layout.addWidget(self.note_input)

        add_button = QtWidgets.QPushButton("Add Notes")
        add_button.setToolTip(
            "Create one checklist item from each non-empty line."
        )
        add_button.clicked.connect(self._add_notes)
        layout.addWidget(add_button)

        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.setAlternatingRowColors(True)
        self.notes_list.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        layout.addWidget(self.notes_list, 1)

        actions = QtWidgets.QHBoxLayout()
        self.copy_done_button = QtWidgets.QPushButton("Copy Done")
        self.copy_done_button.setToolTip(
            "Copy all checked notes to the clipboard."
        )
        self.copy_done_button.clicked.connect(self._copy_done)
        actions.addWidget(self.copy_done_button)

        self.archive_done_button = QtWidgets.QPushButton("Archive Done")
        self.archive_done_button.setToolTip(
            "Move checked notes into a dated archive for this script version."
        )
        self.archive_done_button.clicked.connect(self._archive_done)
        actions.addWidget(self.archive_done_button)
        layout.addLayout(actions)

        self.archives = QtWidgets.QTreeWidget()
        self.archives.setHeaderHidden(True)
        self.archives.setRootIsDecorated(True)
        self.archives.setAlternatingRowColors(True)
        self.archives.setToolTip(
            "Expand an archive to see the completed notes from that version."
        )
        layout.addWidget(QtWidgets.QLabel("ARCHIVES"))
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

        for note in self._data["notes"]:
            if "id" not in note:
                note["id"] = uuid.uuid4().hex

            item = QtWidgets.QListWidgetItem()
            row = NoteRow(note, self.notes_list)
            item.setSizeHint(row.sizeHint())
            self.notes_list.addItem(item)
            self.notes_list.setItemWidget(item, row)
            self._rows[note["id"]] = row
            row.changed.connect(self._note_state_changed)
            row.remove_requested.connect(self._remove_note)

        self.archives.clear()

        for archive in reversed(self._data["archives"]):
            title = "{}  {}".format(
                archive.get("date", ""),
                archive.get("script", "")
            ).strip()
            parent = QtWidgets.QTreeWidgetItem([title])

            for text in archive.get("notes", []):
                QtWidgets.QTreeWidgetItem(parent, [text])

            self.archives.addTopLevelItem(parent)

        folder = os.path.dirname(self._path) if self._path else ""
        self.location_label.setText(
            folder if folder else "Save the Nuke script to enable Shot Notes."
        )
        enabled = bool(self._path)
        self.note_input.setEnabled(enabled)
        self._update_action_buttons()

    def _update_action_buttons(self):
        """Enable completed-note actions only when they can do something."""
        enabled = bool(self._path) and any(
            note.get("done", False)
            for note in self._data["notes"]
        )
        self.copy_done_button.setEnabled(
            enabled
        )
        self.archive_done_button.setEnabled(enabled)

    def _save(self):
        """Persist the current folder's notes."""
        _save_data(self._path, self._data)

    def _add_notes(self):
        """Turn every non-empty input line into a checklist item."""
        if not self._path:
            nuke.message("Save the Nuke script before adding Shot Notes.")
            return

        texts = [
            line.strip()
            for line in self.note_input.toPlainText().splitlines()
            if line.strip()
        ]

        if not texts:
            return

        for text in texts:
            self._data["notes"].append({
                "id": uuid.uuid4().hex,
                "text": text,
                "done": False,
            })

        self.note_input.clear()
        self._save()
        self._refresh()
        self.note_input.setFocus()

    def _note_state_changed(self):
        """Copy checkbox states back into the stored data."""
        for note in self._data["notes"]:
            row = self._rows.get(note["id"])

            if row is not None:
                note["done"] = row.checkbox.isChecked()

        self._save()
        self._update_action_buttons()

    def _remove_note(self, note_id):
        """Delete one checklist item."""
        self._data["notes"] = [
            note
            for note in self._data["notes"]
            if note.get("id") != note_id
        ]
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
            "\n".join("- {}".format(text) for text in texts)
        )

    def _archive_done(self):
        """Archive completed notes with the current date and script name."""
        texts = self._done_texts()

        if not texts:
            return

        self._data["archives"].append({
            "date": datetime.datetime.now().strftime("%d/%m/%y"),
            "script": os.path.basename(_script_path()),
            "notes": texts,
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
        "qtools.shot_notes.ShotNotesWidget",
        PANEL_TITLE,
        PANEL_ID
    )
    _PANEL_REGISTERED = True


def show_shot_notes():
    """Open Shot Notes in the Viewer pane when it is not already open."""
    register_panel()

    existing_pane = nuke.getPaneFor(PANEL_ID)

    if existing_pane is not None:
        return existing_pane

    pane = nuke.getPaneFor("Viewer.1")
    panel = nukescripts.panels.registerWidgetAsPanel(
        "qtools.shot_notes.ShotNotesWidget",
        PANEL_TITLE,
        PANEL_ID,
        True
    )
    panel.addToPane(pane)
    return panel
