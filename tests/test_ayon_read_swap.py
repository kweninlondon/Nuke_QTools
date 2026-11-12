"""Offline behavioral checks; a live AYON/Nuke session is still required for QA."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Knob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class Node:
    def __init__(self, name, kind="Read", path="asset.mov", inputs=()):
        self._name = name
        self.kind = kind
        self.links = list(inputs)
        self.selected = False
        self.position = (40, 90)
        self.container = None
        self.knobs = {"file": Knob(path), "frame_mode": Knob("start at")}
        self.fail_connection = False

    def __getitem__(self, key):
        return self.knobs[key]

    def Class(self):
        return self.kind

    def name(self):
        return self._name

    def fullName(self):
        return self._name

    def setName(self, name):
        self._name = name

    def inputs(self):
        return len(self.links)

    def input(self, index):
        return self.links[index]

    def setInput(self, index, node):
        if self.fail_connection:
            self.fail_connection = False
            raise RuntimeError("Connection failed")
        self.links[index] = node

    def isSelected(self):
        return self.selected

    def setSelected(self, value):
        self.selected = value

    def xpos(self):
        return self.position[0]

    def ypos(self):
        return self.position[1]

    def setXYpos(self, x, y):
        self.position = (x, y)


def repre(identifier, name, ext, version="v1"):
    return {"id": identifier, "name": name, "versionId": version,
            "context": {"ext": ext}}


class ReadSwapTests(unittest.TestCase):
    def setUp(self):
        self.source = repre("mov", "baking_h264", "mov")
        self.target = repre("exr", "exr", "exr")
        self.old = Node("Plate")
        self.old.selected = True
        self.old.container = {"representation": "mov", "project_name": "Library"}
        self.merge = Node("Merge", "Merge2", inputs=(self.old, None, self.old))
        self.viewer = Node("Viewer", "Viewer", inputs=(None, self.old))
        self.nodes = [self.old, self.merge, self.viewer]
        self.nuke = types.ModuleType("nuke")
        self.nuke.allNodes = lambda: list(self.nodes)
        self.nuke.delete = self.delete
        path = Path(__file__).resolve().parents[1] / "python/qtools/ayon_read_swap.py"
        spec = importlib.util.spec_from_file_location("ayon_read_swap_test", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"nuke": self.nuke}):
            spec.loader.exec_module(self.module)
        self.context = {"representation": self.source,
                        "project": {"name": "Library"}}
        self.siblings = [self.source, self.target]
        self.api = types.SimpleNamespace(get_representations=self.query)
        loader = type("LoadClip", (), {})
        self.loads = []
        self.load = types.SimpleNamespace(
            get_representation_context=lambda project, identifier: self.context,
            discover_loader_plugins=lambda: [loader],
            is_compatible_loader=lambda plugin, context: True,
            load_with_repre_context=self.import_read,
        )
        self.module._ayon = lambda: (
            self.api, self.load, lambda node: node.container, lambda: "Work"
        )

    def query(self, project, version_ids):
        self.assertEqual(project, "Library")
        self.assertEqual(version_ids, {"v1"})
        return self.siblings

    def delete(self, node):
        self.nodes.remove(node)
        for peer in self.nodes:
            peer.links = [None if upstream == node else upstream for upstream in peer.links]

    def import_read(self, loader, context, options):
        self.loads.append((context, options))
        new = Node("Read_exr", path="asset.####.exr")
        new.container = {"representation": context["representation"]["id"],
                         "project_name": context["project"]["name"]}
        self.nodes.append(new)

    def swap(self, replace=True):
        return self.module.load_counterpart(self.old, self.context, self.target, replace)

    def test_all_exr_and_mov_variants_are_offered(self):
        other = repre("exr2", "exr_beauty", "exr")
        self.siblings += [other, repre("thumb", "thumbnail", "jpg")]
        _, candidates = self.module.find_counterparts(self.old)
        self.assertEqual({item["id"] for item in candidates}, {"exr", "exr2"})
        self.old.knobs["file"] = Knob("asset.####.exr")
        self.old.container["representation"] = "exr"
        self.context["representation"] = self.target
        self.siblings.append(repre("mov2", "prores", "mov"))
        _, candidates = self.module.find_counterparts(self.old)
        self.assertEqual({item["id"] for item in candidates}, {"mov", "mov2"})

    def test_replace_reconnects_repeated_and_viewer_inputs(self):
        new = self.swap()
        self.assertNotIn(self.old, self.nodes)
        self.assertEqual(new.name(), "Plate")
        self.assertEqual(new.position, (40, 90))
        self.assertEqual(self.merge.links, [new, None, new])
        self.assertEqual(self.viewer.links, [None, new])
        self.assertEqual(new.container["representation"], "exr")
        context, options = self.loads[0]
        self.assertEqual(context["project"]["name"], "Library")
        self.assertFalse(options["add_retime"])

    def test_alongside_leaves_original_connections(self):
        new = self.swap(False)
        self.assertIn(self.old, self.nodes)
        self.assertEqual(self.merge.links, [self.old, None, self.old])
        self.assertEqual(self.viewer.links, [None, self.old])
        self.assertEqual(new.position, (40, -30))

    def test_further_alongside_loads_stack_above_existing_nodes(self):
        first = self.swap(False)
        second = self.swap(False)
        self.assertEqual(first.position, (40, -30))
        self.assertEqual(second.position, (40, -150))
        self.assertEqual(self.old.position, (40, 90))

    def test_batch_row_switches_back_after_replacement(self):
        row = self.module.BatchRow(self.old)
        self.assertTrue(row.checked)
        self.assertEqual(row.target_id, "exr")
        new = row.apply(True)
        self.assertIs(row.node, new)
        self.assertEqual(row.context["representation"]["id"], "exr")
        self.assertEqual(row.target_id, "mov")
        self.assertFalse(row.checked)
        row.checked = True
        back = row.apply(True)
        self.assertIs(row.node, back)
        self.assertEqual(back.container["representation"], "mov")

    def test_batch_multiple_options_require_a_choice_in_both_directions(self):
        self.siblings.extend([repre("exr2", "workingPlate", "exr"),
                              repre("mov2", "prores", "mov")])
        row = self.module.BatchRow(self.old)
        self.assertIsNone(row.target_id)
        with self.assertRaisesRegex(RuntimeError, "Choose"):
            row.apply(True)
        row.target_id = "exr2"
        row.apply(True)
        self.assertEqual({item["id"] for item in row.candidates}, {"mov", "mov2"})
        self.assertIsNone(row.target_id)

    def test_batch_alongside_reports_both_formats_from_scene(self):
        row = self.module.BatchRow(self.old)
        new = row.apply(False)
        self.assertIs(row.node, self.old)
        self.assertFalse(row.checked)
        loaded = self.module.loaded_formats(self.context, self.siblings, self.nodes)
        self.assertEqual(loaded, {"mov": [self.old], "exr": [new]})
        # External deletion is reflected on the next refresh, not a stale flag.
        self.delete(new)
        loaded = self.module.loaded_formats(self.context, self.siblings, self.nodes)
        self.assertEqual(loaded, {"mov": [self.old], "exr": []})

    def test_loaded_status_excludes_other_projects_versions_and_edited_files(self):
        other = Node("Other", path="asset.exr")
        other.container = {"project_name": "Different", "representation": "exr"}
        older = Node("Older", path="asset.exr")
        older.container = {"project_name": "Library", "representation": "old-version-exr"}
        edited = Node("Edited", path="changed.mov")
        edited.container = {"project_name": "Library", "representation": "exr"}
        loaded = self.module.loaded_formats(
            self.context, self.siblings, [self.old, other, older, edited]
        )
        self.assertEqual(loaded, {"mov": [self.old], "exr": []})

    def test_one_invalid_batch_row_does_not_prevent_another_loading(self):
        invalid = Node("Manual")
        invalid_row = self.module.BatchRow(invalid)
        valid_row = self.module.BatchRow(self.old)
        self.assertIn("metadata", invalid_row.error)
        self.assertFalse(invalid_row.checked)
        valid_row.apply(False)
        self.assertEqual(len(self.loads), 1)

    def test_changed_source_file_is_rejected_while_window_is_open(self):
        row = self.module.BatchRow(self.old)
        self.old.knobs["file"] = Knob("edited.exr")
        with self.assertRaisesRegex(RuntimeError, "file format changed"):
            row.apply(True)
        self.assertFalse(self.loads)

    def test_partial_load_failure_cleans_up_and_restores_selection(self):
        def fail(*args, **kwargs):
            self.import_read(*args, **kwargs)
            raise RuntimeError("Import failed")
        self.load.load_with_repre_context = fail
        with self.assertRaisesRegex(RuntimeError, "Import failed"):
            self.swap()
        self.assertEqual(self.nodes, [self.old, self.merge, self.viewer])
        self.assertTrue(self.old.selected)
        self.assertEqual(self.viewer.links, [None, self.old])

    def test_failed_rewire_restores_already_rewired_inputs(self):
        self.viewer.fail_connection = True
        with self.assertRaisesRegex(RuntimeError, "Connection failed"):
            self.swap()
        self.assertEqual(self.nodes, [self.old, self.merge, self.viewer])
        self.assertEqual(self.merge.links, [self.old, None, self.old])
        self.assertEqual(self.old.name(), "Plate")

    def test_wrong_loader_metadata_is_rejected(self):
        def wrong(*args, **kwargs):
            self.import_read(*args, **kwargs)
            self.nodes[-1].container = {"representation": "wrong"}
        self.load.load_with_repre_context = wrong
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            self.swap()
        self.assertEqual(len(self.nodes), 3)

    def test_loader_side_effect_connections_are_restored(self):
        def insert(*args, **kwargs):
            self.import_read(*args, **kwargs)
            self.viewer.setInput(1, self.nodes[-1])
        self.load.load_with_repre_context = insert
        self.swap(False)
        self.assertEqual(self.viewer.links, [None, self.old])

    def test_no_target_or_no_metadata_never_loads(self):
        self.siblings = [self.source]
        with self.assertRaisesRegex(RuntimeError, "No EXR"):
            self.module.find_counterparts(self.old)
        self.old.container = None
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            self.module.find_counterparts(self.old)
        self.assertFalse(self.loads)

    def test_different_version_is_rejected_before_import(self):
        self.target["versionId"] = "v2"
        with self.assertRaisesRegex(RuntimeError, "published version"):
            self.swap()
        self.assertFalse(self.loads)


if __name__ == "__main__":
    unittest.main()
