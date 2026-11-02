"""Real Bash/Python/ffprobe on synthetic PCM; Node with mocked Panorama API."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

HERE = Path(__file__).resolve().parent / 'dota_engine'
sys.path.insert(0, str(HERE))
from test_capture_restore import BASH


class CaptureTests(unittest.TestCase):
    def duration(self, mode, expected='1.0'):
        source = (HERE / 'record.sh').read_text(encoding='utf-8')
        block = source[source.index('py -3.11 -c "\nimport math'):source.index('\nrm -f "$OUT"/sec_')]
        probe = shutil.which('ffprobe')
        self.assertIsNotNone(probe, 'real ffprobe required')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            media = out / 'test.mp4'  # PCM WAV content: ffprobe sniffs content, not suffix.
            with wave.open(str(media), 'wb') as wav:
                wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0\0' * 48000)
            if mode == 'corrupt':
                media.write_bytes(b'not media')
            ff = out / 'ffmpeg.exe' if mode == 'missing' else Path(probe).with_name('ffmpeg.exe')
            # Remove PATH discovery so the missing-tool case is deterministic.
            script = '\n'.join([
                'set -e', "trap 'echo RESTORED' EXIT", 'export PATH=/unused',
                'py() { shift; ' + shlex.quote(Path(sys.executable).as_posix()) + ' "$@"; }',
                'FF=' + shlex.quote(ff.as_posix()), 'OUT=' + shlex.quote(out.as_posix()),
                'NAME=test', 'DUR=' + shlex.quote(expected), block, 'echo ACCEPTED'])
            return subprocess.run([BASH, '--noprofile', '--norc', '-s'], input=script,
                                  text=True, encoding='utf-8', capture_output=True,
                                  env=dict(os.environ, PYTHONIOENCODING='utf-8'), timeout=25)

    def test_duration_pcm_success(self):
        result = self.duration('valid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ACCEPTED', result.stdout)
        self.assertIn('RESTORED', result.stdout)

    def test_duration_mismatch_nan_and_probe_failure_are_fatal(self):
        for mode, expected in [('valid', '0.5'), ('valid', 'nan'), ('corrupt', '1.0')]:
            with self.subTest(mode=mode, expected=expected):
                result = self.duration(mode, expected)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('ACCEPTED', result.stdout)
                self.assertIn('RESTORED', result.stdout)

    def test_missing_probe_is_explicitly_unverified(self):
        result = self.duration('missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('длина не проверена', result.stdout)
        self.assertIn('RESTORED', result.stdout)

    def test_camera_callbacks_stop_restart_and_replace_keys(self):
        harness = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const events = {}, queue = [], applied = []; let time = 0;
const panel = {GetParent() {return this}, FindChildTraverse() {return {style:{}}}};
const context = {DotaDefaultUIElement_t: {},
 $: {GetContextPanel: () => panel, Msg() {}, Schedule: (_, f) => queue.push(f)},
 GameEvents: {Subscribe: (name, fn) => events[name] = fn}, Game: {GetGameTime: () => time},
 GameUI: {SetCameraPitchMin() {}, SetCameraPitchMax() {}, SetCameraYaw() {},
 SetCameraDistance() {}, SetCameraLookAtPositionHeightOffset() {},
 SetCameraTargetPosition: (p) => applied.push(p)}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const keys = () => events.a8_camkeys({part:0, kf:1, dur:10, keys:'0 0 0 1000 45 0 10 0 0 1000 45 0'});
keys(); events.a8_camplay({start:0}); assert.equal(applied.length, 1);
events.a8_camstop({}); const before = applied.length; queue.shift()();
assert.equal(applied.length, before); assert.equal(queue.length, 0);
events.a8_camplay({start:0}); events.a8_camplay({start:0});
const restarted = applied.length; queue.shift()(); // stale run must not reschedule
assert.equal(applied.length, restarted); assert.equal(queue.length, 1);
time = 0.5; queue.shift()(); assert.equal(applied.length, restarted + 1);
events.a8_cam({x:77, y:1, z:0, dist:1000, pitch:45, yaw:0});
const manual = applied.length; queue.shift()(); assert.equal(applied.length, manual);
assert.equal(applied[applied.length - 1][0], 77);
events.a8_camplay({start:0}); keys(); const replaced = applied.length;
queue.shift()(); assert.equal(applied.length, replaced); assert.equal(queue.length, 0);
events.a8_camplay({start:0}); time=11; queue.shift()(); assert.equal(queue.length, 0);
console.log('camera contract OK');
'''
        result = subprocess.run(['node', '-e', harness, str(HERE / 'a8_cam.js')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_server_stop_contract(self):
        # Static server side only: Dota event delivery is not simulated here.
        source = (HERE / 'addon_game_mode.lua').read_text(encoding='utf-8')
        self.assertIn('Send_ServerToAllClients("a8_camstop", {})', source)
        for command in ('a8_t', 'a8_reload', 'a8_black', 'a8_cam', 'a8_play'):
            block = source.split('Convars:RegisterCommand("' + command + '"', 1)[1].split('Convars:RegisterCommand', 1)[0]
            self.assertIn('A8_Stop()', block)
        self.assertEqual(source.count('A8_PLAY = nil'), 1)


if __name__ == '__main__':
    unittest.main()
