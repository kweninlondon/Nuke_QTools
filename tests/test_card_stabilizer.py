"""Unit tests for geometry decisions that do not require a Nuke licence."""

import importlib
import sys
import types
import unittest


class _Format(object):
    def __init__(self, width, height, pixel_aspect=1.0):
        self._width = width
        self._height = height
        self._pixel_aspect = pixel_aspect

    def width(self):
        return self._width

    def height(self):
        return self._height

    def pixelAspect(self):
        return self._pixel_aspect


class _Knob(object):
    def __init__(self, value, values=None):
        self._value = value
        self._values = values

    def value(self):
        return self._value

    def values(self):
        if self._values is None:
            raise AttributeError
        return self._values


class _Node(object):
    def __init__(self, node_class, knobs=None, image=None, format_value=None):
        self._class = node_class
        self._knobs = knobs or {}
        self._image = image
        self._format = format_value

    def Class(self):
        return self._class

    def knob(self, name):
        return self._knobs.get(name)

    def input(self, index):
        return self._image if index == 0 else None

    def format(self):
        return self._format


class CardStabilizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_nuke = types.ModuleType("nuke")
        fake_nuke.root = lambda: _Node("Root", format_value=_Format(1920, 1080))
        fake_nuke.toNode = lambda _name: None
        sys.modules.setdefault("nuke", fake_nuke)
        cls.module = importlib.import_module("qtools.card_stabilizer")

    def _card(self, orientation="XY", image_aspect=True, image=None):
        return _Node("Card2", {
            "type": _Knob(0, ["none", "bilinear", "bicubic"]),
            "orientation": _Knob(
                ["XY", "YZ", "ZX"].index(orientation),
                ["XY", "YZ", "ZX"],
            ),
            "image_aspect": _Knob(image_aspect),
            "z": _Knob(0.0),
        }, image=image)

    def test_card_aspect_includes_pixel_aspect(self):
        image = _Node("Constant", format_value=_Format(2048, 1024, 2.0))
        corners = self.module._plane_corners(self._card(image=image))
        self.assertEqual(corners[0], (-0.5, -0.125, 0.0))
        self.assertEqual(corners[2], (0.5, 0.125, 0.0))

    def test_square_card_ignores_image_format(self):
        image = _Node("Constant", format_value=_Format(2048, 1024, 2.0))
        corners = self.module._plane_corners(
            self._card(image_aspect=False, image=image)
        )
        self.assertEqual(corners[0], (-0.5, -0.5, 0.0))
        self.assertEqual(corners[2], (0.5, 0.5, 0.0))

    def test_supported_orientations_keep_four_distinct_corners(self):
        for orientation in ("XY", "YZ", "ZX"):
            corners = self.module._plane_corners(
                self._card(orientation=orientation, image_aspect=False)
            )
            self.assertEqual(len(set(corners)), 4)

    def test_nonzero_card_z_is_rejected(self):
        card = self._card(image_aspect=False)
        card._knobs["z"] = _Knob(2.0)
        with self.assertRaisesRegex(ValueError, "translate Z"):
            self.module._plane_corners(card)

    def test_projection_mode_accepts_text_or_index(self):
        textual = _Node("Camera2", {
            "projection_mode": _Knob("perspective"),
        })
        indexed = _Node("Camera2", {
            "projection_mode": _Knob(0, ["perspective", "orthographic"]),
        })
        self.assertEqual(
            self.module._enum_name(textual, "projection_mode", ""),
            "perspective",
        )
        self.assertEqual(
            self.module._enum_name(indexed, "projection_mode", ""),
            "perspective",
        )

    def test_unique_name_skips_existing_setups(self):
        existing = {
            "CardStabilize_Projection",
            "CardStabilize_Projection_2",
        }
        original = self.module.nuke.toNode
        self.module.nuke.toNode = lambda name: object() if name in existing else None
        try:
            self.assertEqual(
                self.module._unique_name("CardStabilize_Projection"),
                "CardStabilize_Projection_3",
            )
        finally:
            self.module.nuke.toNode = original

    def test_three_by_three_determinant_uses_column_vectors(self):
        self.assertEqual(
            self.module._determinant3(((2, 0, 0), (0, 3, 0), (0, 0, 4))),
            24,
        )


if __name__ == "__main__":
    unittest.main()
