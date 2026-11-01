import unittest
import numpy as np
from post_review import levels


class LevelsTests(unittest.TestCase):
    def test_dark_and_white_are_distinguished(self):
        black = levels(np.zeros((2, 2, 3), np.uint8))
        white = levels(np.full((2, 2, 3), 255, np.uint8))
        self.assertEqual(black['dark_fraction'], 1)
        self.assertEqual(white['bright_fraction'], 1)
        self.assertEqual(white['dark_fraction'], 0)

    def test_saturated_color_is_not_white(self):
        red = np.zeros((2, 2, 3), np.uint8)
        red[..., 0] = 255
        result = levels(red)
        self.assertEqual(result['channel_limit_fraction'], 1)
        self.assertEqual(result['bright_fraction'], 0)

    def test_float_input_is_rejected(self):
        with self.assertRaises(ValueError):
            levels(np.ones((2, 2, 3)))


if __name__ == '__main__':
    unittest.main()
