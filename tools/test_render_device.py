import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


class DeviceTests(unittest.TestCase):
    def select(self, requested, available, scene_device='GPU'):
        class Preferences:
            backend = 'NONE'
            devices = []

            @property
            def compute_device_type(self):
                return self.backend

            @compute_device_type.setter
            def compute_device_type(self, value):
                if value not in available:
                    raise TypeError('Backend not compiled')
                self.backend = value

            def get_devices(self):
                self.devices = [NS(type=self.backend, name='Test GPU', use=False),
                                NS(type='CPU', name='CPU', use=True)]

        prefs = Preferences()
        bpy = NS(context=NS(preferences=NS(addons={'cycles': NS(preferences=prefs)})))
        path = Path(__file__).parent / 'blender/render_study_frames.py'
        spec = importlib.util.spec_from_file_location('device_under_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'bpy': bpy}), patch.dict(os.environ, A8_CYCLES_DEVICE=requested):
            spec.loader.exec_module(module)
            scene = NS(render=NS(engine='CYCLES'), cycles=NS(device=scene_device))
            result = module.configure_device(scene)
        return result, scene, prefs

    def test_gpu_discovery_without_user_preferences(self):
        result, scene, prefs = self.select('AUTO', ['CUDA'])
        self.assertEqual(result, 'CUDA:Test GPU')
        self.assertEqual(scene.cycles.device, 'GPU')
        self.assertEqual([d.use for d in prefs.devices], [True, False])

    def test_explicit_unavailable_device_fails(self):
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.select('OPTIX', ['CUDA'])

    def test_auto_fallback_and_explicit_cpu(self):
        for requested, devices, mode in [('AUTO', [], 'GPU'), ('CPU', ['CUDA'], 'GPU'),
                                          ('AUTO', ['CUDA'], 'CPU')]:
            result, scene, _ = self.select(requested, devices, mode)
            self.assertEqual(result, 'CPU')
            self.assertEqual(scene.cycles.device, 'CPU')
