"""Regression cases for false-success launches and stale render delivery."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from run_verified import run


class VerifiedRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'attempt'

    def command(self, source):
        return [sys.executable, '-c', source, str(self.out / 'result.bin')]

    def test_fresh_delivery_records_hash_not_quality(self):
        result = run(self.out, ['result.bin'], self.command("import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'fresh')"), 0)
        self.assertEqual(result['status'], 'artifacts_verified')
        self.assertFalse(result['quality_accepted'])
        self.assertEqual(len(result['artifacts'][0]['sha256']), 64)
        self.assertIn('finished_at', json.loads((self.out/'run.json').read_text()))

    def test_zero_exit_without_output_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing'):
            run(self.out, ['result.bin'], self.command('pass'), 0)
        self.assertEqual(json.loads((self.out/'run.json').read_text())['status'], 'failed')

    def test_old_folder_is_never_reused(self):
        self.out.mkdir()
        (self.out/'result.bin').write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            run(self.out, ['result.bin'], self.command('pass'), 0)
        self.assertEqual((self.out/'result.bin').read_bytes(), b'old')

    def test_nonzero_exit_with_output_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'exit code 3'):
            run(self.out, ['result.bin'], self.command("import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'partial'); sys.exit(3)"), 0)

    def test_timeout_is_failed(self):
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            run(self.out, ['result.bin'], self.command('import time; time.sleep(5)'), 0, .05)
        self.assertEqual(json.loads((self.out/'run.json').read_text())['status'], 'failed')

    def test_output_escape_and_logs_rejected(self):
        for path in ['../outside', 'process.log', 'run.json']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                run(self.out, [path], self.command('pass'), 0)
        self.assertFalse(self.out.exists())

    def test_low_space_stops_before_launch(self):
        with patch('run_verified.shutil.disk_usage') as usage, patch('run_verified.subprocess.Popen') as launch:
            usage.return_value.free = 100
            with self.assertRaisesRegex(ValueError, 'Insufficient'):
                run(self.out, ['result.bin'], self.command('pass'))
            launch.assert_not_called()
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
