from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from tools import project_map


class MapTests(unittest.TestCase):
    def test_release_without_git_excludes_local_data(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['tools/example.py', 'cache/secret.py', 'out/source.py', '.venv/library.py']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('')
            with patch.object(project_map, 'ROOT', root), patch.object(
                    project_map.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(128, 'git')):
                self.assertEqual(project_map.tracked_files(), ['tools/example.py'])
