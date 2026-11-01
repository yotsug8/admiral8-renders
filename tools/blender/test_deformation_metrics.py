"""Regression checks for topology versus tessellation, run inside Blender."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deformation_metrics import compare


class DeformationTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(points=[Vector(v) for v in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))],
                         edges=[(0, 1), (1, 2), (2, 3), (3, 0)], polygons=[(0, 1, 2, 3)],
                         triangles=[(0, 1, 2), (0, 2, 3)], world_matrix=[list(r) for r in Matrix.Identity(4)])
        self.args = SimpleNamespace(edge_epsilon=1e-8, area_epsilon=1e-8, growth_m=.03,
                                    stretch_ratio=2., contraction_ratio=.1, top=10)

    def test_rigid_rotation_with_changed_diagonal(self):
        changed = copy.deepcopy(self.base)
        rotation = Matrix.Rotation(math.radians(30), 3, 'Y')
        changed['points'] = [rotation @ p for p in changed['points']]
        changed['triangles'] = [(0, 1, 3), (1, 2, 3)]
        report = compare(self.base, changed, 14, self.args)
        self.assertTrue(report['evaluated_tessellation_changed'])
        self.assertFalse(report['threshold_exceeded'])
        self.assertAlmostEqual(report['min_area_ratio'], 1., places=6)

    def test_changed_polygon_still_rejected(self):
        changed = copy.deepcopy(self.base)
        changed['polygons'] = [(0, 1, 3, 2)]
        with self.assertRaises(ValueError):
            compare(self.base, changed, 0, self.args)

    def test_changed_edge_still_rejected(self):
        changed = copy.deepcopy(self.base)
        changed['edges'][0] = (0, 2)
        with self.assertRaises(ValueError):
            compare(self.base, changed, 0, self.args)

    def test_stretch_detected_despite_changed_diagonal(self):
        changed = copy.deepcopy(self.base)
        changed['points'][1].x = 4.
        changed['triangles'] = [(0, 1, 3), (1, 2, 3)]
        report = compare(self.base, changed, 0, self.args)
        self.assertTrue(report['threshold_exceeded'])
        self.assertGreater(report['stretched_edge_count'], 0)

    def test_collapsed_reference_triangle_detected(self):
        changed = copy.deepcopy(self.base)
        changed['points'][3] = Vector((.5, .5, 0))
        report = compare(self.base, changed, 0, self.args)
        self.assertTrue(report['threshold_exceeded'])
        self.assertGreater(report['contracted_triangle_count'], 0)


if __name__ == '__main__':
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(DeformationTests))
    if not result.wasSuccessful():
        raise RuntimeError('Deformation regression checks failed')
