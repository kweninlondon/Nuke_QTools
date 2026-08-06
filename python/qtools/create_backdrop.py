"""Create consistently styled Nuke backdrops around selected nodes."""

import colorsys
import hashlib
import re

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "CreateBackdrop"

TEXT_SIZES = [
    ("Huge (200 px)", 200),
    ("Big", 50),
    ("Medium", 32),
    ("Small", 20),
]
PALETTES = {
    "Balanced": (0.52, 0.58),
    "Pastel": (0.34, 0.76),
    "Vivid": (0.72, 0.66),
    "Muted": (0.30, 0.52),
    "Dark": (0.48, 0.36),
}
PALETTE_ORDER = ["Balanced", "Pastel", "Vivid", "Muted", "Dark"]

# Familiar departments retain intuitive base families. All other first words
# are assigned a stable hue from their text.
SEMANTIC_HUES = {
    "roto": 0.0,
    "key": 0.31,
    "keying": 0.31,
    "plate": 0.54,
    "cg": 0.08,
    "dmp": 0.78,
    "comp": 0.61,
    "camera": 0.36,
    "3d": 0.36,
}


def _settings():
    return QtCore.QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def _setting_bool(key, default):
    value = _settings().value(key, default)

    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}

    return bool(value)


def _stable_fraction(text, offset=0):
    digest = hashlib.sha256(str(text).encode("utf-8")).digest()
    index = int(offset) % (len(digest) - 1)
    return int.from_bytes(digest[index:index + 2], "big") / 65535.0


def _normalise_title(title):
    return " ".join(re.findall(r"[\w]+", str(title).lower()))


def automatic_rgb(title, palette_name):
    """Return a stable related colour; the first word defines its family."""
    normalised = _normalise_title(title) or "backdrop"
    words = normalised.split()
    family = words[0]
    base_hue = SEMANTIC_HUES.get(family, _stable_fraction(family))

    # Remaining words only make small variations, keeping related titles close.
    variation_key = " ".join(words[1:]) or family
    hue_delta = (_stable_fraction(variation_key, 2) - 0.5) * 0.055
    saturation_delta = (_stable_fraction(variation_key, 7) - 0.5) * 0.10
    value_delta = (_stable_fraction(variation_key, 13) - 0.5) * 0.10
    saturation, value = PALETTES.get(
        palette_name,
        PALETTES["Balanced"]
    )
    red, green, blue = colorsys.hsv_to_rgb(
        (base_hue + hue_delta) % 1.0,
        max(0.12, min(0.90, saturation + saturation_delta)),
        max(0.20, min(0.88, value + value_delta)),
    )
    return tuple(int(round(component * 255)) for component in (red, green, blue))


def _palette_swatches(palette_name):
    saturation, value = PALETTES.get(
        palette_name,
        PALETTES["Balanced"]
    )
    return [
        tuple(
            int(round(component * 255))
            for component in colorsys.hsv_to_rgb(hue / 10.0, saturation, value)
        )
        for hue in range(10)
    ]


def _packed_colour(rgb):
    red, green, blue = rgb
    return (red << 24) | (green << 16) | (blue << 8) | 0xFF


def _contrast_colour(rgb):
    red, green, blue = rgb
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
    return 0x000000FF if luminance > 0.48 else 0xFFFFFFFF


def _node_bounds(node):
    if node.Class() == "BackdropNode":
        return (
            node.xpos(),
            node.ypos(),
            node.xpos() + int(node["bdwidth"].value()),
            node.ypos() + int(node["bdheight"].value()),
        )

    return (
        node.xpos(),
        node.ypos(),
        node.xpos() + node.screenWidth(),
        node.ypos() + node.screenHeight(),
    )


