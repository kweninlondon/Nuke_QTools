"""Preview and apply straight vertical or horizontal node chains."""

import contextlib
import statistics

import nuke
import nukescripts

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


IGNORED_CLASSES = {"BackdropNode", "Viewer"}
SETTINGS_ORGANISATION = "QTools"
SETTINGS_APPLICATION = "NodeAlignment"
MINIMUM_CONNECTION_GAP = 12
PANEL_ID = "com.qtools.NodeAlignment"
PANEL_TITLE = "Node Alignment"
WIDGET_EXPRESSION = (
    "__import__('qtools.node_alignment', "
    "fromlist=['NodeAlignmentWidget']).NodeAlignmentWidget"
)
_PANEL_REGISTERED = False


def _settings():
    return QtCore.QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def _setting_bool(key, default):
    value = _settings().value(key, default)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _node_key(node):
    try:
        return node.fullName()
    except Exception:
        return node.name()


def _node_size(node):
    try:
        return max(1, node.screenWidth()), max(1, node.screenHeight())
    except Exception:
        return 80, 20


def _selected_nodes():
    return [
        node for node in nuke.selectedNodes()
        if node.Class() not in IGNORED_CLASSES
    ]


def _scope_nodes():
    """Use the selection when present, otherwise the current graph."""
    selected = _selected_nodes()
    if selected:
        return selected, "selection"
    return (
        [node for node in nuke.allNodes() if node.Class() not in IGNORED_CLASSES],
        "current script",
    )


def capture_positions(nodes):
    """Capture immutable position and display-size data for selected nodes."""
    result = {}
    for node in nodes:
        width, height = _node_size(node)
        result[_node_key(node)] = {
            "node": node,
            "x": int(node.xpos()),
            "y": int(node.ypos()),
            "width": int(width),
            "height": int(height),
        }
    return result


def _input_nodes(node):
    result = []
    try:
        count = int(node.inputs())
    except Exception:
        count = 0
    for index in range(count):
        try:
            input_node = node.input(index)
        except Exception:
            input_node = None
        if input_node is not None:
            result.append(input_node)
    return result


def _directional_graph(snapshot, orientation):
    """Build adjacency and directed degrees for matching selected connections."""
    keys = set(snapshot)
    neighbours = {key: set() for key in keys}
    incoming = {key: 0 for key in keys}
    outgoing = {key: 0 for key in keys}
    for key, item in snapshot.items():
        for input_node in _input_nodes(item["node"]):
            input_key = _node_key(input_node)
            if input_key not in keys:
                continue
            input_item = snapshot[input_key]
            source_x = item["x"] + item["width"] / 2.0
            source_y = item["y"] + item["height"] / 2.0
            input_x = input_item["x"] + input_item["width"] / 2.0
            input_y = input_item["y"] + input_item["height"] / 2.0
            horizontal_distance = abs(source_x - input_x)
            vertical_distance = abs(source_y - input_y)
            edge_orientation = (
                "horizontal"
                if horizontal_distance > vertical_distance
                else "vertical"
            )
            if edge_orientation != orientation:
                continue
            neighbours[key].add(input_key)
            neighbours[input_key].add(key)
            incoming[key] += 1
            outgoing[input_key] += 1
    return neighbours, incoming, outgoing


def _graph_components(neighbours, allowed):
    """Return connected components restricted to an allowed key set."""
    components = []
    unseen = set(allowed)
    while unseen:
        start = unseen.pop()
        component = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            additions = neighbours[current] & unseen
            unseen.difference_update(additions)
            component.update(additions)
            stack.extend(additions)
        components.append(component)
    return components


def directional_chains(snapshot, orientation):
    """Group selected nodes using only connections matching an orientation."""
    neighbours, _incoming, _outgoing = _directional_graph(
        snapshot, orientation
    )
    connected = {key for key in snapshot if neighbours[key]}
    return _graph_components(neighbours, connected)


def movable_chain_sections(snapshot, orientation):
    """Return rigid chain sections, excluding shared branch/merge junctions."""
    neighbours, incoming, outgoing = _directional_graph(
        snapshot, orientation
    )
    connected = {key for key in snapshot if neighbours[key]}
    junctions = {
        key for key in connected
        if incoming[key] > 1 or outgoing[key] > 1
    }
    sections = _graph_components(neighbours, connected - junctions)
    return [section for section in sections if section]


def spacing_units(snapshot, orientation):
    """Return target chains plus consecutive perpendicular rigid blocks."""
    perpendicular = (
        "horizontal" if orientation == "vertical" else "vertical"
    )
    target_chains = directional_chains(snapshot, orientation)
    target_keys = set().union(*target_chains) if target_chains else set()
    candidates = [
        {"keys": set(section), "kind": "target"}
        for section in target_chains
    ]
    perpendicular_graph, _incoming, _outgoing = _directional_graph(
        snapshot, perpendicular
    )
    perpendicular_keys = {
        key for key in snapshot
        if perpendicular_graph[key] and key not in target_keys
    }
    candidates.extend(
        {"keys": set(section), "kind": "perpendicular"}
        for section in _graph_components(
            perpendicular_graph, perpendicular_keys
        )
    )

    axis = 0 if orientation == "vertical" else 1
    candidates.sort(
        key=lambda candidate: (
            _section_bounds(snapshot, candidate["keys"])[axis],
            _section_bounds(snapshot, candidate["keys"])[axis + 2],
        )
    )
    units = []
    for candidate in candidates:
        if (
            candidate["kind"] == "perpendicular"
            and units
            and units[-1]["kind"] == "perpendicular"
        ):
            units[-1]["keys"].update(candidate["keys"])
        else:
            units.append(candidate)
    return [unit["keys"] for unit in units]


def _snapshot_at_positions(snapshot, positions):
    result = {}
    for key, item in snapshot.items():
        result[key] = dict(item)
        result[key]["x"], result[key]["y"] = positions[key]
    return result


def _section_bounds(snapshot, section):
    left = min(snapshot[key]["x"] for key in section)
    top = min(snapshot[key]["y"] for key in section)
    right = max(
        snapshot[key]["x"] + snapshot[key]["width"] for key in section
    )
    bottom = max(
        snapshot[key]["y"] + snapshot[key]["height"] for key in section
    )
    return left, top, right, bottom


