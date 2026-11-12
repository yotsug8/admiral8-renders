"""Protect ending coverage and reject invalid requested observations."""
import unittest

from tools.reference_review import sample_times


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


if __name__ == '__main__':
    unittest.main()
