"""Check connector insertion and graph preservation without Nuke or Qt."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Node:
    def __init__(self, kind, x=100, y=100, width=80, height=20):
        self.kind = kind
        self.x, self.y, self.width, self.height = x, y, width, height
        self.links = {}

    def Class(self):
        return self.kind

    def __getitem__(self, key):
        return types.SimpleNamespace(value=lambda: "From PLATE")

    def xpos(self):
        return self.x

    def ypos(self):
        return self.y

    def screenWidth(self):
        return self.width

    def screenHeight(self):
        return self.height

    def setXYpos(self, x, y):
        self.x, self.y = x, y

    def setInput(self, index, node):
        self.links[index] = node


class PostageStampPlacementTests(unittest.TestCase):
    def setUp(self):
        qt = types.ModuleType("PySide6")
        qt.QtCore = qt.QtGui = types.SimpleNamespace()
        qt.QtWidgets = types.SimpleNamespace(QDialog=object)
        self.nuke = types.SimpleNamespace(
            Undo=Mock(), zoomToFitSelected=Mock(), delete=Mock(), message=Mock()
        )
        package = types.ModuleType("qtools")
        package.connector_rules = types.SimpleNamespace()
        spec = importlib.util.spec_from_file_location(
            "tested_postage_stamp_creator",
            Path(__file__).parents[1] / "python/qtools/postage_stamp_creator.py",
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "PySide6": qt, "nuke": self.nuke, "qtools": package,
        }):
            spec.loader.exec_module(self.module)
        self.source = Node("Dot", width=12, height=12)
        self.stamp = Node("PostageStamp", width=80, height=60)
        self.module._create_postage_stamp = Mock(return_value=self.stamp)

    def insert(self, connections):
        for destination, index in connections:
            destination.setInput(index, self.source)
        self.module._outgoing_connections = Mock(return_value=connections)
        return self.module._create_stamp_in_source_dot_tree(self.source)

    def test_single_destination_centers_stamp_above_its_original_input(self):
        destination = Node("Merge2", x=300, y=500)
        self.assertIs(self.insert([(destination, 1)]), self.stamp)
        self.assertIs(destination.links[1], self.stamp)
        self.assertEqual((self.stamp.x, self.stamp.y), (300, 428))
        self.nuke.Undo.return_value.end.assert_called_once()

    def test_multiple_branches_share_stamp_below_dot_but_references_stay(self):
        first, second = Node("Grade"), Node("Merge2")
        existing_stamp, viewer = Node("PostageStamp"), Node("Viewer")
        self.insert([(first, 0), (second, 1), (existing_stamp, 0), (viewer, 0)])
        self.assertIs(first.links[0], self.stamp)
        self.assertIs(second.links[1], self.stamp)
        self.assertIs(existing_stamp.links[0], self.source)
        self.assertIs(viewer.links[0], self.source)
        self.assertEqual((self.stamp.x, self.stamp.y), (66, 152))

    def test_no_branches_uses_existing_creation_behaviour(self):
        self.assertIs(self.insert([]), self.stamp)
        self.module._create_postage_stamp.assert_called_once_with(self.source)
        self.nuke.Undo.assert_not_called()

    def test_failed_rewire_restores_previous_branches_and_deletes_new_stamp(self):
        first, second = Node("Grade"), Node("Merge2")
        second.links[1] = self.source
        def set_input(index, node):
            if node is self.stamp:
                raise RuntimeError("Input rejected")
            second.links[index] = node
        second.setInput = set_input
        self.assertIsNone(self.insert([(first, 0), (second, 1)]))
        self.assertIs(first.links[0], self.source)
        self.assertIs(second.links[1], self.source)
        self.nuke.delete.assert_called_once_with(self.stamp)
        self.nuke.Undo.return_value.end.assert_called_once()



if __name__ == "__main__":
    unittest.main()
