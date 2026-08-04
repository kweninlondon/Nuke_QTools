"""Editable naming and colour rules shared by QTools connectors."""

import json
import re

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "PostageStampCreator"
SETTING_RULES = "connector_rules_v1"

# Nuke tile colours use packed RRGGBBAA values.  These defaults deliberately
# remain user-editable; productions can replace them without changing code.
DEFAULT_RULES = [
    {"search": "camera", "prefix": "CAMERA", "remove": "", "colour": 0x5F7F3FFF},
    {"search": "3d", "prefix": "3D", "remove": "", "colour": 0x5F7F3FFF},
    {"search": "roto", "prefix": "ROTO", "remove": "", "colour": 0x4F8F5FFF},
    {"search": "bty, utils", "prefix": "CG", "remove": "", "colour": 0},
    {"search": "dmp", "prefix": "DMP", "remove": "", "colour": 0},
    {"search": "plate", "prefix": "PLATE", "remove": "", "colour": 0},
]


def _settings():
    return QtCore.QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def _clean_remove_setting(value):
    """Discard the obsolete standalone underscore-removal mask."""
    return ", ".join(
        part.strip()
        for part in re.split(r"[,;|]+", str(value or ""))
        if part.strip() and part.strip() != "_"
    )


def rules():
    """Return saved rules, falling back to a fresh copy of the defaults."""
    raw_value = _settings().value(SETTING_RULES, "")

    if raw_value:
        try:
            saved = json.loads(str(raw_value))
            if isinstance(saved, list):
                return [
                    {
                        "search": str(item.get("search", "")),
                        "prefix": str(item.get("prefix", "")).strip().upper(),
                        "remove": _clean_remove_setting(item.get("remove", "")),
                        "colour": int(item.get("colour", 0)),
                    }
                    for item in saved
                    if isinstance(item, dict)
                ]
        except (TypeError, ValueError):
            pass

    return [dict(item) for item in DEFAULT_RULES]


def save_rules(items):
    items = [
        dict(item, remove=_clean_remove_setting(item.get("remove", "")))
        for item in items
    ]
    settings = _settings()
    settings.setValue(SETTING_RULES, json.dumps(items))
    settings.sync()


def _terms(rule):
    return [
        term.strip().lower()
        for term in re.split(r"[,;|]+", rule.get("search", ""))
        if term.strip()
    ]


def matching_rule(text, items=None):
    """Return the first rule whose search term occurs in text."""
    text = str(text or "").lower()

    for rule in items or rules():
        if any(term in text for term in _terms(rule)):
            return rule

    return None


def prefix_rule(prefix, items=None):
    prefix = str(prefix or "").strip().lower()

    for rule in items or rules():
        if rule.get("prefix", "").strip().lower() == prefix:
            return rule

    return None


def rule_for_name(name, items=None):
    """Prefer the first name word as a prefix code, then search all text."""
    words = str(name or "").split()
    rule = prefix_rule(words[0], items) if words else None
    return rule or matching_rule(name, items)


def clean_filename_text(value):
    """Turn filename separators and punctuation into readable spaces."""
    return " ".join(re.sub(r"[^\w]+", " ", str(value or "")).split())


def remove_patterns(value, patterns):
    """Remove comma-separated masks; each # represents exactly one digit."""
    result = str(value or "")

    for pattern in re.split(r"[,;|]+", str(patterns or "")):
        pattern = pattern.strip()

        if not pattern:
            continue

        expression = "".join(
            r"\d" if character == "#" else re.escape(character)
            for character in pattern
        )
        result = re.sub(expression, "", result, flags=re.IGNORECASE)

    return result


def compose_name(
    prefix,
    name,
    remove_special=True,
    removals="",
    replace_underscores=True
):
    prefix = " ".join(str(prefix or "").split()).upper()
    name = remove_patterns(name, removals)
    if replace_underscores:
        name = str(name).replace("_", " ")
    name = clean_filename_text(name) if remove_special else " ".join(
        str(name or "").split()
    )

    if prefix and not name.lower().startswith(prefix.lower() + " "):
        return "{} {}".format(prefix, name).strip()

    return name or prefix


def node_colour(node):
    try:
        return int(node["tile_color"].value())
    except Exception:
        return 0


def set_node_colour(node, colour):
    if node is None or colour is None or "tile_color" not in node.knobs():
        return

    node["tile_color"].setValue(int(colour))


