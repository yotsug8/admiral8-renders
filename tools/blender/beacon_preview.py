"""Build a self-contained two-shot Blender exercise and its render job."""
import argparse
from array import array
import json
import math
from pathlib import Path
import sys
import wave

import bpy
from mathutils import Vector


FPS = 24
FRAMES = 72
CUT = 33
CONTACT = 37
PRESS_END = 43
ROLL_START = -2.65
ROLL_END = 0.71
RADIUS = 0.31
SLOPE = 0.175
ANGLE = math.atan(SLOPE)


def surface(x):
    return 0.23 + (0.75 - x) * SLOPE


def ball_height(x):
    return surface(x) + RADIUS / math.cos(ANGLE)


def material(name, color, metal=0.0, roughness=0.4):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1)
    result.use_nodes = True
    shader = result.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = metal
    shader.inputs['Roughness'].default_value = roughness
    return result


def finish(obj, name, coat, bevel=0):
    obj.name = name
    obj.data.materials.append(coat)
    if bevel:
        edge = obj.modifiers.new('Machined edges', 'BEVEL')
        edge.width = bevel
        edge.segments = 3
        obj.modifiers.new('Face normals', 'WEIGHTED_NORMAL')
    return obj


def box(name, center, size, coat, bevel=0.02):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = bpy.context.object
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj, name, coat, bevel)


def sphere(name, center, radius, coat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24,
                                        radius=radius, location=center)
    obj = finish(bpy.context.object, name, coat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def camera(scene, name, position, target, lens, frame):
    bpy.ops.object.camera_add(location=position)
    obj = bpy.context.object
    obj.name = name
    obj.data.lens = lens
    aim(obj, target)
    scene.timeline_markers.new(name, frame=frame).camera = obj


def area(name, position, target, energy, size, color):
    bpy.ops.object.light_add(type='AREA', location=position)
    light = bpy.context.object
    light.name = name
    light.data.energy, light.data.size, light.data.color = energy, size, color
    aim(light, target)


def build_scene(out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 32
    scene.render.resolution_x, scene.render.resolution_y = 640, 360
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_end = FRAMES
    scene.world = bpy.data.worlds.new('Studio')
    scene.world.color = (0.17, 0.19, 0.24)

    floor = material('Matte blue charcoal', (0.026, 0.044, 0.065), roughness=0.62)
    steel = material('Gunmetal', (0.10, 0.16, 0.21), 0.65)
    brass = material('Warm edge trim', (0.46, 0.22, 0.07), 0.7)
    enamel = material('Blue enamel', (0.022, 0.25, 0.46), 0.35, 0.23)
    stripe = material('Ivory stripe', (0.83, 0.76, 0.53), 0.23, 0.26)
    lens = material('Amber lens', (0.70, 0.19, 0.025), 0.1, 0.26)
    box('Studio floor', (0, 0, -0.08), (100, 100, 0.16), floor, bevel=0)

    # The ramp local X points down the slope. The sphere touches its top plane.
    ramp_x = -1.02
    for name, y, offset, width, thickness, coat in (
        ('Track', 0, -0.06, 0.92, 0.12, steel),
        ('Near rail', -0.45, 0.045, 0.065, 0.09, brass),
        ('Far rail', 0.45, 0.045, 0.065, 0.09, brass),
    ):
        center = (ramp_x + math.sin(ANGLE) * offset, y,
                  surface(ramp_x) + math.cos(ANGLE) * offset)
        box(name, center, (4.20, width, thickness), coat, bevel=0.012).rotation_euler.y = ANGLE
    for x in (-2.55, -0.28):
        height = surface(x) - 0.10
        box('Track foot', (x, 0, 0.045), (0.46, 0.87, 0.09), steel)
        box('Track support', (x, 0, height / 2), (0.28, 0.58, height), steel)

    box('Beacon base', (1.49, 0, 0.095), (1.00, 1.07, 0.19), steel, bevel=0.045)
    box('Beacon housing', (1.55, 0, 0.61), (0.60, 0.80, 0.86), steel, bevel=0.065)
    box('Lens collar', (1.55, 0, 1.04), (0.55, 0.62, 0.12), brass)
    sphere('Signal lens', (1.55, 0, 1.12), 0.23, lens)
    z = ball_height(ROLL_END)
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.155, depth=0.30,
                                       location=(1.17, 0, z), rotation=(0, math.pi / 2, 0))
    plunger = finish(bpy.context.object, 'Contact plunger', brass, bevel=0.012)
    ball = sphere('Rolling ball', (ROLL_START, 0, ball_height(ROLL_START)), RADIUS, enamel)
    bpy.ops.mesh.primitive_torus_add(major_segments=64, minor_segments=12,
                                     major_radius=RADIUS - 0.003, minor_radius=0.012)
    band = finish(bpy.context.object, 'Ball rotation stripe', stripe)
    band.parent = ball
    band.rotation_euler.x = math.radians(24)
    for polygon in band.data.polygons:
        polygon.use_smooth = True

    for frame in range(1, FRAMES + 1):
        progress = min(1, (frame - 1) / (CONTACT - 1))
        press = min(1, max(0, (frame - CONTACT) / (PRESS_END - CONTACT)))
        travel = 0.08 * (1 - (1 - press) ** 2)
        x = ROLL_START + (ROLL_END - ROLL_START) * progress ** 1.6 + travel
        ball.location = (x, 0, ball_height(x))
        ball.rotation_euler.y = (x - ROLL_START) / (RADIUS * math.cos(ANGLE))
        ball.keyframe_insert(data_path='location', frame=frame)
        ball.keyframe_insert(data_path='rotation_euler', frame=frame, index=1)
        plunger.location.x = 1.17 + travel
        plunger.keyframe_insert(data_path='location', frame=frame, index=0)

    bpy.ops.object.light_add(type='POINT', location=(1.35, -0.28, 1.34))
    lamp = bpy.context.object.data
    lamp.color, lamp.shadow_soft_size = (1.0, 0.38, 0.095), 0.17
    shader = lens.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Emission Color'].default_value = (1.0, 0.27, 0.025, 1)
    emission = shader.inputs['Emission Strength']
    for frame, level in ((1, 0), (CONTACT, 0), (CONTACT + 4, 1)):
        lamp.energy = 48 * level
        lamp.keyframe_insert(data_path='energy', frame=frame)
        emission.default_value = 2.6 * level
        emission.keyframe_insert(data_path='default_value', frame=frame)

    area('Soft key', (-2.8, -3.8, 5), (0, 0, 0), 850, 4.5, (0.79, 0.89, 1.0))
    area('Warm fill', (3, -2.6, 2.8), (1, 0, 0.6), 330, 3, (1.0, 0.78, 0.56))
    area('Blue rim', (0, 3.5, 4), (0, 0, 0.5), 1000, 3, (0.43, 0.68, 1.0))
    camera(scene, '01 Track', (-0.25, -7.5, 3.0), (-0.62, 0, 0.61), 44, 1)
    camera(scene, '02 Contact', (-0.23, -3.50, 1.74), (1.08, 0, 0.70), 49, CUT)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'scene.blend'))


