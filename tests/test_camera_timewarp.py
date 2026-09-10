"""Unit tests for Camera TimeWarp key matching without a Nuke licence."""

import importlib
import sys
import types
import unittest


class _Key(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _Curve(object):
    def __init__(self, keys):
        self._keys = keys

    def keys(self):
        return self._keys


class CameraTimeWarpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_nuke = sys.modules.get("nuke")
        sys.modules["nuke"] = types.ModuleType("nuke")
        cls.module = importlib.import_module("qtools.camera_timewarp")

    @classmethod
    def tearDownClass(cls):
        if cls._previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = cls._previous_nuke

    def test_lookup_keys_are_output_to_source_pairs(self):
        curve = _Curve([
            _Key(1009, 1001),
            _Key(1014, 1010),
            _Key(1041, 1015),
        ])
        self.assertEqual(
            self.module._key_pairs(curve),
            [(1009.0, 1001.0), (1014.0, 1010.0), (1041.0, 1015.0)],
        )

    def test_matching_key_uses_small_float_tolerance(self):
        key = _Key(1010.0000001, 42)
        self.assertIs(self.module._matching_key([key], 1010.0), key)
        self.assertIsNone(self.module._matching_key([key], 1010.01))

    def test_duplicate_output_frames_are_rejected(self):
        curve = _Curve([_Key(1009, 1001), _Key(1009, 1010)])
        with self.assertRaisesRegex(ValueError, "duplicate output"):
            self.module._key_pairs(curve)


if __name__ == "__main__":
    unittest.main()
