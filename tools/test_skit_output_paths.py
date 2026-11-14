"""Skit plans isolate synthetic QA from production and never write into assets."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.skit import skit


class SkitOutputTests(unittest.TestCase):
    def test_fake_and_production_plans_use_separate_non_asset_folders(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / '_game' / 'keep.txt'
            asset.parent.mkdir()
            asset.write_text('unique source', encoding='utf-8')
            observed = []

            def make(folder, lines):
                folder = Path(folder)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'voices.json').write_text('{}', encoding='utf-8')
                return {}

            def build(scene, voices, folder):
                observed.append(Path(folder))
                (Path(folder) / 'scene.json').write_text(json.dumps(scene), encoding='utf-8')
                return None, None, None, None, None

            with patch.object(skit, 'REPO', str(root)), \
                    patch.object(skit, 'parse', return_value={'name': 'routing-test', 'events': []}), \
                    patch.object(skit, 'build', side_effect=build), \
                    patch.object(skit.sys, 'argv', ['skit.py', 'unused.txt', '--plan']), \
                    patch.object(skit.sys, 'stdout', Mock()), \
                    patch.dict(skit.sys.modules, {'voices': SimpleNamespace(make=make)}):
                with patch.dict(os.environ, {'SKIT_FAKE': '1'}):
                    skit.main()
                production = root / 'out' / 'skits' / 'routing-test'
                with patch.dict(os.environ, {'SKIT_FAKE': ''}):
                    skit.main()

            self.assertEqual(observed, [root / 'qa' / 'skits' / 'routing-test', production])
            for output in observed:
                self.assertTrue((output / 'voices.json').is_file())
                self.assertTrue((output / 'scene.json').is_file())
            self.assertEqual(asset.read_text(encoding='utf-8'), 'unique source')
            self.assertEqual(list(asset.parent.iterdir()), [asset])


if __name__ == '__main__':
    unittest.main()
