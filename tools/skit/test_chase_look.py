"""Fixed finishing profile: no temporal exposure adaptation or exemplar files."""
import unittest
import numpy as np
from chase_look import ChaseLook


class DaylightTests(unittest.TestCase):
    def test_black_tail_and_output_contract(self):
        look = ChaseLook(None, 'daylight')
        black = np.zeros((20, 20, 3), np.uint8)
        self.assertTrue(np.array_equal(look(black), black))
        result = look(np.full_like(black, 95))
        self.assertEqual(result.shape, black.shape)
        self.assertEqual(result.dtype, np.uint8)

    def test_grey_ramp_remains_monotone(self):
        ramp = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)[None]
        output = ChaseLook.daylight(ramp).astype(float).mean(axis=2)[0]
        self.assertGreaterEqual(np.diff(output).min(), -1.)  # integer rounding

    def test_other_frames_cannot_change_same_frame(self):
        look = ChaseLook(None, 'daylight')
        frame = np.full((20, 20, 3), 95, np.uint8)
        before = look(frame)
        look(np.full_like(frame, 230))
        self.assertTrue(np.array_equal(before, look(frame)))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            ChaseLook(None, 'unknown')


if __name__ == '__main__':
    unittest.main()
