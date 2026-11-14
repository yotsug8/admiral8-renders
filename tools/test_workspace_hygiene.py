from pathlib import Path
from contextlib import redirect_stderr
from io import StringIO
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.workspace_hygiene import audit, directory_link, main


class HygieneTests(unittest.TestCase):
    def project(self, root):
        (root / 'tools').mkdir(parents=True)
        (root / 'PROJECT_GUIDE.md').write_text('guide')
        (root / 'tools/project_map.py').write_text('# index')

    def test_wrong_root_rejected(self):
        with TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                audit(temp)

    def test_cache_audit_preserves_files_and_excludes_libraries(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / 'project'
            self.project(root)
            paths = ['tools/__pycache__/x.pyc', 'out/task/orphan.pyc',
                     'vendor/__pycache__/v.pyc', '.venv/__pycache__/v.pyc',
                     'cache/resources/runtime/__pycache__/v.pyc']
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'keep')
            (root / 'out/empty').mkdir()
            with patch('tools.workspace_hygiene.subprocess.check_output',
                       side_effect=[str(root).encode(), b'video.py\0out/leak.mp4\0assets/logo.png\0']):
                report = audit(root)
            kinds = {(x['kind'], x['path']) for x in report['findings']}
            self.assertIn(('python_cache', 'tools/__pycache__'), kinds)
            self.assertIn(('python_bytecode', 'out/task/orphan.pyc'), kinds)
            self.assertIn(('empty_directory', 'out/empty'), kinds)
            self.assertIn(('tracked_production_or_generated_file', 'out/leak.mp4'), kinds)
            self.assertEqual(sum(x['kind'].startswith('python_') for x in report['findings']), 2)
            for name in paths:
                self.assertEqual((root / name).read_bytes(), b'keep')

    def test_sibling_detection_needs_project_evidence_and_external_is_explicit(self):
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            root = parent / 'project'
            self.project(root)
            self.project(parent / 'project-20261114')
            (parent / 'photos-20261114').mkdir()
            external = parent / 'legacy'
            external.mkdir()
            with patch('tools.workspace_hygiene.subprocess.check_output',
                       side_effect=[str(root).encode(), b'']):
                report = audit(root, [external, parent / 'absent'])
            warnings = [x for x in report['findings'] if x['level'] == 'warning']
            self.assertEqual(len(warnings), 2)
            self.assertEqual(report['external'][1]['exists'], False)

    def test_git_failure_is_not_reported_as_clean(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.project(root)
            with patch('tools.workspace_hygiene.subprocess.check_output',
                       side_effect=subprocess.CalledProcessError(128, 'git')):
                report = audit(root)
            self.assertEqual(report['git_index'], 'unavailable')
            self.assertTrue(report['errors'])

    def test_report_refuses_to_overwrite_existing_file(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.project(root)
            target = root / 'PROJECT_GUIDE.md'
            with patch('sys.argv', ['workspace_hygiene', '--root', str(root), '--json', str(target)]), \
                    patch('tools.workspace_hygiene.subprocess.check_output',
                          side_effect=[str(root).encode(), b'']), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(target.read_text(), 'guide')

    def test_windows_junction_is_recognized_without_python312_api(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        path = Mock()
        path.is_symlink.return_value = False
        path.lstat.return_value = SimpleNamespace(st_file_attributes=0x400)
        self.assertTrue(directory_link(path))


if __name__ == '__main__':
    unittest.main()
