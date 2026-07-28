"""Copy a grouped report of file-based Nuke nodes to the clipboard."""

import html
import os
import re

import nuke

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


READ_TYPE_BY_CLASS = {
    "Read": "image",
    "DeepRead": "deep image",
    "ReadGeo": "geo",
    "ReadGeo2": "geo",
    "Camera": "camera",
    "Camera2": "camera",
    "Camera3": "camera",
    "SceneLoader": "scene",
    "AudioRead": "audio",
    "ParticleCache": "particle cache",
    "PointCloudGenerator": "point cloud",
    "UsdStage": "USD scene",
    "UsdRead": "USD scene",
    "GeoImport": "geo",
}

PREFERRED_FILE_KNOBS = (
    "file",
    "filename",
    "fileName",
    "path",
    "scene_file",
    "cache_file",
    "audiofile",
)

SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "AssetReport"
SETTING_FORMAT = "copy_format"
FORMAT_HTML = "HTML"
FORMAT_PLAIN_TEXT = "Plain text"
FORMAT_MARKDOWN = "Markdown"
COPY_FORMATS = (FORMAT_HTML, FORMAT_PLAIN_TEXT, FORMAT_MARKDOWN)
_dialog = None


def _clean_text(value):
    """Return a trimmed string."""
    return str(value or "").strip()


