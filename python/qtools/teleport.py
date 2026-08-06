"""Share small groups of Nuke nodes through a shared folder."""

from __future__ import print_function

import glob
import os
import subprocess
import sys

import nuke

from qtools import teleport_settings as settings


FILE_PREFIX = "teleport_"
FILE_EXTENSION = ".nk"


def _shared_path():
    path = os.environ.get(settings.SHARED_PATH_ENV, settings.SHARED_PATH)
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    if not path or path == os.path.abspath(""):
        raise RuntimeError("Teleport SHARED_PATH has not been configured.")
    return path


def _ensure_shared_path():
    path = _shared_path()
    if not os.path.isdir(path):
        if settings.CREATE_SHARED_PATH:
            try:
                os.makedirs(path)
            except OSError:
                if not os.path.isdir(path):
                    raise
        else:
            raise RuntimeError("Teleport shared folder does not exist: {0}".format(path))
    return path


def _username():
    value = os.environ.get(settings.USERNAME_ENV) if settings.USERNAME_ENV else None
    if not value:
        import getpass

        value = getpass.getuser()
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    return safe.strip("._") or "unknown_user"


def _teleport_path(user):
    return os.path.join(_shared_path(), FILE_PREFIX + user + FILE_EXTENSION)


def _teleport_files():
    pattern = os.path.join(_shared_path(), FILE_PREFIX + "*" + FILE_EXTENSION)
    return [path for path in glob.glob(pattern) if os.path.isfile(path)]


def _teleporter(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return name[len(FILE_PREFIX) :] if name.startswith(FILE_PREFIX) else None


def _show_error(error):
    nuke.message("Teleport could not complete the operation.<br><br>{0}".format(error))


def telecopy():
    """Save the selected non-Viewer nodes as this user's shared teleport."""
    selection = nuke.selectedNodes()
    for node in selection:
        if node.Class() == "Viewer":
            node["selected"].setValue(False)
    selection = [node for node in selection if node.Class() != "Viewer"]
    if not selection:
        nuke.message("Select at least one non-Viewer node to teleport.")
        return
    try:
        path = os.path.join(
            _ensure_shared_path(), FILE_PREFIX + _username() + FILE_EXTENSION
        )
        nuke.nodeCopy(path)
        print("Teleport: copied nodes to {0}".format(path))
    except Exception as error:
        _show_error(error)


def telepaste(teleporter):
    """Paste the nodes stored by ``teleporter`` into the current script."""
    nuke.nodePaste(_teleport_path(teleporter))
    print("Teleport: pasted {0}".format(teleporter))


def _choose_teleporter():
    files = sorted(_teleport_files(), key=os.path.getmtime, reverse=True)
    teleporters = [_teleporter(path) for path in files]
    teleporters = [user for user in teleporters if user]
    if not teleporters:
        nuke.message("The Teleport folder is empty.")
        return None
    if len(teleporters) == 1:
        return teleporters[0]
    panel = nuke.Panel("Select Teleporter")
    panel.addEnumerationPulldown("Teleporter", " ".join(teleporters))
    return panel.value("Teleporter") if panel.show() else None


def telepaste_ui(latest=False):
    """Choose a teleport to paste, or paste the latest one immediately."""
    try:
        if latest:
            files = _teleport_files()
            teleporter = _teleporter(max(files, key=os.path.getmtime)) if files else None
            if not teleporter:
                nuke.message("The Teleport folder is empty.")
                return
        else:
            teleporter = _choose_teleporter()
        if teleporter:
            telepaste(teleporter)
    except Exception as error:
        _show_error(error)


def _authorised():
    if not settings.ADMIN_PASSWORD:
        return True
    panel = nuke.Panel("Teleport administrator")
    panel.addPasswordInput("Password", "")
    return panel.show() and panel.value("Password") == settings.ADMIN_PASSWORD


def manage(own_only=False):
    """Delete this user's teleport, or let an administrator delete several."""
    try:
        if own_only:
            users = [_username()]
        else:
            if not _authorised():
                nuke.message("Wrong password.")
                return
            users = [_teleporter(path) for path in sorted(_teleport_files())]
            users = [user for user in users if user]
            if not users:
                nuke.message("The Teleport folder is empty.")
                return
            panel = nuke.Panel("Select teleports to delete")
            for user in users:
                panel.addBooleanCheckBox(user, False)
            if not panel.show():
                return
            users = [user for user in users if panel.value(user)]
        existing = [user for user in users if os.path.isfile(_teleport_path(user))]
        if not existing:
            nuke.message("No matching teleport was found.")
            return
        if nuke.ask("Permanently delete {0} teleport(s)?".format(len(existing))):
            for user in existing:
                os.remove(_teleport_path(user))
    except Exception as error:
        _show_error(error)


def explore():
    """Open the shared Teleport folder in the operating-system file browser."""
    try:
        if not _authorised():
            nuke.message("Wrong password.")
            return
        path = _ensure_shared_path()
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as error:
        _show_error(error)
