"""Channel rule resolution, mask batching, and native graph replacement."""
import importlib
import sys
import types
import unittest
from unittest import mock


class ChannelRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(sys.modules, {'nuke': types.ModuleType('nuke')}):
            cls.tool = importlib.import_module('qtools.channel_rules_runtime')

    def test_blank_rules_preserve_everything(self):
        self.assertEqual(self.tool.resolve(['rgba.red', 'depth.Z'], '', ''),
                         (['depth.Z', 'rgba.red'], []))

    def test_remove_wildcard_matches_layer_suffix(self):
        self.assertEqual(self.tool.resolve(['mainbeauty.red', 'diffuse.red'], '*beauty', ''),
                         (['diffuse.red'], ['mainbeauty.red']))

    def test_keep_is_allowlist_and_overrides_remove(self):
        channels = ['light_ENV.red', 'light_ENV.green', 'light_CHAR.red', 'rgba.red']
        keep, removed = self.tool.resolve(channels, '*', ' *_ENV* , ')
        self.assertEqual(keep, ['light_ENV.green', 'light_ENV.red'])
        self.assertEqual(removed, ['light_CHAR.red', 'rgba.red'])

    def test_individual_channel_and_case_sensitive_patterns(self):
        channels = ['rgba.red', 'rgba.green', 'RGBA.red']
        self.assertEqual(self.tool.resolve(channels, 'rgba.r*', ''),
                         (['RGBA.red', 'rgba.green'], ['rgba.red']))

    def test_nonmatching_keep_removes_all(self):
        self.assertEqual(self.tool.resolve(['rgba.red'], '', 'missing*'), ([], ['rgba.red']))

    def test_six_of_twenty_five_layers_in_five_remove_nodes(self):
        channels = ['aov{}.{}'.format(i, c) for i in range(25) for c in ('red', 'green', 'blue')]
        keep, removed = self.tool.resolve(channels, '', ','.join('aov{}'.format(i) for i in range(6)))
        batches = self.tool.removal_masks(channels, removed)
        self.assertEqual(len(keep), 18)
        self.assertEqual(len(batches), 5)
        self.assertEqual(sum(map(len, batches)), 19)
        self.assertTrue(all(len(batch) <= 4 for batch in batches))

    def test_partial_layer_removal_never_removes_its_siblings(self):
        self.assertEqual(self.tool.removal_masks(
            ['rgba.red', 'rgba.green', 'depth.Z'], ['rgba.red', 'depth.Z']),
            [['depth', 'rgba.red']])

    def test_graph_validation_failure_preserves_previous_output(self):
        group = mock.MagicMock()
        group.input.return_value.channels.return_value = ['rgba.red', 'depth.Z']
        group.__getitem__.side_effect = {
            'remove_rules': mock.Mock(value=lambda: 'depth'),
            'keep_rules': mock.Mock(value=lambda: ''),
        }.__getitem__
        input_node = mock.Mock()
        input_node.Class.return_value = 'Input'
        output = mock.Mock()
        output.Class.return_value = 'Output'
        old = mock.Mock()
        old.Class.return_value = 'Remove'
        group.nodes.return_value = [input_node, output, old]
        nuke = mock.MagicMock()
        new = nuke.nodes.Remove.return_value
        new.channels.return_value = ['wrong.red']
        with mock.patch.object(self.tool, 'nuke', nuke):
            with self.assertRaises(RuntimeError):
                self.tool.apply_rules(group)
        output.setInput.assert_not_called()
        nuke.delete.assert_called_once_with(new)
        group.end.assert_called_once()
        nuke.Undo.return_value.end.assert_called_once()


if __name__ == '__main__':
    unittest.main()