def _natural_sort_key(value):
    """Sort embedded numbers numerically, such as Read2 before Read10."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def _get_file_knob(node):
    """Return the first populated asset-path knob on a node."""
    for knob_name in PREFERRED_FILE_KNOBS:
        if knob_name not in node.knobs():
            continue

        knob = node[knob_name]

        try:
            value = knob.value()
        except Exception:
            continue

        if isinstance(value, str) and value.strip():
            return knob

    return None


def _normalise_asset_path(raw_path):
    """Preserve expressions and frame tokens while normalising slashes."""
    return _clean_text(raw_path).replace("\\", "/")


def _split_asset_path(asset_path):
    """Return the filename and directory portions of an asset path."""
    last_slash = asset_path.rfind("/")

    if last_slash == -1:
        return asset_path, ""

    return asset_path[last_slash + 1:], asset_path[:last_slash + 1]


def _detect_read_type(node, file_path):
    """Determine the asset type from the node class and extension."""
    node_class = node.Class()

    if node_class in READ_TYPE_BY_CLASS:
        return READ_TYPE_BY_CLASS[node_class]

    class_lower = node_class.lower()

    for keyword, read_type in (
        ("camera", "camera"),
        ("geo", "geo"),
        ("audio", "audio"),
        ("usd", "USD scene"),
    ):
        if keyword in class_lower:
            return read_type

    if "deep" in class_lower and "read" in class_lower:
        return "deep image"

    if "read" in class_lower:
        return "image"

    extension = os.path.splitext(file_path.lower())[1]

    if extension in {
        ".abc", ".fbx", ".obj", ".usd", ".usda", ".usdc",
        ".gltf", ".glb",
    }:
        return "geo"

    if extension in {".wav", ".mp3", ".aif", ".aiff"}:
        return "audio"

    if extension in {
        ".exr", ".dpx", ".cin", ".tif", ".tiff", ".png",
        ".jpg", ".jpeg", ".mov", ".mp4", ".mxf",
    }:
        return "image"

    return "asset"


def _is_asset_read_node(node):
    """Return True when a node appears to load an external asset."""
    if _get_file_knob(node) is None:
        return False

    if node.Class() in READ_TYPE_BY_CLASS:
        return True

    class_lower = node.Class().lower()
    return any(
        keyword in class_lower
        for keyword in (
            "read", "loader", "import", "camera", "geo", "cache", "usd",
        )
    )


def _asset_nodes():
    """Return every file-based reader/importer, including nodes in Groups."""
    nodes = [
        node
        for node in nuke.allNodes(recurseGroups=True)
        if _is_asset_read_node(node)
    ]
    return sorted(nodes, key=lambda node: _natural_sort_key(node.fullName()))


def _asset_data(node):
    """Return report data for one node."""
    file_knob = _get_file_knob(node)

    try:
        raw_path = file_knob.value()
    except Exception:
        raw_path = ""

    full_path = _normalise_asset_path(raw_path)
    asset_name, directory = _split_asset_path(full_path)

    return {
        "read_name": node.fullName(),
        "asset_name": asset_name or "Unknown",
        "asset_path": directory or "No directory",
        "full_path": full_path,
        "read_type": _detect_read_type(node, full_path),
    }


def _group_assets(assets):
    """Group nodes that reference the same complete file path."""
    groups = {}

    for asset in assets:
        groups.setdefault(asset["full_path"], []).append(asset)

    grouped_results = []

    for grouped_assets in groups.values():
        grouped_assets = sorted(
            grouped_assets,
            key=lambda asset: _natural_sort_key(asset["read_name"])
        )
        first_asset = grouped_assets[0]
        read_types = sorted({
            asset["read_type"]
            for asset in grouped_assets
        })
        grouped_results.append({
            "heading": first_asset["read_name"],
            "read_names": [
                asset["read_name"]
                for asset in grouped_assets
            ],
            "asset_name": first_asset["asset_name"],
            "asset_path": first_asset["asset_path"],
            "full_path": first_asset["full_path"],
            "read_type": ", ".join(read_types),
        })

    return sorted(
        grouped_results,
        key=lambda asset: _natural_sort_key(asset["heading"])
    )


def _all_paths(assets):
    """Return each asset directory once in natural order."""
    return sorted(
        {
            asset["asset_path"]
            for asset in assets
        },
        key=_natural_sort_key
    )


def _build_plain_text_report(assets):
    """Build a plain-text report with one section per unique file."""
    lines = ["NUKE ASSETS REPORT", ""]

    if not assets:
        return "\n".join(
            lines + ["No file-based read or import nodes were selected."]
        )

    for asset in _group_assets(assets):
        lines.extend([
            asset["heading"],
            "",
            "Read name: {}".format(", ".join(asset["read_names"])),
            "Asset name: {}".format(asset["asset_name"]),
            "Asset path: {}".format(asset["asset_path"]),
            "Read type: {}".format(asset["read_type"]),
            "",
        ])

    lines.extend([
        "ALL PATHS",
        "",
        "\n".join(_all_paths(assets)),
    ])

    return "\n".join(lines).rstrip()


def _build_markdown_report(assets):
    """Build a Markdown report with one section per unique file."""
    lines = ["# Nuke Assets Report", ""]

    if not assets:
        return "\n".join(
            lines + ["_No file-based read or import nodes were selected._"]
        )

    for asset in _group_assets(assets):
        lines.extend([
            "## {}".format(asset["heading"]),
            "",
            "- **Read name:** {}".format(
                ", ".join(asset["read_names"])
            ),
            "- **Asset name:** {}".format(asset["asset_name"]),
            "- **Asset path:** `{}`".format(asset["asset_path"]),
            "- **Read type:** {}".format(asset["read_type"]),
            "",
        ])

    lines.extend([
        "## All paths",
        "",
        "```text",
    ])
    lines.extend(_all_paths(assets))
    lines.extend(["```", ""])

    return "\n".join(lines).rstrip()


def _build_html_report(assets):
    """Build a clean HTML report with one section per unique file."""
    parts = [
        "<html><head><meta charset=\"utf-8\"></head>",
        '<body style="font-family: Arial, Helvetica, sans-serif; '
        'font-size: 11pt; color: #202124; line-height: 1.45;">',
        '<h1 style="font-family: Arial, Helvetica, sans-serif; '
        'font-size: 24pt; font-weight: 500; line-height: 1.2; '
        'margin: 0 0 24px 0;">Nuke Assets Report</h1>',
    ]

    if not assets:
        parts.append(
            '<p style="font-style: italic;">'
            "No file-based read or import nodes were selected.</p>"
        )

    for asset in _group_assets(assets):
        read_names = html.escape(", ".join(asset["read_names"]))
        asset_name = html.escape(asset["asset_name"])
        asset_path = html.escape(asset["asset_path"])
        read_type = html.escape(asset["read_type"])

        parts.extend([
            '<section style="margin: 0 0 26px 0;">',
            '<h2 style="font-family: Arial, Helvetica, sans-serif; '
            'font-size: 16pt; font-weight: 500; line-height: 1.25; '
            'margin: 0 0 9px 0;">{}</h2>'.format(
                html.escape(asset["heading"])
            ),
            '<ul style="margin: 0; padding-left: 24px;">',
            '<li style="margin: 3px 0;"><strong>Read name:</strong> '
            "{}</li>".format(read_names),
            '<li style="margin: 3px 0;"><strong>Asset name:</strong> '
            "{}</li>".format(asset_name),
            '<li style="margin: 3px 0;"><strong>Asset path:</strong> '
            '<code style="font-family: Consolas, Monaco, monospace; '
            'font-size: 10pt; background: #f5f5f5; border: 1px solid '
            '#d8d8d8; border-radius: 3px; padding: 1px 4px;">'
            "{}</code></li>".format(asset_path),
            '<li style="margin: 3px 0;"><strong>Read type:</strong> '
            "{}</li>".format(read_type),
            "</ul>",
            "</section>",
        ])

    all_paths = "\n".join(_all_paths(assets))
    parts.extend([
        '<h2 style="font-family: Arial, Helvetica, sans-serif; '
        'font-size: 16pt; font-weight: 500; margin: 28px 0 10px 0;">'
        "All paths</h2>",
        '<pre style="display: block; white-space: pre-wrap; '
        'font-family: Consolas, Monaco, monospace; font-size: 10pt; '
        'line-height: 1.45; '
        'background: #f3f4f6; border: 1px solid #dfe1e5; '
        'border-radius: 6px; padding: 14px; margin: 0;">'
        "<code>{}</code></pre>".format(html.escape(all_paths)),
    ])

    parts.append("</body></html>")
    return "".join(parts)


def _copy_report(assets, copy_format):
    """Build and copy the selected report format to the clipboard."""
    app = QtWidgets.QApplication.instance()

    if app is None:
        raise RuntimeError("Could not access Nuke's QApplication instance.")

    plain_text = _build_plain_text_report(assets)
    mime_data = QtCore.QMimeData()

    if copy_format == FORMAT_HTML:
        mime_data.setText(plain_text)
        mime_data.setHtml(_build_html_report(assets))
    elif copy_format == FORMAT_MARKDOWN:
        mime_data.setText(_build_markdown_report(assets))
    else:
        mime_data.setText(plain_text)

    app.clipboard().setMimeData(mime_data)


class AssetReportDialog(QtWidgets.QDialog):
    """Select asset nodes and copy a formatted, grouped report."""

    def __init__(self, parent=None):
        super(AssetReportDialog, self).__init__(parent)
        self._nodes_by_name = {}
        self._settings = QtCore.QSettings(
            SETTINGS_ORGANISATION,
            SETTINGS_APPLICATION
        )

        self.setWindowTitle("Copy Asset Report")
        self.resize(620, 560)
        self._build_ui()
        self._populate_nodes()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        explanation = QtWidgets.QLabel(
            "Choose the file-based nodes to include. Assets sharing a path "
            "are grouped beneath one path heading."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.filter_field = QtWidgets.QLineEdit()
        self.filter_field.setPlaceholderText("Filter nodes or paths…")
        self.filter_field.textChanged.connect(self._filter_items)
        layout.addWidget(self.filter_field)

        self.node_list = QtWidgets.QListWidget()
        layout.addWidget(self.node_list, 1)

        selection_layout = QtWidgets.QHBoxLayout()
        select_all_button = QtWidgets.QPushButton("Select All")
        select_none_button = QtWidgets.QPushButton("Select None")
        select_graph_button = QtWidgets.QPushButton("Use Graph Selection")
        select_all_button.clicked.connect(
            lambda: self._set_visible_checked(True)
        )
        select_none_button.clicked.connect(
            lambda: self._set_visible_checked(False)
        )
        select_graph_button.clicked.connect(self._use_graph_selection)
        selection_layout.addWidget(select_all_button)
        selection_layout.addWidget(select_none_button)
        selection_layout.addWidget(select_graph_button)
        selection_layout.addStretch(1)
        layout.addLayout(selection_layout)

        format_layout = QtWidgets.QHBoxLayout()
        format_layout.addWidget(QtWidgets.QLabel("Copy format:"))
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(COPY_FORMATS)
        saved_format = self._settings.value(
            SETTING_FORMAT,
            FORMAT_HTML
        )
        format_index = self.format_combo.findText(str(saved_format))
        self.format_combo.setCurrentIndex(max(0, format_index))
        format_layout.addWidget(self.format_combo)
        format_layout.addStretch(1)
        layout.addLayout(format_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Cancel
        )
        self.copy_button = buttons.addButton(
            "Copy Report",
            QtWidgets.QDialogButtonBox.AcceptRole
        )
        buttons.rejected.connect(self.reject)
        self.copy_button.clicked.connect(self._copy_selected_report)
        layout.addWidget(buttons)

    def _populate_nodes(self):
        selected_names = {
            node.fullName()
            for node in nuke.selectedNodes()
            if _is_asset_read_node(node)
        }
        nodes = _asset_nodes()
        check_all = not selected_names

        for node in nodes:
            asset = _asset_data(node)
            name = node.fullName()
            self._nodes_by_name[name] = node
            item = QtWidgets.QListWidgetItem(
                "{}  —  {}".format(name, asset["full_path"])
            )
            item.setData(QtCore.Qt.UserRole, name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked
                if check_all or name in selected_names
                else QtCore.Qt.Unchecked
            )
            self.node_list.addItem(item)

        self.copy_button.setEnabled(bool(nodes))

    def _filter_items(self, text):
        search_text = _clean_text(text).lower()

        for row in range(self.node_list.count()):
            item = self.node_list.item(row)
            item.setHidden(search_text not in item.text().lower())

    def _set_visible_checked(self, checked):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked

        for row in range(self.node_list.count()):
            item = self.node_list.item(row)

            if not item.isHidden():
                item.setCheckState(state)

    def _use_graph_selection(self):
        selected_names = {
            node.fullName()
            for node in nuke.selectedNodes()
            if _is_asset_read_node(node)
        }

        for row in range(self.node_list.count()):
            item = self.node_list.item(row)
            item.setCheckState(
                QtCore.Qt.Checked
                if item.data(QtCore.Qt.UserRole) in selected_names
                else QtCore.Qt.Unchecked
            )

    def _checked_assets(self):
        assets = []

        for row in range(self.node_list.count()):
            item = self.node_list.item(row)

            if item.checkState() != QtCore.Qt.Checked:
                continue

            node = self._nodes_by_name.get(
                item.data(QtCore.Qt.UserRole)
            )

            if node is not None:
                assets.append(_asset_data(node))

        return assets

    def _copy_selected_report(self):
        assets = self._checked_assets()

        if not assets:
            nuke.message("Select at least one asset node to copy.")
            return

        copy_format = self.format_combo.currentText()
        self._settings.setValue(SETTING_FORMAT, copy_format)
        _copy_report(assets, copy_format)
        self.accept()

        nuke.message(
            "{} asset node{} copied as {}.".format(
                len(assets),
                "" if len(assets) == 1 else "s",
                copy_format,
            )
        )


def show_asset_report():
    """Show the modeless asset-report selection dialog."""
    global _dialog

    if _dialog is not None:
        try:
            _dialog.close()
        except Exception:
            pass

    _dialog = AssetReportDialog()
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    _dialog.destroyed.connect(_clear_dialog_reference)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def _clear_dialog_reference(*_args):
    """Clear the retained dialog reference after Qt deletes it."""
    global _dialog
    _dialog = None