def audio(out):
    rate = 48000
    contact_time = (CONTACT - 1) / FPS
    samples = array('h')
    for sample in range(FRAMES * rate // FPS):
        t = sample / rate
        progress = min(1, t / contact_time)
        fade = min(1, t / 0.09, max(0, (contact_time - t) / 0.04))
        roll = 0.105 * fade * progress ** 0.55 * (
            math.sin(math.tau * (57 * t + 19 * t * t))
            + 0.36 * math.sin(math.tau * (112 * t + 33 * t * t)))
        impact = t - contact_time
        click = 0 if impact < 0 else 0.56 * math.exp(-72 * impact) * (
            0.7 * math.sin(math.tau * 390 * impact) + 0.3 * math.sin(math.tau * 1180 * impact))
        cue = impact - 4 / FPS
        bell = 0 if cue < 0 else 0.23 * min(1, cue / 0.012) * math.exp(-8 * cue) * (
            math.sin(math.tau * 740 * cue) + 0.29 * math.sin(math.tau * 1109 * cue))
        pan = 0.23 + progress * 0.49
        samples.extend((round(32767 * ((1 - pan) * roll + 0.52 * click + 0.55 * bell)),
                        round(32767 * (pan * roll + 0.75 * click + 0.70 * bell))))
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(out / 'mix.wav'), 'wb') as wav:
        wav.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(samples.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args(sys.argv[sys.argv.index('--') + 1:]).out.resolve()
    out.mkdir(parents=True)
    build_scene(out)
    audio(out)
    job = dict(schema_version=1, scene='scene.blend', out='draft', frames=[1, FRAMES + 1],
               size=[640, 360], fps=FPS, wav='mix.wav')
    (out / 'job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
