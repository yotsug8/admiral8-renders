"""Two real processes cannot enter the shared QA directory concurrently."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check import exclusive_check


class CheckLockTests(unittest.TestCase):
    def test_second_process_refused_then_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'check.lock')
            command = [sys.executable, '-c',
                       'import sys; from check import exclusive_check\nwith exclusive_check(sys.argv[1]): print("acquired")', path]
            with exclusive_check(path):
                second = subprocess.run(command, cwd=Path(__file__).parent, capture_output=True, text=True)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn('Check lock unavailable', second.stderr)
            third = subprocess.run(command, cwd=Path(__file__).parent, capture_output=True, text=True)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertIn('acquired', third.stdout)

    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'check.lock')
            with self.assertRaises(ValueError):
                with exclusive_check(path):
                    raise ValueError('simulated check failure')
            with exclusive_check(path):
                pass


if __name__ == '__main__':
    unittest.main()
