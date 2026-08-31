"""Conform a movie Read node to the Nuke project's frame rate."""

from __future__ import division

import os
import re

import nuke


MOVIE_EXTENSIONS = {
    ".mov", ".mp4", ".m4v", ".avi", ".mxf", ".webm", ".mkv"
}

METHODS = ("Retime", "OFlow", "Kronos")

FPS_METADATA_KEYS = (
    "input/frame_rate",
    "input/framerate",
    "quicktime/frame_rate",
    "quicktime/framerate",
    "mov/frame_rate",
)


def _as_fps(value):
    """Return a positive float parsed from common FPS metadata formats."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            numerator = float(value[0])
            denominator = float(value[1])
            return numerator / denominator if denominator else None
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    text = str(value).strip()
    ratio = re.search(r"(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)", text)
    try:
        if ratio:
            denominator = float(ratio.group(2))
            fps = float(ratio.group(1)) / denominator if denominator else 0.0
        else:
            number = re.search(r"-?\d+(?:\.\d+)?", text)
            fps = float(number.group(0)) if number else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None

    return fps if fps > 0 else None


def _file_fps(read_node):
    """Read the encoded frame rate from a Read node's stream metadata."""
    first = int(read_node.firstFrame())
    metadata = read_node.metadata() or {}

    for key in FPS_METADATA_KEYS:
        fps = _as_fps(metadata.get(key))
        if fps:
            return fps, key

        try:
            fps = _as_fps(read_node.metadata(key, first))
        except Exception:
            fps = None
        if fps:
            return fps, key

    # Be tolerant of reader/version-specific naming while preferring keys
    # which clearly describe a frame rate rather than timecode rates.
    for key, value in sorted(metadata.items()):
        lowered = str(key).lower()
        if "frame_rate" in lowered or "framerate" in lowered:
            fps = _as_fps(value)
            if fps:
                return fps, str(key)

    return None, None


def _selected_read():
    reads = [node for node in nuke.selectedNodes() if node.Class() == "Read"]
    if len(reads) != 1:
        nuke.message("Select exactly one Read node containing a movie file.")
        return None

    read_node = reads[0]
    path = str(read_node["file"].value() or "")
    extension = os.path.splitext(path)[1].lower()
    if extension not in MOVIE_EXTENSIONS:
        if not nuke.ask(
            "The selected file does not have a recognised movie extension.\n\n"
            "Try to read its frame-rate metadata anyway?"
        ):
            return None
    return read_node


def _set_enum(knob, label, fallback_index):
    """Set an Enumeration_Knob by label with an index fallback."""
    try:
        knob.setValue(label)
    except Exception:
        knob.setValue(fallback_index)


def _configure_retimer(node, method, speed):
    """Configure a newly created timing node to the requested speed."""
    if method == "Retime":
        node["speed"].setValue(speed)
        return

    # OFlow and Kronos share the same modern timing controls. Output Speed is
    # used because it directly expresses source FPS / project FPS.
    if "timing2" not in node.knobs() or "timingOutputSpeed" not in node.knobs():
        raise RuntimeError(
            "{} in this Nuke version does not expose the expected timing "
            "controls.".format(method)
        )
    _set_enum(node["timing2"], "Output Speed", 0)
    node["timingOutputSpeed"].setValue(speed)


def _create_node(class_name):
    """Create a node without opening its properties panel."""
    constructor = getattr(nuke.nodes, class_name, None)
    if constructor is None:
        raise RuntimeError("{} is not available in this Nuke edition.".format(class_name))
    return constructor()


def _place_below(node, upstream, row=1):
    node.setXpos(upstream.xpos())
    node.setYpos(upstream.ypos() + (110 * row))


def create_retime(read_node, method, source_fps, project_fps, start_frame):
    """Create and return a configured retimer, plus an optional TimeOffset."""
    if method not in METHODS:
        raise ValueError("Unknown retime method: {}".format(method))
    if source_fps <= 0 or project_fps <= 0:
        raise ValueError("Frame rates must be greater than zero.")

    created = []
    try:
        speed = source_fps / project_fps
        retimer = _create_node(method)
        created.append(retimer)
        retimer.setInput(0, read_node)
        _configure_retimer(retimer, method, speed)
        _place_below(retimer, read_node)
        retimer["label"].setValue(
            "{:.6g} → {:.6g} fps\n{:.6g}x".format(
                source_fps, project_fps, speed
            )
        )

        output = retimer
        offset = int(start_frame) - int(read_node.firstFrame())
        if offset:
            output = _create_node("TimeOffset")
            created.append(output)
            output.setInput(0, retimer)
            output["time_offset"].setValue(offset)
            _place_below(output, retimer)
            output["label"].setValue("Start at {}".format(int(start_frame)))
    except Exception:
        for node in reversed(created):
            try:
                nuke.delete(node)
            except Exception:
                pass
        raise

    for node in nuke.selectedNodes():
        node.setSelected(False)
    output.setSelected(True)
    return retimer, output


def show_dialog():
    """Show the conform dialog for the selected movie Read node."""
    read_node = _selected_read()
    if read_node is None:
        return

    source_fps, metadata_key = _file_fps(read_node)
    project_fps = float(nuke.root()["fps"].value())
    first_frame = int(read_node.firstFrame())

    panel = nuke.Panel("QuickTime FPS Conform")
    panel.addSingleLineInput("Read node", read_node.name())
    panel.addSingleLineInput(
        "Detected file FPS",
        "{:.9g}".format(source_fps) if source_fps else "Not found"
    )
    panel.addSingleLineInput("Project FPS", "{:.9g}".format(project_fps))
    panel.addEnumerationPulldown("Method", " ".join(METHODS))
    panel.addSingleLineInput("Start frame", str(first_frame))

    if not panel.show():
        return

    # The detected value remains editable, which also provides a deliberate
    # fallback for files whose headers do not expose a usable FPS value.
    chosen_source_fps = _as_fps(panel.value("Detected file FPS"))
    chosen_project_fps = _as_fps(panel.value("Project FPS"))
    try:
        start_frame = int(float(panel.value("Start frame")))
    except (TypeError, ValueError):
        nuke.message("Start frame must be a whole frame number.")
        return

    if not chosen_source_fps:
        key_text = "\nChecked metadata key: {}".format(metadata_key) if metadata_key else ""
        nuke.message(
            "Nuke could not detect a valid file FPS. Enter it manually in "
            "Detected file FPS.{}".format(key_text)
        )
        return
    if not chosen_project_fps:
        nuke.message("Project FPS must be greater than zero.")
        return

    method = panel.value("Method")
    try:
        with nuke.Undo():
            nuke.Undo.name("Conform movie FPS")
            create_retime(
                read_node,
                method,
                chosen_source_fps,
                chosen_project_fps,
                start_frame,
            )
    except Exception as error:
        nuke.message("Could not create the retime:\n{}".format(error))
