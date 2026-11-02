"""A02-A06 CPU and Blender background regressions; synthetic assets, no render.

py -3.11 tools/blender/test_audit_blender_fixes.py
blender -b --factory-startup --disable-autoexec --python-exit-code 2
    -P tools/blender/test_audit_blender_fixes.py
"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study_contact_events as events

try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None


def definitions(filename, namespace):
    """Production helpers without executing the resource-heavy scene builder."""
    tree = ast.parse((HERE / filename).read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    exec(compile(tree, str(HERE / filename), 'exec'), namespace)
    return namespace


def gait_payload(source_hash='a'*64):
    return dict(actor='actor', fps=30, frames=[0, 3], source_sha256=source_hash,
                paws={k: dict(contact_entry_times_s=[1/30]) for k in
                      ('hand_L', 'hand_R', 'ankle_L', 'ankle_R')},
                selection={k: [dict(mesh='body', vertices=3)] for k in
                           ('hand_L', 'hand_R', 'ankle_L', 'ankle_R')})


class CPUContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'gait.json'

    def read(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')
        return events.load_gait(self.path)

    def test_valid_report_and_pairing(self):
        actor, fps, frames, contacts, data = self.read(gait_payload())
        self.assertEqual((actor, fps, frames), ('actor', 30, (0, 3)))
        self.assertEqual(len(list(events.paired_entries(contacts))), 2)

    def test_missing_or_malformed_hash(self):
        for value in (None, '', 'z'*64, 'a'*63, 4):
            with self.subTest(value=value), self.assertRaises(ValueError):
                data = gait_payload(); data['source_sha256'] = value
                self.read(data)

    def test_invalid_contact_times(self):
        for times in ([.2], [0, 0], [float('nan')], [True]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                data = gait_payload(); data['paws']['hand_L']['contact_entry_times_s'] = times
                self.read(data)

    def test_diagnostic_environment_clears_save_mode(self):
        ns = definitions('views_world.py', dict(os=os))
        with patch.dict(os.environ, {'A8_BLEND': 'dont-save.blend', 'A8_VIEWS': 'actor:0'}):
            ns['diagnostic_environment']()
            self.assertNotIn('A8_BLEND', os.environ)
            self.assertNotIn('A8_VIEWS', os.environ)

    def test_legacy_camera_curves(self):
        ns = definitions('render_scene.py', {})
        key = SimpleNamespace(interpolation='BEZIER')
        action = SimpleNamespace(fcurves=[SimpleNamespace(keyframe_points=[key])])
        ns['hold_camera_keys'](SimpleNamespace(animation_data=SimpleNamespace(action=action)))
        self.assertEqual(key.interpolation, 'CONSTANT')


@unittest.skipIf(bpy is None, 'requires Blender background')
class BlenderContracts(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.sc = bpy.context.scene
        self.sc.render.fps = 30
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = bpy.data.objects.new('actor_root', None)
        self.sc.collection.objects.link(self.root)
        self.body = self.mesh('body', [(-1, -1, 0), (1, -1, 0), (0, 1, 0)])
        self.weapon = self.mesh('sword', [(0, -.5, -1), (0, -.5, 1), (0, .5, 0)])
        self.body.parent = self.weapon.parent = self.root
        self.cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
        self.sc.collection.objects.link(self.cam)
        self.cam.location = (0, -5, 2)
        self.cam.rotation_euler = (-self.cam.location).to_track_quat('-Z', 'Y').to_euler()
        self.sc.camera = self.cam
        bpy.context.view_layer.update()
        import re
        from contact_metrics import visible_meshes
        self.ns = definitions('views_world.py', dict(
            bpy=bpy, sc=self.sc, re=re, os=os, json=json, visible_meshes=visible_meshes,
            ACTORS={'actor': dict(root=self.root, arm=None)}, HERO_OBJS={self.body, self.weapon}))

    def mesh(self, name, vertices):
        data = bpy.data.meshes.new(name)
        data.from_pydata(vertices, [], [tuple(range(len(vertices)))] if vertices else [])
        obj = bpy.data.objects.new(name, data)
        self.sc.collection.objects.link(obj)
        return obj

    def clip(self, frames=(1, 2), wall=False):
        with patch.dict(os.environ, {'A8_CLIP': '1', 'A8_WALL': '1' if wall else ''}), \
                contextlib.redirect_stdout(io.StringIO()):
            return self.ns['clip_check']('actor', frames)

    def test_clip_intersection_without_vmdl_name(self):
        result = self.clip()
        self.assertEqual(result['status'], 'intersection')
        self.assertEqual(result['checked_pairs'], 2)

    def test_clip_separated(self):
        self.weapon.location.x = 10
        self.assertEqual(self.clip()['status'], 'no_surface_intersections')

    def test_clip_empty_frames(self):
        self.assertEqual(self.clip([])['status'], 'inconclusive')

    def test_clip_missing_weapon_or_body(self):
        for obj in (self.body, self.weapon):
            self.ns['HERO_OBJS'] = {obj}
            self.assertEqual(self.clip()['status'], 'inconclusive')

    def test_clip_empty_geometry(self):
        self.weapon.data.clear_geometry()
        self.assertEqual(self.clip()['status'], 'inconclusive')

    def test_clip_animated_render_visibility(self):
        for obj in (self.body, self.weapon):
            obj.hide_render = True; obj.keyframe_insert('hide_render', frame=1)
            obj.hide_render = False; obj.keyframe_insert('hide_render', frame=2)
        self.sc.frame_set(1)
        result = self.clip()
        self.assertEqual(result['checked_frames'], 1)
        self.assertEqual(result['incomplete_frames'], [1])
        self.assertEqual(result['status'], 'intersection')
        self.weapon.location.x = 10
        self.assertEqual(self.clip()['status'], 'inconclusive')

    def test_clip_hidden_collection_and_viewport(self):
        group = bpy.data.collections.new('hidden')
        self.sc.collection.children.link(group)
        self.sc.collection.objects.unlink(self.weapon)
        group.objects.link(self.weapon)
        group.hide_render = True
        self.assertEqual(self.clip()['status'], 'inconclusive')
        group.hide_render = False
        self.weapon.hide_set(True)
        self.assertEqual(self.clip()['status'], 'inconclusive')

    def test_clip_wall_missing_other_actor(self):
        self.weapon.location.x = 10
        self.assertEqual(self.clip(wall=True)['status'], 'inconclusive')

    def test_views_cli_strict_status_and_blend_conflict(self):
        source = (HERE/'views_world.py').read_text(encoding='utf-8')
        original_open = open
        stub = ('import bpy, os\n'
                'if os.environ.get("A8_BLEND"): raise AssertionError("save mode leaked")\n'
                'sc=bpy.context.scene\n'
                'ACTORS={"actor": {"root": bpy.data.objects["actor_root"], "arm": None}}\n'
                'HERO_OBJS={bpy.data.objects["body"], bpy.data.objects["sword"]}\n'
                'PICK=[1]; N=2; OUT="unused"\n')
        def safe_open(path, *args, **kwargs):
            return io.StringIO(stub) if Path(path).name == 'render_scene.py' else original_open(path, *args, **kwargs)
        def exit_status(code):
            raise SystemExit(code)
        for hidden, expected in ((False, 1), (True, 3)):
            self.weapon.hide_render = hidden
            with patch.dict(os.environ, {'A8_CLIP': '1', 'A8_CLIP_STRICT': '1',
                                         'A8_WVIEWS': 'actor:0', 'A8_BLEND': 'forbidden.blend',
                                         'A8_FAST': '', 'A8_WALL': ''}), \
                    patch('builtins.open', side_effect=safe_open), \
                    patch.object(os, '_exit', side_effect=exit_status), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                exec(compile(source, str(HERE/'views_world.py'), 'exec'),
                     dict(__file__=str(HERE/'views_world.py'), __name__='__main__'))
            self.assertEqual(caught.exception.code, expected)

    def test_layered_camera_cut_and_other_slot(self):
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        hold = definitions('render_scene.py', dict(
            action_get_channelbag_for_slot=action_get_channelbag_for_slot))['hold_camera_keys']
        for frame, x in ((9, 0), (10, 20)):
            self.cam.location.x = x; self.cam.keyframe_insert('location', frame=frame)
            self.cam.data.lens = 30+x; self.cam.data.keyframe_insert('lens', frame=frame)
        action = self.cam.animation_data.action
        self.root.animation_data_create().action = action
        self.root.animation_data.action_slot = action.slots.new(id_type='OBJECT', name='other')
        for frame, x in ((9, 0), (10, 4)):
            self.root.location.x = x; self.root.keyframe_insert('location', frame=frame)
        bag = action_get_channelbag_for_slot(action, self.root.animation_data.action_slot)
        for curve in bag.fcurves:
            for key in curve.keyframe_points:
                key.interpolation = 'LINEAR'
        hold(self.cam); hold(self.cam.data)
        self.sc.frame_set(9, subframe=.75)
        self.assertAlmostEqual(self.cam.location.x, 0)
        self.assertAlmostEqual(self.cam.data.lens, 30)
        self.assertAlmostEqual(self.root.location.x, 3)
        self.sc.frame_set(10)
        self.assertAlmostEqual(self.cam.location.x, 20)

    def test_map_material_scope_real_import(self):
        import dota_map
        mat = bpy.data.materials.new('prop')
        mat.use_nodes = True
        mat['vmat'] = {'ShaderName': 'prop.vfx'}
        bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bsdf.inputs['Roughness'].default_value = .17
        self.body.data.materials.append(mat)
        self.body.select_set(True)
        bpy.context.view_layer.objects.active = self.body
        glb = self.directory/'map.glb'
        bpy.ops.export_scene.gltf(filepath=str(glb), use_selection=True, export_extras=True)
        before = len(mat.node_tree.nodes)
        first = dota_map.load(str(glb), str(self.directory))
        self.assertEqual(len(mat.node_tree.nodes), before)
        self.assertAlmostEqual(bsdf.inputs['Roughness'].default_value, .17)
        imported = {s.material for o in first for s in o.material_slots if s.material}
        self.assertTrue(imported)
        for m in imported:
            shader = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            self.assertAlmostEqual(shader.inputs['Roughness'].default_value, .6)
            shader.inputs['Roughness'].default_value = .23
        old_counts = {m: len(m.node_tree.nodes) for m in imported}
        dota_map.load(str(glb), str(self.directory))
        self.assertEqual({m: len(m.node_tree.nodes) for m in imported}, old_counts)
        self.assertEqual(len(mat.node_tree.nodes), before)
        for m in imported:
            shader = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            self.assertAlmostEqual(shader.inputs['Roughness'].default_value, .23)

    def test_map_shared_material_is_copied(self):
        import dota_map
        mat = bpy.data.materials.new('shared')
        mat.use_nodes = True; mat['vmat'] = {'ShaderName': 'water_dota.vfx'}
        self.body.data.materials.append(mat)
        created = []
        def import_shared(**kwargs):
            clone = self.body.copy()
            self.sc.collection.objects.link(clone)
            created.append(clone)
        fake = SimpleNamespace(data=bpy.data, context=bpy.context,
                               ops=SimpleNamespace(import_scene=SimpleNamespace(gltf=import_shared)))
        with patch.object(dota_map, 'bpy', fake):
            dota_map.load('unused', str(self.directory))
        self.assertFalse(mat.get('_water'))
        self.assertEqual(self.body.material_slots[0].material, mat)
        self.assertTrue(created[0].material_slots[0].material.get('_water'))

    def test_map_texture_cache_includes_directory_and_color(self):
        import dota_map
        dota_map._img.clear()
        for dirname in ('first', 'second'):
            folder = self.directory/dirname; folder.mkdir()
            im = bpy.data.images.new(dirname, width=1, height=1)
            im.filepath_raw = str(folder/'same.png'); im.file_format = 'PNG'; im.save()
        dota_map.TEX = str(self.directory/'first')
        first = dota_map.img('same.vtex')
        self.assertEqual(first, dota_map.img('same.vtex'))
        noncolor = dota_map.img('same.vtex', False)
        dota_map.TEX = str(self.directory/'second')
        second = dota_map.img('same.vtex')
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, noncolor)
        self.assertEqual(noncolor.colorspace_settings.name, 'Non-Color')

    def save_report_scene(self):
        source = self.directory/'source.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        path = self.directory/'gait.json'
        path.write_text(json.dumps(gait_payload(events.file_hash(source))), encoding='utf-8')
        return source, path

    def invoke_events(self, gait, *extra, output=None):
        out = output or self.directory/'events.json'
        events.main(['--gait', str(gait), '--actor-root', 'actor_root', '--out', str(out), *extra])
        return json.loads(out.read_text(encoding='utf-8'))

    def test_events_exact_scene(self):
        source, gait = self.save_report_scene()
        report = self.invoke_events(gait)
        self.assertEqual(len(report['footsteps']), 2)
        self.assertEqual(report['provenance']['scene_sha256'], events.file_hash(source))

    def test_events_wrong_hash_and_actor(self):
        source, gait = self.save_report_scene()
        data = json.loads(gait.read_text())
        for key, value in (('source_sha256', 'b'*64), ('actor', 'other')):
            wrong = dict(data); wrong[key] = value
            gait.write_text(json.dumps(wrong))
            with self.assertRaises(ValueError):
                self.invoke_events(gait)

    def test_events_foreign_selection(self):
        _, gait = self.save_report_scene()
        data = json.loads(gait.read_text())
        data['selection']['hand_L'][0]['mesh'] = 'Camera'
        gait.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'outside actor'):
            self.invoke_events(gait)

    def test_events_output_hardlink_protection(self):
        source, gait = self.save_report_scene()
        for target in (source, gait):
            alias = self.directory/(target.stem+'_alias.json')
            os.link(target, alias)
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                self.invoke_events(gait, output=alias)
            self.assertEqual(target.read_bytes(), before)

    def test_events_camera_only_and_changed_motion(self):
        source, gait = self.save_report_scene()
        bpy.context.scene.camera.location.x += 2
        candidate = self.directory/'camera.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(candidate))
        bpy.ops.wm.open_mainfile(filepath=str(candidate), load_ui=False, use_scripts=False)
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            self.invoke_events(gait)
        report = self.invoke_events(gait, '--camera-only-source', str(source))
        self.assertEqual(report['provenance']['mode'], 'camera_only_sampled')
        self.assertEqual(Path(bpy.data.filepath), candidate)
        bpy.data.objects['actor_root'].location.x += .1
        bpy.ops.wm.save_as_mainfile(filepath=str(candidate))
        bpy.ops.wm.open_mainfile(filepath=str(candidate), load_ui=False, use_scripts=False)
        with self.assertRaisesRegex(ValueError, 'motion/geometry differs'):
            self.invoke_events(gait, '--camera-only-source', str(source))

    def test_events_camera_only_changed_geometry_and_wrong_source(self):
        source, gait = self.save_report_scene()
        bpy.data.objects['body'].data.vertices[0].co.z += .1
        candidate = self.directory/'mesh_change.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(candidate))
        bpy.ops.wm.open_mainfile(filepath=str(candidate), load_ui=False, use_scripts=False)
        with self.assertRaisesRegex(ValueError, 'source hash'):
            self.invoke_events(gait, '--camera-only-source', str(candidate))
        with self.assertRaisesRegex(ValueError, 'motion/geometry differs'):
            self.invoke_events(gait, '--camera-only-source', str(source))
        alias = self.directory/'source_alias.json'
        os.link(source, alias)
        original = source.read_bytes()
        with self.assertRaises(ValueError):
            self.invoke_events(gait, '--camera-only-source', str(source), output=alias)
        self.assertEqual(source.read_bytes(), original)

    def test_chase_effective_fps_interval_cuts_and_speed(self):
        import chase_audit
        self.root.name = 'hoodwink_root'
        arm = bpy.data.objects.new('rig', bpy.data.armatures.new('rig'))
        self.sc.collection.objects.link(arm); arm.parent = self.root
        bpy.context.view_layer.objects.active = arm; arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bone = arm.data.edit_bones.new('arm_upper_L'); bone.tail = (0, 0, 1)
        bpy.ops.object.mode_set(mode='OBJECT')
        for frame, x, angle in ((0, 0, 0), (120, 8, .6)):
            self.root.location.x = x; self.root.keyframe_insert('location', frame=frame)
            arm.pose.bones['arm_upper_L'].rotation_mode = 'XYZ'
            arm.pose.bones['arm_upper_L'].rotation_euler.z = angle
            arm.pose.bones['arm_upper_L'].keyframe_insert('rotation_euler', frame=frame)
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        for obj in (self.root, arm):
            ad = obj.animation_data
            for curve in action_get_channelbag_for_slot(ad.action, ad.action_slot).fcurves:
                for key in curve.keyframe_points: key.interpolation = 'LINEAR'
        self.sc.render.fps_base = 2
        out = io.StringIO()
        with patch.object(chase_audit.json, 'loads', return_value={'shots': [{'start': 0}, {'start': 4}]}), \
                contextlib.redirect_stdout(out):
            chase_audit.audit()
        report = json.loads(out.getvalue().split('CHASE_REGRESSION ', 1)[1])
        self.assertEqual(report['samples'], round(8*15*4)-round(2.2*15*4))
        self.assertEqual(report['excluded_camera_cuts'], [60])
        self.assertEqual(report['fps'], 15)
        self.assertAlmostEqual(report['maximum_forelimb_spine_rotation_per_quarter_frame']['head_speed_m_s'], 1, places=3)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful():
        raise RuntimeError('Audit Blender regressions failed')
