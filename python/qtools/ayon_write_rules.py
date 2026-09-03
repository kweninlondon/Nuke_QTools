"""Editable filename rules for deriving AYON Write variants."""

import json
import os
import re

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "AyonWriteCreator"
SETTING_RULES = "variant_rules_v1"

DEFAULT_RULES = [
    {"search": "roto_", "remove": "_v###", "variant": ""},
    {"search": "matte_", "remove": "_v###", "variant": ""},
    {"search": "mask_", "remove": "_v###", "variant": ""},
]


def _settings():
    return QtCore.QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def rules():
    raw_value = _settings().value(SETTING_RULES, "")
    if raw_value:
        try:
            saved = json.loads(str(raw_value))
            if isinstance(saved, list):
                return [
                    {
                        "search": str(item.get("search", "")).strip(),
                        "remove": str(item.get("remove", "")).strip(),
                        "variant": str(item.get("variant", "")).strip(),
                    }
                    for item in saved
                    if isinstance(item, dict) and item.get("search")
                ]
        except (TypeError, ValueError):
            pass
    return [dict(item) for item in DEFAULT_RULES]


def save_rules(items):
    settings = _settings()
    settings.setValue(SETTING_RULES, json.dumps(items))
    settings.sync()


def _terms(value):
    return [
        term.strip()
        for term in re.split(r"[,;|]+", str(value or ""))
        if term.strip()
    ]


def _remove_patterns(value, patterns):
    result = str(value or "")
    for pattern in _terms(patterns):
        expression = "".join(
            r"\d" if character == "#" else re.escape(character)
            for character in pattern
        )
        result = re.sub(expression, "", result, flags=re.IGNORECASE)
    return result


def source_text(node):
    """Return the best filename-like text for a Read or Write node."""
    try:
        value = str(node["file"].value() or "")
    except Exception:
        value = ""
    if value:
        basename = os.path.basename(value.replace("\\", "/"))
        stem, extension = os.path.splitext(basename)
        if extension:
            basename = stem
        return basename
    try:
        return str(node["label"].value() or node.name())
    except Exception:
        return str(node.name())


def clean_variant(value):
    value = re.sub(r"(?:[._-]?%0?\d*d|[._-]?#+)$", "", str(value or ""))
    value = re.sub(r"[._-]+", " ", value)
    words = [word for word in value.split() if word]
    return "".join(word[:1].upper() + word[1:] for word in words)


def proposed_variant(text, items=None):
    """Return ``(variant, matched)`` using the first matching rule."""
    original = str(text or "")
    lowered = original.lower()
    for rule in items or rules():
        for term in _terms(rule.get("search", "")):
            index = lowered.find(term.lower())
            if index < 0:
                continue
            fixed = clean_variant(rule.get("variant", ""))
            if fixed:
                return fixed, True
            remainder = original[index + len(term):]
            remainder = _remove_patterns(remainder, rule.get("remove", ""))
            variant = clean_variant(remainder)
            return (variant or clean_variant(original), True)

    fallback = _remove_patterns(original, "_v###, v###")
    return clean_variant(fallback), False


class RuleEditorDialog(QtWidgets.QDialog):
    """Edit ordered filename-to-variant rules."""

    def __init__(self, parent=None):
        super(RuleEditorDialog, self).__init__(parent)
        self.setWindowTitle("AYON Write variant rules")
        self.resize(760, 400)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Rules are checked top to bottom. Separate alternatives with commas. "
            "Each # in Remove matches one digit. If Fixed variant is empty, the "
            "filename text after the matched search becomes the variant."
        ))
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Filename search", "Remove", "Fixed variant"]
        )
        for column in range(3):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QtWidgets.QHeaderView.Stretch
            )
        layout.addWidget(self.table)

        controls = QtWidgets.QHBoxLayout()
        add_button = QtWidgets.QPushButton("Add rule")
        remove_button = QtWidgets.QPushButton("Remove selected")
        defaults_button = QtWidgets.QPushButton("Restore defaults")
        controls.addWidget(add_button)
        controls.addWidget(remove_button)
        controls.addWidget(defaults_button)
        controls.addStretch()
        layout.addLayout(controls)

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
        for column, key in enumerate(("search", "remove", "variant")):
            self.table.setItem(
                row, column, QtWidgets.QTableWidgetItem(rule.get(key, ""))
            )

    def _remove_selected(self):
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            self.table.removeRow(row)

    def _restore_defaults(self):
        self.table.setRowCount(0)
        for rule in DEFAULT_RULES:
            self._add_rule(rule)

    def _save(self):
        result = []
        for row in range(self.table.rowCount()):
            values = []
            for column in range(3):
                item = self.table.item(row, column)
                values.append(item.text().strip() if item else "")
            if values[0]:
                result.append(dict(zip(("search", "remove", "variant"), values)))
        save_rules(result)
        self.accept()


def edit_rules(parent=None):
    return RuleEditorDialog(parent).exec()
