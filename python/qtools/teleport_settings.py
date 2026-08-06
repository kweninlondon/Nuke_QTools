"""Studio settings for QTools Teleport.

Set SHARED_PATH here, or provide TELEPORT_SHARED_PATH in the environment.
"""

# Shared read/write folder used by all participating Nuke workstations.
# Examples: r"\\server\pipeline\teleport" or "/mnt/pipeline/teleport"
SHARED_PATH = "~/teleport_shared"
SHARED_PATH_ENV = "TELEPORT_SHARED_PATH"
CREATE_SHARED_PATH = True

# Leave empty to identify artists by their operating-system login.
USERNAME_ENV = ""

# Optional UI guard for Manage All and Explore. Folder permissions provide
# actual access control; this value is not a security boundary.
ADMIN_PASSWORD = ""

SHORTCUT_COPY = "Ctrl+Alt+C"
SHORTCUT_PASTE = "Ctrl+Alt+V"
SHORTCUT_PASTE_LATEST = "Ctrl+Alt+Shift+V"
