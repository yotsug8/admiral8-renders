"""Narrow source-review regressions; synthetic CPU data, no assets or renders.

Python: -m unittest tools.blender.test_audit_blender_studies.CPUContracts
Blender: -b --factory-startup --disable-autoexec --python-exit-code 2 -P this_file
Functions are compiled from the reviewed sources without their study builders.
"""
import ast
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from json_output import json_output_path, write_json_report

try:
    import bpy
    from mathutils import Matrix
    from mathutils.bvhtree import BVHTree
    from contact_metrics import visible_meshes
except ImportError:
    bpy = None


def functions(filename, names, namespace, optimize=0):
    tree = ast.parse((HERE / filename).read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(tree, filename, 'exec', optimize=optimize), namespace)
    return namespace


class CPUContracts(unittest.TestCase):
    def test_bvh_import_executes_under_optimization(self):
        for optimize in (0, 1):
            with self.subTest(optimize=optimize):
                fake = Mock()
                fake.ops.import_anim.bvh.return_value = {'FINISHED'}
                ns = functions('study_ready_standing_clip.py', {'import_bvh'}, dict(bpy=fake), optimize)
                self.assertIs(ns['import_bvh'](Path('synthetic.bvh')), fake.context.object)
                fake.ops.import_anim.bvh.assert_called_once()

    def test_bvh_cancelled_is_error_even_under_optimization(self):
        for optimize in (0, 1):
            with self.subTest(optimize=optimize):
                fake = Mock()
                fake.ops.import_anim.bvh.return_value = {'CANCELLED'}
                ns = functions('study_ready_standing_clip.py', {'import_bvh'}, dict(bpy=fake), optimize)
                with self.assertRaises(RuntimeError):
                    ns['import_bvh'](Path('synthetic.bvh'))

    def run_neck_main(self, source, output, loaded=''):
        import argparse
        code = source.read_text(encoding='utf-8')
        node = ast.parse(code).body[0]
        fake = SimpleNamespace(data=SimpleNamespace(filepath=loaded),
                               app=SimpleNamespace(version_string='synthetic', build_hash=b'test'))
        audit = Mock(return_value={'checked': True})
        ns = functions('study_close_neck_audit.py', {'main'}, dict(
            argparse=argparse, ast=ast, hashlib=hashlib, json=json, Path=Path, sys=sys,
            bpy=fake, Vector=None, audit=audit, __file__=str(HERE/'study_close_neck_audit.py'),
            EXPECTED=hashlib.sha256(ast.get_source_segment(code, node).encode()).hexdigest(),
            json_output_path=json_output_path, write_json_report=write_json_report))
        with patch.object(sys, 'argv', ['blender', '--', '--source', str(source), '--out', str(output)]), redirect_stdout(io.StringIO()):
            ns['main']()
        return audit

    def test_neck_report_refuses_input_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source.py'
            content = 'def close_neck(head, bodies):\n    pass\n'
            source.write_text(content, encoding='utf-8')
            alias = root/'alias.json'
            os.link(source, alias)
            for output in (source, alias):
                with self.subTest(output=output.name), self.assertRaises(ValueError):
                    self.run_neck_main(source, output)
                self.assertEqual(source.read_text(encoding='utf-8'), content)

    def test_neck_report_refuses_loaded_scene_alias_and_blend_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source.py'
            source.write_text('def close_neck(head, bodies):\n    pass\n', encoding='utf-8')
            scene = root/'loaded.blend'
            scene.write_bytes(b'synthetic scene sentinel')
            alias = root/'scene_alias.json'
            os.link(scene, alias)
            for output in (scene, alias, root/'new.blend'):
                with self.subTest(output=output.name), self.assertRaises(ValueError):
                    self.run_neck_main(source, output, str(scene))
            self.assertEqual(scene.read_bytes(), b'synthetic scene sentinel')

    def test_neck_report_creates_safe_parent_and_json(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'source.py'
            source.write_text('def close_neck(head, bodies):\n    pass\n', encoding='utf-8')
            output = Path(temp)/'reports'/'neck.json'
            audit = self.run_neck_main(source, output)
            self.assertEqual(audit.call_count, 4)
            self.assertTrue(json.loads(output.read_text())['assertions_passed'])

    def run_staging_verify(self, root):
        fake = Mock()
        fake.data.objects = {name: object() for name in (
            'face_staging_camera', 'face_staging_target', 'face_staging_support')}
        fake.data.images.load.return_value.size = (640, 360)
        dump = Mock()
        ns = functions('study_face_staging.py', {'verify'}, dict(
            SOURCE=root/'source.blend', OUT=root, digest=lambda path: 'synthetic_hash',
            witness=lambda: 'actor_witness', geometry_check=lambda *args: {},
            dump=dump, json=json))
        with patch.dict(sys.modules, {'bpy': fake}), redirect_stdout(io.StringIO()):
            ns['verify']()
        return dump.call_args.args[1]

    def test_staging_requires_both_variants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'render_budget.json').write_text('[]', encoding='utf-8')
            for existing in (0, 1):
                if existing:
                    (root/'a').mkdir()
                    (root/'a/face_staging.blend').write_bytes(b'synthetic')
                with self.subTest(existing=existing), self.assertRaises(ValueError):
                    self.run_staging_verify(root)

    def test_staging_reports_both_present_variants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'render_budget.json').write_text('[]', encoding='utf-8')
            for variant in ('a', 'b'):
                (root/variant).mkdir()
                (root/variant/'face_staging.blend').write_bytes(b'synthetic')
            self.assertEqual(set(self.run_staging_verify(root)['variants']), {'a', 'b'})


