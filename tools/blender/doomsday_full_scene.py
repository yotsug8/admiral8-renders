"""Whole 14-second lightweight performance, using preserved assets and audio.

Requires the local source pose bank and the reviewed contact excerpt. Neither
the cache nor game resources are distributed with this authoring script.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doomsday_performance as motion
import doomsday_arm_controls as controls
from doomsday_hand_orientation import required_hand_angles
from doomsday_native_pressure import write_pose
from doomsday_pressure_study import main_rig

OUT = ROOT / '_game/skits/doomsday/v12/full_scene'


def smooth(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


def prepare():
    manifest = json.loads((OUT / 'source_bank_manifest.json').read_text(encoding='utf8'))
    with np.load(OUT / 'source_bank.npz') as cache:
        data = {name: cache[name].copy() for name in cache.files}
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / '_game/skits/doomsday/v12/native_pressure/native_pressure.blend'))
    scene = bpy.context.scene
    actors = {name: main_rig(scene, name) for name in ('axe', 'rubick')}
    pressure = {name: [] for name in actors}
    for frame in range(80):
        scene.frame_set(frame)
        for name, actor in actors.items():
            pressure[name].append(motion.snapshot(actor))
    names = {name: manifest['actors'][name]['bone_names'] for name in actors}
    bank = {name: [{bone: Matrix(matrix.tolist()) for bone, matrix in zip(names[name], row)}
                   for row in data[name]] for name in actors}
    transforms = {}
    for name, root in (('axe', 'root'), ('rubick', 'Root_0')):
        transforms[name] = pressure[name][0][root] @ bank[name][327][root].inverted()
        bank[name] = [{bone: transforms[name] @ matrix for bone, matrix in pose.items()} for pose in bank[name]]
    base = pressure['axe'][0]
    control = bpy.data.objects['DoomsdayArmControls_L']
    scene.frame_set(0)
    write_pose(actors['axe'], base)
    control.matrix_world = controls._space(actors['axe'], 'L')
    bpy.context.view_layer.update()
    # Recover the authored pole in the canonical clavicle space, not the last baked frame's control space.
    recipe = json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
    pole_local = Vector(recipe['pole_local'])
    weapon_binding = base['wrist_R'].inverted() @ base['axe_1']
    left_binding = base['axe_1'].inverted() @ base['wrist_L']
    fingers = {side: {b.name: base['wrist_' + side].inverted() @ base[b.name]
                      for b in actors['axe'].pose.bones['wrist_' + side].children_recursive
                      if b.name != 'axe_1' and not b.name.startswith('chain_')}
               for side in ('L', 'R')}
    for actor in actors.values():
        actor.animation_data_clear()
    return scene, actors, pressure, bank, manifest, data, control, pole_local, weapon_binding, left_binding, fingers


def before_contact(frame, state):
    scene, actors, pressure, bank, manifest, data, control, pole_local, weapon_binding, left_binding, fingers = state
    axe = actors['axe']
    source = bank['axe'][frame]
    base = pressure['axe'][0]
    # Preserve the ground preparation/legs, but author the upper-body windup
    # around the actual grip rather than forcing the old incompatible shaft pose.
    settle = smooth((frame - 252) / 27)
    support = motion.mix(axe, source, base, settle)
    attach = support['root'] @ base['root'].inverted()
    authored = {n: attach @ matrix for n, matrix in base.items()}
    for side in ('L', 'R'):
        for bone in [axe.pose.bones['thigh_' + side], *axe.pose.bones['thigh_' + side].children_recursive]:
            authored[bone.name] = support[bone.name]
    if frame < 225:
        lift = motion.curve(frame, ((195, 0), (210, 35), (225, 70)))
    else:
        lift = 70 * (1 - ((frame - 225) / 54) ** 1.7)
    lateral = (authored['bicep_R'].translation - authored['bicep_L'].translation).normalized()
    motion.branch(axe, authored, 'bicep_R', math.radians(lift), lateral)
    pose = motion.mix(axe, source, authored, smooth((frame - 195) / 30))
    pose['axe_1'] = pose['wrist_R'] @ weapon_binding
    for name, local in fingers['R'].items():
        pose[name] = pose['wrist_R'] @ local
    # The opening charge is one-handed; the upper hand joins for the strike.
    held = smooth((frame - 207) / 18)
    write_pose(axe, pose)
    control.matrix_world = controls._space(axe, 'L')
    bpy.context.view_layer.update()
    shoulder = pose['bicep_L'].translation
    lateral = pose['bicep_L'].translation - pose['bicep_R'].translation
    lateral.z = 0
    lateral.normalize()
    forward = lateral.cross(Vector((0, 0, 1))).normalized()
    free_target = shoulder + lateral * .50 + forward * .25 + Vector((0, 0, -.50))
    free_pole = shoulder + lateral * .65 + forward * .10 + Vector((0, 0, -.28))
    target_object = bpy.data.objects[control['target']]
    pole_object = bpy.data.objects[control['pole']]
    target_object.location = control.matrix_world.inverted() @ free_target
    pole_object.location = control.matrix_world.inverted() @ free_pole
    for name in ('forearm_roll', 'hand_flex', 'hand_deviation'):
        control[name] = 0.
    controls.apply_controls(control)
    free_orientation = (axe.matrix_world @ axe.pose.bones['wrist_L'].matrix).to_quaternion()
    if held > 0:
        target = pose['axe_1'] @ left_binding
        approach = free_target.lerp(target.translation, held)
        approach += (lateral * .32 + forward * .12) * math.sin(math.pi * held)
        reach = sum((control.matrix_world.to_3x3() @
                     (control.data.bones[n].tail_local - control.data.bones[n].head_local)).length
                    for n in ('upper', 'lower'))
        if (approach - shoulder).length > .98 * reach and held < 1:
            approach = shoulder + (approach - shoulder).normalized() * (.98 * reach)
        target_object.location = control.matrix_world.inverted() @ approach
        final_pole = control.matrix_world @ pole_local
        pole_object.location = control.matrix_world.inverted() @ free_pole.lerp(final_pole, held)
        angles, error = required_hand_angles(control, free_orientation.slerp(target.to_quaternion(), held))
        for name, value in angles.items():
            control[name] = value
        controls.apply_controls(control)
        reach_error = ((axe.matrix_world @ axe.pose.bones['wrist_L'].matrix).translation - approach).length
        if reach_error > .002:
            raise ValueError(f'Left grasp is unreachable at {frame}: {reach_error:.5f}')
    else:
        angles, error, reach_error = {}, 0., 0.
    pose = motion.snapshot(axe)
    free_pose = {n: matrix.copy() for n, matrix in pose.items()}
    closed_pose = {n: matrix.copy() for n, matrix in pose.items()}
    reference = bank['axe'][225]
    for name, local in fingers['L'].items():
        free_pose[name] = pose['wrist_L'] @ reference['wrist_L'].inverted() @ reference[name]
        closed_pose[name] = pose['wrist_L'] @ local
    closure = smooth((held - .65) / .35)
    pose = motion.mix(axe, free_pose, closed_pose, closure)
    pose['axe_1'] = pose['wrist_R'] @ weapon_binding
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.data.shape_keys:
            corrective = obj.data.shape_keys.key_blocks.get('Authored left finger separation')
            if corrective:
                corrective.value = closure
    defender = motion.mix(actors['rubick'], bank['rubick'][frame], pressure['rubick'][0], smooth((frame - 246) / 33))
    return pose, defender, {'frame': frame, 'left_hold': held, 'reach_error': reach_error,
                           'left_corrective': closure,
                           'angles_degrees': {n: math.degrees(v) for n, v in angles.items()},
                           'orientation_error': error}


def camera(scene, actor_poses, frame):
    axe, rubick = actor_poses
    head, opponent = axe['head'].translation, rubick['Head_0'].translation
    weapon = axe['axe_1'].translation
    cam = scene.camera
    cam.data.type = 'PERSP'
    if frame < 45:
        target = head.lerp(opponent, .5) + Vector((0, 0, -.6))
        offset, lens = Vector((9, -5, 3)), 34
    elif frame < 120:
        target = head.lerp(weapon, .65) + Vector((0, 0, -.1))
        offset, lens = Vector((3.5, -4.5, .7)), 52
    elif frame < 195:
        target = head + Vector((0, 0, -.05))
        offset, lens = Vector((2.5, -3.3, .2)), 60
    elif frame < 252:
        target = head + Vector((0, 0, .2))
        offset, lens = Vector((-6.5, -5, 1.3)), 34
    elif frame < 279:
        target = head.lerp(weapon, .25) + Vector((0, 0, .2))
        offset, lens = Vector((-6, -4, 1)), 32
    elif frame < 291:
        recipe = json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
        target = axe['axe_1'] @ Vector(recipe['contact_weapon_local'])
        offset, lens = Vector((2.7, -1, 1.4)), 72
    elif frame < 330:
        target = head + Vector((0, -.45, -.25))
        offset, lens = Vector((4, -3.5, .5)), 55
    elif frame < 360:
        target = opponent + Vector((0, 0, .15))
        offset, lens = Vector((-3.18, 3.18, .3)), 48
    else:
        target = head + Vector((0, -.15, -.1))
        offset, lens = Vector((2.8, -3.4, .25)), 60
    cam.location = target + offset
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = lens
    cam.keyframe_insert('location', frame=frame)
    cam.keyframe_insert('rotation_euler', frame=frame)
    cam.data.keyframe_insert('lens', frame=frame)


def build(output, probes=False):
    state = prepare()
    scene, actors, pressure, bank, manifest, data, control, *_ = state
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = 'DraftGround'
    floor.color = (.12, .13, .15, 1)
    scene.display.shading.color_type = 'OBJECT'
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.resolution_percentage = 100
    report, result = [], {'axe': [], 'rubick': []}
    selected = (0, 120, 225, 245, 252, 266, 278) if probes else range(420)
    for frame in selected:
        scene.frame_set(frame)
        if frame < 279:
            axe, rubick, row = before_contact(frame, state)
        else:
            index = min(frame - 279, 79)
            axe = {n: m.copy() for n, m in pressure['axe'][index].items()}
            rubick = {n: m.copy() for n, m in pressure['rubick'][index].items()}
            if frame >= 359:
                reaction = smooth((frame - 359) / 60)
                # A sustained confrontation ends with a change of attention, not an idle reset.
                motion.branch(actors['axe'], axe, 'head', math.radians(-3 * reaction), 'Z')
                motion.branch(actors['rubick'], rubick, 'Head_0', math.radians(2 * reaction), 'Z')
            row = {'frame': frame, 'phase': 'contact_or_reaction'}
        report.append(row)
        for name, pose in (('axe', axe), ('rubick', rubick)):
            write_pose(actors[name], pose)
            result[name].append(pose)
        if probes:
            scene.timeline_markers.clear()
            camera(scene, (axe, rubick), frame)
            scene.render.filepath = str(output / f'probe_{frame:03}.png')
            bpy.ops.render.render(write_still=True)
    if probes:
        (output / 'preflight.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        return scene
    for name, actor in actors.items():
        motion.bake(actor, result[name])
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
    for frame in range(420):
        for channel, value in zip(manifest['facial_channels'], data['facial_values'][frame]):
            obj = scene.objects.get(channel['object'])
            if obj and obj.data.shape_keys and channel['shape'] in obj.data.shape_keys.key_blocks:
                key = obj.data.shape_keys.key_blocks[channel['shape']]
                key.value = float(value)
                key.keyframe_insert('value', frame=frame)
        for obj in scene.objects:
            if obj.type == 'MESH' and obj.data.shape_keys:
                corrective = obj.data.shape_keys.key_blocks.get('Authored left finger separation')
                if corrective:
                    corrective.value = report[frame].get('left_corrective', 1.)
                    corrective.keyframe_insert('value', frame=frame)
    scene.timeline_markers.clear()
    scene.camera.animation_data_clear()
    scene.camera.data.animation_data_clear()
    for frame in range(420):
        camera(scene, (result['axe'][frame], result['rubick'][frame]), frame)
    scene.frame_start, scene.frame_end, scene.render.fps = 0, 419, 30
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.resolution_percentage = 100
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.frame_set(0)
    scene['review_status'] = 'WHOLE-SCENE LIGHT DRAFT; independent visual and geometry review pending'
    (output / 'build_report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'full_scene.blend'), compress=True)
    return scene


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--probes', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    build(args.output.resolve(), args.probes)
