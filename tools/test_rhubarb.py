"""Cue validation and an optional real CPU silence check; no network or GPU."""
import json
from pathlib import Path
import tempfile
import unittest
import wave

from tools.skit.rhubarb import generate, validate_cues, RESOURCES


class CueValidationTests(unittest.TestCase):
    def test_rejects_missing_tail_overlap_unknown_shape_and_nonfinite_time(self):
        for cues in [[], [{'start': 0, 'end': .5, 'value': 'X'}],
                     [{'start': 0, 'end': 1, 'value': 'invalid'}],
                     [{'start': float('nan'), 'end': 1, 'value': 'X'}],
                     [{'start': 0, 'end': .6, 'value': 'X'},
                      {'start': .5, 'end': 1, 'value': 'A'}]]:
            with self.subTest(cues=cues), self.assertRaises(ValueError):
                validate_cues({'metadata': {'duration': 1}, 'mouthCues': cues})

    @unittest.skipUnless((RESOURCES / 'runtime/rhubarb-1.14.0/release.zip').is_file(),
                         'Optional Rhubarb runtime not installed')
    def test_real_silence_cyrillic_path_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'кириллица'
            folder.mkdir()
            source, target = folder / 'тишина.wav', folder / 'рот.json'
            with wave.open(str(source), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b'\x00\x00' * 16000)
            generate(source, target)
            result = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(result['mouthCues'], [{'start': 0, 'end': 1, 'value': 'X'}])
            self.assertEqual(result['provenance']['face_mapping'], 'not performed')
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                generate(source, target)
            self.assertEqual(target.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
