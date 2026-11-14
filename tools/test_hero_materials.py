"""Imported metal/roughness/cutout maps must survive scene preparation."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


def prepare(material, overrides=None):
    source = Path(__file__).parent / 'blender/render_scene.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fix_hero_mats')
    scope = dict(D={'material_overrides': overrides or {}}, math=math,
                 HERO=dict(sat=1, val=1, hue=0))
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    scope['fix_hero_mats']([NS(material_slots=[NS(material=material)])])


class Material(dict):
    def __init__(self):
        self.name = 'test_skin'
        sockets = {n: NS(links=[object()], default_value=.3) for n in
                   ('Alpha', 'Metallic', 'Roughness', 'Emission Strength')}
        self.shader = NS(type='BSDF_PRINCIPLED', inputs=sockets)
        def remove(link):
            for socket in sockets.values():
                if link in socket.links:
                    socket.links.remove(link)
        self.node_tree = NS(nodes=[self.shader], links=NS(remove=remove))

    def __bool__(self):
        return True


class HeroMaterialTests(unittest.TestCase):
    def test_original_maps_survive_and_repeated_call_is_safe(self):
        material = Material()
        links = {k: list(v.links) for k, v in material.shader.inputs.items()}
        prepare(material)
        prepare(material)
        self.assertEqual({k: v.links for k, v in material.shader.inputs.items()}, links)

    def test_skin_fix_does_not_destroy_other_channels(self):
        material = Material()
        prepare(material, {'test_skin': {'Alpha': 1, 'Metallic': 0}})
        self.assertEqual(material.shader.inputs['Alpha'].links, [])
        self.assertEqual(material.shader.inputs['Alpha'].default_value, 1)
        self.assertEqual(material.shader.inputs['Metallic'].default_value, 0)
        self.assertEqual(len(material.shader.inputs['Roughness'].links), 1)
        self.assertEqual(len(material.shader.inputs['Emission Strength'].links), 1)

    def test_invalid_corrections_fail_instead_of_silently_clamping(self):
        for correction in ({'Roughness': 2}, {'Alpha': float('nan')},
                           {'Metallic': True}, {'Unknown': 0}):
            with self.subTest(correction=correction), self.assertRaises(ValueError):
                prepare(Material(), {'test_skin': correction})
