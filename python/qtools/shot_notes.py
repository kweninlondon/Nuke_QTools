"""Folder-based production notes in a dockable Nuke panel."""

import datetime
import json
import os
import re
import uuid

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


PANEL_TITLE = "Shot Notes"
NOTES_FILENAME = ".qtools_shot_notes.json"
SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "ShotNotes"
_FLOATING_WINDOW = None


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

        add_notes_header = QtWidgets.QHBoxLayout()
        self.add_notes_toggle = QtWidgets.QToolButton()
        self.add_notes_toggle.setText("ADD NOTES")
        self.add_notes_toggle.setCheckable(True)
        self.add_notes_toggle.setChecked(False)
        self.add_notes_toggle.setArrowType(QtCore.Qt.RightArrow)
        self.add_notes_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonTextBesideIcon
        )
        self.add_notes_toggle.setToolTip(
            "Show or hide the controls for adding notes."
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

        self.archives_toggle.setText(
            "ARCHIVES ({})".format(len(self._data["archives"]))
        )
        folder = os.path.dirname(self._path) if self._path else ""
        self.location_label.setText(
            folder if folder else "Save the Nuke script to enable Shot Notes."
        )
        enabled = bool(self._path)
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
            })

        self._save()
        self._refresh()

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


class ShotNotesWindow(QtWidgets.QDialog):
    """Modeless floating Shot Notes window with remembered geometry."""

    def __init__(self, parent=None):
        super(ShotNotesWindow, self).__init__(parent)
        self.setWindowTitle(PANEL_TITLE)
        self.setWindowFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self.resize(430, 650)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ShotNotesWidget(self))

        settings = QtCore.QSettings(
            SETTINGS_ORGANISATION,
            SETTINGS_APPLICATION
        )
        geometry = settings.value("window_geometry")

        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_geometry(self):
        """Remember the floating window's current size and position."""
        settings = QtCore.QSettings(
            SETTINGS_ORGANISATION,
            SETTINGS_APPLICATION
        )
        settings.setValue("window_geometry", self.saveGeometry())

    def closeEvent(self, event):
        """Hide instead of destroying so the shortcut can reopen quickly."""
        self._save_geometry()
        event.ignore()
        self.hide()

    def hideEvent(self, event):
        """Persist geometry whenever the window is toggled off."""
        self._save_geometry()
        super(ShotNotesWindow, self).hideEvent(event)


def show_shot_notes():
    """Toggle the modeless floating Shot Notes window."""
    global _FLOATING_WINDOW

    if _FLOATING_WINDOW is None:
        _FLOATING_WINDOW = ShotNotesWindow(
            parent=_nuke_main_window()
        )

    if _FLOATING_WINDOW.isVisible():
        _FLOATING_WINDOW.hide()
        return _FLOATING_WINDOW

    _FLOATING_WINDOW.show()
    _FLOATING_WINDOW.raise_()
    _FLOATING_WINDOW.activateWindow()
    return _FLOATING_WINDOW
