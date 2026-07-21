"""Move selected Dot labels into StickyNote nodes."""

import nuke


def _copy_font_parameters(source, target):
    """Copy font-related knobs shared by source and target."""
    source_knobs = source.knobs()
    target_knobs = target.knobs()

    for knob_name, source_knob in source_knobs.items():
        if not knob_name.startswith("note_font"):
            continue

        if knob_name not in target_knobs:
            continue

        try:
            target_knobs[knob_name].setValue(source_knob.value())
        except Exception:
            pass


def clean_up_selected_dots():
    """Replace selected Dot labels with matching StickyNote labels."""
    selected_dots = [
        node
        for node in nuke.selectedNodes()
        if node.Class() == "Dot"
    ]

    if not selected_dots:
        nuke.message("Select at least one Dot to clean up.")
        return []

    for node in nuke.selectedNodes():
        node.setSelected(False)

    sticky_notes = []

    for dot in selected_dots:
        sticky_note = nuke.createNode(
            "StickyNote",
            inpanel=False
        )
        sticky_note.setXYpos(dot.xpos(), dot.ypos())

        if "label" in dot.knobs() and "label" in sticky_note.knobs():
            sticky_note["label"].setValue(dot["label"].value())
            _copy_font_parameters(dot, sticky_note)
            dot["label"].setValue("")

        sticky_notes.append(sticky_note)

    for sticky_note in sticky_notes:
        sticky_note.setSelected(True)

    return sticky_notes
