"""Build a cheap 2D stabilization setup from a Card2 or Axis and camera."""

from __future__ import division

import math

import nuke


CAMERA_CLASSES = {"Camera", "Camera2", "Camera3"}
PLANE_CLASSES = {"Card2", "Axis", "Axis2", "Axis3"}
CORNER_NAMES = ("BL", "BR", "TR", "TL")
HORIZONTAL_SPACING = 120


def _message(text):
    nuke.message("Card Stabilizer\n\n{}".format(text))


def _selection():
    selected = list(nuke.selectedNodes())
    cameras = [node for node in selected if node.Class() in CAMERA_CLASSES]
    planes = [node for node in selected if node.Class() in PLANE_CLASSES]
    if len(selected) != 2 or len(cameras) != 1 or len(planes) != 1:
        raise ValueError(
            "Select exactly one Camera and one Card2 or Axis, then run the tool."
        )
    return planes[0], cameras[0]


def _knob_value(node, name, default=None):
    knob = node.knob(name)
    return knob.value() if knob is not None else default


def _enum_name(node, name, default):
    knob = node.knob(name)
    if knob is None:
        return default
    try:
        values = knob.values()
        return str(values[int(knob.value())])
    except Exception:
        return str(knob.value())


def _format_aspect(image_node=None):
    """Return display aspect, including pixel aspect."""
    try:
        format_value = image_node.format() if image_node is not None else nuke.root().format()
        width = float(format_value.width())
        height = float(format_value.height())
        pixel_aspect = float(format_value.pixelAspect())
    except Exception as error:
        raise ValueError("Could not read the image format: {}".format(error))
    if width <= 0 or height <= 0 or pixel_aspect <= 0:
        raise ValueError("The image format has an invalid size or pixel aspect.")
    return width * pixel_aspect / height


def _validate_card(card):
    """Reject Card2 geometry changes that four planar points cannot reproduce."""
    deform_type = _enum_name(card, "type", "none").lower()
    if deform_type not in ("none", "0"):
        raise ValueError(
            "Bilinear/bicubic Card deformation is not planar and cannot be "
            "represented accurately by one CornerPin."
        )
    distortion_knobs = (
        "lens_in_distort_a", "lens_in_distort_b", "lens_in_distort_c",
        "lens_in_distortion",
    )
    if any(abs(float(_knob_value(card, name, 0.0))) > 1e-12 for name in distortion_knobs):
        raise ValueError(
            "Card lens distortion bends its edges. Disable the Card's Lens "
            "Distortion controls before creating a planar CornerPin."
        )
    if abs(float(_knob_value(card, "z", 0.0))) > 1e-12:
        raise ValueError(
            "This tool supports Card transform depth, not the Card's legacy z "
            "geometry control. Set Card z to 0 and use translate Z instead."
        )


def _matrix_at(node, knob_name, frame):
    matrix = nuke.math.Matrix4()
    knob = node[knob_name]
    for index in range(16):
        matrix[index] = knob.getValueAt(frame, index)
    matrix.transpose()
    return matrix


def _axis_frustum_corners(axis, camera, reference_frame):
    """Return a reference-camera frustum plane through the Axis position."""
    if int(_knob_value(camera, "projection_mode", 0)) != 0:
        raise ValueError("Axis frustum mode currently requires a perspective Camera.")
    for name, expected in (
        ("winroll", 0.0), ("win_translate", (0.0, 0.0)),
        ("win_scale", (1.0, 1.0)),
    ):
        targets = expected if isinstance(expected, tuple) else (expected,)
        values = tuple(
            camera[name].getValueAt(reference_frame, component)
            for component in range(len(targets))
        )
        if any(abs(float(a) - float(b)) > 1e-10 for a, b in zip(values, targets)):
            raise ValueError(
                "Axis frustum mode requires default Camera window controls."
            )

    camera_world = _matrix_at(camera, "matrix", reference_frame)
    axis_world = _matrix_at(axis, "world_matrix", reference_frame)
    axis_position = axis_world * nuke.math.Vector4(0.0, 0.0, 0.0, 1.0)
    camera_position = camera_world.inverse() * axis_position
    depth = -float(camera_position.z)
    if depth <= 0.0:
        raise ValueError("The selected Axis must be in front of the Camera.")

    focal = float(camera["focal"].getValueAt(reference_frame))
    aperture = float(camera["haperture"].getValueAt(reference_frame))
    if focal <= 0.0 or aperture <= 0.0:
        raise ValueError("The Camera focal length and aperture must be positive.")
    half_width = depth * aperture / (2.0 * focal)
    half_height = half_width / _format_aspect()
    local_corners = (
        (-half_width, -half_height, -depth),
        (half_width, -half_height, -depth),
        (half_width, half_height, -depth),
        (-half_width, half_height, -depth),
    )
    result = []
    for x, y, z in local_corners:
        point = camera_world * nuke.math.Vector4(x, y, z, 1.0)
        result.append((point.x, point.y, point.z))
    return result