def spaced_chain_positions(
    snapshot,
    orientation,
    minimum_gap,
    anchor,
    force_exact=False,
):
    """Space rigid parallel chain sections while preserving larger gaps."""
    result = original_positions(snapshot)
    sections = spacing_units(snapshot, orientation)
    if len(sections) < 2:
        return result

    axis = 0 if orientation == "vertical" else 1
    records = []
    for section in sections:
        bounds = _section_bounds(snapshot, section)
        start = bounds[axis]
        end = bounds[axis + 2]
        records.append({
            "keys": section,
            "start": float(start),
            "end": float(end),
            "size": float(end - start),
        })
    records.sort(key=lambda record: (record["start"], record["end"]))

    relative_starts = [0.0]
    for previous, current in zip(records, records[1:]):
        original_gap = current["start"] - previous["end"]
        preserved_gap = (
            float(minimum_gap)
            if force_exact else max(float(minimum_gap), original_gap)
        )
        relative_starts.append(
            relative_starts[-1] + previous["size"] + preserved_gap
        )
    new_span = relative_starts[-1] + records[-1]["size"]
    original_start = records[0]["start"]
    original_end = records[-1]["end"]
    if anchor in {"left", "top"}:
        target_start = original_start
    elif anchor in {"right", "bottom"}:
        target_start = original_end - new_span
    elif anchor in {"center", "middle"}:
        target_start = (original_start + original_end - new_span) / 2.0
    else:
        raise ValueError("Unknown spacing anchor: {}".format(anchor))

    for record, relative_start in zip(records, relative_starts):
        shift = target_start + relative_start - record["start"]
        for key in record["keys"]:
            x, y = result[key]
            if axis == 0:
                x += shift
            else:
                y += shift
            result[key] = (int(round(x)), int(round(y)))
    return result


def _median(values):
    return float(statistics.median(values)) if values else 0.0


def _packed_chain_coordinates(records, minimum_gap, mode):
    """Move interior nodes while preserving the first and last anchors."""
    if len(records) < 3:
        return [record["start"] for record in records]
    minimum_gap = float(minimum_gap)
    first_start = records[0]["start"]
    last_end = records[-1]["end"]
    total_size = sum(record["size"] for record in records)
    available_span = last_end - first_start
    maximum_gap = (
        available_span - total_size
    ) / float(len(records) - 1)
    if maximum_gap < 0:
        return [record["start"] for record in records]
    safe_gap = min(minimum_gap, maximum_gap)

    if mode == "start":
        starts = [first_start]
        cursor = records[0]["end"] + safe_gap
        for record in records[1:-1]:
            starts.append(cursor)
            cursor += record["size"] + safe_gap
        starts.append(records[-1]["start"])
        return starts
    elif mode == "end":
        starts = [record["start"] for record in records]
        cursor = records[-1]["start"] - safe_gap
        for index in range(len(records) - 2, 0, -1):
            cursor -= records[index]["size"]
            starts[index] = cursor
            cursor -= safe_gap
        return starts
    elif mode == "even":
        safe_gap = maximum_gap
    else:
        raise ValueError("Unknown within-chain mode: {}".format(mode))

    starts = [first_start]
    cursor = records[0]["end"] + safe_gap
    for record in records[1:-1]:
        starts.append(cursor)
        cursor += record["size"] + safe_gap
    starts.append(records[-1]["start"])
    return starts


def _constrain_to_fixed_endpoints(records, starts, minimum_gap):
    """Clamp proposed interior positions to collision-free anchored bounds."""
    if len(records) < 3:
        return [record["start"] for record in records]
    total_size = sum(record["size"] for record in records)
    available_span = records[-1]["end"] - records[0]["start"]
    maximum_gap = (
        available_span - total_size
    ) / float(len(records) - 1)
    if maximum_gap < 0:
        return [record["start"] for record in records]
    safe_gap = min(float(minimum_gap), maximum_gap)
    constrained = [records[0]["start"]]
    last_start = records[-1]["start"]
    for index in range(1, len(records) - 1):
        lower = (
            constrained[index - 1]
            + records[index - 1]["size"]
            + safe_gap
        )
        remaining_sizes = sum(
            record["size"] for record in records[index + 1:-1]
        )
        remaining_gaps = len(records) - 1 - index
        upper = last_start - remaining_sizes - safe_gap * remaining_gaps
        constrained.append(min(max(starts[index], lower), upper))
    constrained.append(last_start)
    return constrained


