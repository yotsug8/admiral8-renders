"""Offline production regressions: synthetic inputs, real FFmpeg/ffprobe, no TTS/game."""
import contextlib
import copy
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import grade
from chase_look import ChaseLook
import assemble_study
import study
import voices
import video

FF = imageio_ffmpeg.get_ffmpeg_exe()


class Output(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


def target(light=1):
    return dict(L=[float(x * light) for x in grade.PCT], C=[12., 25., 15.], b_mid=3., n=1)


def wav(path, duration, channels=1):
    t = np.arange(round(duration * 48000)) / 48000
    a = (np.sin(t * 2 * np.pi * 440) * 8000).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(np.repeat(a[:, None], channels, axis=1).tobytes())


def fixture(path, fps=15, frames=15, audio_duration=None):
    command = [FF, '-v', 'error', '-y', '-f', 'lavfi', '-i',
               f'testsrc2=size=64x96:rate={fps}:duration={float(frames/Fraction(fps)):.12g}']
    if audio_duration is not None:
        command += ['-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={audio_duration}',
                    '-c:a', 'aac']
    subprocess.run(command + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)


def streams(path):
    result = subprocess.run([os.environ.get('FFPROBE') or shutil.which('ffprobe'),
                            '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                           capture_output=True, text=True, check=True)
    return json.loads(result.stdout)['streams']


class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (os.environ.get('FFPROBE') or shutil.which('ffprobe')):
            raise RuntimeError('These regressions require ffprobe; no silent skip')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='audit-production-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / 'target.json'
        self.target.write_text(json.dumps(target()), encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch.object(grade, 'TARGET', str(self.target)).start()
        patch.object(socket, 'create_connection', side_effect=AssertionError('Network forbidden')).start()
        patch.dict(os.environ, {'GRADE': '', 'SUBS': '', 'PYTHONDONTWRITEBYTECODE': '1'}).start()

    def main(self, module, args):
        out = Output()
        with patch.object(sys, 'argv', [module.__file__, *map(str, args)]), contextlib.redirect_stdout(out):
            module.main()
        return out.getvalue()

    def mix(self, source, result, duration, *, capture_times=None, broken_voice=False):
        scene = self.root / 'scene.json'
        scene.write_text(json.dumps(dict(dur=duration, fps=30, voices={'line': ['actor', 0]},
                                         actors={}, fx=[])), encoding='utf-8')
        (self.root/'voices.json').write_text('{}', encoding='utf-8')
        if broken_voice:
            (self.root/'line.wav').write_bytes(b'not a wav')
        else:
            wav(self.root/'line.wav', duration)
        output = Output()
        original = grade.transcode
        def traced(src, dst, transform, **kwargs):
            if capture_times is not None:
                def overlay(seconds):
                    capture_times.append(seconds)
                    return None
                transform.__globals__['overlay'] = overlay
            return original(src, dst, transform, **kwargs)
        with patch.object(sys, 'argv', ['mix.py', str(source), str(result), str(scene)]), \
                patch.object(grade, 'transcode', traced), contextlib.redirect_stdout(output):
            runpy.run_path(str(HERE/'mix.py'), run_name='__main__')
        return output.getvalue()

    def test_study_out_is_output_not_an_input(self):
        source = self.root/'input.mp4'; fixture(source)
        out = self.root/'new-output'
        self.main(study, [source, '--out', out])
        rows = json.loads((out/'metrics.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['dur'], 1.)
        self.assertTrue((out/'input_sheet.jpg').is_file())
        # Existing output containing invalid MP4 must never be consumed as input.
        (out/'not-an-input.mp4').write_bytes(b'invalid')
        self.main(study, ['--out', out, source])
        self.assertEqual(len(json.loads((out/'metrics.json').read_text(encoding='utf-8'))), 1)

    def test_grade_preserves_integer_and_fractional_cadence(self):
        for fps, count in [(15, 15), (30, 30), (60, 30), ('30000/1001', 30)]:
            with self.subTest(fps=fps):
                source, out = self.root/'in.mp4', self.root/'out.mp4'
                fixture(source, fps, count)
                before = grade.video_timing(source)
                self.main(grade, [source, out])
                self.assertEqual(grade.video_timing(out), before)

    def test_grade_trims_long_audio_to_picture_duration(self):
        source, out = self.root/'in.mp4', self.root/'out.mp4'
        fixture(source, audio_duration=2)
        self.main(grade, [source, out])
        audio = next(s for s in streams(out) if s['codec_type'] == 'audio')
        self.assertLess(abs(float(audio['duration']) - 1), .025)
        self.assertEqual(grade.video_timing(out)['count'], 15)

    def test_mix_real_fps_subtitle_seconds_and_audio_duration(self):
        for fps, count in [(15, 15), (30, 30), ('30000/1001', 30)]:
            with self.subTest(fps=fps):
                source, out = self.root/'in.mp4', self.root/'out.mp4'
                fixture(source, fps, count)
                duration = float(count / Fraction(fps)); times = []
                with patch.dict(os.environ, {'GRADE': 'match' if fps == 30 else ''}):
                    self.mix(source, out, duration, capture_times=times)
                self.assertEqual(grade.video_timing(out), grade.video_timing(source))
                self.assertEqual(len(times), count)
                self.assertAlmostEqual(times[-1], float((count-1)/Fraction(fps)), places=10)
                audio = next(s for s in streams(out) if s['codec_type'] == 'audio')
                self.assertLess(abs(float(audio['duration']) - duration), .025)
                pcm = subprocess.run([FF, '-v', 'error', '-i', str(out), '-vn', '-ac', '1',
                                      '-ar', '48000', '-f', 'f32le', '-'], capture_output=True, check=True).stdout
                samples = np.frombuffer(pcm, np.float32)
                peak = np.argmax(abs(np.fft.rfft(samples))) * 48000 / len(samples)
                self.assertAlmostEqual(peak, 440, delta=2)
                with wave.open(str(self.root/'mix.wav')) as w:
                    self.assertLessEqual(abs(w.getnframes()/w.getframerate()-duration), 1/48000)

    def test_mix_refuses_scene_duration_mismatch_and_broken_voice(self):
        source, out = self.root/'in.mp4', self.root/'out.mp4'; fixture(source)
        with self.assertRaisesRegex(ValueError, 'Scene duration'):
            self.mix(source, out, 2)
        self.assertFalse(out.exists())
        with self.assertRaises(subprocess.CalledProcessError):
            self.mix(source, out, 1, broken_voice=True)
        self.assertFalse(out.exists())

    def test_vfr_rejected_without_changing_existing_output(self):
        source, out = self.root/'vfr.mp4', self.root/'old.mp4'
        subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'testsrc2=size=64x96:rate=30:duration=1', '-vf',
            "setpts='if(lt(N,15),N,15+(N-15)*2)/(30*TB)'", '-fps_mode', 'vfr',
            '-c:v', 'libx264', str(source)], check=True)
        out.write_bytes(b'previous result')
        with self.assertRaisesRegex(ValueError, 'Variable video timestamps'):
            self.main(grade, [source, out])
        self.assertEqual(out.read_bytes(), b'previous result')

    def test_real_encoder_failure_and_transform_exception_preserve_output(self):
        source = self.root/'in.mp4'; fixture(source)
        # Unknown output muxer gives a real FFmpeg nonzero exit (or broken pipe).
        out = self.root/'old.unsupported'; out.write_bytes(b'previous result')
        with self.assertRaises((subprocess.CalledProcessError, BrokenPipeError)):
            grade.transcode(source, out, lambda frame, t: frame)
        self.assertEqual(out.read_bytes(), b'previous result')
        out = self.root/'old.mp4'; out.write_bytes(b'previous result')
        with self.assertRaisesRegex(RuntimeError, 'transform failed'):
            grade.transcode(source, out, Mock(side_effect=RuntimeError('transform failed')))
        self.assertEqual(out.read_bytes(), b'previous result')
        self.assertFalse(list(self.root.glob('.grade-*')))

    def test_real_decoder_error_and_missing_frame_are_not_success(self):
        source, out = self.root/'in.mp4', self.root/'out.mp4'; fixture(source)
        timing = grade.video_timing(source)
        source.write_bytes(b'broken after probe')
        with self.assertRaises(subprocess.CalledProcessError):
            grade.transcode(source, out, lambda frame, t: frame, timing=timing)
        fixture(source, frames=14)
        with self.assertRaisesRegex(ValueError, 'frame count changed'):
            grade.transcode(source, out, lambda frame, t: frame, timing=timing)
        self.assertFalse(out.exists())

    def test_voice_cache_updates_metadata_without_any_backend(self):
        line = dict(name='line', who='old', text='{старое|тот же текст}', voice={})
        with patch.dict(os.environ, {'SKIT_FAKE': '1'}):
            old = voices.make(str(self.root), [line])['line']
            before = (self.root/'line.wav').read_bytes()
            changed = dict(line, who='new', text='{новое|тот же текст}')
            with contextlib.ExitStack() as stack:
                for name in ('_fake', '_fish', '_fishref', '_edge', '_sapi', '_game', 'heard'):
                    stack.enter_context(patch.object(voices, name, side_effect=AssertionError(name)))
                new = voices.make(str(self.root), [changed])['line']
            self.assertEqual((new['text'], new['who']), ('новое', 'new'))
            for k in ('key', 'dur', 'env', 'say', 'voice'):
                self.assertEqual(new[k], old[k])
            self.assertEqual((self.root/'line.wav').read_bytes(), before)
            self.assertEqual(json.loads((self.root/'voices.json').read_text(encoding='utf-8'))['line'], new)

    def test_registry_only_fish_reaches_backend_and_restores_cached_key(self):
        registry = types.SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=Mock(), QueryValueEx=Mock(return_value=('fake-test-key', 1)))
        handle = contextlib.nullcontext(object()); registry.OpenKey.return_value = handle
        previous = video.FISH_KEY
        with patch.dict(os.environ, {'FISH_API_KEY': '', 'SKIT_FAKE': ''}), \
                patch.dict(sys.modules, {'winreg': registry}), patch.object(voices.os, 'name', 'nt'):
            self.assertEqual(voices.engine(), 'fish')
            def backend(*args, **kwargs):
                self.assertEqual(video.FISH_KEY, 'fake-test-key')
            with patch.object(video, 'tts_fish', side_effect=backend):
                voices._fish('text', 'voice', 'unused')
            self.assertEqual(video.FISH_KEY, previous)
            with patch.object(video, 'tts_fish', side_effect=RuntimeError('backend failed')):
                with self.assertRaises(RuntimeError):
                    voices._fish('text', 'voice', 'unused')
            self.assertEqual(video.FISH_KEY, previous)
        with patch.dict(os.environ, {'SKIT_FAKE': '1'}), patch.object(voices, 'fish_key', side_effect=AssertionError):
            self.assertEqual(voices.engine(), 'fake')

    def test_pinned_legacy_is_independent_of_target_and_samples(self):
        rgb = np.random.default_rng(7).integers(0, 256, (2, 20, 20, 3), dtype=np.uint8)
        look = ChaseLook(rgb); snapshot = look.snapshot(); expected = look(rgb[0])
        self.target.write_text(json.dumps(target(.5)), encoding='utf-8')
        with patch.object(grade, 'target', side_effect=AssertionError('No exemplar access')):
            restored = ChaseLook(None, snapshot=json.loads(json.dumps(snapshot)))
        np.testing.assert_array_equal(restored(rgb[0]), expected)
        self.assertEqual(snapshot, restored.snapshot())
        broken = copy.deepcopy(snapshot); broken['state']['grade']['state']['lut'][10] += .1
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            ChaseLook(None, snapshot=broken)
        broken = copy.deepcopy(snapshot); broken['state']['implementation']['numpy'] = 'different'
        broken['sha256'] = grade.data_hash(broken['state'])
        with self.assertRaisesRegex(ValueError, 'implementation'):
            ChaseLook(None, snapshot=broken)
        with patch.object(grade, 'Grade', side_effect=AssertionError):
            daylight = ChaseLook(None, 'daylight')
            self.assertIsNone(daylight.snapshot()['state']['grade'])

    def recipe(self):
        frames = self.root/'input'; frames.mkdir()
        for i in range(3):
            Image.fromarray(np.full((64, 36, 3), [75 + 15*i, 100, 120], np.uint8)).save(frames/f'f{i:04d}.png')
        with wave.open(str(self.root/'silence.wav'), 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(bytes(48000 * 4))
        recipe = dict(fps=10, picture_frames=3, duration=1., size=[36, 64], audio='silence.wav',
                      look_samples=[0, 1, 2], look_target='target.json',
                      look_target_sha256=hashlib.sha256(self.target.read_bytes()).hexdigest(),
                      ranges=[dict(start=0, stop=3, folder='input')], silent_check=[.5, .9])
        path = self.root/'recipe.json'; path.write_text(json.dumps(recipe), encoding='utf-8')
        return path

    def test_assembly_frozen_recipe_repeats_real_png_and_mp4_after_target_changes(self):
        recipe = self.recipe(); first, second = self.root/'first', self.root/'second'
        self.main(assemble_study, [recipe, '--assets', self.root, '--out', first])
        report = json.loads((first/'assembly_report.json').read_text())
        pin = report['look_snapshot']
        self.assertEqual(report['look_target_file_sha256'], hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(pin['state']['grade']['state']['target_sha256'], grade.data_hash(target()))
        self.assertEqual(len(pin['state']['grade']['state']['lut']), 401)
        self.target.write_text('broken mutable target', encoding='utf-8')
        self.main(assemble_study, [first/'recipe_frozen.json', '--assets', self.root, '--out', second])
        for name in ['frames/f0000.png', 'frames/f0001.png', 'frames/f0002.png', 'kunkka_hoodwink_chase.mp4']:
            self.assertEqual((first/name).read_bytes(), (second/name).read_bytes(), name)

    def test_assembly_rejects_changed_explicit_target_before_output(self):
        recipe = self.recipe(); out = self.root/'out'
        self.target.write_text(json.dumps(target(.5)), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'target hash mismatch'):
            self.main(assemble_study, [recipe, '--assets', self.root, '--out', out, '--validate-only'])
        self.assertFalse(out.exists())

    def test_old_recipe_defaults_and_snapshot_file_keep_same_frames(self):
        path = self.recipe(); recipe = json.loads(path.read_text())
        recipe.pop('look_target'); recipe.pop('look_target_sha256')
        path.write_text(json.dumps(recipe), encoding='utf-8')
        first, second = self.root/'first', self.root/'second'
        self.main(assemble_study, [path, '--assets', self.root, '--out', first])
        report = json.loads((first/'assembly_report.json').read_text())
        self.assertIsNone(report['look_target_file_sha256'])
        self.assertEqual(report['look_snapshot']['state']['grade']['state']['target'], target())
        recipe['look_snapshot'] = 'first/look_snapshot.json'
        path.write_text(json.dumps(recipe), encoding='utf-8')
        self.target.write_text('no longer readable JSON', encoding='utf-8')
        self.main(assemble_study, [path, '--assets', self.root, '--out', second])
        self.assertEqual((first/'frames/f0001.png').read_bytes(), (second/'frames/f0001.png').read_bytes())


if __name__ == '__main__':
    unittest.main()
