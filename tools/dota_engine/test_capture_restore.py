"""Run the real capture snapshot/trap blocks in Bash with a fake console.

No game, network, settings changes or rendering. Does not certify live delivery
if the game quits before restoration. Run with Python and Git Bash installed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


HERE = Path(__file__).resolve().parent
BASH = (os.environ.get('GIT_BASH') or
        str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe')
        if os.name == 'nt' else shutil.which('bash'))
VALUES = dict(dota_camera_edgemove='1', dota_camera_disable_zoom='0',
              fps_max='144', dota_hud_healthbars='1', r_depth_of_field='0',
              host_framerate='0.025', fog_override_enable='1', fog_enable='1',
              r_farz='-1')


class RestoreTests(unittest.TestCase):
    def run_block(self, name, missing='', ending='exit 0'):
        source = (HERE / name).read_text(encoding='utf-8')
        marker = '\nC "dota_camera' if name == 'record.sh' else '\nC "dota_hud'
        block = source[source.index('get() {'):source.index(marker)]
        # Execute the script's actual capture/parsing/EXIT handler, not a copy.
        cases = '\n'.join(f'{k}) printf \'%s = %s\\n\' "$4" \'{v}\';;'
                          for k, v in VALUES.items())
        script = '''set -e
HERE=unused
py() {
  [ "$4" != "$MISSING" ] || return 0
  case "$4" in
''' + cases + '''
  *) return 2;;
  esac
}
C() { printf 'RESTORE %s\n' "$@"; }
''' + block + '\n' + ending + '\n'
        # stdin avoids generating temporary shell files or touching game paths.
        return subprocess.run([BASH, '--noprofile', '--norc', '-s'], input=script,
                              env=dict(os.environ, MISSING=missing),
                              capture_output=True, text=True, encoding='utf-8')

    def test_restore_exact_nondefault_values_on_success_failure_and_signal(self):
        for name in ('record.sh', 'shots.sh'):
            expected = VALUES if name == 'record.sh' else {
                k: VALUES[k] for k in ('dota_camera_edgemove',
                                      'dota_camera_disable_zoom',
                                      'dota_hud_healthbars', 'r_depth_of_field')}
            for ending, code in [('exit 0', 0), ('false', 1),
                                 ('kill -TERM $$', 143), ('kill -INT $$', 130)]:
                with self.subTest(name=name, ending=ending):
                    result = self.run_block(name, ending=ending)
                    self.assertEqual(result.returncode, code, result.stderr)
                    restored = dict(line.removeprefix('RESTORE ').split(' ', 1)
                                    for line in result.stdout.splitlines()
                                    if line.startswith('RESTORE '))
                    self.assertEqual(restored, expected)

    def test_missing_snapshot_aborts_without_setting_any_variable(self):
        for name in ('record.sh', 'shots.sh'):
            names = VALUES if name == 'record.sh' else (
                'dota_camera_edgemove', 'dota_camera_disable_zoom',
                'dota_hud_healthbars', 'r_depth_of_field')
            for missing in names:
                with self.subTest(name=name, missing=missing):
                    result = self.run_block(name, missing)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertNotIn('RESTORE ', result.stdout)


if __name__ == '__main__':
    unittest.main()
