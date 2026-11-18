"""Connector naming regressions without a Nuke or Qt installation."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class ConnectorRulesTests(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        settings = types.SimpleNamespace(
            value=lambda key, default: self.saved.get(key, default),
            setValue=lambda key, value: self.saved.__setitem__(key, value),
            sync=lambda: None,
        )
        qt = types.ModuleType("PySide6")
        qt.QtCore = types.SimpleNamespace(QSettings=lambda *args: settings)
        qt.QtGui = types.SimpleNamespace()
        qt.QtWidgets = types.SimpleNamespace(QDialog=object)
        path = Path(__file__).parents[1] / "python/qtools/connector_rules.py"
        spec = importlib.util.spec_from_file_location("tested_connector_rules", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"PySide6": qt}):
            spec.loader.exec_module(self.module)
        self.global_rule = dict(search="", prefix="", remove="SHOW_, v###", colour=0)
        self.plate_rule = dict(search="plate", prefix="PLATE", remove="_main", colour=0)
        self.render_rule = dict(search="render", prefix="CG", remove="_beauty", colour=0)
        self.module.save_rules([self.plate_rule, self.global_rule, self.render_rule])

    def test_global_cleanup_precedes_specific_removals_for_both_sources(self):
        for filename, rule, expected in [
            ("SHOW_plate_main_v001", self.plate_rule, "PLATE plate"),
            ("SHOW_render_beauty_v002", self.render_rule, "CG render"),
        ]:
            self.assertEqual(self.module.matching_rule(filename), rule)
            self.assertEqual(self.module.compose_name(
                rule["prefix"], filename, removals=rule["remove"]
            ), expected)

    def test_global_rules_run_before_search_and_without_a_match(self):
        self.global_rule["remove"] = "SHOW_plate_, v###"
        self.module.save_rules([self.global_rule, self.plate_rule, self.render_rule])
        self.assertIsNone(self.module.matching_rule("SHOW_plate_other_v001"))
        self.assertEqual(self.module.compose_name("", "SHOW_plate_other_v001"), "other")
        self.assertIsNone(self.module.prefix_rule(""))
        self.assertIsNone(self.module.matching_rule("plate", []))

    def test_editor_saves_and_reloads_blank_search_removal(self):
        values = ["", "", "SHOW_, v###"]
        table = types.SimpleNamespace(
            rowCount=lambda: 1,
            item=lambda row, col: types.SimpleNamespace(text=lambda: values[col]),
            cellWidget=lambda row, col: types.SimpleNamespace(property=lambda key: 0),
        )
        dialog = types.SimpleNamespace(table=table, accept=lambda: None)
        self.module.RuleEditorDialog._save(dialog)
        self.assertEqual(self.module.rules(), [self.global_rule])


if __name__ == "__main__":
    unittest.main()
