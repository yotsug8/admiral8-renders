"""Numerical stage/map contracts, independent of Dota and rendered appearance."""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

HERE = Path(__file__).resolve().parent / 'dota_engine'
sys.path.insert(0, str(HERE))
from stage import Stage
from ground_map import Ground


class GeometryTests(unittest.TestCase):
    def stage(self, ground=None):
        return Stage(lambda t: (0, 0, 0, 1400, 45, 0), 0.2, ground=ground,
                     max_h=10, safe_x=10, safe_y=10, max_over=1)

    def test_world_height_can_remove_and_reveal_contact(self):
        g = Ground.__new__(Ground)
        g.h = lambda x, y: x * 30
        g.blocked = lambda *args: 0
        g.building = lambda *args: None
        st = self.stage(g)
        for name, x, z in [('a', 0, 0), ('b', 10, 0)]:
            st.actor(name, [], lambda t, pts: (*pts[0], 0, 0, 0), [], world=[(x, 0)], z=z)
        with patch.object(st, 'cam_blocked', return_value=None):
            self.assertNotIn(('касание', ('a', 'b')), st.problems())
            st.actors['a']['z'] = 300
            self.assertIn(('касание', ('a', 'b')), st.problems())
        st.ground = None
        self.assertNotIn(('касание', ('a', 'b')), st.problems())

    def test_coincident_movable_anchors_are_separated(self):
        st = self.stage()
        for name in ('a', 'b'):
            st.actor(name, [(0, 0.4)], lambda t, pts: (*pts[0], 0, 0, 0), [])
        self.assertIn(('касание', ('a', 'b')), st.problems())
        st.solve(rounds=100)
        self.assertFalse(st.problems())
        self.assertGreater(st.actors['a']['anchors'][0][0], 0)
        self.assertLess(st.actors['b']['anchors'][0][0], 0)

    def test_ground_edges_clamp_height_and_block_outside(self):
        g = Ground.__new__(Ground)
        g.H = np.array([[0., 10., 20.], [30., 40., 50.], [60., 70., 80.]])
        g.N = np.zeros((3, 3), dtype=int)
        g.S, g.R = 10, 10
        self.assertEqual(g.h(-5, 5), 20)
        for x, y, expected in [(-100, 100, 0), (100, 100, 20), (-100, -100, 60),
                                (100, -100, 80), (-100, 0, 30), (100, 0, 50),
                                (0, 100, 10), (0, -100, 70)]:
            self.assertEqual(g.h(x, y), expected)
            self.assertEqual(g.code(x, y), 1)
        for x, y in [(-10, 10), (10, -10), (10, 10), (-10, -10)]:
            self.assertEqual(g.code(x, y), 0)
        for x, y in [(-10.01, 0), (10.01, 0), (0, 10.01), (0, -10.01)]:
            self.assertEqual(g.code(x, y), 1)

    def test_water_full_empty_and_edge_masks(self):
        source = (HERE / 'water_map.py').read_text(encoding='utf-8')
        # Execute the actual erosion block; no world assets, no duplicated algorithm.
        block = source[source.index('dist=np.zeros'):source.index('ys,xs=')]
        code = compile(ast.parse(block), str(HERE / 'water_map.py'), 'exec')
        for shape in [(1, 1), (1, 5), (5, 1), (5, 5), (4, 6)]:
            ns = {'np': np, 'a': np.ones(shape, dtype=bool)}
            exec(code, ns)
            expected = np.fromfunction(lambda i, j: np.minimum(np.minimum(i + 1, shape[0] - i), np.minimum(j + 1, shape[1] - j)), shape)
            np.testing.assert_array_equal(ns['dist'], expected)
        for mask in [np.zeros((3, 3), bool), np.eye(3, dtype=bool)]:
            ns = {'np': np, 'a': mask}
            exec(code, ns)
            np.testing.assert_array_equal(ns['dist'], mask.astype(int))


if __name__ == '__main__':
    unittest.main()
