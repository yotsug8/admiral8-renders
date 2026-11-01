"""Real concurrent render/spawn regression and isolation of audition scratch files."""
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import video


def _speech_worker(root, target, start, counter):
    video.HERE = Path(root)
    video.FISH_KEY = 'offline-test'
    for key in ('FV_SILENT', 'FV_FAKE_TTS'):
        os.environ.pop(key, None)

    def synthesize(text, path, voice, align):
        with counter.get_lock():
            counter.value += 1
        time.sleep(.15)
        Path(path).write_bytes((Path(root) / 'voice.mp3').read_bytes())

    if not start.wait(10):
        raise RuntimeError('speech barrier timed out')
    with patch.object(video, 'tts_fish', side_effect=synthesize), \
            patch.object(video, 'align_words', return_value=[('Тест', 0, .2)]):
        video.speak('Тест', Path(target))


def _render_worker(root, name, color, frequency, ready, release):
    root = Path(root)
    video.WORK = root / 'shared'
    os.environ.update(FV_SILENT='1', FV_WORKERS='1', FV_QA_DIR=str(root / 'frames'))
    for key in ('FV_DRAFT', 'FV_QA_ONLY', 'FV_FAKE_TTS', 'FV_BADGE'):
        os.environ.pop(key, None)
    original_prepare = video.prepare

    def prepare(ep, heroes, items, work_dir):
        ready.put(str(work_dir))
        if not release.wait(20):
            raise RuntimeError('render overlap barrier timed out')
        segs, _ = original_prepare(ep, heroes, items, work_dir)
        segs[0]['dur'] = .3
        segs[0]['_pcm'] = .25 * np.sin(2 * np.pi * frequency * np.arange(round(.3 * video.SR)) / video.SR)
        return segs, .3

    episode = {'parts': [{'voice': 'Проверка.', 'scene': {'camera': False, 'bg': {'color': color}, 'items': []}}]}
    with patch.object(video, 'load_consts', return_value={}), patch.object(video, 'prepare', prepare):
        video.render(episode, root / 'out' / (name + '.mp4'))


class RenderIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'shared'
        context = patch.object(video, 'WORK', self.work)
        context.start()
        self.addCleanup(context.stop)
        self.processes = []
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        for process in self.processes:
            if process.is_alive():
                process.kill()
            process.join(10)
            process.close()

    def assert_scratch_clean(self):
        self.assertEqual(list((self.work / 'runs').glob('*')), [])

    def test_two_real_renders_keep_video_audio_covers_and_qa_separate(self):
        context = multiprocessing.get_context('spawn')
        ready, release = context.Queue(), context.Event()
        self.addCleanup(ready.close)
        cases = [('red', '#e02020', 440), ('blue', '#2020e0', 880)]
        for name, color, frequency in cases:
            worker = context.Process(target=_render_worker, args=(str(self.root), name, color, frequency, ready, release))
            worker.start()
            self.processes.append(worker)
        dirs = [Path(ready.get(timeout=20)), Path(ready.get(timeout=20))]
        self.assertNotEqual(*dirs)
        self.assertTrue(all(p.is_dir() for p in dirs))  # both renders are alive before either proceeds
        release.set()
        for worker in self.processes:
            worker.join(60)
            self.assertFalse(worker.is_alive())
            self.assertEqual(worker.exitcode, 0)
        qa_dirs = []
        for name, _, frequency in cases:
            target = self.root / 'out' / (name + '.mp4')
            with Image.open(target.with_name('cover_' + name + '.png')) as image:
                pixel = image.convert('RGB').getpixel((100, 1000))
            channel = 0 if name == 'red' else 2
            self.assertGreater(pixel[channel], max(pixel[i] for i in range(3) if i != channel) + 80)
            raw = video.subprocess.run([video.ffmpeg_exe(), '-loglevel', 'error', '-i', str(target),
                                        '-frames:v', '1', '-vf', 'scale=1:1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                       capture_output=True, check=True).stdout
            self.assertGreater(raw[channel], max(raw[i] for i in range(3) if i != channel) + 60)
            pcm = video.mp3_to_pcm(target)
            spectrum = np.abs(np.fft.rfft(pcm * np.hanning(len(pcm))))
            peak = np.argmax(spectrum) * video.SR / len(pcm)
            self.assertAlmostEqual(peak, frequency, delta=8)
            report = json.loads(target.with_name('qa_' + name + '.json').read_text(encoding='utf-8'))
            self.assertEqual(report['expected_frames'], report['actual_frames'])
            directory = Path(report['frames_dir'])
            self.assertEqual(len(list(directory.glob('frame_*.jpg'))), len(report['actual_frames']))
            qa_dirs.append(directory)
        self.assertNotEqual(*qa_dirs)
        self.assertFalse((self.work / 'cover.png').exists())  # spawn workers must not use module-global WORK
        self.assert_scratch_clean()

    def test_output_lock_covers_sidecar_collisions_before_any_render(self):
        target = self.root / 'out' / 'facts_sample.mp4'
        with video._output_lock(target):
            for other in (target, target.with_suffix('.mov'), target.with_name('sample.mp4')):
                with self.subTest(output=other.name), patch.object(video, '_render') as renderer:
                    with self.assertRaises(RuntimeError):
                        video.render({}, other)
                    renderer.assert_not_called()
        with video._output_lock(target):
            pass

    @unittest.skipUnless(os.name == 'nt', 'Windows path aliases')
    def test_windows_extended_path_uses_the_same_output_lock(self):
        target = self.root / 'same.mp4'
        extended = Path('\\\\?\\' + str(target.absolute()))
        self.assertEqual(video._output_identity(target), video._output_identity(extended))
        with video._output_lock(target), self.assertRaises(RuntimeError):
            with video._output_lock(extended):
                pass

    def test_concurrent_speech_requests_build_paid_cache_only_once(self):
        source = self.root / 'voice.mp3'
        video.subprocess.run([video.ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'lavfi',
                              '-i', 'sine=frequency=440:duration=0.2', str(source)], check=True)
        context = multiprocessing.get_context('spawn')
        start, count = context.Event(), context.Value('i', 0)
        outputs = [self.root / 'first.mp3', self.root / 'second.mp3']
        for output in outputs:
            worker = context.Process(target=_speech_worker, args=(str(self.root), str(output), start, count))
            worker.start()
            self.processes.append(worker)
        start.set()
        for worker in self.processes:
            worker.join(15)
            self.assertFalse(worker.is_alive())
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(count.value, 1)
        self.assertTrue(all(p.read_bytes() == source.read_bytes() for p in outputs))

    def test_failed_render_preserves_previous_result_and_cleans_only_own_scratch(self):
        target = self.root / 'existing.mp4'
        target.write_bytes(b'previous complete video')
        sibling = self.work / 'runs' / 'another-active-render'
        sibling.mkdir(parents=True)
        (sibling / 'v0.mp3').write_bytes(b'other voice')
        before = video.FISH_TEMP, video.FISH_SPEED

        def failed(ep, out, consts, work):
            video.apply_voice_settings({'fish_temp': .01, 'fish_speed': .5})
            (work / 'video.mp4').write_bytes(b'partial')
            raise RuntimeError('render failed')

        with patch.object(video, '_render', side_effect=failed), self.assertRaisesRegex(RuntimeError, 'render failed'):
            video.render({}, target)
        self.assertEqual(target.read_bytes(), b'previous complete video')
        self.assertEqual((sibling / 'v0.mp3').read_bytes(), b'other voice')
        self.assertEqual(list((self.work / 'runs').iterdir()), [sibling])
        self.assertEqual((video.FISH_TEMP, video.FISH_SPEED), before)

    def test_audition_failure_restores_badge_and_keeps_other_files(self):
        episode = self.root / 'episode.json'
        episode.write_text(json.dumps({'parts': [{'voice': 'test'}]}), encoding='utf-8')
        self.work.mkdir()
        voice = self.work / 'v0.mp3'
        voice.write_bytes(b'belongs to an older render')
        output = self.root / 'out'
        output.mkdir()
        existing = output / 'aud_1.mp4'
        existing.write_bytes(b'not an audition temporary')
        with patch.dict(os.environ, {'FV_BADGE': 'original'}), \
                patch.object(video, 'render', side_effect=RuntimeError('failed')), \
                self.assertRaisesRegex(RuntimeError, 'failed'):
            try:
                video.audition(episode, 'voice:name', output)
            finally:
                self.assertEqual(os.environ['FV_BADGE'], 'original')
        self.assertEqual(voice.read_bytes(), b'belongs to an older render')
        self.assertEqual(existing.read_bytes(), b'not an audition temporary')
        self.assert_scratch_clean()


if __name__ == '__main__':
    unittest.main()
