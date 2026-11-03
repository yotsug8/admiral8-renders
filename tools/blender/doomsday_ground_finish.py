"""Break up the existing court texture without changing terrain or actor geometry.

Call apply(scene) before the material probes. Returns a JSON-serializable recipe;
the caller owns rendering and saving. Uses only images already in the scene.
"""
import json
import math

import bpy


PREFIX = 'Ground finish | '
PARAMETERS = {
    'stone_layers': [
        {'scale': .33, 'rotation_degrees': 11, 'offset': (0, 0, 0)},
        {'scale': .47, 'rotation_degrees': 79, 'offset': (3.71, -2.13, 0)},
    ],
    'coordinate_warp_scale': .13,
    'coordinate_warp_amount': .45,
    'stone_patch_scale': .23,
    'dust_patch_scale': .105,
    'dust_mask_interval': (.43, .64),
    'dust_texture_scale': .14,
    'normal_strength_stone': .65,
    'normal_strength_dust': .30,
    'dust_max_color_mix': .55,
    'dust_photo_saturation': .12,
    'dust_neutral_tint': (.115, .118, .12, 1),
    'dust_tint_mix': .20,
    'dust_roughness': .94,
}


def apply(scene):
    floor = scene.objects.get('Stone court')
    if floor is None or floor.type != 'MESH' or floor.active_material is None:
        raise ValueError('Stone court with its existing ground material is required')
    material = floor.active_material
    if material.users > 1:
        material = material.copy()
        material.name = 'Rocky ground | spatial finish'
        floor.active_material = material
    tree = material.node_tree
    if tree is None:
        raise ValueError('Ground material must have a node tree')
    shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    required = ('rocks_ground_02_col_4k.jpg', 'rocks_ground_02_nor_gl_4k.jpg',
                'rocks_ground_02_rough_4k.jpg', 'rocky_terrain_02_diff_4k.jpg')
    images = {name: bpy.data.images.get(name) for name in required}
    if any(image is None for image in images.values()):
        raise ValueError('Missing existing ground images: ' + ', '.join(
            name for name, image in images.items() if image is None))
    for node in list(tree.nodes):
        if node.name.startswith(PREFIX):
            tree.nodes.remove(node)

    def node(kind, label):
        n = tree.nodes.new(kind)
        n.name = PREFIX + label
        n.label = label
        n.location = (-1200 + (len(tree.nodes) % 8) * 230,
                      -450 - (len(tree.nodes) // 8) * 180)
        return n

    def link(source, target):
        tree.links.new(source, target)

    def vector_math(operation, label, first, second=None, scale=None):
        n = node('ShaderNodeVectorMath', label)
        n.operation = operation
        link(first, n.inputs[0])
        if second is not None:
            if isinstance(second, tuple):
                n.inputs[1].default_value = second
            else:
                link(second, n.inputs[1])
        if scale is not None:
            if isinstance(scale, (int, float)):
                n.inputs['Scale'].default_value = scale
            else:
                link(scale, n.inputs['Scale'])
        return n.outputs['Vector']

    def mix(label, factor, first, second):
        n = node('ShaderNodeMixRGB', label)
        n.blend_type = 'MIX'
        if isinstance(factor, (int, float)):
            n.inputs[0].default_value = factor
        else:
            link(factor, n.inputs[0])
        for socket, value in zip(n.inputs[1:3], (first, second)):
            if isinstance(value, tuple):
                socket.default_value = value
            else:
                link(value, socket)
        return n.outputs['Color']

    def noise(label, scale, coordinates):
        n = node('ShaderNodeTexNoise', label)
        n.noise_dimensions = '3D'
        n.inputs['Scale'].default_value = scale
        n.inputs['Detail'].default_value = 2
        n.inputs['Roughness'].default_value = .63
        link(coordinates, n.inputs['Vector'])
        return n

    def ramp(label, source, interval):
        n = node('ShaderNodeValToRGB', label)
        n.color_ramp.interpolation = 'EASE'
        for element, position in zip(n.color_ramp.elements, interval):
            element.position = position
        link(source, n.inputs['Fac'])
        return n.outputs['Color']

    def mapping(label, coordinates, scale, angle, offset=(0, 0, 0)):
        n = node('ShaderNodeMapping', label)
        n.inputs['Scale'].default_value = (scale,) * 3
        n.inputs['Rotation'].default_value[2] = math.radians(angle)
        n.inputs['Location'].default_value = offset
        link(coordinates, n.inputs['Vector'])
        return n.outputs['Vector']

    def texture(label, name, coordinates):
        n = node('ShaderNodeTexImage', label)
        n.image = images[name]
        n.extension = 'REPEAT'
        link(coordinates, n.inputs['Vector'])
        return n.outputs['Color']

    geometry = node('ShaderNodeNewGeometry', 'World coordinates')
    position = geometry.outputs['Position']
    warp = noise('Slow coordinate warp', PARAMETERS['coordinate_warp_scale'], position)
    centered = vector_math('SUBTRACT', 'Center warp', warp.outputs['Color'], (.5,) * 3)
    warped = vector_math('ADD', 'Warped world coordinates', position,
                         vector_math('SCALE', 'Small warp amplitude', centered,
                                     scale=PARAMETERS['coordinate_warp_amount']))
    patches = noise('Stone orientation patches', PARAMETERS['stone_patch_scale'], position)
    stone_mask = ramp('Stone layer selection', patches.outputs['Fac'], (.36, .64))
    dust_noise = noise('Broad dust deposits', PARAMETERS['dust_patch_scale'], warped)
    dust_mask = ramp('Dust and exposed stone zones', dust_noise.outputs['Fac'],
                     PARAMETERS['dust_mask_interval'])
    normal_strength = mix('Dust softens stone detail', dust_mask,
                          (PARAMETERS['normal_strength_stone'],) * 3 + (1,),
                          (PARAMETERS['normal_strength_dust'],) * 3 + (1,))
    colors, roughness, normals = [], [], []
    for index, recipe in enumerate(PARAMETERS['stone_layers']):
        coordinates = mapping(f'Stone {index} orientation', warped, recipe['scale'],
                              recipe['rotation_degrees'], recipe['offset'])
        colors.append(texture(f'Stone {index} color', required[0], coordinates))
        roughness.append(texture(f'Stone {index} roughness', required[2], coordinates))
        normal = node('ShaderNodeNormalMap', f'Stone {index} normal')
        link(texture(f'Stone {index} normal image', required[1], coordinates), normal.inputs['Color'])
        link(normal_strength, normal.inputs['Strength'])
        # Rotate the sampled normal back with the texture, preserving direction
        # on the flat contact court rather than leaving the old tile's normals.
        rotation = node('ShaderNodeVectorRotate', f'Stone {index} normal direction')
        rotation.rotation_type = 'AXIS_ANGLE'
        rotation.inputs['Angle'].default_value = -math.radians(recipe['rotation_degrees'])
        link(geometry.outputs['Normal'], rotation.inputs['Axis'])
        link(normal.outputs['Normal'], rotation.inputs['Vector'])
        normals.append(rotation.outputs['Vector'])
    stone = mix('Nonrepeating stone blend', stone_mask, *colors)
    grade = node('ShaderNodeHueSaturation', 'Stone restrained color')
    grade.inputs['Saturation'].default_value = .55
    grade.inputs['Value'].default_value = .72
    link(stone, grade.inputs['Color'])
    dust_coords = mapping('Large dust texture', warped, PARAMETERS['dust_texture_scale'], -23)
    dust_photo = texture('Existing terrain dust detail', required[3], dust_coords)
    dust_grade = node('ShaderNodeHueSaturation', 'Neutral dust photograph')
    dust_grade.inputs['Saturation'].default_value = PARAMETERS['dust_photo_saturation']
    dust_grade.inputs['Value'].default_value = .72
    link(dust_photo, dust_grade.inputs['Color'])
    dust = mix('Dust mineral tint', PARAMETERS['dust_tint_mix'],
               dust_grade.outputs['Color'], PARAMETERS['dust_neutral_tint'])
    coverage = node('ShaderNodeMath', 'Keep stone visible beneath dust')
    coverage.operation = 'MULTIPLY'
    coverage.inputs[1].default_value = PARAMETERS['dust_max_color_mix']
    link(dust_mask, coverage.inputs[0])
    link(mix('Stone with broad dust deposits', coverage.outputs[0], grade.outputs['Color'], dust),
         shader.inputs['Base Color'])
    rock_roughness = mix('Stone roughness blend', stone_mask, *roughness)
    link(mix('Dust matte surface', dust_mask, rock_roughness, (.94, .94, .94, 1)),
         shader.inputs['Roughness'])
    difference = vector_math('SUBTRACT', 'Normal difference', normals[1], normals[0])
    normal = vector_math('ADD', 'Blended normal', normals[0],
                         vector_math('SCALE', 'Normal patch blend', difference, scale=stone_mask))
    link(vector_math('NORMALIZE', 'Final ground normal', normal), shader.inputs['Normal'])
    report = {
        'object': floor.name, 'material': material.name, 'parameters': PARAMETERS,
        'images': list(images), 'added_nodes': sum(n.name.startswith(PREFIX) for n in tree.nodes),
        'geometry_changed': False,
        'minimum_stone_color_fraction': 1 - PARAMETERS['dust_max_color_mix'],
        'camera_effect': 'World-anchored 4-10 unit dust/stone zones vary the visible court '
                         'in Establish and Attack; close contact shots see local detail, '
                         'without a screen-space overlay or animated texture swimming.',
        'limits': 'Render review required. Texture normal rotation is designed for the '
                  'horizontal contact court; distant deformed ridges are approximate. '
                  'No new images, geometry, lights, actors or cameras.',
    }
    scene['ground_finish_recipe'] = json.dumps(report)
    return report
