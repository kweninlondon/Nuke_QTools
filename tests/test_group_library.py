"""Library scanning and pre-import Viewer filtering without a Nuke licence."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


class GroupLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(sys.modules, {"nuke": types.ModuleType("nuke")}):
            cls.library = importlib.import_module("qtools.group_library")

    def test_scan_nested_folders_duplicate_roots_and_missing_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Nested').mkdir()
            (root / 'Nested' / 'Example.NK').write_text('Group {}')
            (root / 'ignored.txt').write_text('')
            libraries, warnings = self.library.discover([folder, folder, folder + '/missing'])
            self.assertEqual(libraries, [(folder, ['Nested/Example.NK'])])
            self.assertEqual(len(warnings), 1)

    def test_removes_viewers_inside_groups_and_preserves_knob_text(self):
        source = ('Group {\n name Test\n}\n'
                  'NoOp {\n label {Example\nViewer {\n name KeepText\n}\n}\n}\n'
                  'Viewer {\n label {nested {braces}}\n}\n'
                  'set viewer [stack 0]\nend_group\nViewer {\n name Outside\n}\n')
        expected = ('Group {\n name Test\n}\n'
                    'NoOp {\n label {Example\nViewer {\n name KeepText\n}\n}\n}\n'
                    'push 0\nset viewer [stack 0]\nend_group\npush 0\n')
        self.assertEqual(self.library.strip_viewers(source), expected)

    def test_escaped_braces_comments_and_crlf(self):
        source = '# comment {\r\nNoOp {\r\n label \\{hello\\}\r\n}\r\nViewer {\r\n}\r\n'
        self.assertEqual(self.library.strip_viewers(source),
                         '# comment {\r\nNoOp {\r\n label \\{hello\\}\r\n}\r\npush 0\n')

    def test_rejects_truncated_file(self):
        with self.assertRaises(ValueError):
            self.library.strip_viewers('Viewer {\n label {unfinished}\n')

    def test_bundled_group_is_unchanged(self):
        path = Path(self.library.cg_to_film._GROUP_PATH)
        source = path.read_text()
        self.assertEqual(self.library.strip_viewers(source), source)

    def test_filters_before_paste_and_cleans_up_on_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.nk'
            source = 'NoOp {\n}\nViewer {\n}\n'
            path.write_text(source)
            pasted = []

            def paste(filename):
                pasted.append(filename)
                self.assertEqual(Path(filename).read_text(), 'NoOp {\n}\npush 0\n')
                raise RuntimeError('Import error')

            nuke = mock.Mock()
            nuke.nodePaste.side_effect = paste
            with mock.patch.object(self.library, 'nuke', nuke), mock.patch.object(
                    self.library, 'preferences', return_value=([], True)):
                self.library.import_group(str(path))
            self.assertFalse(Path(pasted[0]).exists())
            self.assertEqual(path.read_text(), source)
            nuke.Undo.end.assert_called_once()
            nuke.message.assert_called_once()

    def test_reload_rebuilds_both_menus_and_binds_each_file(self):
        menus = [mock.Mock(), mock.Mock()]
        libraries = [('/one/Library', ['Nested/A.nk', 'B.nk']),
                     ('/two/Library', ['C.nk'])]
        with mock.patch.object(self.library, '_live_menus', return_value=menus), mock.patch.object(
                self.library, 'preferences', return_value=([], False)), mock.patch.object(
                self.library, 'discover', return_value=(libraries, [])):
            self.assertEqual(self.library.reload_menus(), (3, []))
            self.library.reload_menus()
        for menu in menus:
            self.assertEqual(menu.clearMenu.call_count, 2)
            self.assertEqual([call.args[0] for call in menu.addMenu.call_args_list],
                             ['Library', 'Library (2)', 'Library', 'Library (2)'])
            nested = menu.addMenu.return_value.addMenu.return_value
            callback = nested.addCommand.call_args.args[1]
            self.assertEqual(callback.args, ('/one/Library/Nested/A.nk',))

    def test_save_supports_scoped_qt_enums(self):
        core = types.SimpleNamespace(QSettings=types.SimpleNamespace(
            Status=types.SimpleNamespace(NoError=0)))
        settings = mock.Mock(spec=['setValue', 'sync', 'status'])
        settings.status.return_value = 0
        with mock.patch.object(self.library, '_qt', return_value=(core, None)), mock.patch.object(
                self.library, '_settings', return_value=settings):
            self.library.save_preferences(['/groups'], True)
        settings.sync.assert_called_once()

    def test_resolves_live_menus_without_registration_state(self):
        groups = mock.Mock(spec=['clearMenu', 'addCommand', 'addSeparator', 'addMenu'])
        toolbar = mock.Mock(spec=['clearMenu', 'addCommand', 'addSeparator', 'addMenu'])
        main = mock.Mock(spec=['menu'])
        main.menu.return_value = groups
        menu_bar = mock.Mock(spec=['menu'])
        menu_bar.menu.return_value = main
        nodes = mock.Mock(spec=['menu'])
        nodes.menu.return_value = toolbar
        nuke = mock.Mock()
        nuke.menu.side_effect = lambda name: {'Nuke': menu_bar, 'Nodes': nodes}[name]
        with mock.patch.object(self.library, 'nuke', nuke), mock.patch.object(
                self.library, '_registered_menus', None), mock.patch.object(
                self.library, 'preferences', return_value=([], False)):
            self.assertEqual(self.library._live_menus(), (groups, toolbar))
            self.library.reload_menus(scan=([], []))
        groups.clearMenu.assert_called_once()
        toolbar.clearMenu.assert_called_once()
        menu_bar.menu.assert_called_with('QTools')
        main.menu.assert_called_with('Groups')
        nodes.menu.assert_called_with('QTools')

    def test_startup_uses_supplied_menu_objects(self):
        menus = (mock.Mock(), mock.Mock())
        with mock.patch.object(self.library, '_registered_menus', None), mock.patch.object(
                self.library, 'reload_menus') as reload:
            self.library.register_menus(*menus)
            self.assertEqual(self.library._live_menus(), menus)
            reload.assert_called_once()

    def test_library_startup_failure_keeps_settings_available(self):
        groups, toolbar = mock.Mock(), mock.Mock()
        nuke = mock.Mock()
        with mock.patch.object(self.library, '_registered_menus', None), mock.patch.object(
                self.library, 'nuke', nuke), mock.patch.object(
                self.library, 'reload_menus', side_effect=RuntimeError('scan failed')):
            self.library.register_menus(groups, toolbar)
        groups.addCommand.assert_called_once_with('Group Settings…', self.library.show_settings)
        self.assertIn('scan failed', nuke.tprint.call_args.args[0])

    def test_disabled_filter_pastes_original(self):
        nuke = mock.Mock()
        with mock.patch.object(self.library, 'nuke', nuke), mock.patch.object(
                self.library, 'preferences', return_value=([], False)):
            self.library.import_group('/library/example.nk')
        nuke.nodePaste.assert_called_once_with('/library/example.nk')


if __name__ == '__main__':
    unittest.main()
