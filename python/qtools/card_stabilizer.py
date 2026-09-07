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


def _unique_name(base_name):
    """Return a root-level node name that does not already exist."""
    if nuke.toNode(base_name) is None:
        return base_name
    suffix = 2
    while nuke.toNode("{}_{}".format(base_name, suffix)) is not None:
        suffix += 1
    return "{}_{}".format(base_name, suffix)


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
    projection_mode = _enum_name(camera, "projection_mode", "perspective")
    if projection_mode.strip().lower() not in ("perspective", "0"):
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
    world_to_axis = axis_world.inverse()
    for x, y, z in local_corners:
        world_point = camera_world * nuke.math.Vector4(x, y, z, 1.0)
        point = world_to_axis * world_point
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
            return _axis_frustum_corners(plane, camera, reference_frame), plane

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


def _options():
    panel = nuke.Panel("Card / Axis Transform")
    panel.addSingleLineInput("Reference frame", str(nuke.frame()))
    panel.addEnumerationPulldown("Mode", "Stabilise Match Move")
    panel.addBooleanCheckBox("Live transform", True)
    if not panel.show():
        return None
    value = panel.value("Reference frame")
    try:
        frame = float(value)
    except (TypeError, ValueError):
        raise ValueError("Reference frame must be a number.")
    if not math.isfinite(frame):
        raise ValueError("Reference frame must be a finite number.")
    return {
        "reference_frame": frame,
        "mode": str(panel.value("Mode")),
        "live": bool(panel.value("Live transform")),
    }


def _set_position(node, x, y):
    node.setXYpos(int(round(x)), int(round(y)))


def _create_reconcile_group(axis_input, camera, corners, x, y):
    group = nuke.nodes.Group(
        name=_unique_name("CardStabilize_Projection"),
        label="4 corner projections\n{} + {}".format(
            axis_input.name(), camera.name()
        ),
    )
    _set_position(group, x, y)

    group.begin()
    try:
        # Set numbers explicitly: Nuke can otherwise reorder Group inputs.
        axis_node = nuke.nodes.Input(name="Axis_Input", number=0)
        camera_node = nuke.nodes.Input(name="Camera_Input", number=1)
        for input_node, number in (
            (axis_node, 0), (camera_node, 1),
        ):
            input_node["number"].setValue(number)
        format_node = nuke.nodes.Constant(
            name="Projection_Format",
            label="project format for pixel coordinates",
        )
        for index, (corner_name, point) in enumerate(zip(CORNER_NAMES, corners), 1):
            corner_axis = nuke.nodes.Axis2(
                name="CornerAxis_{}".format(corner_name),
                label="{} corner\ndriven by input Axis".format(corner_name),
            )
            # Axis2 scripting order is look=0, parent axis=1.
            corner_axis.setInput(1, axis_node)
            for component, value in enumerate(point):
                corner_axis["translate"].setValue(float(value), component)
            corner_axis.setXYpos((index - 1) * HORIZONTAL_SPACING, 60)
            if corner_axis.input(1) is not axis_node:
                raise RuntimeError(
                    "Nuke did not parent {} to the Axis input.".format(
                        corner_axis.name()
                    )
                )

            reconcile = nuke.nodes.Reconcile3D(
                name="Corner_{}".format(corner_name),
                label="{} corner".format(corner_name),
            )
            # Reconcile3D scripting order is img=0, cam=1, axis=2.
            reconcile.setInput(0, format_node)
            reconcile.setInput(1, camera_node)
            reconcile.setInput(2, corner_axis)
            reconcile["calc_output"].setValue(True)
            reconcile.setXYpos((index - 1) * HORIZONTAL_SPACING, 150)
            if (
                reconcile.input(0) is not format_node
                or reconcile.input(1) is not camera_node
                or reconcile.input(2) is not corner_axis
            ):
                raise RuntimeError(
                    "Nuke did not preserve the inputs on {}.".format(
                        reconcile.name()
                    )
                )
    finally:
        group.end()
    group.setInput(0, axis_input)
    group.setInput(1, camera)
    if group.input(0) is not axis_input or group.input(1) is not camera:
        raise RuntimeError("Nuke did not preserve the Group's Axis/Camera input order.")
    return group


def _reconcile_path(group, corner_index):
    return "{}.Corner_{}".format(
        group.fullName(), CORNER_NAMES[corner_index - 1]
    )


def _reconcile_node(group, corner_index):
    node = nuke.toNode(_reconcile_path(group, corner_index))
    if node is None:
        raise RuntimeError(
            "Could not resolve internal {} Reconcile3D.".format(
                CORNER_NAMES[corner_index - 1]
            )
        )
    return node


def _set_live_corner(corner_pin, knob_name, group, corner_index):
    reconcile_path = _reconcile_path(group, corner_index)
    for component, suffix in enumerate(("x", "y")):
        corner_pin[knob_name].setExpression(
            "{}.output.{}".format(reconcile_path, suffix), component
        )


def _set_baked_corner(corner_pin, knob_name, group, corner_index):
    knob = corner_pin[knob_name]
    source = _reconcile_node(group, corner_index)["output"]
    for component in range(2):
        knob.setAnimated(component)
        for frame in range(int(nuke.root().firstFrame()), int(nuke.root().lastFrame()) + 1):
            knob.setValueAt(source.getValueAt(frame, component), frame, component)


def create_stabilizer():
    """Create a grouped four-point projection and a CornerPin2D."""
    try:
        plane, camera = _selection()
        options = _options()
    except ValueError as error:
        _message(error)
        return []
    if options is None:
        return []
    reference_frame = options["reference_frame"]
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
        projection_group = _create_reconcile_group(
            axis_input, camera, corners, start_x, top_y
        )
        created.append(projection_group)

        reference_points = []
        for index in range(1, 5):
            output = _reconcile_node(projection_group, index)["output"]
            reference_points.append(tuple(
                float(output.getValueAt(reference_frame, component))
                for component in range(2)
            ))
        distinct_points = {
            (round(point[0], 7), round(point[1], 7))
            for point in reference_points
        }
        if len(distinct_points) != 4:
            raise RuntimeError(
                "The four projected corners are not distinct. Check that the "
                "Axis is in front of the Camera and try again."
            )

        mode = options["mode"]
        node_name = _unique_name(
            "Card_Stabilise" if mode == "Stabilise" else "Card_MatchMove"
        )
        corner_pin = nuke.nodes.CornerPin2D(
            name=node_name,
            label=(
                "{} · reference frame {} · {}\n"
                "Connect the rendered plate/card here"
            ).format(
                mode.upper(), reference_frame,
                "LIVE" if options["live"] else "BAKED",
            ),
        )
        corner_pin["invert"].setValue(mode == "Match Move")
        _set_position(
            corner_pin,
            start_x,
            top_y + 170,
        )
        created.append(corner_pin)

        # The moving projection is the source/from side. CornerPin invert turns
        # the same mapping into its match-move counterpart.
        for index in range(1, 5):
            if options["live"]:
                _set_live_corner(
                    corner_pin, "from{}".format(index), projection_group, index
                )
            else:
                _set_baked_corner(
                    corner_pin, "from{}".format(index), projection_group, index
                )
            for component in range(2):
                value = reference_points[index - 1][component]
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