@unittest.skipIf(bpy is None, 'requires Blender background')
class BlenderContracts(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.frames = [1, 1.25]
        self.bones = ('root', 'spine1', 'spine2', 'spine3', 'neck1', 'head')
        self.compare = functions('study_retarget_smoke.py', {'compare'}, dict(
            FRAMES=self.frames, BONES=self.bones, Matrix=Matrix, math=math, json=json))['compare']
        self.surface = functions('study_character_overlap.py', {'surface_audit'}, dict(
            bpy=bpy, BVHTree=BVHTree, COUNT=2, json=json, visible_meshes=visible_meshes))['surface_audit']

    def samples(self):
        return [{name: [list(row) for row in Matrix.Identity(4)] for name in self.bones} for _ in self.frames]

    def test_matrix_identity_passes_and_motion_mismatch_fails(self):
        before = self.samples()
        self.assertTrue(self.compare(before, copy.deepcopy(before))['passed'])
        after = copy.deepcopy(before)
        after[-1]['head'][0][3] = .001
        with self.assertRaises(ValueError):
            self.compare(before, after)

    def test_nonfinite_matrices_never_pass(self):
        for value in (float('nan'), float('inf'), -float('inf'), 1e100):
            for side in (0, 1):
                for row, col in ((0, 3), (0, 0), (3, 3)):
                    with self.subTest(value=value, side=side, index=(row, col)):
                        inputs = [self.samples(), self.samples()]
                        inputs[side][-1]['head'][row][col] = value
                        with self.assertRaises(ValueError):
                            self.compare(*inputs)

    def test_incomplete_matrix_samples_fail(self):
        with self.assertRaises(ValueError):
            self.compare([], [])
        after = self.samples()
        after[-1]['head'] = [[1, 0], [0, 1]]
        with self.assertRaises(ValueError):
            self.compare(self.samples(), after)

    def mesh(self, name, vertices, faces=((0, 1, 2),)):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], faces)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def fixture(self, bodies=True, crossing=False):
        body_objects = []
        for case in ('control', 'follow'):
            self.mesh('0_'+case+'.righthook_model', [(0, -.5, -1), (0, -.5, 1), (0, .5, 0)])
            if bodies:
                body = self.mesh('0_'+case+'.upper_body', [(-1, -1, 0), (1, -1, 0), (0, 1, 0)])
                body.location.x = 0 if crossing else 3
                body_objects.append(body)
        bpy.context.view_layer.update()
        return body_objects

    def measure(self):
        with redirect_stdout(io.StringIO()):
            return self.surface(self.folder)

    def test_surface_separation_and_crossing(self):
        bodies = self.fixture()
        self.assertEqual(self.measure()['max_non_grip_crossings'], 0)
        for body in bodies:
            body.location.x = 0
        self.assertGreater(self.measure()['max_non_grip_crossings'], 0)

    def test_surface_no_body_is_not_zero_crossings(self):
        self.fixture(bodies=False)
        with self.assertRaises(ValueError):
            self.measure()
        self.assertFalse((self.folder/'surfaces.json').exists())

    def test_surface_empty_triangles_is_inconclusive(self):
        bodies = self.fixture()
        bodies[0].data.clear_geometry()
        with self.assertRaises(ValueError):
            self.measure()

    def test_surface_grip_mask_cannot_empty_the_audit(self):
        bodies = self.fixture()
        bodies[0].vertex_groups.new(name='wrist_r').add([0, 1, 2], 1., 'REPLACE')
        with self.assertRaises(ValueError):
            self.measure()

    def test_surface_hidden_collection_is_not_coverage(self):
        bodies = self.fixture()
        hidden = bpy.data.collections.new('hidden_body')
        bpy.context.scene.collection.children.link(hidden)
        bpy.context.scene.collection.objects.unlink(bodies[0])
        hidden.objects.link(bodies[0])
        hidden.hide_render = True
        with self.assertRaises(ValueError):
            self.measure()

    def test_surface_animated_visibility_is_checked_each_frame(self):
        bodies = self.fixture()
        body = bodies[0]
        body.hide_render = False
        body.keyframe_insert('hide_render', frame=0)
        body.hide_render = True
        body.keyframe_insert('hide_render', frame=1)
        bpy.context.scene.frame_set(0)
        with self.assertRaises(ValueError):
            self.measure()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful():
        raise SystemExit(1)
