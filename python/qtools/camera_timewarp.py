"""Remap sparse Camera animation keys using selected TimeWarp lookup keys."""

from __future__ import division

import nuke


CAMERA_CLASSES = {"Camera", "Camera2", "Camera3"}
TIMEWARP_CLASSES = {"TimeWarp"}
FRAME_TOLERANCE = 1e-6


def _message(text):
    nuke.message("Apply TimeWarp to Camera\n\n{}".format(text))


def _selected_nodes():
    selected = list(nuke.selectedNodes())
    cameras = [node for node in selected if node.Class() in CAMERA_CLASSES]
    timewarps = [node for node in selected if node.Class() in TIMEWARP_CLASSES]
    if len(selected) != 2 or len(cameras) != 1 or len(timewarps) != 1:
        raise ValueError("Select exactly one Camera and one TimeWarp node.")
    return cameras[0], timewarps[0]


def _key_pairs(curve):
    """Return TimeWarp pairs as ``(output_frame, source_frame)``."""
    pairs = [(float(key.x), float(key.y)) for key in curve.keys()]
    if not pairs:
        raise ValueError("The TimeWarp lookup curve has no keys.")
    outputs = [output for output, _source in pairs]
    if len(set(outputs)) != len(outputs):
        raise ValueError("The TimeWarp contains duplicate output key frames.")
    return pairs


def _lookup_curve(timewarp):
    lookup = timewarp.knob("lookup")
    if lookup is None:
        raise ValueError("The selected TimeWarp has no lookup knob.")
    animations = lookup.animations() or []
    if not animations:
        raise ValueError("Animate the TimeWarp lookup curve before running the tool.")
    return animations[0]


def _matching_key(keys, source_frame):
    for key in keys:
        if abs(float(key.x) - source_frame) <= FRAME_TOLERANCE:
            return key
    return None


def _camera_curve_plan(camera, pairs):
    """Collect values before any Camera curves are modified."""
    plan = []
    expression_channels = []
    for knob_name, knob in camera.knobs().items():
        try:
            animations = knob.animations() or []
        except Exception:
            continue
        for component, curve in enumerate(animations):
            if curve is None:
                continue
            try:
                has_expression = knob.hasExpression(component)
            except Exception:
                has_expression = False
            if has_expression:
                expression_channels.append("{}.{}".format(knob_name, component))
                continue
            keys = list(curve.keys())
            if not keys:
                continue
            remapped = []
            for output_frame, source_frame in pairs:
                source_key = _matching_key(keys, source_frame)
                if source_key is not None:
                    remapped.append((output_frame, float(source_key.y)))
            plan.append((knob, knob_name, component, remapped, len(keys)))
    if expression_channels:
        raise ValueError(
            "Expression-driven Camera channels are not supported: {}".format(
                ", ".join(expression_channels)
            )
        )
    if not plan:
        raise ValueError("The selected Camera has no animated keyframe channels.")
    if not any(remapped for _knob, _name, _component, remapped, _count in plan):
        raise ValueError(
            "None of the TimeWarp source frames match Camera keyframes."
        )
    return plan


def _format_frame(value):
    rounded = round(value)
    return str(int(rounded)) if abs(value - rounded) <= FRAME_TOLERANCE else str(value)


def apply_selected():
    """Apply the selected TimeWarp's keyed mapping to the selected Camera."""
    try:
        camera, timewarp = _selected_nodes()
        pairs = _key_pairs(_lookup_curve(timewarp))
        plan = _camera_curve_plan(camera, pairs)
    except ValueError as error:
        _message(error)
        return False

    mapping_text = ", ".join(
        "{} ← {}".format(_format_frame(output), _format_frame(source))
        for output, source in pairs
    )
    old_key_count = sum(count for _knob, _name, _component, _keys, count in plan)
    new_key_count = sum(len(keys) for _knob, _name, _component, keys, _count in plan)
    if not nuke.ask(
        "Apply this mapping to {}?\n\n{}\n\n"
        "All existing Camera animation keys will be removed, then {} matched "
        "keys will be created (currently {} keys).".format(
            camera.name(), mapping_text, new_key_count, old_key_count
        )
    ):
        return False

    undo = nuke.Undo()
    undo.begin("Apply TimeWarp to Camera")
    try:
        for knob, _knob_name, component, remapped, _old_count in plan:
            knob.clearAnimated(component)
            if not remapped:
                continue
            knob.setAnimated(component)
            for output_frame, value in remapped:
                knob.setValueAt(value, output_frame, component)
        return True
    except Exception as error:
        _message("Could not retime the Camera:\n{}".format(error))
        return False
    finally:
        undo.end()
