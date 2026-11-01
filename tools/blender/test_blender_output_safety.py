"""Source-byte regressions; optional real Blender CPU integration, no render.

py -3.11 tools/blender/test_blender_output_safety.py
blender -b --factory-startup --disable-autoexec --python-exit-code 2
    -P tools/blender/test_blender_output_safety.py
"""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from json_output import write_json_report

try:
    import bpy
except ImportError:
    bpy = None


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        # No .blend suffix: equality protection must work independently of suffix.
        self.source = self.directory / 'input.data'
        self.original = b'BLENDER\x00\xff\x10source bytes\r\n'
        self.source.write_bytes(self.original)

    def refused(self, output):
        with self.assertRaises(ValueError):
            write_json_report(output, '{"status":"error"}', [self.source])
        self.assertEqual(self.source.read_bytes(), self.original)

    def link(self, kind):
        alias = self.directory / 'alias.json'
        try:
            if kind == 'hardlink':
                os.link(self.source, alias)
            else:
                alias.symlink_to(self.source)
        except OSError as exc:
            self.skipTest(f'{kind} unavailable: {exc}')
        self.assertTrue(alias.samefile(self.source))
        return alias

    def test_equal_path_preserves_bytes(self):
        self.refused(self.source)

    def test_normalized_relative_alias_preserves_bytes(self):
        (self.directory / 'child').mkdir()
        alias = self.directory / 'child' / '..' / self.source.name
        self.refused(Path(os.path.relpath(alias)))

    def test_hardlink_preserves_bytes(self):
        alias = self.link('hardlink')
        self.refused(alias)
        self.assertEqual(alias.read_bytes(), self.original)

    def test_symlink_preserves_bytes(self):
        alias = self.link('symlink')
        self.refused(alias)
        self.assertEqual(alias.read_bytes(), self.original)

    def test_case_alias_preserves_bytes_where_supported(self):
        alias = self.source.with_name(self.source.name.upper())
        if not alias.exists() or not alias.samefile(self.source):
            self.skipTest('case-sensitive filesystem')
        self.refused(alias)

    def test_blend_suffix_is_rejected_even_without_known_input(self):
        for name in ('other.blend', 'other.BLEND'):
            with self.subTest(name=name):
                output = self.directory / name
                output.write_bytes(self.original)
                with self.assertRaises(ValueError):
                    write_json_report(output, '{}', [])
                self.assertEqual(output.read_bytes(), self.original)

    def test_missing_parent_is_not_created(self):
        output = self.directory / 'missing' / 'report.json'
        with self.assertRaises(ValueError):
            write_json_report(output, '{}', [self.source])
        self.assertFalse(output.parent.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_distinct_output_and_unsaved_scene(self):
        output = self.directory / 'report.json'
        for payload in ('{"status":"pass"}\n', '{"status":"error"}'):
            write_json_report(output, payload, ['', self.source])
            self.assertEqual(output.read_text(encoding='utf-8'), payload)
            self.assertEqual(self.source.read_bytes(), self.original)


@unittest.skipIf(bpy is None, 'requires Blender for real main()/scene integration')
class BlenderOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {name: importlib.import_module(name) for name in (
            'camera_audit', 'contact_metrics', 'gait_metrics',
            'shot_continuity', 'deformation_metrics')}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 3
        scene.render.fps, scene.render.fps_base = 30, 1
        for name, x in (('actor', 0), ('target', 1)):
            root = bpy.data.objects.new(name + '_root', None)
            scene.collection.objects.link(root)
            rig = bpy.data.armatures.new(name + '_rig')
            arm = bpy.data.objects.new(name + '_arm', rig)
            scene.collection.objects.link(arm)
            arm.parent = root
            bpy.context.view_layer.objects.active = arm
            arm.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT')
            bone = rig.edit_bones.new('hand_L')
            bone.head, bone.tail = (0, 0, 0), (0, 0, .2)
            bpy.ops.object.mode_set(mode='OBJECT')
            arm.select_set(False)
            mesh = bpy.data.meshes.new(name + '_mesh')
            mesh.from_pydata([(0, 0, 0), (.1, 0, 0), (0, .1, 0), (0, 0, .1)],
                             [], [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)])
            body = bpy.data.objects.new(name + '_body', mesh)
            scene.collection.objects.link(body)
            body.parent = root
            body.vertex_groups.new(name='hand_L').add(list(range(4)), 1., 'REPLACE')
            body.modifiers.new('skin', 'ARMATURE').object = arm
            root.location.x = x
        camera = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
        scene.collection.objects.link(camera)
        camera.location = (0, -3, 1)
        camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera = camera
        self.source = self.directory / 'scene.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.candidate = self.directory / 'candidate.blend'
        shutil.copyfile(self.source, self.candidate)
        self.metadata = self.directory / 'actors.json'
        self.metadata.write_text(json.dumps({'actor': dict(
            root='actor_root', arm='actor_arm', objs=['actor_body'])}), encoding='utf-8')
        self.storyboard = self.directory / 'story.json'
        self.storyboard.write_text(json.dumps(dict(fps=30, shots=[dict(
            start=0, end=.1, kind='test', actors=['actor'])])), encoding='utf-8')
        self.originals = {p: p.read_bytes() for p in (
            self.source, self.candidate, self.metadata, self.storyboard)}

    def invoke(self, name, output, *, error=False):
        bpy.ops.wm.open_mainfile(filepath=str(self.source), load_ui=False, use_scripts=False)
        options = {
            'camera_audit': ['--actor', 'actor', '--frames', '1-3', '--mode', 'body'],
            'contact_metrics': ['--actor', 'actor', '--target', 'target', '--frames', '1-3'],
            'gait_metrics': ['--actor', 'actor', '--metadata', str(self.metadata),
                             '--start', '1', '--end', '3', '--step', '1', '--floor-z', '0'],
            'shot_continuity': ['--storyboard', str(self.storyboard), '--frame-origin', '1'],
            'deformation_metrics': [str(self.source), str(self.candidate),
                '--actor', 'actor', '--mesh-suffix', 'body', '--frames', '1-3'],
        }[name]
        if error:
            # Valid CLI, missing actor: exercise the report-on-analysis-error paths.
            options[options.index('--actor') + 1] = 'missing'
        argv = options + ['--json', str(output)]
        module = self.modules[name]

        def exit_status(code):
            raise SystemExit(code)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch.object(sys, 'argv', ['blender', '--', *argv]), \
                patch.object(os, '_exit', side_effect=exit_status):
            try:
                code = module.main(argv) if name == 'camera_audit' else module.main()
            except SystemExit as exc:
                code = exc.code
            except (ValueError, OSError):
                code = 2  # gait/deformation propagate to Blender or their outer handler.
        for path, original in self.originals.items():
            self.assertEqual(path.read_bytes(), original, f'{name} changed {path.name}')
        return code or 0

    def check_rejection(self, output, names=None):
        for name in names or self.modules:
            with self.subTest(cli=name, output=output.name):
                self.assertEqual(self.invoke(name, output), 2)

    def test_equal_and_normalized_source_paths(self):
        (self.directory / 'child').mkdir()
        self.check_rejection(self.source)
        self.check_rejection(Path(os.path.relpath(
            self.directory / 'child' / '..' / self.source.name)))

    def test_existing_hardlink(self):
        alias = self.directory / 'linked.json'
        try:
            os.link(self.source, alias)
        except OSError as exc:
            self.skipTest(f'hardlink unavailable: {exc}')
        self.check_rejection(alias)
        self.assertEqual(alias.read_bytes(), self.originals[self.source])

    def test_existing_symlink(self):
        alias = self.directory / 'linked.json'
        try:
            alias.symlink_to(self.source)
        except OSError as exc:
            self.skipTest(f'symlink unavailable: {exc}')
        self.check_rejection(alias)
        self.assertEqual(alias.read_bytes(), self.originals[self.source])

    def test_deformation_candidate_hardlink(self):
        alias = self.directory / 'candidate.json'
        os.link(self.candidate, alias)
        self.check_rejection(alias, ['deformation_metrics'])

    def test_auxiliary_inputs(self):
        self.check_rejection(self.metadata, ['gait_metrics'])
        self.check_rejection(self.storyboard, ['shot_continuity'])

    def test_error_reports_cannot_overwrite_source(self):
        for name in ('camera_audit', 'contact_metrics', 'deformation_metrics'):
            with self.subTest(cli=name):
                self.assertEqual(self.invoke(name, self.source, error=True), 2)
        # shot_continuity takes actors from the storyboard, not --actor.
        self.storyboard.write_text('{}', encoding='utf-8')
        self.originals[self.storyboard] = self.storyboard.read_bytes()
        self.check_rejection(self.source, ['shot_continuity'])

    def test_safe_reports_still_work(self):
        for name in self.modules:
            with self.subTest(cli=name):
                output = self.directory / (name + '.json')
                self.assertIn(self.invoke(name, output), (0, 1, 3))
                report = json.loads(output.read_text(encoding='utf-8'))
                self.assertNotEqual(report.get('status'), 'error')
                self.assertNotEqual(report.get('summary', {}).get('status'), 'error')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError('Blender output safety regressions failed')
