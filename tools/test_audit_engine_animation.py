"""Real Blender mathutils + DMX serialization on synthetic bones, no renderer/game.

Runs the actual calibration block and writer extracted from anim_to_dmx.py.
Does not test glTF import, action-slot selection, skinning, or resourcecompiler.
"""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent / 'dota_engine'
SOURCE = (HERE / 'anim_to_dmx.py').read_text(encoding='utf-8')
WORKER = '--engine-worker' in sys.argv


class AnimationTests(unittest.TestCase):
    def test_blender_contracts(self):
        sys.path.insert(0, str(HERE.parent))
        from paths import BLENDER
        result = subprocess.run([BLENDER, '-b', '--factory-startup', '--python-exit-code', '1',
                                 '-P', str(Path(__file__).resolve()), '--', '--engine-worker'],
                                capture_output=True, text=True, encoding='utf-8', timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('ENGINE_ANIMATION_OK', result.stdout)


@unittest.skipUnless(WORKER, 'runs inside the Blender subprocess')
class BlenderTests(unittest.TestCase):
    def namespace(self, count=3):
        import numpy as np
        from mathutils import Matrix, Vector, Quaternion
        sys.path.insert(0, str(HERE))
        import datamodel
        names = ['a', 'b', 'c']
        matrices = {n: Matrix.Translation(Vector(p)) for n, p in zip(names, [(0, 0, 0), (10, 0, 0), (0, 10, 0)])}
        ns = dict(np=np, Matrix=Matrix, Vector=Vector, Quaternion=Quaternion, os=os,
                  datamodel=datamodel, common=names, order=names + ['extra'], NI=count, FPS=30,
                  idle_bl=[{n: m.copy() for n, m in matrices.items()} for _ in range(count)],
                  idle_dmx=[{n: m.copy() for n, m in matrices.items()} for _ in range(count)],
                  log=lambda *args: None)
        ns['bl_mats'] = lambda action, frames, fps: [{n: m.copy() for n, m in matrices.items()} for _ in frames]
        ns['joints'] = {n: ({'transform': {'position': list(m.translation), 'orientation': [0, 0, 0, 1]}}, None) for n, m in matrices.items()}
        ns['joints']['extra'] = ({'transform': {'position': [0, 0, 0], 'orientation': [0, 0, 0, 1]}}, 'a')
        for node in ast.parse(SOURCE).body:
            if isinstance(node, ast.FunctionDef) and node.name in ('q2m', 'local', 'source_idle_frame', 'write'):
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(HERE / 'anim_to_dmx.py'), 'exec'), ns)
        return ns

    def calibrate(self, ns):
        block = SOURCE[SOURCE.index('P = np.array'):SOURCE.index('\ndef source_idle_frame')]
        with patch.dict(os.environ, {'A8_DMX_MAX_POS': '1', 'A8_DMX_MAX_ANGLE': '0.01'}):
            exec(compile(block, str(HERE / 'anim_to_dmx.py'), 'exec'), ns)

    def test_single_frame_and_loop_hold_written_values(self):
        for count in (1, 3):
            for loop in (False, True):
                with self.subTest(count=count, loop=loop), tempfile.TemporaryDirectory() as tmp:
                    ns = self.namespace(count)
                    self.calibrate(ns)
                    dm = ns['datamodel']
                    model = dm.DataModel('model', 1)
                    root = model.add_element('root')
                    al = root['animationList'] = model.add_element('animations')
                    clip = model.add_element('idle')
                    al['animations'] = dm.make_array([clip], dm.Element)
                    tf = clip['timeFrame'] = model.add_element('timeFrame')
                    tf['duration'] = dm.Time(1)
                    channels = []
                    for attr, typ, vals in [('position', dm.Vector3, [[0, 0, 0], [2, 0, 0], [0, 0, 0]][:count]),
                                            ('orientation', dm.Quaternion, [[0, 0, 0, 1]] * count)]:
                        ch = model.add_element(attr)
                        ch['toElement'] = model.add_element('extra')
                        ch['toAttribute'] = attr
                        log = ch['log'] = model.add_element('log')
                        lay = model.add_element('layer')
                        lay['values'] = dm.make_array([typ(v) for v in vals], typ)
                        lay['times'] = dm.make_array([dm.Time(k / 30) for k in range(count)], dm.Time)
                        log['layers'] = dm.make_array([lay], dm.Element)
                        channels.append(ch)
                    clip['channels'] = dm.make_array(channels, dm.Element)
                    ns.update(OUT=tmp, PREFIX='test', SRC_IDLE=str(Path(tmp) / 'idle.dmx'),
                              by_tr={'extra': {ch['toAttribute']: ch for ch in channels}})
                    model.write(ns['SRC_IDLE'], 'binary', 9)
                    ns['write']('result', None, 5, loop_src_idle=loop)
                    result = dm.load(str(Path(tmp) / 'test_result.dmx'))
                    result_clip = result.root['animationList']['animations'][0]
                    self.assertIs(type(result_clip['timeFrame']['duration']), dm.Time)
                    self.assertAlmostEqual(result_clip['timeFrame']['duration'], 5 / 30, places=3)
                    values = result_clip['channels'][0]['log']['layers'][0]['values']
                    expected = [0] * 6 if count == 1 else ([0, 2, 0, 2, 0, 2] if loop else [0, 2, 0, 0, 0, 0])
                    self.assertEqual([round(v[0], 5) for v in values], expected)
                    self.assertEqual(len(result_clip['channels'][1]['log']['layers'][0]['times']), 6)

    def test_bad_position_and_between_stride_rotation_refuse(self):
        ns = self.namespace(6)
        ns['idle_dmx'][1]['b'].translation.x += 10
        with self.assertRaisesRegex(ValueError, 'ошибка подобия|перенос не допущен'):
            self.calibrate(ns)
        ns = self.namespace(6)
        # Frame 1 was missed by the former range(0, NI, 5) validation.
        ns['idle_dmx'][1]['a'] = ns['Matrix'].Rotation(0.2, 4, 'Z')
        with self.assertRaisesRegex(ValueError, 'перенос не допущен'):
            self.calibrate(ns)

    def test_degenerate_and_nonfinite_refuse(self):
        ns = self.namespace(1)
        for matrices in (ns['idle_bl'], ns['idle_dmx']):
            for name in ns['common']:
                matrices[0][name] = ns['Matrix'].Identity(4)
        with self.assertRaisesRegex(ValueError, 'вырожденный'):
            self.calibrate(ns)
        ns = self.namespace(1)
        ns['idle_bl'][0]['b'].translation.x = float('nan')
        with self.assertRaisesRegex(ValueError, 'конечными'):
            self.calibrate(ns)
        ns = self.namespace(1)
        ns['common'] = ['a']
        with self.assertRaisesRegex(ValueError, 'минимум три'):
            self.calibrate(ns)

    def test_empty_idle_rejected(self):
        ns = self.namespace(1)
        with self.assertRaises(ValueError):
            ns['source_idle_frame'](0, 0, True)
        # Actual top-level guard, before indexing idle_bl[0].
        block = SOURCE[SOURCE.index('if NI < 1:'):SOURCE.index('\ndef dmx_world')]
        with self.assertRaises(ValueError):
            exec(block, {'NI': 0})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlenderTests if WORKER else AnimationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError('animation contract tests failed')
    if WORKER:
        print('ENGINE_ANIMATION_OK: 4 tests')
