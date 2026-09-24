"""Configurable .nk libraries shared by the main menu and QTools toolbar."""

import functools
import json
import os
import re
import tempfile

import nuke

from qtools import cg_to_film

_menus = ()
_dialog = None


def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets
    return QtCore, QtWidgets


def _settings():
    core, _ = _qt()
    return core.QSettings("QTools", "GroupLibrary")


def preferences():
    try:
        value = json.loads(str(_settings().value("library_v1", "{}")))
        paths = value.get("paths", [])
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError("Invalid paths")
        return paths, bool(value.get("delete_viewers", False))
    except (ValueError, TypeError, AttributeError):
        return [], False


def normalize_path(path):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def discover(paths):
    """Return (root, relative files) libraries and readable scan warnings."""
    libraries, warnings, seen = [], [], set()
    for path in paths:
        root = normalize_path(path)
        key = os.path.normcase(os.path.realpath(root))
        if key in seen:
            continue
        seen.add(key)
        if not os.path.isdir(root):
            warnings.append("Folder unavailable: " + root)
            continue
        files = []
        for folder, dirs, names in os.walk(root, followlinks=False,
                                           onerror=lambda error: warnings.append(str(error))):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(names, key=str.casefold):
                if name.lower().endswith(".nk") and not name.startswith("."):
                    files.append(os.path.relpath(os.path.join(folder, name), root))
        libraries.append((root, files))
    return libraries, warnings


def strip_viewers(source):
    """Remove serialized Viewer blocks without executing their knob scripts.

    Nuke writes node knobs as Tcl braced blocks. Track escaped braces and
    whole blocks so Viewer text inside a label or Python knob is left alone.
    A null stack entry preserves references to the removed node.
    """
    output = []
    depth = 0
    removing = False
    for line in source.splitlines(keepends=True):
        if depth == 0:
            removing = bool(re.match(r"^\s*Viewer\s*\{", line))
            if removing:
                output.append("push 0\n")
            if line.lstrip().startswith("#"):
                output.append(line)
                continue
        if not removing:
            output.append(line)
        escaped = False
        for char in line:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    raise ValueError("Unbalanced braces in group file")
        if depth == 0:
            removing = False
    if depth:
        raise ValueError("Unclosed block in group file")
    return "".join(output)


def import_group(path):
    temporary = None
    try:
        _, delete_viewers = preferences()
        paste_path = path
        if delete_viewers:
            with open(path, "r", encoding="utf-8", errors="surrogateescape") as stream:
                source = strip_viewers(stream.read())
            with tempfile.NamedTemporaryFile(mode="w", suffix=".nk", delete=False,
                                             encoding="utf-8", errors="surrogateescape") as stream:
                temporary = stream.name
                stream.write(source)
            paste_path = temporary
        nuke.Undo.begin("Import QTools Group")
        try:
            return nuke.nodePaste(paste_path)
        finally:
            nuke.Undo.end()
    except Exception as error:
        nuke.message("Could not import group:\n{}\n\n{}".format(path, error))
        return None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def register_menus(*menus):
    global _menus
    _menus = menus
    reload_menus()


def reload_menus():
    paths, _ = preferences()
    libraries, warnings = discover(paths)
    count = sum(len(files) for _, files in libraries)
    for menu in _menus:
        menu.clearMenu()
        menu.addCommand("CG To Film", functools.partial(import_group, cg_to_film._GROUP_PATH),
                        icon="qtools.svg")
        used = {"CG To Film"}
        for root, files in libraries:
            label = os.path.basename(root) or root
            base, index = label, 2
            while label in used:
                label = "{} ({})".format(base, index)
                index += 1
            used.add(label)
            library_menu = menu.addMenu(label, icon="qtools.svg")
            submenus = {(): library_menu}
            for relative in files:
                parts = relative.split(os.sep)
                for length in range(1, len(parts)):
                    key = tuple(parts[:length])
                    if key not in submenus:
                        submenus[key] = submenus[key[:-1]].addMenu(parts[length - 1])
                title = os.path.splitext(parts[-1])[0]
                if os.path.isdir(os.path.join(root, *parts[:-1], title)):
                    title += " (.nk)"
                submenus[tuple(parts[:-1])].addCommand(
                    title,
                    functools.partial(import_group, os.path.join(root, relative)),
                    icon="qtools.svg")
    for warning in warnings:
        nuke.tprint("QTools Groups: " + warning)
    return count, warnings


def show_settings():
    global _dialog
    _, widgets = _qt()
    if _dialog is not None and _dialog.isVisible():
        _dialog.raise_()
        _dialog.activateWindow()
        return

    class SettingsDialog(widgets.QDialog):
        def __init__(self):
            super(SettingsDialog, self).__init__(widgets.QApplication.activeWindow())
            self.setWindowTitle("QTools Group Settings")
            self.resize(640, 380)
            layout = widgets.QVBoxLayout(self)
            layout.addWidget(widgets.QLabel("Group folders (.nk files; subfolders become submenus):"))
            self.paths = widgets.QListWidget()
            paths, remove = preferences()
            self.paths.addItems(paths)
            layout.addWidget(self.paths)
            row = widgets.QHBoxLayout()
            layout.addLayout(row)
            for text, callback in (("Add folder…", self.add_folder),
                                   ("Add path…", self.add_path),
                                   ("Remove selected", self.remove_path)):
                button = widgets.QPushButton(text)
                button.clicked.connect(callback)
                row.addWidget(button)
            self.remove = widgets.QCheckBox("delete viewers")
            self.remove.setChecked(remove)
            self.remove.setToolTip("Remove Viewers from imported files, including inside Groups, before pasting.")
            layout.addWidget(self.remove)
            self.status = widgets.QLabel("Changes are saved when you click Save and reload list.")
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            save = widgets.QPushButton("Save and reload list")
            save.clicked.connect(self.save)
            layout.addWidget(save)
            close = widgets.QPushButton("Close")
            close.clicked.connect(self.close)
            layout.addWidget(close)

        def append_path(self, path):
            if path.strip():
                path = normalize_path(path.strip())
                existing = [self.paths.item(i).text() for i in range(self.paths.count())]
                if path not in existing:
                    self.paths.addItem(path)

        def add_folder(self):
            self.append_path(widgets.QFileDialog.getExistingDirectory(self, "Choose group folder"))

        def add_path(self):
            path, accepted = widgets.QInputDialog.getText(self, "Add group path", "Folder path:")
            if accepted:
                self.append_path(path)

        def remove_path(self):
            for item in self.paths.selectedItems():
                self.paths.takeItem(self.paths.row(item))

        def save(self):
            settings = _settings()
            settings.setValue("library_v1", json.dumps({
                "paths": [self.paths.item(i).text() for i in range(self.paths.count())],
                "delete_viewers": self.remove.isChecked(),
            }))
            settings.sync()
            if settings.status() != settings.NoError:
                self.status.setText("Could not save group settings. Check your user preferences permissions.")
                return
            count, warnings = reload_menus()
            self.status.setText("Loaded {} group files.{}".format(
                count, "\n" + "\n".join(warnings) if warnings else ""))

    _dialog = SettingsDialog()
    _dialog.show()
