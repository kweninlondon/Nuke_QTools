"""Create consistently styled Nuke backdrops around selected nodes."""

import colorsys
import difflib
import hashlib
import json
import re

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "CreateBackdrop"

TEXT_SIZES = [
    ("Huge", 200),
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
COLOUR_METHODS = [
    ("Hash - Distinct", "hash"),
    ("Text similarity - Related", "similarity"),
]
FAMILY_ROOT_KNOB = "qtools_backdrop_families"

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


def _unpacked_colour(value):
    value = int(value)
    return (value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF


def _family_registry():
    """Read the per-script backdrop colour-family registry."""
    families = {}
    root = nuke.root()

    if FAMILY_ROOT_KNOB in root.knobs():
        try:
            payload = json.loads(str(root[FAMILY_ROOT_KNOB].value() or "{}"))
            families.update(payload.get("families", payload))
        except (TypeError, ValueError):
            pass

    return families


def _save_family_registry(families):
    root = nuke.root()

    if FAMILY_ROOT_KNOB not in root.knobs():
        knob = nuke.String_Knob(FAMILY_ROOT_KNOB, FAMILY_ROOT_KNOB)
        knob.setVisible(False)
        root.addKnob(knob)

    root[FAMILY_ROOT_KNOB].setValue(json.dumps({
        "version": 1,
        "families": families,
    }, sort_keys=True))


def _matching_family(title, families):
    """Return the longest word-prefix family, then a same-root fallback."""
    words = _normalise_title(title).split()

    if not words:
        return None

    prefix_matches = []
    root_matches = []

    for family in families:
        family_words = family.split()

        if not family_words or family_words[0] != words[0]:
            continue

        root_matches.append(family)

        if words[:len(family_words)] == family_words:
            prefix_matches.append(family)

    if prefix_matches:
        return max(prefix_matches, key=lambda item: (len(item.split()), len(item)))

    if root_matches:
        return min(root_matches, key=lambda item: (len(item.split()), len(item)))

    return None


def _family_variation_rgb(title, family, base_rgb):
    normalised = _normalise_title(title)

    if normalised == family:
        return base_rgb

    red, green, blue = (component / 255.0 for component in base_rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    hue += (_stable_fraction(normalised, 3) - 0.5) * 0.035
    saturation += (_stable_fraction(normalised, 9) - 0.5) * 0.06
    value += (_stable_fraction(normalised, 15) - 0.5) * 0.06
    varied = colorsys.hsv_to_rgb(
        hue % 1.0,
        max(0.08, min(0.95, saturation)),
        max(0.12, min(0.95, value)),
    )
    return tuple(int(round(component * 255)) for component in varied)


def _label_similarity(first, second):
    first = _normalise_title(first)
    second = _normalise_title(second)
    direct = difflib.SequenceMatcher(None, first, second).ratio()
    ordered = difflib.SequenceMatcher(
        None,
        " ".join(sorted(first.split())),
        " ".join(sorted(second.split())),
    ).ratio()
    return max(direct, ordered)


def _similarity_rgb(title, examples, palette_name):
    """Reuse the hue of the most textually similar existing backdrop."""
    matches = [
        (_label_similarity(title, other_title), other_rgb)
        for other_title, other_rgb in examples
        if _normalise_title(other_title) != _normalise_title(title)
    ]

    if not matches:
        return automatic_rgb(title, palette_name)

    score, rgb = max(matches, key=lambda item: item[0])

    if score < 0.72:
        return automatic_rgb(title, palette_name)

    return _family_variation_rgb(title, "", rgb)


def _backdrop_colour_examples():
    examples = []

    for backdrop in nuke.allNodes("BackdropNode"):
        try:
            label = str(backdrop["label"].value() or "")
            rgb = _unpacked_colour(backdrop["tile_color"].value())
        except Exception:
            continue

        if _normalise_title(label):
            examples.append((label, rgb))

    return examples


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


def _expanded_geometry(current, candidate):
    """Union two Backdrop geometries so no current edge moves inward."""
    current_left, current_top, current_width, current_height = current
    candidate_left, candidate_top, candidate_width, candidate_height = candidate
    left = min(current_left, candidate_left)
    top = min(current_top, candidate_top)
    right = max(
        current_left + current_width,
        candidate_left + candidate_width,
    )
    bottom = max(
        current_top + current_height,
        candidate_top + candidate_height,
    )
    return left, top, right - left, bottom - top


def _capture_graph_positions(excluded=None):
    """Capture graph positions so Backdrop resizing cannot drag nodes."""
    excluded = set(excluded or [])
    return [
        (node, node.xpos(), node.ypos())
        for node in nuke.allNodes()
        if node not in excluded
    ]


def _restore_graph_positions(positions):
    """Restore Backdrops first, then regular nodes nested inside them."""
    backdrops = []
    regular_nodes = []

    for item in positions:
        if item[0].Class() == "BackdropNode":
            backdrops.append(item)
        else:
            regular_nodes.append(item)

    backdrops.sort(
        key=lambda item: -int(item[0]["bdwidth"].value())
        * int(item[0]["bdheight"].value())
    )

    for node, xpos, ypos in backdrops + regular_nodes:
        try:
            node.setXYpos(int(xpos), int(ypos))
        except Exception:
            pass


def _nodes_inside_backdrop(backdrop):
    """Return non-Backdrop nodes fully contained by a backdrop."""
    left, top, right, bottom = _node_bounds(backdrop)
    contained = []

    for node in nuke.allNodes():
        if node is backdrop or node.Class() in {"BackdropNode", "Viewer"}:
            continue

        node_left, node_top, node_right, node_bottom = _node_bounds(node)
        if (
            node_left >= left
            and node_top >= top
            and node_right <= right
            and node_bottom <= bottom
        ):
            contained.append(node)

    return contained


def _inferred_margin_factor(backdrop, nodes):
    """Estimate the tool margin used to create an existing backdrop."""
    if not nodes:
        return 1.0

    left, _top, right, bottom = _node_bounds(backdrop)
    bounds = [_node_bounds(node) for node in nodes]
    padding = sorted([
        max(0, min(item[0] for item in bounds) - left),
        max(0, right - max(item[2] for item in bounds)),
        max(0, bottom - max(item[3] for item in bounds)),
    ])
    margin = padding[len(padding) // 2]
    return max(0.0, min(5.0, margin / float(_average_node_size(nodes))))


def _base_font_name(font_name):
    """Remove a Bold style token while preserving the rest of a font name."""
    return " ".join(
        token for token in str(font_name).split()
        if token.lower() != "bold"
    )


def _label_font(font_name, font_size, bold):
    """Build a Qt font that approximates Nuke's graph label rendering."""
    font = QtGui.QFont(font_name) if font_name else QtGui.QFont()
    font.setPixelSize(max(1, int(font_size)))
    font.setBold(bool(bold))
    return font


def _wrap_title(title, backdrop_width, font_size, bold=False, font_name=""):
    """Wrap a title at word boundaries when it exceeds the backdrop width."""
    words = str(title).split()

    if len(words) < 2:
        return " ".join(words)

    metrics = QtGui.QFontMetricsF(
        _label_font(font_name, font_size, bold)
    )
    available_width = max(1.0, float(backdrop_width) - 24.0)

    def text_width(text):
        if hasattr(metrics, "horizontalAdvance"):
            return metrics.horizontalAdvance(text)
        return metrics.width(text)

    lines = []
    current = words[0]

    for word in words[1:]:
        candidate = "{} {}".format(current, word)

        if text_width(candidate) <= available_width:
            current = candidate
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return "\n".join(lines)


def _make_label(title, geometry, font_size, bold, font_name, wrap_title):
    if not wrap_title:
        return title

    return _wrap_title(title, geometry[2], font_size, bold, font_name)


def _make_room_for_label(geometry, label, font_size):
    """Extend the backdrop upward for every wrapped line after the first."""
    extra_lines = max(0, str(label).count("\n"))

    if not extra_lines:
        return geometry

    left, top, width, height = geometry
    extra_height = extra_lines * (int(font_size) + 4)
    return left, top - extra_height, width, height + extra_height


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


def _bounds_contain(outer, inner):
    """Return whether one left/top/right/bottom box contains another."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _bounds_intersect(first, second):
    """Return whether two closed boxes overlap or touch at their edges."""
    return (
        first[0] <= second[2]
        and first[2] >= second[0]
        and first[1] <= second[3]
        and first[3] >= second[1]
    )


def _align_backdrop_geometry(geometry, selected_nodes, tolerance_ratio=0.50):
    """Expand nearby edges to existing Backdrop coordinates when possible."""
    left, top, width, height = geometry
    right = left + width
    bottom = top + height
    horizontal_tolerance = tolerance_ratio * width
    vertical_tolerance = tolerance_ratio * height
    influence_left = left - horizontal_tolerance
    influence_right = right + horizontal_tolerance
    influence_top = top - vertical_tolerance
    influence_bottom = bottom + vertical_tolerance
    selected_nodes = set(selected_nodes)
    left_candidates = []
    right_candidates = []
    top_candidates = []
    bottom_candidates = []
    nearby_bounds = []

    for backdrop in nuke.allNodes("BackdropNode"):
        if backdrop in selected_nodes:
            continue

        other_left, other_top, other_right, other_bottom = _node_bounds(
            backdrop
        )

        intersects_influence = not (
            other_right < influence_left
            or other_left > influence_right
            or other_bottom < influence_top
            or other_top > influence_bottom
        )

        if not intersects_influence:
            continue

        nearby_bounds.append(
            (other_left, other_top, other_right, other_bottom)
        )
        left_candidates.append((other_left, horizontal_tolerance))
        right_candidates.append((other_right, horizontal_tolerance))
        top_candidates.append((other_top, vertical_tolerance))
        bottom_candidates.append((other_bottom, vertical_tolerance))

    aligned_left = _closest_outward_edge(left, left_candidates, -1)
    aligned_right = _closest_outward_edge(right, right_candidates, 1)
    aligned_top = _closest_outward_edge(top, top_candidates, -1)
    aligned_bottom = _closest_outward_edge(bottom, bottom_candidates, 1)

    original_bounds = (left, top, right, bottom)

    # Parallel edges may share an X or Y coordinate only while the Backdrops
    # remain separated. Reject boundary contact, overlap, or new containment.
    # Existing intentional nesting remains valid.
    for other_bounds in nearby_bounds:
        aligned_bounds = (
            aligned_left,
            aligned_top,
            aligned_right,
            aligned_bottom,
        )

        originally_nested = (
            _bounds_contain(original_bounds, other_bounds)
            or _bounds_contain(other_bounds, original_bounds)
        )

        if (
            _bounds_intersect(aligned_bounds, other_bounds)
            and not originally_nested
        ):
            if aligned_left < left and other_bounds[0] < left:
                aligned_left = left
            if aligned_top < top and other_bounds[1] < top:
                aligned_top = top
            if aligned_right > right and other_bounds[2] > right:
                aligned_right = right
            if aligned_bottom > bottom and other_bounds[3] > bottom:
                aligned_bottom = bottom

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

    def __init__(self, nodes, parent=None, edit_backdrop=None):
        super(CreateBackdropDialog, self).__init__(parent)
        self._nodes = list(nodes)
        self._edit_backdrop = edit_backdrop
        self._initial_selection = list(nuke.selectedNodes())
        self._manual_rgb = (58, 132, 134)
        self._families = _family_registry()
        self._colour_examples = _backdrop_colour_examples()
        self._pending_family = None
        self._pending_family_rgb = None
        self._preview_backdrop = None
        self._influence_backdrop = None
        self._edit_snapshot = None
        self._graph_positions = []
        self._preview_font_name = ""
        self._preview_ready = False
        self._undo_disabled = False
        self.setWindowTitle(
            "Edit backdrop" if self._edit_backdrop is not None
            else "Create backdrop"
        )
        self.setMinimumWidth(520)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.title_field = QtWidgets.QLineEdit()
        self.title_field.setPlaceholderText("Enter backdrop title...")
        form.addRow("Title:", self.title_field)

        self.text_size_combo = QtWidgets.QComboBox()
        for label, value in TEXT_SIZES:
            self.text_size_combo.addItem(label, value)
        saved_text_size = int(_settings().value("text_size", 50))
        size_index = self.text_size_combo.findData(saved_text_size)
        self.text_size_combo.setCurrentIndex(size_index if size_index >= 0 else 0)
        self.bold_checkbox = QtWidgets.QCheckBox("Bold")
        self.bold_checkbox.setChecked(_setting_bool("bold", False))
        self.bold_checkbox.setToolTip(
            "Use the bold variant of Nuke's backdrop font."
        )
        text_widget = QtWidgets.QWidget()
        text_layout = QtWidgets.QHBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.text_size_combo)
        text_layout.addWidget(self.bold_checkbox)
        text_layout.addStretch()
        form.addRow("Text:", text_widget)

        self.wrap_title_checkbox = QtWidgets.QCheckBox(
            "Wrap title to fit backdrop"
        )
        self.wrap_title_checkbox.setChecked(
            _setting_bool("wrap_title", True)
        )
        self.wrap_title_checkbox.setToolTip(
            "Move whole words onto new lines when the title is wider than "
            "the backdrop."
        )
        form.addRow("Title layout:", self.wrap_title_checkbox)

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

        colour_widget = QtWidgets.QWidget()
        colour_options = QtWidgets.QHBoxLayout(colour_widget)
        colour_options.setContentsMargins(0, 0, 0, 0)
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
        form.addRow("Colour:", colour_widget)

        self.colour_method_combo = QtWidgets.QComboBox()
        for label, value in COLOUR_METHODS:
            self.colour_method_combo.addItem(label, value)
        saved_method = str(_settings().value("colour_method", "hash"))
        method_index = self.colour_method_combo.findData(saved_method)
        self.colour_method_combo.setCurrentIndex(
            method_index if method_index >= 0 else 0
        )
        self.colour_method_combo.setToolTip(
            "Choose how unmatched labels receive an initial colour. Saved "
            "script families always take priority."
        )
        form.addRow("Unmatched labels:", self.colour_method_combo)

        swatch_widget = QtWidgets.QWidget()
        self.swatch_layout = QtWidgets.QHBoxLayout(swatch_widget)
        self.swatch_layout.setContentsMargins(0, 0, 0, 0)
        self._swatch_buttons = []
        form.addRow("Manual:", swatch_widget)

        self.margin_field = QtWidgets.QDoubleSpinBox()
        self.margin_field.setRange(0.0, 5.0)
        self.margin_field.setSingleStep(0.25)
        self.margin_field.setDecimals(2)
        self.margin_field.setValue(
            float(_settings().value("margin_factor", 1.0))
        )
        self.margin_field.setToolTip(
            "Spacing on every side. 1.0 equals the representative width of "
            "the selected nodes."
        )
        margin_widget = QtWidgets.QWidget()
        margin_layout = QtWidgets.QHBoxLayout(margin_widget)
        margin_layout.setContentsMargins(0, 0, 0, 0)
        margin_layout.addWidget(self.margin_field)
        margin_layout.addWidget(QtWidgets.QLabel("× node"))
        margin_layout.addStretch()
        form.addRow("Margin:", margin_widget)

        self.refit_geometry_label = QtWidgets.QLabel("Geometry:")
        self.refit_geometry_checkbox = QtWidgets.QCheckBox(
            "Refit backdrop around contained nodes"
        )
        self.refit_geometry_checkbox.setChecked(
            self._edit_backdrop is not None
        )
        self.refit_geometry_checkbox.setToolTip(
            "Recalculate the backdrop bounds from its contained nodes and "
            "the selected margin when Apply is clicked."
        )
        form.addRow(
            self.refit_geometry_label,
            self.refit_geometry_checkbox,
        )
        edit_mode = self._edit_backdrop is not None
        self.refit_geometry_label.setVisible(edit_mode)
        self.refit_geometry_checkbox.setVisible(edit_mode)

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
        form.addRow("Align:", self.align_edges_checkbox)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            "Apply" if self._edit_backdrop is not None else "Create"
        )
        layout.addWidget(buttons)

        self.palette_combo.currentTextChanged.connect(self._rebuild_swatches)
        self.title_field.textChanged.connect(self._title_changed)
        self.auto_colour_checkbox.toggled.connect(self._auto_colour_toggled)
        self.colour_method_combo.currentIndexChanged.connect(
            self._update_colour_preview
        )
        self.margin_field.valueChanged.connect(self._update_graph_preview)
        self.refit_geometry_checkbox.toggled.connect(
            self._refit_geometry_toggled
        )
        self.align_edges_checkbox.toggled.connect(self._update_graph_preview)
        self.text_size_combo.currentIndexChanged.connect(
            self._update_graph_preview
        )
        self.bold_checkbox.toggled.connect(self._update_graph_preview)
        self.wrap_title_checkbox.toggled.connect(self._update_graph_preview)
        self.appearance_combo.currentTextChanged.connect(
            self._update_graph_preview
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        self._rebuild_swatches()
        self._load_edit_values()
        self._refit_geometry_toggled(
            self.refit_geometry_checkbox.isChecked()
        )
        self._auto_colour_toggled(self.auto_colour_checkbox.isChecked())
        self._start_graph_preview()
        QtCore.QTimer.singleShot(0, self._update_graph_preview)
        self.title_field.setFocus()

    def _load_edit_values(self):
        """Populate controls from the selected Backdrop in edit mode."""
        backdrop = self._edit_backdrop

        if backdrop is None:
            return

        knobs = backdrop.knobs()
        label = str(backdrop["label"].value() or "")
        self.title_field.setText(" ".join(label.split()))

        font_size = int(backdrop["note_font_size"].value())
        size_index = self.text_size_combo.findData(font_size)

        if size_index < 0:
            self.text_size_combo.addItem(
                "Custom ({})".format(font_size), font_size
            )
            size_index = self.text_size_combo.count() - 1

        self.text_size_combo.setCurrentIndex(size_index)
        font_name = str(
            backdrop["note_font"].value() if "note_font" in knobs else ""
        )
        self._preview_font_name = _base_font_name(font_name)
        self.bold_checkbox.setChecked("bold" in font_name.lower())
        self.wrap_title_checkbox.setChecked(
            "\n" in label or _setting_bool("wrap_title", True)
        )

        if "appearance" in knobs:
            appearance = str(backdrop["appearance"].value())
            appearance_index = self.appearance_combo.findText(appearance)
            if appearance_index >= 0:
                self.appearance_combo.setCurrentIndex(appearance_index)

        self.auto_colour_checkbox.setChecked(False)
        self._manual_rgb = _unpacked_colour(backdrop["tile_color"].value())
        self.margin_field.setValue(
            _inferred_margin_factor(backdrop, self._nodes)
        )

        if not self._nodes:
            self.refit_geometry_checkbox.setChecked(False)
            self.refit_geometry_checkbox.setEnabled(False)
            self.margin_field.setToolTip(
                "This empty backdrop keeps its existing geometry."
            )

    def _refit_geometry_toggled(self, checked):
        enabled = bool(checked) or self._edit_backdrop is None
        if self._edit_backdrop is not None and not self._nodes:
            enabled = False
        self.margin_field.setEnabled(enabled)
        self.align_edges_checkbox.setEnabled(enabled)
        self._update_graph_preview()

    def _start_graph_preview(self):
        """Create temporary graph nodes while preventing undo-stack noise."""
        try:
            nuke.Undo.disable()
            self._undo_disabled = True
            self._graph_positions = _capture_graph_positions(
                [self._edit_backdrop] if self._edit_backdrop is not None else []
            )
            z_order = _next_backdrop_z_order()
            if self._edit_backdrop is not None:
                self._edit_snapshot = self._capture_backdrop_state(
                    self._edit_backdrop
                )
                self._preview_backdrop = self._edit_backdrop
            else:
                self._influence_backdrop = nuke.nodes.BackdropNode(
                    label="Zone of influence (50%)",
                    tile_color=0x808080FF,
                    note_font_color=0xFFFFFFFF,
                    note_font_size=50,
                    z_order=z_order - 1,
                )
                self._preview_backdrop = nuke.nodes.BackdropNode(
                    z_order=z_order,
                )
            if (
                self._edit_backdrop is None
                and "note_font" in self._preview_backdrop.knobs()
            ):
                self._preview_font_name = str(
                    self._preview_backdrop["note_font"].value() or ""
                )

            if self._influence_backdrop is not None:
                if "appearance" in self._influence_backdrop.knobs():
                    self._influence_backdrop["appearance"].setValue("Border")
                if "border_width" in self._influence_backdrop.knobs():
                    self._influence_backdrop["border_width"].setValue(3)

            self._preview_ready = True
            self._update_graph_preview()

            for node in self._nodes:
                node.setSelected(True)
            self._preview_backdrop.setSelected(False)
            if self._influence_backdrop is not None:
                self._influence_backdrop.setSelected(False)
        except Exception:
            self.cleanup_graph_preview()

    @staticmethod
    def _capture_backdrop_state(backdrop):
        state = {
            "xpos": backdrop.xpos(),
            "ypos": backdrop.ypos(),
            "bdwidth": backdrop["bdwidth"].value(),
            "bdheight": backdrop["bdheight"].value(),
        }
        for name in (
            "label",
            "note_font_size",
            "tile_color",
            "note_font_color",
            "appearance",
            "border_width",
            "note_font",
        ):
            if name in backdrop.knobs():
                state[name] = backdrop[name].value()
        return state

    @staticmethod
    def _restore_backdrop_state(backdrop, state):
        if backdrop is None or not state:
            return
        for name, value in state.items():
            if name in {"xpos", "ypos", "bdwidth", "bdheight"}:
                continue
            if name in backdrop.knobs():
                backdrop[name].setValue(value)
        backdrop.setXYpos(int(state["xpos"]), int(state["ypos"]))
        backdrop["bdwidth"].setValue(state["bdwidth"])
        backdrop["bdheight"].setValue(state["bdheight"])

    def cleanup_graph_preview(self):
        """Remove temporary graph nodes and restore normal undo recording."""
        self._preview_ready = False

        self._restore_backdrop_state(
            self._edit_backdrop,
            self._edit_snapshot,
        )
        _restore_graph_positions(self._graph_positions)
        self._edit_snapshot = None
        self._graph_positions = []

        for node in (self._preview_backdrop, self._influence_backdrop):
            if node is None:
                continue
            if node is self._edit_backdrop:
                continue
            try:
                nuke.delete(node)
            except Exception:
                pass

        self._preview_backdrop = None
        self._influence_backdrop = None

        if self._undo_disabled:
            try:
                nuke.Undo.enable()
            except Exception:
                pass
            self._undo_disabled = False

        for node in nuke.selectedNodes():
            try:
                node.setSelected(False)
            except Exception:
                pass

        for node in self._initial_selection:
            try:
                node.setSelected(True)
            except Exception:
                pass

    def _preview_geometries(self):
        values = self.values()

        if self._edit_backdrop is not None and not values["refit_geometry"]:
            state = self._edit_snapshot
            geometry = (
                state["xpos"],
                state["ypos"],
                state["bdwidth"],
                state["bdheight"],
            )
            label = _make_label(
                values["title"] or "Backdrop preview",
                geometry,
                values["font_size"],
                values["bold"],
                values["font_name"],
                values["wrap_title"],
            )
            return values, geometry, (1000000000, 1000000000, 1, 1), label

        base = _backdrop_geometry(
            self._nodes,
            values["margin_factor"],
            values["font_size"]
        )
        left, top, width, height = base
        influence = (
            left - width * 0.5,
            top - height * 0.5,
            width * 2.0,
            height * 2.0,
        )
        aligned = base

        if values["align_edges"]:
            excluded_nodes = self._nodes + [
                self._preview_backdrop,
            ]
            if self._influence_backdrop is not None:
                excluded_nodes.append(self._influence_backdrop)
            if self._edit_backdrop is not None:
                excluded_nodes.append(self._edit_backdrop)
            aligned = _align_backdrop_geometry(
                base,
                excluded_nodes
            )

        label = _make_label(
            values["title"] or "Backdrop preview",
            aligned,
            values["font_size"],
            values["bold"],
            values["font_name"],
            values["wrap_title"],
        )
        aligned = _make_room_for_label(
            aligned, label, values["font_size"]
        )

        if self._edit_backdrop is not None:
            state = self._edit_snapshot
            aligned = _expanded_geometry(
                (
                    state["xpos"],
                    state["ypos"],
                    state["bdwidth"],
                    state["bdheight"],
                ),
                aligned,
            )

        return values, aligned, influence, label

    def _set_preview_geometry(self, node, geometry):
        left, top, width, height = geometry
        node.setXYpos(int(round(left)), int(round(top)))
        node["bdwidth"].setValue(int(round(width)))
        node["bdheight"].setValue(int(round(height)))

    def _update_graph_preview(self, _value=None):
        """Refresh both temporary Backdrops from the current controls."""
        if not self._preview_ready:
            return

        values, preview_geometry, influence_geometry, label = (
            self._preview_geometries()
        )
        preview = self._preview_backdrop
        preview.setSelected(False)
        if self._influence_backdrop is not None:
            self._influence_backdrop.setSelected(False)
        preview["label"].setValue(label)
        preview["note_font_size"].setValue(values["font_size"])
        preview["tile_color"].setValue(_packed_colour(values["rgb"]))
        preview["note_font_color"].setValue(
            _contrast_colour(values["rgb"])
        )

        if "appearance" in preview.knobs():
            preview["appearance"].setValue(values["appearance"])
        if "border_width" in preview.knobs():
            preview["border_width"].setValue(
                4 if values["appearance"] == "Border" else 2
            )
        if "note_font" in preview.knobs():
            font_name = self._preview_font_name
            if values["bold"] and "bold" not in font_name.lower():
                font_name = "{} Bold".format(font_name).strip()
            preview["note_font"].setValue(font_name)

        self._set_preview_geometry(preview, preview_geometry)

        if values["align_edges"] and self._influence_backdrop is not None:
            self._set_preview_geometry(
                self._influence_backdrop,
                influence_geometry
            )
        elif self._influence_backdrop is not None:
            self._set_preview_geometry(
                self._influence_backdrop,
                (1000000000, 1000000000, 1, 1)
            )

        _restore_graph_positions(self._graph_positions)
        preview.setSelected(False)
        if self._influence_backdrop is not None:
            self._influence_backdrop.setSelected(False)

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

        if self.auto_colour_checkbox.isChecked():
            family = _normalise_title(self.title_field.text())

            if family:
                self._pending_family = family
                self._pending_family_rgb = rgb

        self._update_colour_preview()

    def _auto_colour_toggled(self, checked):
        for button in self._swatch_buttons:
            button.setEnabled(True)
            button.setToolTip(
                "Set this as the current label family's colour"
                if checked else "Use this manual backdrop colour"
            )
        self.colour_method_combo.setEnabled(checked)
        self._update_colour_preview()

    def _title_changed(self, _text=None):
        if (
            self._pending_family
            and _normalise_title(self.title_field.text())
            != self._pending_family
        ):
            self._pending_family = None
            self._pending_family_rgb = None

        self._update_colour_preview()

    def _automatic_colour(self):
        title = self.title_field.text()
        families = dict(self._families)

        if self._pending_family and self._pending_family_rgb is not None:
            families[self._pending_family] = _packed_colour(
                self._pending_family_rgb
            )

        family = _matching_family(title, families)

        if family:
            return _family_variation_rgb(
                title,
                family,
                _unpacked_colour(families[family]),
            )

        if self.colour_method_combo.currentData() == "similarity":
            return _similarity_rgb(
                title,
                self._colour_examples,
                self.palette_combo.currentText(),
            )

        return automatic_rgb(title, self.palette_combo.currentText())

    def selected_rgb(self):
        if self.auto_colour_checkbox.isChecked():
            return self._automatic_colour()
        return self._manual_rgb

    def _update_colour_preview(self, _value=None):
        rgb = self.selected_rgb()
        self.auto_preview.setStyleSheet(
            "background-color: rgb({}, {}, {}); border: 1px solid #777;".format(
                *rgb
            )
        )
        self._update_graph_preview()

    def _accept(self):
        settings = _settings()
        settings.setValue("margin_factor", self.margin_field.value())
        settings.setValue("align_edges", self.align_edges_checkbox.isChecked())
        settings.setValue("text_size", self.text_size_combo.currentData())
        settings.setValue("bold", self.bold_checkbox.isChecked())
        settings.setValue("wrap_title", self.wrap_title_checkbox.isChecked())
        settings.setValue("appearance", self.appearance_combo.currentText())
        settings.setValue("palette", self.palette_combo.currentText())
        settings.setValue("auto_colour", self.auto_colour_checkbox.isChecked())
        settings.setValue("colour_method", self.colour_method_combo.currentData())
        settings.sync()
        self.accept()

    def values(self):
        return {
            "title": " ".join(self.title_field.text().split()),
            "margin_factor": float(self.margin_field.value()),
            "align_edges": self.align_edges_checkbox.isChecked(),
            "font_size": int(self.text_size_combo.currentData()),
            "bold": self.bold_checkbox.isChecked(),
            "wrap_title": self.wrap_title_checkbox.isChecked(),
            "font_name": self._preview_font_name,
            "family": (
                self._pending_family
                if self.auto_colour_checkbox.isChecked()
                else None
            ),
            "family_rgb": (
                self._pending_family_rgb
                if self.auto_colour_checkbox.isChecked()
                else None
            ),
            "appearance": self.appearance_combo.currentText(),
            "rgb": self.selected_rgb(),
            "refit_geometry": self.refit_geometry_checkbox.isChecked(),
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
    """Create a backdrop, or edit the single selected Backdrop in place."""
    selected_nodes = [
        node for node in nuke.selectedNodes()
        if node.Class() != "Viewer"
    ]

    if not selected_nodes:
        nuke.message("Select at least one node to create a backdrop.")
        return None

    selected_backdrops = [
        node for node in selected_nodes
        if node.Class() == "BackdropNode"
    ]

    if len(selected_backdrops) > 1:
        nuke.message("Select only one backdrop to edit it.")
        return None

    edit_backdrop = selected_backdrops[0] if selected_backdrops else None
    nodes = (
        _nodes_inside_backdrop(edit_backdrop)
        if edit_backdrop is not None
        else selected_nodes
    )
    dialog = CreateBackdropDialog(
        nodes,
        parent=_nuke_main_window(),
        edit_backdrop=edit_backdrop,
    )

    try:
        result = dialog.exec()
        values = dialog.values() if result == QtWidgets.QDialog.Accepted else None
    finally:
        dialog.cleanup_graph_preview()

    if values is None:
        return None

    preserve_geometry = edit_backdrop is not None and (
        not nodes or not values["refit_geometry"]
    )

    if preserve_geometry:
        left, top, right, bottom = _node_bounds(edit_backdrop)
        xpos, ypos = left, top
        width, height = right - left, bottom - top
    else:
        xpos, ypos, width, height = _backdrop_geometry(
            nodes,
            values["margin_factor"],
            values["font_size"]
        )

    if values["align_edges"] and nodes:
        excluded_nodes = list(nodes)
        if edit_backdrop is not None:
            excluded_nodes.append(edit_backdrop)
        xpos, ypos, width, height = _align_backdrop_geometry(
            (xpos, ypos, width, height),
            excluded_nodes
        )
    label = _make_label(
        values["title"],
        (xpos, ypos, width, height),
        values["font_size"],
        values["bold"],
        values["font_name"],
        values["wrap_title"],
    )
    if not preserve_geometry:
        xpos, ypos, width, height = _make_room_for_label(
            (xpos, ypos, width, height), label, values["font_size"]
        )
        if edit_backdrop is not None:
            left, top, right, bottom = _node_bounds(edit_backdrop)
            xpos, ypos, width, height = _expanded_geometry(
                (left, top, right - left, bottom - top),
                (xpos, ypos, width, height),
            )
    undo = nuke.Undo()
    undo.begin(
        "Edit QTools Backdrop" if edit_backdrop is not None
        else "Create QTools Backdrop"
    )
    graph_positions = []

    try:
        families = _family_registry()

        if values["family"] and values["family_rgb"] is not None:
            families[values["family"]] = _packed_colour(
                values["family_rgb"]
            )
            _save_family_registry(families)

        if edit_backdrop is None:
            backdrop = nuke.nodes.BackdropNode(
                z_order=_next_backdrop_z_order(),
            )
        else:
            backdrop = edit_backdrop

        graph_positions = _capture_graph_positions([backdrop])
        for node in nuke.selectedNodes():
            node.setSelected(False)

        backdrop["label"].setValue(label)
        backdrop["note_font_size"].setValue(values["font_size"])
        backdrop["tile_color"].setValue(_packed_colour(values["rgb"]))
        backdrop["note_font_color"].setValue(
            _contrast_colour(values["rgb"])
        )

        if "appearance" in backdrop.knobs():
            backdrop["appearance"].setValue(values["appearance"])

        if "note_font" in backdrop.knobs():
            font_name = _base_font_name(values["font_name"])
            if values["bold"]:
                font_name = "{} Bold".format(font_name).strip()
            backdrop["note_font"].setValue(font_name)

        if "border_width" in backdrop.knobs():
            backdrop["border_width"].setValue(
                4 if values["appearance"] == "Border" else 2
            )

        # Some Nuke versions adjust Backdrop geometry while appearance/font
        # knobs are changing. Reapply the computed graph coordinates last so
        # accepted edge alignments remain exact.
        backdrop.setXYpos(int(xpos), int(ypos))
        backdrop["bdwidth"].setValue(int(width))
        backdrop["bdheight"].setValue(int(height))
        _restore_graph_positions(graph_positions)

        for node in nuke.selectedNodes():
            node.setSelected(False)
        backdrop.setSelected(True)
        return backdrop
    finally:
        _restore_graph_positions(graph_positions)
        undo.end()
