"""CPU regressions for run() sampling/history; Blender geometry is stubbed.

Run: py -3.11 tools/blender/test_shot_continuity.py
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load_audit():
    spec = importlib.util.spec_from_file_location(
        'shot_continuity_under_test', Path(__file__).with_name('shot_continuity.py'))
    module = importlib.util.module_from_spec(spec)
    # Do not require Blender, or replace modules globally for other tests.
    with patch.dict(sys.modules, {
        'bpy': SimpleNamespace(),
        'mathutils': SimpleNamespace(Vector=None, Quaternion=None),
        'camera_audit': SimpleNamespace(LIMITATIONS=[]),
    }), patch.object(sys, 'path', sys.path.copy()):
        spec.loader.exec_module(module)
    return module


class ProjectionSamplingTests(unittest.TestCase):
    def audit(self, shots, centers, step=30, threshold=.01):
        audit = load_audit()
        camera = SimpleNamespace(name='same_camera', matrix_world=None,
            data=SimpleNamespace(type='PERSP', lens=50., ortho_scale=1.))
        camera.evaluated_get = lambda graph: camera
        root = SimpleNamespace(matrix_world=None)
        root.evaluated_get = lambda graph: root
        scene = SimpleNamespace(render=SimpleNamespace(fps=30, fps_base=1),
            frame_start=0, frame_end=shots[-1][1]-1, frame_current=7,
            frame_subframe=.25, camera=camera, objects=[])

        def frame_set(frame, subframe=0.):
            scene.frame_current, scene.frame_subframe = frame, subframe

        scene.frame_set = frame_set
        calls = []

        def project(scene, args):
            calls.append((args.start, args.actor))
            center = centers(args.start, args.actor)
            return dict(frames=[dict(center_uv=center, surface_vertices=10,
                                    clipped_bbox_area=.1)])

        audit.surface.actor_root = lambda scene, actor: root
        audit.surface.audit = project
        audit.state = lambda matrix: {}
        audit.delta = lambda a, b: dict(distance=0., angle_deg=0., scale_delta=0.)
        audit.scenery_probe = lambda *args: [dict(kind='scenery')]
        audit.cut_directions = lambda *args: []
        with tempfile.TemporaryDirectory() as directory:
            storyboard = Path(directory)/'story.json'
            storyboard.write_text(json.dumps(dict(fps=30, shots=[
                dict(start=start/30, end=end/30, kind='test', actors=['a', 'b'])
                for start, end in shots])), encoding='utf-8')
            audit.bpy.context = SimpleNamespace(scene=scene,
                evaluated_depsgraph_get=lambda: None)
            audit.bpy.data = SimpleNamespace(filepath=str(storyboard))
            args = SimpleNamespace(storyboard=storyboard, expect=[], frame_origin=0,
                max_frames=600, weapon_regex='weapon', min_bbox=.0001,
                surface_step=step, scenery_step=12, max_uv_step=threshold,
                max_camera_step=.5, max_root_step=.25, max_weapon_step=.5,
                max_angle=20., max_lens_step=5.)
            with contextlib.redirect_stdout(io.StringIO()):
                report = audit.run(args)
        self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))
        self.assertEqual(len(calls), len(set(calls)))
        return report

    @staticmethod
    def projection(report, frame, actor='a'):
        return report['frames'][frame]['actors'][actor]['projection']

    @staticmethod
    def steps(report):
        return [(f['frame'], f['actor']) for f in report['flags']
                if f['kind'] == 'projection_step']

    def test_sparse_motion_scaled_by_actual_interval(self):
        report = self.audit([(0, 36)], lambda f, a: [f*.005, .5])
        self.assertEqual(self.steps(report), [])  # .15 total exceeds .01, rate does not.
        for frame, prior, interval in [(30, 0, 30), (35, 30, 5)]:
            p = self.projection(report, frame)
            self.assertEqual(p['previous_projection_frame'], prior)
            self.assertEqual(p['projection_frame_interval'], interval)
            self.assertAlmostEqual(p['center_drift_uv_per_frame'], .005)
            self.assertAlmostEqual(p['consecutive_center_drift_uv'], .005*interval)

    def test_sparse_excess_and_short_endpoint_detected_per_actor(self):
        report = self.audit([(0, 36)],
            lambda f, a: [f*.02 if a == 'a' else .5, .5])
        self.assertEqual(self.steps(report), [(30, 'a'), (35, 'a')])

    def test_same_camera_cut_resets_history_and_resumes_comparison(self):
        report = self.audit([(0, 31), (31, 67)],
            lambda f, a: [0. if f < 31 else 10.+(f-31)*.02, .5])
        self.assertEqual(self.steps(report),
                         [(61, 'a'), (61, 'b'), (66, 'a'), (66, 'b')])
        self.assertNotIn('center_drift_uv_per_frame', self.projection(report, 31))
        self.assertEqual(self.projection(report, 61)['previous_projection_frame'], 31)
        self.assertEqual(len(report['cuts']), 1)

    def test_dense_samples_keep_one_frame_threshold(self):
        report = self.audit([(0, 3)], lambda f, a: [f*.02, .5], step=1)
        self.assertEqual(self.steps(report), [(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')])
        self.assertEqual(self.projection(report, 2)['projection_frame_interval'], 1)

    def test_missing_center_does_not_bridge_invalid_sample(self):
        report = self.audit([(0, 61)],
            lambda f, a: None if f == 30 else [float(f), .5])
        self.assertEqual(self.steps(report), [])
        self.assertNotIn('center_drift_uv_per_frame', self.projection(report, 60))


if __name__ == '__main__':
    unittest.main()