def _smart_chain_coordinates(records, minimum_gap):
    """Pack local clusters while preserving large intentional separations."""
    if len(records) < 3:
        return [record["start"] for record in records]
    gaps = [
        current["start"] - previous["end"]
        for previous, current in zip(records, records[1:])
    ]
    nonnegative = sorted(max(0.0, gap) for gap in gaps)
    lower_half = nonnegative[:max(1, (len(nonnegative) + 1) // 2)]
    typical_gap = _median(lower_half)
    typical_size = _median([record["size"] for record in records])
    cluster_break = max(
        float(minimum_gap) * 2.0 + 1.0,
        typical_gap * 2.5,
        typical_size * 1.5,
    )

    clusters = []
    start = 0
    for index, gap in enumerate(gaps):
        if gap > cluster_break:
            clusters.append((start, index + 1))
            start = index + 1
    clusters.append((start, len(records)))

    starts = [record["start"] for record in records]
    for first, end in clusters:
        cluster = records[first:end]
        original_center = (
            cluster[0]["start"] + cluster[-1]["end"]
        ) / 2.0
        packed_span = sum(record["size"] for record in cluster)
        packed_span += float(minimum_gap) * (len(cluster) - 1)
        cursor = original_center - packed_span / 2.0
        for index in range(first, end):
            starts[index] = cursor
            cursor += records[index]["size"] + float(minimum_gap)

    # Resolve any cluster collisions, then retain the original overall center.
    for index in range(1, len(records)):
        required = (
            starts[index - 1]
            + records[index - 1]["size"]
            + float(minimum_gap)
        )
        if starts[index] < required:
            shift = required - starts[index]
            containing_cluster = next(
                cluster for cluster in clusters
                if cluster[0] <= index < cluster[1]
            )
            for member in range(containing_cluster[0], containing_cluster[1]):
                starts[member] += shift
    original_center = (records[0]["start"] + records[-1]["end"]) / 2.0
    new_center = (starts[0] + starts[-1] + records[-1]["size"]) / 2.0
    center_shift = original_center - new_center
    proposed = [start + center_shift for start in starts]
    return _constrain_to_fixed_endpoints(records, proposed, minimum_gap)


def within_chain_positions(snapshot, orientation, mode, minimum_gap):
    """Space chain interiors, using endpoints and Dots as fixed anchors."""
    result = original_positions(snapshot)
    axis = 1 if orientation == "vertical" else 0
    size_name = "height" if orientation == "vertical" else "width"
    for chain in movable_chain_sections(snapshot, orientation):
        if len(chain) < 2:
            continue
        records = []
        for key in chain:
            start = float(snapshot[key]["y" if axis == 1 else "x"])
            size = float(snapshot[key][size_name])
            records.append({
                "key": key,
                "start": start,
                "end": start + size,
                "size": size,
            })
        records.sort(key=lambda record: (record["start"], record["end"]))
        anchor_indices = [0]
        anchor_indices.extend(
            index for index, record in enumerate(records[1:-1], 1)
            if snapshot[record["key"]]["node"].Class() == "Dot"
        )
        anchor_indices.append(len(records) - 1)
        anchor_indices = sorted(set(anchor_indices))
        for first, last in zip(anchor_indices, anchor_indices[1:]):
            segment = records[first:last + 1]
            starts = (
                _smart_chain_coordinates(segment, minimum_gap)
                if mode == "smart"
                else _packed_chain_coordinates(segment, minimum_gap, mode)
            )
            for record, start in zip(segment[1:-1], starts[1:-1]):
                x, y = result[record["key"]]
                if axis == 1:
                    y = int(round(start))
                else:
                    x = int(round(start))
                result[record["key"]] = (x, y)
    return result


def straightened_positions(snapshot, orientation):
    """Align node centres to the median vertical or horizontal centre line."""
    result = {
        key: (item["x"], item["y"])
        for key, item in snapshot.items()
    }
    if len(snapshot) < 2:
        return result

    def median(values):
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2.0

    if orientation == "vertical":
        centres = sorted(
            item["x"] + item["width"] / 2.0
            for item in snapshot.values()
        )
        anchor = median(centres)
        for key, item in snapshot.items():
            result[key] = (
                int(round(anchor - item["width"] / 2.0)),
                item["y"],
            )
    elif orientation == "horizontal":
        centres = sorted(
            item["y"] + item["height"] / 2.0
            for item in snapshot.values()
        )
        anchor = median(centres)
        for key, item in snapshot.items():
            result[key] = (
                item["x"],
                int(round(anchor - item["height"] / 2.0)),
            )
    else:
        raise ValueError("Unknown chain orientation: {}".format(orientation))
    return result


def smart_straightened_positions(snapshot, orientations):
    """Straighten independent directional chains without collapsing branches."""
    result = original_positions(snapshot)
    for orientation in ("vertical", "horizontal"):
        if orientation not in orientations:
            continue
        for chain in directional_chains(snapshot, orientation):
            chain_snapshot = {key: snapshot[key] for key in chain}
            aligned = straightened_positions(chain_snapshot, orientation)
            for key in chain:
                if orientation == "vertical":
                    result[key] = (aligned[key][0], result[key][1])
                else:
                    result[key] = (result[key][0], aligned[key][1])
    return result


@contextlib.contextmanager
def _undo_suppressed():
    nuke.Undo.disable()
    try:
        yield
    finally:
        nuke.Undo.enable()


def set_positions(snapshot, positions, preview=True):
    manager = _undo_suppressed() if preview else contextlib.nullcontext()
    with manager:
        for key, position in positions.items():
            snapshot[key]["node"].setXYpos(*position)


def original_positions(snapshot):
    return {
        key: (item["x"], item["y"])
        for key, item in snapshot.items()
    }


def _clear_node_selection(snapshot):
    for item in snapshot.values():
        try:
            item["node"].setSelected(False)
        except Exception:
            try:
                item["node"]["selected"].setValue(False)
            except Exception:
                pass


def _nuke_main_window():
    """Find Nuke's main window so the tool stays above the Node Graph."""
    application = QtWidgets.QApplication.instance()
    active = application.activeWindow()
    while active is not None and active.parentWidget() is not None:
        active = active.parentWidget()
    if isinstance(active, QtWidgets.QMainWindow):
        return active
    for widget in application.topLevelWidgets():
        if isinstance(widget, QtWidgets.QMainWindow) and widget.isVisible():
            return widget
    return None


def _chain_icon(orientation, aligned, palette, size=58):
    """Draw an original icon so no external icon package is required."""
    ratio = QtWidgets.QApplication.instance().devicePixelRatio()
    pixmap = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    foreground = palette.color(QtGui.QPalette.ButtonText)
    guide = palette.color(QtGui.QPalette.Highlight)
    guide.setAlpha(230)
    pen = QtGui.QPen(guide, 3.0)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    if aligned:
        painter.setPen(pen)
        if orientation == "vertical":
            painter.drawLine(
                QtCore.QLineF(size / 2.0, 5, size / 2.0, size - 5)
            )
        else:
            painter.drawLine(
                QtCore.QLineF(5, size / 2.0, size - 5, size / 2.0)
            )

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(foreground)
    node_width = 26
    node_height = 10
    if orientation == "vertical":
        offsets = (0, 0, 0) if aligned else (-8, 7, -4)
        for index, offset in enumerate(offsets):
            x = size / 2.0 - node_width / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(
                    x, 8 + index * 17, node_width, node_height
                ),
                2,
                2,
            )
    else:
        offsets = (0, 0, 0) if aligned else (-8, 7, -4)
        horizontal_node_width = 17.5
        for index, offset in enumerate(offsets):
            y = size / 2.0 - node_height / 2.0 + offset
            painter.drawRoundedRect(
                QtCore.QRectF(
                    1 + index * 19.25,
                    y,
                    horizontal_node_width,
                    node_height,
                ),
                2,
                2,
            )
    painter.end()
    return QtGui.QIcon(pixmap)


def _between_icon(orientation, active, palette, size=58):
    """Draw three connected chains changing from irregular to regular gaps."""
    ratio = QtWidgets.QApplication.instance().devicePixelRatio()
    pixmap = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    foreground = palette.color(QtGui.QPalette.ButtonText)
    connector = (
        palette.color(QtGui.QPalette.Highlight)
        if active else palette.color(QtGui.QPalette.Mid)
    )
    connector.setAlpha(230 if active else 210)
    painter.setPen(QtGui.QPen(connector, 1.5))
    if orientation == "vertical":
        chain_positions = (7, 25, 43) if active else (5, 20, 45)
        for x in chain_positions:
            painter.drawLine(QtCore.QLineF(x + 4, 5, x + 4, 53))
    else:
        chain_positions = (7, 25, 43) if active else (5, 20, 45)
        for y in chain_positions:
            painter.drawLine(QtCore.QLineF(5, y + 4, 53, y + 4))

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(foreground)
    if orientation == "vertical":
        for x in chain_positions:
            for y in (3, 25, 47):
                painter.drawRoundedRect(QtCore.QRectF(x, y, 8, 7), 1.5, 1.5)
    else:
        for y in chain_positions:
            for x in (3, 25, 47):
                painter.drawRoundedRect(QtCore.QRectF(x, y, 7, 8), 1.5, 1.5)
    painter.end()
    return QtGui.QIcon(pixmap)


def _within_icon(orientation, active, palette, size=58):
    """Draw one chain with fixed endpoints and adjustable interior spacing."""
    ratio = QtWidgets.QApplication.instance().devicePixelRatio()
    pixmap = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    foreground = palette.color(QtGui.QPalette.ButtonText)
    connector = (
        palette.color(QtGui.QPalette.Highlight)
        if active else palette.color(QtGui.QPalette.Mid)
    )
    connector.setAlpha(230 if active else 210)
    painter.setPen(QtGui.QPen(connector, 2.0))
    if orientation == "vertical":
        painter.drawLine(QtCore.QLineF(29, 5, 29, 53))
        positions = (3, 18, 33, 48) if active else (3, 13, 34, 48)
    else:
        painter.drawLine(QtCore.QLineF(5, 29, 53, 29))
        positions = (3, 18, 33, 48) if active else (3, 13, 34, 48)

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(foreground)
    for position in positions:
        if orientation == "vertical":
            rect = QtCore.QRectF(19, position, 20, 7)
        else:
            rect = QtCore.QRectF(position, 19, 7, 20)
        painter.drawRoundedRect(rect, 1.5, 1.5)
    painter.end()
    return QtGui.QIcon(pixmap)


class NodeAlignmentWidget(QtWidgets.QWidget):
    """Dockable Properties-pane alignment editor with live preview."""

    def __init__(self, parent=None):
        super(NodeAlignmentWidget, self).__init__(parent)
        self.setMinimumWidth(230)
        nodes, self._scope_description = _scope_nodes()
        self._snapshot = capture_positions(nodes)
        self._preview = original_positions(self._snapshot)
        self._dirty = False
        self._session_active = True
        self._ever_shown = False
        self._resolving_hide = False
        self._build_ui()
        self._restore_settings()
        self.live_align_button.setChecked(True)
        self._update_state()
        self._manual_timer = QtCore.QTimer(self)
        self._manual_timer.setInterval(250)
        self._manual_timer.timeout.connect(self._detect_manual_moves)
        self._manual_timer.start()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        session_row = QtWidgets.QHBoxLayout()
        self.selection_label = QtWidgets.QLabel()
        self.update_selection_button = QtWidgets.QPushButton("Update Selection")
        self.live_align_button = QtWidgets.QPushButton("Live Align")
        self.live_align_button.setCheckable(True)
        self.live_align_button.setChecked(False)
        self.live_align_button.setToolTip(
            "Turn on live alignment for the current scope."
        )
        self.live_align_button.setStyleSheet(
            "QPushButton:checked {"
            " background-color: #e88722;"
            " border-color: #ffad45;"
            " color: #ffffff;"
            "}"
        )
        session_row.addWidget(self.selection_label, 1)
        session_row.addWidget(self.update_selection_button)
        session_row.addWidget(self.live_align_button)
        layout.addLayout(session_row)

        chain_group = QtWidgets.QGroupBox("Chain Alignment")
        button_layout = QtWidgets.QHBoxLayout(chain_group)
        self.vertical_button = self._make_chain_button(
            "Vertical chain", "vertical"
        )
        self.horizontal_button = self._make_chain_button(
            "Horizontal chain", "horizontal"
        )
        button_layout.addWidget(self.vertical_button)
        button_layout.addWidget(self.horizontal_button)
        layout.addWidget(chain_group)

        spacing_group = QtWidgets.QGroupBox("Between Chains")
        spacing_layout = QtWidgets.QGridLayout(spacing_group)
        self.space_vertical_button = self._make_spacing_button(
            "Space vertical chains", "vertical"
        )
        self.space_horizontal_button = self._make_spacing_button(
            "Space horizontal chains", "horizontal"
        )
        (
            self.vertical_anchor_widget,
            self.vertical_anchor_group,
            self.vertical_anchor_buttons,
        ) = self._make_anchor_selector(
            (("Left", "left"), ("Center", "center"), ("Right", "right")),
            "center",
        )
        (
            self.horizontal_anchor_widget,
            self.horizontal_anchor_group,
            self.horizontal_anchor_buttons,
        ) = self._make_anchor_selector(
            (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")),
            "middle",
        )
        spacing_layout.addWidget(self.space_vertical_button, 0, 0)
        spacing_layout.addWidget(self.vertical_anchor_widget, 0, 1)
        spacing_layout.addWidget(self.space_horizontal_button, 1, 0)
        spacing_layout.addWidget(self.horizontal_anchor_widget, 1, 1)

        (
            vertical_gap_row,
            self.vertical_gap_slider,
            self.vertical_gap_spin,
        ) = self._make_gap_control("X gap:")
        (
            horizontal_gap_row,
            self.horizontal_gap_slider,
            self.horizontal_gap_spin,
        ) = self._make_gap_control("Y gap:")
        self.vertical_gap_row = vertical_gap_row
        self.horizontal_gap_row = horizontal_gap_row
        spacing_layout.addLayout(self.vertical_gap_row, 2, 0, 1, 2)
        spacing_layout.addLayout(self.horizontal_gap_row, 3, 0, 1, 2)
        self.force_gap_checkbox = QtWidgets.QCheckBox(
            "Force exact gaps (allow chains to move closer)"
        )
        self.force_gap_checkbox.setToolTip(
            "Use the chosen gap for every neighbouring unit, including gaps "
            "that are currently larger."
        )
        spacing_layout.addWidget(self.force_gap_checkbox, 4, 0, 1, 2)
        layout.addWidget(spacing_group)

        within_group = QtWidgets.QGroupBox("Within Chains")
        within_layout = QtWidgets.QGridLayout(within_group)
        self.within_vertical_button = self._make_within_button("vertical")
        self.within_horizontal_button = self._make_within_button("horizontal")
        orientation_row = QtWidgets.QHBoxLayout()
        orientation_row.addWidget(self.within_vertical_button)
        orientation_row.addWidget(self.within_horizontal_button)
        within_layout.addWidget(QtWidgets.QLabel("Direction:"), 0, 0)
        within_layout.addLayout(orientation_row, 0, 1)
        (
            self.within_mode_widget,
            self.within_mode_group,
            self.within_mode_buttons,
        ) = self._make_anchor_selector(
            (
                ("Top/Left", "start"),
                ("Bottom/Right", "end"),
                ("Even", "even"),
                ("Smart", "smart"),
            ),
            "smart",
        )
        within_layout.addWidget(QtWidgets.QLabel("Mode:"), 1, 0)
        within_layout.addWidget(self.within_mode_widget, 1, 1)
        (
            vertical_node_gap_row,
            self.vertical_node_gap_slider,
            self.vertical_node_gap_spin,
        ) = self._make_gap_control(
            "Vertical gap:", MINIMUM_CONNECTION_GAP, 30
        )
        (
            horizontal_node_gap_row,
            self.horizontal_node_gap_slider,
            self.horizontal_node_gap_spin,
        ) = self._make_gap_control(
            "Horizontal gap:", MINIMUM_CONNECTION_GAP, 30
        )
        self.vertical_node_gap_row = vertical_node_gap_row
        self.horizontal_node_gap_row = horizontal_node_gap_row
        within_layout.addLayout(self.vertical_node_gap_row, 2, 0, 1, 2)
        within_layout.addLayout(self.horizontal_node_gap_row, 3, 0, 1, 2)
        layout.addWidget(within_group)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        footer = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.apply_button = QtWidgets.QPushButton("Apply")
        footer.addWidget(self.reset_button)
        footer.addStretch()
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)

        self.vertical_button.toggled.connect(
            lambda checked: self._toggle("vertical", checked)
        )
        self.horizontal_button.toggled.connect(
            lambda checked: self._toggle("horizontal", checked)
        )
        self.space_vertical_button.toggled.connect(
            lambda checked: self._toggle_spacing("vertical", checked)
        )
        self.space_horizontal_button.toggled.connect(
            lambda checked: self._toggle_spacing("horizontal", checked)
        )
        for slider, spin in (
            (self.vertical_gap_slider, self.vertical_gap_spin),
            (self.horizontal_gap_slider, self.horizontal_gap_spin),
        ):
            slider.valueChanged.connect(
                lambda value, field=spin: self._gap_slider_changed(
                    value, field
                )
            )
            spin.valueChanged.connect(
                lambda value, control=slider: self._gap_field_changed(
                    value, control
                )
            )
            spin.valueChanged.connect(self._recompute_preview)
        self.force_gap_checkbox.toggled.connect(self._recompute_preview)
        self.within_vertical_button.toggled.connect(
            lambda checked: self._toggle_within("vertical", checked)
        )
        self.within_horizontal_button.toggled.connect(
            lambda checked: self._toggle_within("horizontal", checked)
        )
        for slider, spin in (
            (self.vertical_node_gap_slider, self.vertical_node_gap_spin),
            (self.horizontal_node_gap_slider, self.horizontal_node_gap_spin),
        ):
            slider.valueChanged.connect(
                lambda value, field=spin: self._gap_slider_changed(value, field)
            )
            spin.valueChanged.connect(
                lambda value, control=slider: self._gap_field_changed(
                    value, control
                )
            )
            spin.valueChanged.connect(self._recompute_preview)
        for button in list(self.vertical_anchor_buttons.values()) + list(
            self.horizontal_anchor_buttons.values()
        ) + list(self.within_mode_buttons.values()):
            button.toggled.connect(self._anchor_changed)
        self.reset_button.clicked.connect(self.reset_changes)
        self.apply_button.clicked.connect(self.apply_changes)
        self.live_align_button.toggled.connect(self._preview_toggled)
        self.update_selection_button.clicked.connect(self.update_selection)

    @staticmethod
    def _make_gap_control(label, minimum=0, default=50):
        row = QtWidgets.QHBoxLayout()
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(minimum, 1000)
        slider.setPageStep(50)
        slider.setValue(default)
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, 5000)
        spin.setSingleStep(10)
        spin.setValue(default)
        spin.setSuffix(" px")
        row.addWidget(QtWidgets.QLabel(label))
        row.addWidget(slider, 1)
        row.addWidget(spin)
        return row, slider, spin

    @staticmethod
    def _gap_from_slider(slider_value):
        if slider_value <= 500:
            return int(slider_value)
        return int(500 + (slider_value - 500) * 9)

    @staticmethod
    def _slider_from_gap(gap_value):
        if gap_value <= 500:
            return int(gap_value)
        return int(round(500 + (gap_value - 500) / 9.0))

    def _gap_slider_changed(self, slider_value, field):
        field.setValue(self._gap_from_slider(slider_value))

    def _gap_field_changed(self, gap_value, slider):
        blocker = QtCore.QSignalBlocker(slider)
        slider.setValue(self._slider_from_gap(gap_value))
        del blocker

    def _restore_settings(self):
        settings = _settings()
        self.vertical_gap_spin.setValue(
            int(settings.value("vertical_gap", 50))
        )
        self.horizontal_gap_spin.setValue(
            int(settings.value("horizontal_gap", 50))
        )
        legacy_node_gap = int(settings.value("node_gap", 30))
        self.vertical_node_gap_spin.setValue(
            int(settings.value("vertical_node_gap", legacy_node_gap))
        )
        self.horizontal_node_gap_spin.setValue(
            int(settings.value("horizontal_node_gap", legacy_node_gap))
        )
        self.force_gap_checkbox.setChecked(
            _setting_bool("force_exact_gap", False)
        )
        vertical_anchor = str(settings.value("vertical_anchor", "center"))
        horizontal_anchor = str(
            settings.value("horizontal_anchor", "middle")
        )
        self.vertical_anchor_buttons.get(
            vertical_anchor,
            self.vertical_anchor_buttons["center"],
        ).setChecked(True)
        self.horizontal_anchor_buttons.get(
            horizontal_anchor,
            self.horizontal_anchor_buttons["middle"],
        ).setChecked(True)
        within_mode = str(settings.value("within_mode", "smart"))
        self.within_mode_buttons.get(
            within_mode,
            self.within_mode_buttons["smart"],
        ).setChecked(True)
        self.vertical_button.setChecked(
            _setting_bool("align_vertical", False)
        )
        self.horizontal_button.setChecked(
            _setting_bool("align_horizontal", False)
        )
        self.space_vertical_button.setChecked(
            _setting_bool("space_vertical", False)
        )
        self.space_horizontal_button.setChecked(
            _setting_bool("space_horizontal", False)
        )
        self.within_vertical_button.setChecked(
            _setting_bool("within_vertical", False)
        )
        self.within_horizontal_button.setChecked(
            _setting_bool("within_horizontal", False)
        )

    def _save_settings(self):
        settings = _settings()
        settings.setValue("align_vertical", self.vertical_button.isChecked())
        settings.setValue(
            "align_horizontal", self.horizontal_button.isChecked()
        )
        settings.setValue(
            "space_vertical", self.space_vertical_button.isChecked()
        )
        settings.setValue(
            "space_horizontal", self.space_horizontal_button.isChecked()
        )
        settings.setValue(
            "vertical_anchor",
            self._checked_anchor(self.vertical_anchor_buttons),
        )
        settings.setValue(
            "horizontal_anchor",
            self._checked_anchor(self.horizontal_anchor_buttons),
        )
        settings.setValue("vertical_gap", self.vertical_gap_spin.value())
        settings.setValue("horizontal_gap", self.horizontal_gap_spin.value())
        settings.setValue(
            "vertical_node_gap", self.vertical_node_gap_spin.value()
        )
        settings.setValue(
            "horizontal_node_gap", self.horizontal_node_gap_spin.value()
        )
        settings.setValue(
            "force_exact_gap", self.force_gap_checkbox.isChecked()
        )
        settings.setValue(
            "within_vertical", self.within_vertical_button.isChecked()
        )
        settings.setValue(
            "within_horizontal", self.within_horizontal_button.isChecked()
        )
        settings.setValue(
            "within_mode", self._checked_anchor(self.within_mode_buttons)
        )
        settings.sync()

    def _make_chain_button(self, label, orientation):
        button = QtWidgets.QToolButton()
        button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(58, 58))
        button.setMinimumSize(82, 72)
        button.setIcon(
            _chain_icon(orientation, False, self.palette())
        )
        button.setProperty("orientation", orientation)
        button.setToolTip(
            "{}: straighten each selected {} tree."
            .format(label, orientation)
        )
        return button

    def _make_spacing_button(self, label, orientation):
        button = QtWidgets.QToolButton()
        button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(46, 46))
        button.setFixedSize(62, 56)
        button.setIcon(_between_icon(orientation, False, self.palette()))
        button.setProperty("orientation", orientation)
        direction = "left/right" if orientation == "vertical" else "up/down"
        button.setToolTip(
            "{} {} as rigid units; preserve their internal layout."
            .format(label, direction)
        )
        return button

    def _make_within_button(self, orientation):
        button = QtWidgets.QToolButton()
        button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        button.setCheckable(True)
        button.setIconSize(QtCore.QSize(46, 46))
        button.setFixedSize(62, 56)
        button.setIcon(_within_icon(orientation, False, self.palette()))
        button.setProperty("orientation", orientation)
        button.setToolTip(
            "Adjust spacing inside {} chains; their two end nodes stay fixed."
            .format(orientation)
        )
        return button

    def _make_anchor_selector(self, choices, default):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        group = QtWidgets.QButtonGroup(widget)
        group.setExclusive(True)
        buttons = {}
        for label, value in choices:
            button = QtWidgets.QPushButton(label)
            button.setCheckable(True)
            button.setProperty("anchor", value)
            button.setChecked(value == default)
            group.addButton(button)
            layout.addWidget(button)
            buttons[value] = button
        return widget, group, buttons

    def _set_button_icon(self, button, aligned):
        button.setIcon(
            _chain_icon(
                button.property("orientation"), aligned, self.palette()
            )
        )

    def _set_spacing_icon(self, button, active):
        button.setIcon(
            _between_icon(
                button.property("orientation"), active, self.palette()
            )
        )

    def _toggle(self, orientation, checked):
        button = (
            self.vertical_button
            if orientation == "vertical"
            else self.horizontal_button
        )
        self._set_button_icon(button, checked)
        self._recompute_preview()

    def _toggle_spacing(self, orientation, checked):
        button = (
            self.space_vertical_button
            if orientation == "vertical"
            else self.space_horizontal_button
        )
        self._set_spacing_icon(button, checked)
        self._recompute_preview()

    def _toggle_within(self, orientation, checked):
        button = (
            self.within_vertical_button
            if orientation == "vertical"
            else self.within_horizontal_button
        )
        button.setIcon(_within_icon(orientation, checked, self.palette()))
        self._recompute_preview()

    def _anchor_changed(self, checked):
        if checked:
            self._recompute_preview()

    @staticmethod
    def _set_layout_visible(layout, visible):
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                widget.setVisible(visible)

    @staticmethod
    def _checked_anchor(buttons):
        for value, button in buttons.items():
            if button.isChecked():
                return value
        raise RuntimeError("Spacing anchor group has no checked button")

    def _write_positions(self, positions, preview=True):
        set_positions(self._snapshot, positions, preview=preview)

    def _detect_manual_moves(self, force=False, recompute=True):
        """Rebase preview deviations as user-authored Node Graph moves."""
        if (
            not self._session_active
            or (not force and not self.live_align_button.isChecked())
        ):
            return
        changed = False
        for key, item in list(self._snapshot.items()):
            try:
                current = (int(item["node"].xpos()), int(item["node"].ypos()))
            except Exception:
                continue
            expected = self._preview.get(key, (item["x"], item["y"]))
            if current == expected:
                continue
            item["x"] += current[0] - expected[0]
            item["y"] += current[1] - expected[1]
            self._preview[key] = current
            changed = True
        if changed and recompute:
            self._recompute_preview()

    def _preview_toggled(self, checked):
        if checked:
            if self._scope_description == "no active scope":
                nodes, self._scope_description = _scope_nodes()
                self._snapshot = capture_positions(nodes)
                self._preview = original_positions(self._snapshot)
                self._dirty = False
            self._session_active = True
            self._recompute_preview()
        else:
            self._detect_manual_moves(force=True, recompute=False)
            self._write_positions(original_positions(self._snapshot))
            self._preview = original_positions(self._snapshot)
            self._dirty = False
            self.status_label.setText("Live Align off.")
            self._update_state()

    def update_selection(self):
        """Resolve the old preview and explicitly recapture its scope."""
        if self._dirty and not self._resolve_pending("Update Selection"):
            return
        nodes, self._scope_description = _scope_nodes()
        self._snapshot = capture_positions(nodes)
        self._preview = original_positions(self._snapshot)
        self._dirty = False
        self._session_active = True
        if not self.live_align_button.isChecked():
            self.live_align_button.setChecked(True)
        else:
            self._recompute_preview()

    def _recompute_preview(self, *_args):
        if not self.live_align_button.isChecked():
            self._preview = original_positions(self._snapshot)
            self._dirty = False
            self.status_label.setText("Live Align off.")
            self._update_state()
            return
        self._detect_manual_moves(recompute=False)
        orientations = {
            name
            for name, toggle in (
                ("vertical", self.vertical_button),
                ("horizontal", self.horizontal_button),
            )
            if toggle.isChecked()
        }
        positions = smart_straightened_positions(
            self._snapshot, orientations
        )
        aligned_snapshot = _snapshot_at_positions(self._snapshot, positions)
        if self.space_vertical_button.isChecked():
            vertical_positions = spaced_chain_positions(
                aligned_snapshot,
                "vertical",
                self.vertical_gap_spin.value(),
                self._checked_anchor(self.vertical_anchor_buttons),
                self.force_gap_checkbox.isChecked(),
            )
            positions = {
                key: (vertical_positions[key][0], positions[key][1])
                for key in positions
            }
        if self.space_horizontal_button.isChecked():
            horizontal_positions = spaced_chain_positions(
                aligned_snapshot,
                "horizontal",
                self.horizontal_gap_spin.value(),
                self._checked_anchor(self.horizontal_anchor_buttons),
                self.force_gap_checkbox.isChecked(),
            )
            positions = {
                key: (positions[key][0], horizontal_positions[key][1])
                for key in positions
            }
        within_snapshot = _snapshot_at_positions(self._snapshot, positions)
        within_mode = self._checked_anchor(self.within_mode_buttons)
        if self.within_vertical_button.isChecked():
            vertical_within = within_chain_positions(
                within_snapshot,
                "vertical",
                within_mode,
                self.vertical_node_gap_spin.value(),
            )
            positions = {
                key: (positions[key][0], vertical_within[key][1])
                for key in positions
            }
        if self.within_horizontal_button.isChecked():
            horizontal_within = within_chain_positions(
                within_snapshot,
                "horizontal",
                within_mode,
                self.horizontal_node_gap_spin.value(),
            )
            positions = {
                key: (horizontal_within[key][0], positions[key][1])
                for key in positions
            }
        self._preview = positions
        self._write_positions(positions)
        self._dirty = self._preview != original_positions(self._snapshot)
        moved = sum(
            self._preview[key] != original_positions(self._snapshot)[key]
            for key in self._preview
        )
        self.status_label.setText(
            "{} node{} moved by Live Align."
            .format(moved, "" if moved == 1 else "s")
            if (
                orientations
                or self.space_vertical_button.isChecked()
                or self.space_horizontal_button.isChecked()
                or self.within_vertical_button.isChecked()
                or self.within_horizontal_button.isChecked()
            )
            else "No alignment operation selected."
        )
        self._update_state()

    def _update_state(self):
        count = len(self._snapshot)
        self.update_selection_button.setVisible(
            self._scope_description != "no active scope"
        )
        self.selection_label.setText(
            "{} node{} ({})".format(
                count, "" if count == 1 else "s", self._scope_description
            )
        )
        enabled = count >= 2
        self.vertical_button.setEnabled(enabled)
        self.horizontal_button.setEnabled(enabled)
        self.space_vertical_button.setEnabled(enabled)
        self.space_horizontal_button.setEnabled(enabled)
        self.vertical_anchor_widget.setEnabled(
            enabled and self.space_vertical_button.isChecked()
        )
        self.horizontal_anchor_widget.setEnabled(
            enabled and self.space_horizontal_button.isChecked()
        )
        self._set_layout_visible(
            self.vertical_gap_row,
            self.space_vertical_button.isChecked(),
        )
        self._set_layout_visible(
            self.horizontal_gap_row,
            self.space_horizontal_button.isChecked(),
        )
        within_enabled = (
            enabled
            and (
                self.within_vertical_button.isChecked()
                or self.within_horizontal_button.isChecked()
            )
        )
        self.within_vertical_button.setEnabled(enabled)
        self.within_horizontal_button.setEnabled(enabled)
        self.within_mode_widget.setEnabled(within_enabled)
        even_mode = self.within_mode_buttons["even"].isChecked()
        vertical_within_enabled = (
            enabled and self.within_vertical_button.isChecked()
        )
        horizontal_within_enabled = (
            enabled and self.within_horizontal_button.isChecked()
        )
        self.vertical_node_gap_slider.setEnabled(vertical_within_enabled)
        self.vertical_node_gap_spin.setEnabled(vertical_within_enabled)
        self.horizontal_node_gap_slider.setEnabled(horizontal_within_enabled)
        self.horizontal_node_gap_spin.setEnabled(horizontal_within_enabled)
        self._set_layout_visible(
            self.vertical_node_gap_row,
            vertical_within_enabled and not even_mode,
        )
        self._set_layout_visible(
            self.horizontal_node_gap_row,
            horizontal_within_enabled and not even_mode,
        )
        self.apply_button.setEnabled(
            self._session_active and self._dirty
        )
        self.reset_button.setEnabled(
            self._session_active
            and (
                self.vertical_button.isChecked()
                or self.horizontal_button.isChecked()
                or self.space_vertical_button.isChecked()
                or self.space_horizontal_button.isChecked()
                or self.within_vertical_button.isChecked()
                or self.within_horizontal_button.isChecked()
            )
        )
        if not enabled:
            if self._scope_description == "no active scope":
                self.status_label.setText(
                    "Turn on Live Align to start aligning."
                )
            else:
                self.status_label.setText(
                    "The current scope needs at least two nodes."
                )

    def apply_changes(self, _checked=False):
        self._detect_manual_moves()
        self._save_settings()
        final_positions = dict(self._preview)
        if self._dirty:
            self._write_positions(original_positions(self._snapshot))
            try:
                nuke.Undo.begin("Node Alignment")
                self._write_positions(final_positions, preview=False)
            finally:
                nuke.Undo.end()
        applied_snapshot = self._snapshot
        self._dirty = False
        self._session_active = False
        self.live_align_button.setChecked(False)
        _clear_node_selection(applied_snapshot)
        self._snapshot = {}
        self._preview = {}
        self._scope_description = "no active scope"
        self._update_state()
        self.status_label.setText(
            "Alignment applied. Turn on Live Align to start again."
        )

    def reset_changes(self):
        self._detect_manual_moves()
        self._preview = original_positions(self._snapshot)
        self._write_positions(self._preview)
        self._dirty = False
        self._save_settings()
        self._session_active = False
        self.live_align_button.setChecked(False)
        self._snapshot = {}
        self._preview = {}
        self._scope_description = "no active scope"
        self._update_state()
        self.status_label.setText(
            "Alignment reset; settings and manual moves retained."
        )

    def _resolve_pending(self, title="Leave Node Alignment"):
        self._detect_manual_moves(force=True)
        if not self._dirty:
            self._save_settings()
            self._session_active = False
            return True
        answer = QtWidgets.QMessageBox.question(
            self,
            title,
            "Apply the live alignment changes before continuing?",
            QtWidgets.QMessageBox.Save
            | QtWidgets.QMessageBox.Discard
            | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if answer == QtWidgets.QMessageBox.Save:
            self.apply_changes()
            return True
        elif answer == QtWidgets.QMessageBox.Discard:
            self._save_settings()
            self._write_positions(original_positions(self._snapshot))
            self._preview = original_positions(self._snapshot)
            self._dirty = False
            self._session_active = False
            return True
        return False

    def showEvent(self, event):
        super(NodeAlignmentWidget, self).showEvent(event)
        if self._ever_shown and not self._session_active:
            nodes, self._scope_description = _scope_nodes()
            self._snapshot = capture_positions(nodes)
            self._preview = original_positions(self._snapshot)
            self._dirty = False
            self._session_active = True
            self.live_align_button.setChecked(True)
            self._recompute_preview()
        self._ever_shown = True

    def hideEvent(self, event):
        if (
            self._ever_shown
            and self._session_active
            and not self._resolving_hide
        ):
            self._resolving_hide = True
            can_leave = self._resolve_pending()
            self._resolving_hide = False
            if not can_leave:
                QtCore.QTimer.singleShot(0, lambda: _activate_panel_widget(self))
        super(NodeAlignmentWidget, self).hideEvent(event)

    def closeEvent(self, event):
        if self._session_active and not self._resolve_pending():
            event.ignore()
            return
        event.accept()


def register_panel():
    """Register Node Alignment in Nuke's pane and workspace system."""
    global _PANEL_REGISTERED
    if _PANEL_REGISTERED:
        return
    nukescripts.panels.registerWidgetAsPanel(
        WIDGET_EXPRESSION, PANEL_TITLE, PANEL_ID
    )
    _PANEL_REGISTERED = True


def _alignment_widgets():
    application = QtWidgets.QApplication.instance()
    if application is None:
        return []
    return [
        widget for widget in application.allWidgets()
        if isinstance(widget, NodeAlignmentWidget)
    ]


def _activate_panel_widget(widget):
    """Select the stacked page containing an existing alignment widget."""
    child = widget
    parent = child.parentWidget()
    activated = False
    while parent is not None:
        if isinstance(parent, QtWidgets.QStackedWidget):
            index = parent.indexOf(child)
            if index >= 0:
                parent.setCurrentIndex(index)
                activated = True
        child = parent
        parent = child.parentWidget()
    if activated:
        widget.setFocus()
    return activated


def _activate_properties_tab():
    """Switch from Node Alignment back to Properties in the same pane."""
    application = QtWidgets.QApplication.instance()
    if application is None:
        return False
    for tab_bar in application.allWidgets():
        if not isinstance(tab_bar, QtWidgets.QTabBar):
            continue
        alignment_index = -1
        properties_index = -1
        for index in range(tab_bar.count()):
            text = str(tab_bar.tabText(index)).replace("&", "").strip()
            if text == PANEL_TITLE:
                alignment_index = index
            elif text == "Properties":
                properties_index = index
        if (
            alignment_index >= 0
            and properties_index >= 0
            and tab_bar.currentIndex() == alignment_index
        ):
            tab_bar.setCurrentIndex(properties_index)
            return True
    return False


def show_panel():
    """Open or activate Node Alignment beside Nuke's Properties panel."""
    register_panel()
    for widget in _alignment_widgets():
        try:
            if _activate_panel_widget(widget):
                return widget
            widget.deleteLater()
        except RuntimeError:
            # Nuke can briefly retain a Python wrapper after its tab is closed.
            continue
    pane = nuke.getPaneFor("Properties.1") or nuke.getPaneFor("Scene Graph")
    panel = nukescripts.panels.registerWidgetAsPanel(
        WIDGET_EXPRESSION, PANEL_TITLE, PANEL_ID, True
    )
    panel.addToPane(pane)
    QtCore.QTimer.singleShot(
        0,
        lambda: [
            _activate_panel_widget(widget)
            for widget in _alignment_widgets()
        ],
    )
    return panel


# Keep old menu/workspace calls working.
show_dialog = show_panel