class RuleEditorDialog(QtWidgets.QDialog):
    """Edit ordered filename search, prefix and colour mappings."""

    def __init__(self, parent=None):
        super(RuleEditorDialog, self).__init__(parent)
        self.setWindowTitle("Connector colour rules")
        self.resize(900, 420)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Rules are checked from top to bottom. Separate alternative "
            "filename searches or removal masks with commas. In Remove, "
            "each # matches one digit."
        ))
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Name search", "Prefix", "Remove", "Colour"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )
        layout.addWidget(self.table)

        row_buttons = QtWidgets.QHBoxLayout()
        add_button = QtWidgets.QPushButton("Add rule")
        remove_button = QtWidgets.QPushButton("Remove selected")
        defaults_button = QtWidgets.QPushButton("Restore defaults")
        row_buttons.addWidget(add_button)
        row_buttons.addWidget(remove_button)
        row_buttons.addWidget(defaults_button)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)
        add_button.clicked.connect(lambda: self._add_rule({}))
        remove_button.clicked.connect(self._remove_selected)
        defaults_button.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        for rule in rules():
            self._add_rule(rule)

    def _add_rule(self, rule):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(
            rule.get("search", "")
        ))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(
            rule.get("prefix", "")
        ))
        remove_item = QtWidgets.QTableWidgetItem(rule.get("remove", ""))
        remove_item.setToolTip(
            "Examples: v### removes v followed by three digits; "
            "AOI_###_##_## removes that numbered filename prefix."
        )
        self.table.setItem(row, 2, remove_item)
        button = QtWidgets.QPushButton()
        colour = int(rule.get("colour", 0))
        button.setProperty("nuke_colour", colour)
        self._style_colour_button(button, colour)
        button.clicked.connect(
            lambda _checked=False, control=button: self._choose_colour(control)
        )
        self.table.setCellWidget(row, 3, button)

    def _style_colour_button(self, button, colour):
        if not colour:
            button.setText("No colour")
            button.setStyleSheet("QPushButton { min-width: 90px; }")
            button.setToolTip(
                "No Nuke tile colour. Click to choose a colour; "
                "right-click to clear."
            )
            button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            try:
                button.customContextMenuRequested.disconnect()
            except (RuntimeError, TypeError):
                pass
            button.customContextMenuRequested.connect(
                lambda _position, control=button: self._clear_colour(control)
            )
            return

        rgb = (int(colour) >> 8) & 0xFFFFFF
        button.setText("#{:06X}".format(rgb))
        button.setStyleSheet(
            "QPushButton { background-color: #%06X; min-width: 90px; }" % rgb
        )
        button.setToolTip("Click to change; right-click for No colour.")
        button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        try:
            button.customContextMenuRequested.disconnect()
        except (RuntimeError, TypeError):
            pass
        button.customContextMenuRequested.connect(
            lambda _position, control=button: self._clear_colour(control)
        )

    def _clear_colour(self, button):
        button.setProperty("nuke_colour", 0)
        self._style_colour_button(button, 0)

    def _choose_colour(self, button):
        colour = int(button.property("nuke_colour"))
        rgb = (colour >> 8) & 0xFFFFFF
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255),
            self,
            "Choose connector colour"
        )

        if chosen.isValid():
            packed = (
                (chosen.red() << 24)
                | (chosen.green() << 16)
                | (chosen.blue() << 8)
                | 0xFF
            )
            button.setProperty("nuke_colour", packed)
            self._style_colour_button(button, packed)

    def _remove_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)

        for row in rows:
            self.table.removeRow(row)

    def _restore_defaults(self):
        self.table.setRowCount(0)

        for rule in DEFAULT_RULES:
            self._add_rule(rule)

    def _save(self):
        result = []

        for row in range(self.table.rowCount()):
            search_item = self.table.item(row, 0)
            prefix_item = self.table.item(row, 1)
            remove_item = self.table.item(row, 2)
            colour_button = self.table.cellWidget(row, 3)
            search = search_item.text().strip() if search_item else ""
            prefix = prefix_item.text().strip().upper() if prefix_item else ""
            remove = remove_item.text().strip() if remove_item else ""

            if search and prefix:
                result.append({
                    "search": search,
                    "prefix": prefix,
                    "remove": remove,
                    "colour": int(colour_button.property("nuke_colour")),
                })

        save_rules(result)
        self.accept()


def edit_rules(parent=None):
    return RuleEditorDialog(parent).exec()
