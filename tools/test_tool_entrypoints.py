"""Shared helpers must work from both a direct CLI and package consumers."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tools.check import exclusive_check
from tools.render_storage import file_lock


ROOT = Path(__file__).resolve().parents[1]


class EntrypointTests(unittest.TestCase):
    def test_related_package_imports_in_isolated_processes(self):
        modules = [
            'tools.dialogue_request', 'tools.quickstart', 'tools.scene_request_3d',
            'tools.skit.character_voice', 'tools.skit.game_vo', 'tools.skit.hero_render',
            'tools.skit.skit', 'tools.skit.grade', 'tools.dota_engine.troupe',
            'tools.dota_engine.ground_map', 'tools.dota_engine.stage',
            'tools.dota_engine.hero_parts', 'tools.blender.run_render_job',
            'tools.blender.export_render_job',
        ]
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        for module in modules:
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, '-B', '-c', f'import {module}'],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_direct_cli_help_remains_available(self):
        for name in ['quickstart', 'dialogue_request', 'blender/run_render_job', 'check']:
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, '-B', str(ROOT / 'tools' / (name + '.py')), '--help'],
                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)

    def test_paths_package_import_without_sys_path_mutation(self):
        env = dict(os.environ, BLENDER='chosen-blender', DOTA_ROOT='chosen-game')
        env.pop('PYTHONPATH', None)
        result = subprocess.check_output(
            [sys.executable, '-B', '-c',
             'import json; from tools.paths import BLENDER, DOTA_ROOT; '
             'print(json.dumps([BLENDER, DOTA_ROOT]))'],
            cwd=ROOT, env=env, text=True,
        )
        self.assertEqual(json.loads(result), ['chosen-blender', 'chosen-game'])

    def test_check_lock_interoperates_and_releases_after_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'check.lock'
            with file_lock(path):
                with self.assertRaisesRegex(RuntimeError, 'File lock unavailable'):
                    with exclusive_check(path):
                        self.fail('Already locked check was allowed to run')
            with self.assertRaisesRegex(ValueError, 'check failed'):
                with exclusive_check(path):
                    raise ValueError('check failed')
            with file_lock(path):
                self.assertTrue(path.is_file())


if __name__ == '__main__':
    unittest.main()