def _plane_corners(plane, camera=None, reference_frame=None):
    """Return corners and the node that supplies their local transform."""
    is_card = plane.Class() == "Card2"
    if is_card:
        _validate_card(plane)
        image = plane.input(0)
        use_image_aspect = bool(_knob_value(plane, "image_aspect", True))
        aspect = _format_aspect(image) if use_image_aspect else 1.0
        orientation = _enum_name(plane, "orientation", "XY").upper()
    else:
        if camera is None or reference_frame is None:
            # Kept as a small pure fallback for unit testing.
            aspect = _format_aspect()
            orientation = "XY"
        else:
            return _axis_frustum_corners(plane, camera, reference_frame), None

    half_width = 0.5
    half_height = 0.5 / aspect
    uv_corners = (
        (-half_width, -half_height),
        (half_width, -half_height),
        (half_width, half_height),
        (-half_width, half_height),
    )
    if orientation == "XY":
        corners = [(u, v, 0.0) for u, v in uv_corners]
        return (corners, plane) if camera is not None else corners
    if orientation == "YZ":
        corners = [(0.0, u, v) for u, v in uv_corners]
        return (corners, plane) if camera is not None else corners
    if orientation == "ZX":
        corners = [(v, 0.0, u) for u, v in uv_corners]
        return (corners, plane) if camera is not None else corners
    raise ValueError("Unsupported Card orientation: {}".format(orientation))


def _reference_frame():
    value = nuke.getInput("Stabilization reference frame", str(nuke.frame()))
    if value is None:
        return None
    try:
        frame = float(value)
    except (TypeError, ValueError):
        raise ValueError("Reference frame must be a number.")
    if not math.isfinite(frame):
        raise ValueError("Reference frame must be a finite number.")
    return frame


def _set_position(node, x, y):
    node.setXYpos(int(round(x)), int(round(y)))


def _create_format_source(plane, y):
    source = nuke.nodes.Constant(
        name="CardStabilize_Format",
        label="projection format\n[root.format.name]",
    )
    if source.knob("hide_input") is not None:
        source["hide_input"].setValue(True)
    _set_position(source, plane.xpos() - 180, y)
    return source


def _create_reconcile(axis_input, camera, format_source, point, corner_name, x, y):
    reconcile = nuke.nodes.Reconcile3D(
        name="CardStabilize_{}".format(corner_name),
        label="{} corner\nlive projection".format(corner_name),
    )
    # Native order documented by Foundry: axis, cam, img.
    reconcile.setInput(0, axis_input)
    reconcile.setInput(1, camera)
    reconcile.setInput(2, format_source)
    for component, value in enumerate(point):
        reconcile["point"].setValue(float(value), component)
    reconcile["calc_output"].setValue(True)
    _set_position(reconcile, x, y)
    return reconcile


def _set_live_corner(corner_pin, knob_name, reconcile):
    for component, suffix in enumerate(("x", "y")):
        corner_pin[knob_name].setExpression(
            "{}.output.{}".format(reconcile.name(), suffix), component
        )


def create_stabilizer():
    """Create four Reconcile3Ds and a stabilizing CornerPin2D."""
    try:
        plane, camera = _selection()
        reference_frame = _reference_frame()
    except ValueError as error:
        _message(error)
        return []
    if reference_frame is None:
        return []
    try:
        corners, axis_input = _plane_corners(plane, camera, reference_frame)
    except ValueError as error:
        _message(error)
        return []

    created = []
    undo = nuke.Undo()
    undo.begin("Create Card Stabilizer")
    try:
        top_y = max(plane.ypos(), camera.ypos()) + 150
        start_x = min(plane.xpos(), camera.xpos())
        format_source = _create_format_source(plane, top_y)
        created.append(format_source)

        reconciles = []
        for index, (corner_name, point) in enumerate(zip(CORNER_NAMES, corners)):
            reconcile = _create_reconcile(
                axis_input, camera, format_source, point, corner_name,
                start_x + index * HORIZONTAL_SPACING, top_y,
            )
            reconciles.append(reconcile)
            created.append(reconcile)

        corner_pin = nuke.nodes.CornerPin2D(
            name="Card_Stabilize",
            label=(
                "STABILIZED at frame {}\n"
                "Connect the rendered plate/card here"
            ).format(reference_frame),
        )
        _set_position(
            corner_pin,
            start_x + (3 * HORIZONTAL_SPACING) / 2,
            top_y + 170,
        )
        created.append(corner_pin)

        # Stabilization maps the live card quadrilateral (source/from) to the
        # frozen reference quadrilateral (destination/to).
        for index, reconcile in enumerate(reconciles, 1):
            _set_live_corner(corner_pin, "from{}".format(index), reconcile)
            for component in range(2):
                value = reconcile["output"].getValueAt(reference_frame, component)
                corner_pin["to{}".format(index)].setValue(float(value), component)

        for node in nuke.selectedNodes():
            node["selected"].setValue(False)
        corner_pin["selected"].setValue(True)
        return created
    except Exception as error:
        for node in reversed(created):
            try:
                nuke.delete(node)
            except Exception:
                pass
        _message("Could not create the stabilization setup:\n{}".format(error))
        return []
    finally:
        undo.end()
