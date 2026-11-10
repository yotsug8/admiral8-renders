"""Real FFmpeg regressions for interrupted and corrupted local clip caches."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import video


class ClipCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.source_tmp.name) / 'source.mkv'
        subprocess.run([video.ffmpeg_exe(), '-y', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'color=red:s=32x32:r=30:d=0.2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=0.2',
                        '-c:v', 'ffv1', '-c:a', 'pcm_s16le', str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.source_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'work'
        self.context = patch.object(video, 'WORK', self.work)
        self.context.start()
        self.addCleanup(self.context.stop)
        self.node = dict(src='file:' + self.source.as_posix(), w=32, h=32, dur=1)

    def extract(self, **options):
        return video.video_frames(dict(self.node, **options))

    def cache(self):
        return next(self.work.glob('vid_*'))

    def assert_no_staging(self):
        self.assertFalse(list(self.work.glob('.vid_*')))
        self.assertFalse(list(self.work.glob('.audio_*')))

    def test_complete_short_source_is_reused_without_ffmpeg(self):
        # Requested duration exceeds source length: six valid frames, not 30 missing ones.
        first = self.extract(audio=1)
        self.assertEqual(len(first['frames']), 6)
        with patch.object(video.subprocess, 'run', side_effect=AssertionError('cache miss')):
            self.assertEqual(self.extract(audio=1), first)
        self.assert_no_staging()

    def test_failed_extraction_never_publishes_partial_frames_and_retry_succeeds(self):
        real_run = subprocess.run

        def interrupted(args, **kw):
            if str(args[-1]).endswith('%04d.jpg'):
                Image.new('RGB', (32, 32), 'blue').save(Path(args[-1]).with_name('0001.jpg'))
                raise subprocess.CalledProcessError(1, args)
            return real_run(args, **kw)

        with patch.object(video.subprocess, 'run', side_effect=interrupted):
            with self.assertRaises(subprocess.CalledProcessError):
                self.extract()
        self.assertFalse(list(self.work.glob('vid_*')))
        self.assert_no_staging()
        self.assertEqual(len(self.extract()['frames']), 6)

    def test_missing_corrupt_or_unmarked_frames_are_rebuilt(self):
        expected = self.extract()
        cache = self.cache()
        original = (cache / '0001.jpg').read_bytes()
        for failure in ('missing', 'corrupt', 'unmarked', 'extra'):
            with self.subTest(failure=failure):
                if failure == 'missing':
                    (cache / '0002.jpg').unlink()
                elif failure == 'corrupt':
                    (cache / '0001.jpg').write_bytes(b'x' * len(original))
                elif failure == 'unmarked':
                    (cache / 'frames.json').unlink()
                else:
                    (cache / '9999.jpg').write_bytes(original)
                self.assertEqual(self.extract(), expected)
                self.assertEqual((cache / '0001.jpg').read_bytes(), original)
                self.assertFalse((cache / '9999.jpg').exists())
                self.assert_no_staging()

    def test_successful_ffmpeg_without_frames_is_rejected(self):
        # Some FFmpeg versions return success for an empty selection; emulate that contract.
        with patch.object(video.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stderr='')):
            with self.assertRaisesRegex(ValueError, 'последовательности кадров'):
                self.extract(**{'from': 2})
        self.assertFalse(list(self.work.glob('vid_*')))
        self.assert_no_staging()

    def test_interrupted_and_corrupt_audio_does_not_poison_frame_cache(self):
        expected = self.extract()
        real_run = subprocess.run

        def interrupted(args, **kw):
            if str(args[-1]).endswith('a.wav'):
                Path(args[-1]).write_bytes(b'broken WAV')
                raise subprocess.CalledProcessError(1, args)
            raise AssertionError('completed frames should be reused')

        with patch.object(video.subprocess, 'run', side_effect=interrupted):
            with self.assertRaises(subprocess.CalledProcessError):
                self.extract(audio=1)
        self.assertEqual(self.extract(), expected)
        self.assertFalse((self.cache() / 'a.wav').exists())
        self.assert_no_staging()
        sound = self.extract(audio=1)
        wav = Path(sound['wav'])
        original = wav.read_bytes()
        wav.write_bytes(b'x' * len(original))
        with patch.object(video.subprocess, 'run', wraps=real_run) as run:
            self.assertEqual(self.extract(audio=1), sound)
            self.assertEqual(run.call_count, 1)  # only audio is repaired
        self.assertEqual(wav.read_bytes(), original)
        self.assertEqual(len(list(self.work.glob('vid_*'))), 1)

    def test_invalid_dimensions_and_times_fail_before_ffmpeg(self):
        for fields in ({'w': 0}, {'h': -2}, {'dur': 0}, {'dur': float('inf')}, {'from': -1}):
            with self.subTest(fields=fields), patch.object(video.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    self.extract(**fields)
                run.assert_not_called()


class ImageReferenceTests(unittest.TestCase):
    def test_missing_empty_and_directory_are_errors_valid_file_is_uri(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(video, 'HERE', Path(tmp)):
            root = Path(tmp)
            (root / 'empty.png').touch()
            (root / 'folder').mkdir()
            for name in ('absent.png', 'empty.png', 'folder'):
                with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                    video.image_ref('file:' + name, {}, {})
            path = root / 'valid.png'
            Image.new('RGB', (2, 2), 'red').save(path)
            self.assertEqual(video.image_ref('file:valid.png', {}, {}), path.as_uri())


if __name__ == '__main__':
    unittest.main()
