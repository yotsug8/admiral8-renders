from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from tools.skit import grade


class ReferenceSelectionTests(unittest.TestCase):
    def test_requires_selection(self):
        with self.assertRaisesRegex(ValueError, 'Select reference'):
            grade.target([])

    def test_does_not_sample_unselected_library_members(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'chosen.mp4').write_bytes(b'fixture')
            (root / 'unrelated.mp4').write_bytes(b'fixture')
            measure = {'L': [50] * len(grade.PCT), 'C': [20, 30, 20], 'b_mid': 2}
            with patch.object(grade, 'REFERENCES', root), patch.object(grade, 'TARGET', str(root / 'target.json')), \
                    patch.object(grade, 'sample', return_value=None) as sample, \
                    patch.object(grade, 'measure', return_value=measure):
                result = grade.target(['chosen.mp4'])
            sample.assert_called_once_with(str(root / 'chosen.mp4'))
            self.assertEqual(result['n'], 1)
            self.assertTrue((root / 'target.json').is_file())