def _average_node_size(nodes):
    """Return a stable representative width for the selected nodes."""
    sizes = sorted(
        max(30, int(node.screenWidth()))
        for node in nodes
        if node.Class() != "BackdropNode"
    )

    if not sizes:
        return 80

    middle = len(sizes) // 2
    median = (
        sizes[middle]
        if len(sizes) % 2
        else (sizes[middle - 1] + sizes[middle]) / 2.0
    )
    return max(40, min(160, int(round(median))))


def _backdrop_geometry(nodes, margin_factor, font_size):
    margin = int(round(_average_node_size(nodes) * margin_factor))
    bounds = [_node_bounds(node) for node in nodes]
    left = min(item[0] for item in bounds) - margin
    top = min(item[1] for item in bounds) - margin - font_size - 18
    right = max(item[2] for item in bounds) + margin
    bottom = max(item[3] for item in bounds) + margin
    return left, top, right - left, bottom - top


def _closest_outward_edge(current, candidates, direction):
    """Return the nearest candidate that only expands the new backdrop."""
    eligible = [
        candidate for candidate, tolerance in candidates
        if (
            (candidate <= current if direction < 0 else candidate >= current)
            and abs(candidate - current) <= tolerance
        )
    ]

    if not eligible:
        return current

    return min(eligible, key=lambda candidate: abs(candidate - current))


def _align_backdrop_geometry(geometry, selected_nodes, tolerance_ratio=0.50):
    """Expand nearby edges to existing Backdrop coordinates when possible."""
    left, top, width, height = geometry
    right = left + width
    bottom = top + height
    selected_nodes = set(selected_nodes)
    left_candidates = []
    right_candidates = []
    top_candidates = []
    bottom_candidates = []

    for backdrop in nuke.allNodes("BackdropNode"):
        if backdrop in selected_nodes:
            continue

        other_left, other_top, other_right, other_bottom = _node_bounds(
            backdrop
        )
        other_width = other_right - other_left
        other_height = other_bottom - other_top
        horizontal_tolerance = tolerance_ratio * max(width, other_width)
        vertical_tolerance = tolerance_ratio * max(height, other_height)
        left_candidates.append((other_left, horizontal_tolerance))
        right_candidates.append((other_right, horizontal_tolerance))
        top_candidates.append((other_top, vertical_tolerance))
        bottom_candidates.append((other_bottom, vertical_tolerance))

    aligned_left = _closest_outward_edge(left, left_candidates, -1)
    aligned_right = _closest_outward_edge(right, right_candidates, 1)
    aligned_top = _closest_outward_edge(top, top_candidates, -1)
    aligned_bottom = _closest_outward_edge(bottom, bottom_candidates, 1)
    return (
        aligned_left,
        aligned_top,
        aligned_right - aligned_left,
        aligned_bottom - aligned_top,
    )


def _next_backdrop_z_order():
    values = []

    for backdrop in nuke.allNodes("BackdropNode"):
        try:
            values.append(int(backdrop["z_order"].value()))
        except Exception:
            continue

    return min(values or [0]) - 1


