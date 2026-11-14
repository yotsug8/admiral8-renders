import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tools.project_workspace import create


class WorkspaceTests(unittest.TestCase):
    def test_preserves_prompt_and_refuses_existing_work(self):
        with TemporaryDirectory() as folder:
            root = create(folder, 'new-video', '  Герой бежит по лестнице  ')
            self.assertEqual(json.loads((root / 'project.json').read_text(encoding='utf-8'))['prompt'],
                             'Герой бежит по лестнице')
            marker = root / 'source/keep.blend'
            marker.write_bytes(b'unique scene')
            with self.assertRaises(FileExistsError):
                create(folder, 'new-video', 'another request')
            self.assertEqual(marker.read_bytes(), b'unique scene')

    def test_rejects_escape_and_empty_prompt_without_creating_folder(self):
        with TemporaryDirectory() as folder:
            for name, prompt in [('../escape', 'x'), ('valid', '  '), ('A:/absolute', 'x')]:
                with self.assertRaises(ValueError):
                    create(folder, name, prompt)
            self.assertEqual(list(Path(folder).iterdir()), [])
