from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile
from tools.optional_addons import extract


class AddonTests(unittest.TestCase):
    def test_archive_escape_is_rejected_before_extraction(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for member in ('../escape.py', '/absolute.py', '..\\escape.py'):
                if '\\' in member and __import__('os').name != 'nt':
                    continue
                archive = root / 'input.zip'
                with zipfile.ZipFile(archive, 'w') as output:
                    output.writestr('safe.py', 'pass')
                    output.writestr(member, 'bad')
                with self.assertRaises(ValueError):
                    extract(archive, root / 'result')
                self.assertFalse((root / 'result/safe.py').exists())

    def test_valid_package_is_preserved(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(root / 'input.zip', 'w') as output:
                output.writestr('addon/__init__.py', 'value=42\n')
            extract(root / 'input.zip', root / 'result')
            self.assertEqual((root / 'result/addon/__init__.py').read_text(), 'value=42\n')
