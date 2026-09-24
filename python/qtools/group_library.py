"""Configurable .nk libraries shared by the main menu and QTools toolbar."""

import functools
import json
import os
import re
import tempfile
import traceback

import nuke

from qtools import cg_to_film

_dialog = None
_registered_menus = None


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


def register_menus(groups=None, toolbar=None):
    """Use the actual menus returned at startup; contain library failures."""
    global _registered_menus
    if groups is not None and toolbar is not None:
        _registered_menus = (groups, toolbar)
    try:
        reload_menus()
    except Exception:
        nuke.tprint("QTools group library failed to load:\n" + traceback.format_exc())
        # Leave settings reachable so invalid paths can be corrected, and let
        # the remaining QTools startup commands continue registering.
        if groups is not None:
            try:
                groups.clearMenu()
                groups.addCommand("Group Settings…", show_settings)
            except Exception:
                nuke.tprint("QTools group settings could not be registered:\n" +
                            traceback.format_exc())


def _live_menus():
    """Resolve current Nuke menu objects, including after Python module reloads."""
    if _registered_menus is not None:
        return _registered_menus
    # findItem returns a MenuItem wrapper in Nuke 16, even for submenus.
    # Menu.menu returns the Menu object with clearMenu/addCommand methods.
    main = nuke.menu("Nuke").menu("QTools")
    groups = main.menu("Groups")
    toolbar = nuke.menu("Nodes").menu("QTools")
    return groups, toolbar


def save_preferences(paths, delete_viewers):
    core, _ = _qt()
    settings = _settings()
    settings.setValue("library_v1", json.dumps({
        "paths": paths, "delete_viewers": delete_viewers,
    }))
    settings.sync()
    # PySide6 enums belong to their type, not the QSettings instance. An
    # instance lookup can raise after saving and prevent the menus refreshing.
    if settings.status() != core.QSettings.Status.NoError:
        raise OSError("Could not save group settings. Check your user preferences permissions.")


def reload_menus(scan=None):
    paths, _ = preferences()
    libraries, warnings = discover(paths) if scan is None else scan
    count = sum(len(files) for _, files in libraries)
    for index, menu in enumerate(_live_menus()):
        menu.clearMenu()
        if index == 0:
            menu.addCommand("Group Settings…", show_settings)
            menu.addSeparator()
        menu.addCommand("CG To Film", functools.partial(import_group, cg_to_film._GROUP_PATH))
        used = {"CG To Film", "Group Settings…"}
        for root, files in libraries:
            label = os.path.basename(root) or root
            base, index = label, 2
            while label in used:
                label = "{} ({})".format(base, index)
                index += 1
            used.add(label)
            library_menu = menu.addMenu(label)
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
                    functools.partial(import_group, os.path.join(root, relative)))
    for warning in warnings:
        nuke.tprint("QTools Groups: " + warning)
    return count, warnings


def show_settings():
    global _dialog
    core, widgets = _qt()
    path_role = core.Qt.ItemDataRole.UserRole
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
            self.last_reload = None
            for path in paths:
                self.append_path(path)
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
            self.status = widgets.QLabel("Closing saves settings. Cancel discards changes since the last reload.")
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            buttons = widgets.QHBoxLayout()
            layout.addLayout(buttons)
            reload_button = widgets.QPushButton("Reload list")
            reload_button.clicked.connect(self.reload)
            buttons.addWidget(reload_button)
            cancel = widgets.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)

        def current_paths(self):
            return [self.paths.item(i).data(path_role) for i in range(self.paths.count())]

        def snapshot(self):
            return self.current_paths(), self.remove.isChecked()

        def append_path(self, path):
            if path.strip():
                path = normalize_path(path.strip())
                if path not in self.current_paths():
                    item = widgets.QListWidgetItem(path)
                    item.setData(path_role, path)
                    self.paths.addItem(item)

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
            try:
                save_preferences(*self.snapshot())
                return True
            except Exception as error:
                self.status.setText("Save failed: {}".format(error))
                return False

        def reload(self):
            if not self.save():
                return False
            try:
                scan = discover(self.current_paths())
                count, warnings = reload_menus(scan=scan)
                counts = {os.path.normcase(os.path.realpath(root)): len(files)
                          for root, files in scan[0]}
                for i in range(self.paths.count()):
                    item = self.paths.item(i)
                    path = item.data(path_role)
                    loaded = counts.get(os.path.normcase(os.path.realpath(path)))
                    suffix = ("{} nodes loaded".format(loaded) if loaded is not None
                              else "0 nodes loaded; unavailable")
                    item.setText("{} ({})".format(path, suffix))
                self.last_reload = self.snapshot()
            except Exception as error:
                self.status.setText("Reload failed: {}".format(error))
                return False
            self.status.setText("Loaded {} group files.{}".format(
                count, "\n" + "\n".join(warnings) if warnings else ""))
            return True

        def closeEvent(self, event):
            if not self.save():
                event.ignore()
                return
            if self.last_reload != self.snapshot():
                answer = widgets.QMessageBox.question(
                    self, "Reload group list?",
                    "Settings saved. Reload the group menus now?",
                    widgets.QMessageBox.Yes | widgets.QMessageBox.No,
                    widgets.QMessageBox.Yes,
                )
                if answer == widgets.QMessageBox.Yes and not self.reload():
                    event.ignore()
                    return
            event.accept()

    _dialog = SettingsDialog()
    _dialog.show()
