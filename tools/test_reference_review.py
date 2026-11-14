"""Protect ending coverage and reject invalid requested observations."""
import unittest
import hashlib
from pathlib import Path
import subprocess
import tempfile

from tools.reference_review import sample_times, technical_review


class ReferenceSamplingTests(unittest.TestCase):
    def test_opening_and_closing_beat_included(self):
        times = sample_times(24, 8)
        self.assertEqual(len(times), 8)
        self.assertEqual(times[0], 0)
        self.assertAlmostEqual(times[-1], 23.9)

    def test_short_video_stays_inside_duration(self):
        self.assertTrue(all(0 <= t < .02 for t in sample_times(.02, 2)))

    def test_invalid_and_explicit_times(self):
        for times in ([-1], [float('nan')], [float('inf')], [6], []):
            with self.assertRaises(ValueError):
                sample_times(6, 12, times)
        self.assertEqual(sample_times(6, 12, [4, 0, 4, 2]), [0, 2, 4])


class TechnicalReviewTests(unittest.TestCase):
    def test_truncated_mkv_at_cluster_boundary_is_not_complete_even_with_exit_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'complete.mkv'
            subprocess.run([
                'ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                'testsrc2=size=64x64:rate=30:duration=4', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-g', '10', '-cluster_time_limit', '333', str(source)], check=True)
            raw = source.read_bytes()
            marker, offsets, cursor = bytes.fromhex('1f43b675'), [], 0
            while (cursor := raw.find(marker, cursor)) != -1:
                offsets.append(cursor)
                cursor += len(marker)
            self.assertGreater(len(offsets), 3)
            broken = root / 'truncated.mkv'
            broken.write_bytes(raw[:offsets[len(offsets) // 2]])
            report = technical_review(broken, 'truncated', root / 'review')
            self.assertEqual(report['exit_code'], 0)  # FFmpeg's misleading success is the regression.
            self.assertEqual(report['decode'], 'failed')
            self.assertLess(report['decoded_video_frames'], 120)
            self.assertTrue(report['integrity_messages'])
            self.assertTrue(report['duration_observation']['review_candidate'])
            self.assertIn('File ended prematurely', (root / 'review/decode.log').read_text())

    def test_real_decode_reports_known_black_freeze_and_audio_without_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'fixture.mkv'
            subprocess.run([
                'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=64x64:r=30:d=0.5',
                '-f', 'lavfi', '-i', 'color=black:s=64x64:r=30:d=0.5',
                '-f', 'lavfi', '-i', 'testsrc2=s=64x64:r=30:d=0.5',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.5:sample_rate=48000',
                '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
                '-map', '[v]', '-map', '3:a', '-c:v', 'ffv1', '-c:a', 'pcm_s16le',
                str(source)], check=True)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            report = technical_review(source, 'fixture', root / 'review')
            self.assertEqual(report['decode'], 'completed')
            self.assertEqual(report['decoded_video_frames'], 45)
            self.assertEqual(report['source_sha256'], digest)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            self.assertEqual(len(report['black_intervals']), 1)
            self.assertAlmostEqual(report['black_intervals'][0]['start_s'], .5, places=2)
            self.assertAlmostEqual(report['black_intervals'][0]['end_s'], 1, places=2)
            self.assertGreaterEqual(len(report['freeze_intervals']), 1)
            self.assertLess(float(report['audio_metrics']['true_peak_dbtp']), -10)
            self.assertEqual(report['audio_review'], 'not performed')
            self.assertEqual(report['artistic_review'], 'pending')
            self.assertTrue((root / 'review/decode.log').is_file())

    def test_silent_video_reports_absent_audio_and_open_freeze(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'silent.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=blue:s=32x32:r=30:d=0.5', '-c:v', 'ffv1', str(source)], check=True)
            report = technical_review(source, 'silent', root / 'review')
            self.assertEqual(report['decode'], 'completed')
            self.assertEqual(report['decoded_video_frames'], 15)
            self.assertEqual(report['audio_metrics']['status'], 'absent')
            self.assertEqual(report['freeze_intervals'][0]['end_s'], None)


if __name__ == '__main__':
    unittest.main()
