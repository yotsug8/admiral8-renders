"""Synthetic PCM checks; no game assets, production outputs or listening."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np

import pudge_tank_sound as sound


class PudgeSoundAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pudge_audit_audio_')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.out = root / '_game/skits/pudge_tank/polish_v2'
        names = ('weapons/hero/rattletrap/attack01.wav',
                 'physics/movement/hero/gyrocopter/idle_loop.wav',
                 'weapons/creep/good/engine_attack01.wav',
                 'physics/damage/engines/dire_base_destruction_01.wav')
        self.paths = [self.out / 'audio_sources/sounds' / n for n in names]
        self.paths.append(root / '_game/sfx/step01')
        t = np.arange(3 * sound.SR) / sound.SR
        samples = (.2 * np.sin(2*np.pi*300*t) * 32767).astype('<i2')
        self.samples = samples
        for path in self.paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(sound.SR)
                wav.writeframes(samples.tobytes())
        fake_file = root / 'tools/skit/pudge_tank_sound.py'
        self.root_patch = patch.object(sound, '__file__', str(fake_file))
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)

    def test_reject_empty_silent_nonfinite_and_single_sample(self):
        for values in ([], [0.] * 2000, [float('nan')] * 2000,
                       [float('inf')] * 2000, [.2]):
            with self.subTest(sample_count=len(values), first=values[:1]):
                raw = np.asarray(values, dtype=np.float32).tobytes()
                with patch.object(sound, 'ff', return_value=SimpleNamespace(stdout=raw)):
                    with patch.object(sound, 'encode', side_effect=AssertionError('Invalid cue reached encoding')):
                        with self.assertRaisesRegex(ValueError, 'Invalid|Silent|short'):
                            sound.build(self.out)
                self.assertFalse((self.out / 'sound_qa.json').exists())

    def test_six_cues_real_ffmpeg_and_silence(self):
        # A quiet but nonzero recording is valid even below the trim threshold.
        for scale in (1., .001):
            with self.subTest(source_scale=scale):
                for source in self.paths:
                    with wave.open(str(source), 'wb') as wav:
                        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(sound.SR)
                        wav.writeframes((self.samples * scale).astype('<i2').tobytes())
                path, report = sound.build(self.out)
                samples = sound.decode(path)
                self.assertEqual(samples.shape, (480000, 2))
                self.assertTrue(np.isfinite(samples).all())
                self.assertEqual(len(report['cues']), 6)
                self.assertEqual(report['max_simultaneous_cues'], 1)
                self.assertFalse(report['audio_heard'])
                self.assertTrue(all(np.isfinite(v) for v in report['meter'].values()))
                self.assertTrue(all(row['peak'] < 1e-7 for row in report['silent_intervals']))
                self.assertEqual(json.loads((self.out / 'sound_qa.json').read_text()), report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
