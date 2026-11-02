"""CPU regressions: run with Blender -b --factory-startup --python-exit-code 2 -P.

Real bpy evaluation/save/reopen, synthetic objects only. Render calls are spies.
"""
import ast
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pudge_tank_finish import ground_actor_shadow


def empty(name):
    ob = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def run_script(name, render):
    # Substitute only rendering; scene graph, animation, IO and script are real.
    proxy = SimpleNamespace(context=bpy.context, data=bpy.data,
                            ops=SimpleNamespace(wm=bpy.ops.wm,
                                                render=SimpleNamespace(render=render)))
    path = HERE / name
    with patch.dict(sys.modules, {'bpy': proxy}):
        exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'),
             {'__file__': str(path), '__name__': '__main__'})


class PudgeBlenderAudit(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.preferences.filepaths.save_version = 0
        self.temp = tempfile.TemporaryDirectory(prefix='pudge_audit_')
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def test_hatch_clipping_preserves_uv_material_and_outside_area(self):
        # Execute the actual two helpers without the production build/render.
        path = HERE / 'pudge_tank_motion.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('split_polygon', 'open_well')]
        env = dict(bpy=bpy, math=math, Vector=Vector, RIM_RADIUS=1., SEAT=Vector((10, 20, 0)))
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), env)
        bpy.ops.mesh.primitive_plane_add(size=4, location=(10, 20, 5))
        ob = bpy.context.object
        mat = bpy.data.materials.new('test armor'); ob.data.materials.append(mat)
        ob.data.polygons[0].use_smooth = True
        bpy.context.view_layer.update()
        env['open_well'](ob)
        ob.data.calc_loop_triangles()
        area = sum(t.area for t in ob.data.loop_triangles)
        self.assertAlmostEqual(area, 16 - 16 * math.sin(math.tau / 32), places=4)
        self.assertEqual(ob.data.materials[0], mat)
        for face in ob.data.polygons:
            self.assertTrue(face.use_smooth)
            self.assertEqual(face.material_index, 0)
            for index in face.loop_indices:
                vertex = ob.data.vertices[ob.data.loops[index].vertex_index].co
                uv = ob.data.uv_layers[0].data[index].uv
                self.assertAlmostEqual(uv.x, vertex.x / 4 + .5, places=5)
                self.assertAlmostEqual(uv.y, vertex.y / 4 + .5, places=5)

    def test_grounded_shadow_survives_layers_and_reopen(self):
        scene = bpy.context.scene
        hero = empty('pudge_root')
        for name in ('detailed_tank', 'heavy_launcher', 'enemy_ancient'):
            empty(name)
        for frame, location in ((0, (0, 0, 3)), (65, (1, 2, 5)), (299, (3, 4, 3))):
            hero.location = location
            hero.keyframe_insert('location', frame=frame)
        bpy.ops.mesh.primitive_plane_add(size=2)
        blob = bpy.context.object
        blob.name = 'pudge_blob'
        blob.parent = hero
        mat = bpy.data.materials.new('blob test'); mat.use_nodes = True
        gain = mat.node_tree.nodes.new('ShaderNodeMath'); gain.operation = 'MULTIPLY'
        blob.data.materials.append(mat)
        empty('static_environment')
        ground_actor_shadow(scene)
        self.assertIsNone(blob.parent)
        scene.frame_start, scene.frame_end = 0, 299
        bpy.ops.wm.save_as_mainfile(filepath=str(self.out / 'scene.blend'))
        (self.out / 'build.json').write_text(json.dumps({'frames': 300, 'cuts': [0, 39, 108, 300]}))
        renders = []

        def render(**kwargs):
            renders.append((kwargs, bpy.data.objects.get('pudge_blob'),
                            blob.hide_render if blob.name in bpy.data.objects else None))
            if kwargs.get('write_still'):
                self.assertTrue(blob.hide_render, 'Grounded shadow was baked into a static plate')

        run_script('pudge_tank_layers.py', render)
        self.assertEqual(len(renders), 4)
        self.assertIsNotNone(bpy.data.objects.get('pudge_blob'))
        self.assertNotIn('static_environment', bpy.data.objects)
        bpy.ops.wm.open_mainfile(filepath=str(self.out / 'layers.blend'))
        blob = bpy.data.objects['pudge_blob']
        self.assertIsNone(blob.parent)
        scene = bpy.context.scene
        for frame in range(300):
            scene.frame_set(frame)
            self.assertEqual(blob.hide_render, frame >= 66)
            self.assertAlmostEqual(blob.matrix_world.translation.z, 3.012, places=4)
        # The next production step must still find the object and rebake it.
        self.assertEqual(len(ground_actor_shadow(scene)['samples']), 300)

    def test_failed_support_grip_replaces_previous_qa(self):
        hero = empty('pudge_root'); empty('detailed_tank')
        weapon = empty('heavy_launcher')
        rig = bpy.data.armatures.new('test rig')
        arm = bpy.data.objects.new('test rig', rig)
        bpy.context.scene.collection.objects.link(arm); arm.parent = hero
        bpy.context.view_layer.objects.active = arm; arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        for name in ('wrist_L', 'wrist_R', 'weapon_rt_1'):
            bone = rig.edit_bones.new(name); bone.head = (0, 0, 0); bone.tail = (0, 1, 0)
        bpy.ops.object.mode_set(mode='OBJECT')
        weapon['prop_grip'] = [0, 0, 0]
        weapon['grip_local_bone'] = [0, 0, 0]
        weapon['support_grip'] = [.02, 0, 0]
        weapon['support_local_wrist'] = [0, 0, 0]
        bpy.ops.wm.save_as_mainfile(filepath=str(self.out / 'candidate.blend'))
        report = self.out / 'saved_qa.json'
        report.write_text('{"stale_success": true}')
        with self.assertRaisesRegex(ValueError, 'Support hand'):
            run_script('pudge_tank_epic_qa.py', lambda **kw: self.fail('Unexpected render'))
        data = json.loads(report.read_text())
        self.assertNotIn('stale_success', data)
        self.assertAlmostEqual(data['support_reference_error_m'], .02, places=6)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PudgeBlenderAudit))
    if not result.wasSuccessful():
        raise RuntimeError('Pudge CPU Blender regressions failed')