class CreateBackdropDialog(QtWidgets.QDialog):
    """Collect backdrop title, layout, typography and colour choices."""

    def __init__(self, parent=None):
        super(CreateBackdropDialog, self).__init__(parent)
        self._manual_rgb = (58, 132, 134)
        self.setWindowTitle("Create backdrop")
        self.setMinimumWidth(520)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.title_field = QtWidgets.QLineEdit()
        self.title_field.setPlaceholderText("Enter backdrop title...")
        form.addRow("Title:", self.title_field)

        self.margin_field = QtWidgets.QDoubleSpinBox()
        self.margin_field.setRange(0.0, 5.0)
        self.margin_field.setSingleStep(0.25)
        self.margin_field.setDecimals(2)
        self.margin_field.setSuffix(" × node")
        self.margin_field.setValue(
            float(_settings().value("margin_factor", 1.0))
        )
        self.margin_field.setToolTip(
            "Spacing on every side. 1.0 equals the representative width of "
            "the selected nodes."
        )
        form.addRow("Margin:", self.margin_field)

        self.align_edges_checkbox = QtWidgets.QCheckBox(
            "Align nearby backdrop edges"
        )
        self.align_edges_checkbox.setChecked(
            _setting_bool("align_edges", True)
        )
        self.align_edges_checkbox.setToolTip(
            "Expand edges to nearby backdrop coordinates within 50%. Edges "
            "never move inward past the selected margin."
        )
        form.addRow("", self.align_edges_checkbox)

        self.text_size_combo = QtWidgets.QComboBox()
        for label, value in TEXT_SIZES:
            self.text_size_combo.addItem(label, value)
        saved_text_size = int(_settings().value("text_size", 50))
        size_index = self.text_size_combo.findData(saved_text_size)
        self.text_size_combo.setCurrentIndex(size_index if size_index >= 0 else 0)
        form.addRow("Text:", self.text_size_combo)

        self.bold_checkbox = QtWidgets.QCheckBox("Bold")
        self.bold_checkbox.setChecked(_setting_bool("bold", False))
        self.bold_checkbox.setToolTip(
            "Use the bold variant of Nuke's backdrop font."
        )
        form.addRow("", self.bold_checkbox)

        self.appearance_combo = QtWidgets.QComboBox()
        self.appearance_combo.addItems(["Fill", "Border"])
        saved_appearance = str(_settings().value("appearance", "Fill"))
        appearance_index = self.appearance_combo.findText(saved_appearance)
        self.appearance_combo.setCurrentIndex(
            appearance_index if appearance_index >= 0 else 0
        )
        form.addRow("Appearance:", self.appearance_combo)

        self.palette_combo = QtWidgets.QComboBox()
        self.palette_combo.addItems(PALETTE_ORDER)
        saved_palette = str(_settings().value("palette", "Balanced"))
        palette_index = self.palette_combo.findText(saved_palette)
        self.palette_combo.setCurrentIndex(palette_index if palette_index >= 0 else 0)
        form.addRow("Colour palette:", self.palette_combo)
        layout.addLayout(form)

        colour_options = QtWidgets.QHBoxLayout()
        self.auto_colour_checkbox = QtWidgets.QCheckBox("Auto assign colour")
        self.auto_colour_checkbox.setChecked(
            _setting_bool("auto_colour", True)
        )
        self.auto_preview = QtWidgets.QLabel()
        self.auto_preview.setFixedSize(70, 24)
        colour_options.addWidget(self.auto_colour_checkbox)
        colour_options.addWidget(QtWidgets.QLabel("Result:"))
        colour_options.addWidget(self.auto_preview)
        colour_options.addStretch()
        layout.addLayout(colour_options)

        self.swatch_layout = QtWidgets.QHBoxLayout()
        self.swatch_layout.addWidget(QtWidgets.QLabel("Manual colour:"))
        self._swatch_buttons = []
        layout.addLayout(self.swatch_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Create")
        layout.addWidget(buttons)

        self.palette_combo.currentTextChanged.connect(self._rebuild_swatches)
        self.title_field.textChanged.connect(self._update_colour_preview)
        self.auto_colour_checkbox.toggled.connect(self._auto_colour_toggled)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        self._rebuild_swatches()
        self._auto_colour_toggled(self.auto_colour_checkbox.isChecked())
        self.title_field.setFocus()

    def _rebuild_swatches(self, _palette=None):
        while self._swatch_buttons:
            button = self._swatch_buttons.pop()
            self.swatch_layout.removeWidget(button)
            button.deleteLater()

        swatches = _palette_swatches(self.palette_combo.currentText())

        for rgb in swatches:
            button = QtWidgets.QPushButton()
            button.setFixedSize(28, 24)
            button.setStyleSheet(
                "background-color: rgb({}, {}, {});".format(*rgb)
            )
            button.setToolTip("Use this manual backdrop colour")
            button.clicked.connect(
                lambda _checked=False, colour=rgb: self._select_swatch(colour)
            )
            self._swatch_buttons.append(button)
            self.swatch_layout.addWidget(button)

        self._manual_rgb = swatches[5]
        self._auto_colour_toggled(self.auto_colour_checkbox.isChecked())
        self._update_colour_preview()

    def _select_swatch(self, rgb):
        self._manual_rgb = rgb
        self._update_colour_preview()

    def _auto_colour_toggled(self, checked):
        for button in self._swatch_buttons:
            button.setEnabled(not checked)
        self._update_colour_preview()

    def selected_rgb(self):
        if self.auto_colour_checkbox.isChecked():
            return automatic_rgb(
                self.title_field.text(),
                self.palette_combo.currentText()
            )
        return self._manual_rgb

    def _update_colour_preview(self, _value=None):
        rgb = self.selected_rgb()
        self.auto_preview.setStyleSheet(
            "background-color: rgb({}, {}, {}); border: 1px solid #777;".format(
                *rgb
            )
        )

    def _accept(self):
        settings = _settings()
        settings.setValue("margin_factor", self.margin_field.value())
        settings.setValue("align_edges", self.align_edges_checkbox.isChecked())
        settings.setValue("text_size", self.text_size_combo.currentData())
        settings.setValue("bold", self.bold_checkbox.isChecked())
        settings.setValue("appearance", self.appearance_combo.currentText())
        settings.setValue("palette", self.palette_combo.currentText())
        settings.setValue("auto_colour", self.auto_colour_checkbox.isChecked())
        settings.sync()
        self.accept()

    def values(self):
        return {
            "title": " ".join(self.title_field.text().split()),
            "margin_factor": float(self.margin_field.value()),
            "align_edges": self.align_edges_checkbox.isChecked(),
            "font_size": int(self.text_size_combo.currentData()),
            "bold": self.bold_checkbox.isChecked(),
            "appearance": self.appearance_combo.currentText(),
            "rgb": self.selected_rgb(),
        }


def _nuke_main_window():
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


def create_backdrop():
    """Open the options window and create a backdrop around selected nodes."""
    nodes = [
        node for node in nuke.selectedNodes()
        if node.Class() != "Viewer"
    ]

    if not nodes:
        nuke.message("Select at least one node to create a backdrop.")
        return None

    dialog = CreateBackdropDialog(parent=_nuke_main_window())

    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return None

    values = dialog.values()
    xpos, ypos, width, height = _backdrop_geometry(
        nodes,
        values["margin_factor"],
        values["font_size"]
    )

    if values["align_edges"]:
        xpos, ypos, width, height = _align_backdrop_geometry(
            (xpos, ypos, width, height),
            nodes
        )
    undo = nuke.Undo()
    undo.begin("Create QTools Backdrop")

    try:
        backdrop = nuke.nodes.BackdropNode(
            xpos=xpos,
            ypos=ypos,
            bdwidth=width,
            bdheight=height,
            label=values["title"],
            note_font_size=values["font_size"],
            tile_color=_packed_colour(values["rgb"]),
            note_font_color=_contrast_colour(values["rgb"]),
            z_order=_next_backdrop_z_order(),
        )

        if "appearance" in backdrop.knobs():
            backdrop["appearance"].setValue(values["appearance"])

        if values["bold"] and "note_font" in backdrop.knobs():
            font_name = str(backdrop["note_font"].value() or "")

            if "bold" not in font_name.lower():
                backdrop["note_font"].setValue(
                    "{} Bold".format(font_name).strip()
                )

        if "border_width" in backdrop.knobs():
            backdrop["border_width"].setValue(
                4 if values["appearance"] == "Border" else 2
            )

        for node in nuke.selectedNodes():
            node.setSelected(False)
        backdrop.setSelected(True)
        return backdrop
    finally:
        undo.end()
