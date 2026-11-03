"""Short contact performance from a reproducible PALM-controlled pose.

Right arm stays FK. The weapon follows it, the left arm uses native IK,
and the body/legs are authored before the hand solution. This is a light
motion review, not a finished film or a general rig.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doomsday_arm_controls as controls
import doomsday_performance as motion
from doomsday_hand_orientation import required_hand_angles
from doomsday_pressure_study import main_rig


def write_pose(arm, pose):
    inverse = arm.matrix_world.inverted()
    for bone in arm.pose.bones:
        basis = motion._basis(bone, inverse @ pose[bone.name],
                              inverse @ pose[bone.parent.name] if bone.parent else None)
        bone.location, bone.rotation_quaternion, bone.scale = basis.decompose()
        bone.rotation_mode = 'QUATERNION'
    bpy.context.view_layer.update()


def contact_pose(recipe):
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / recipe['source']))
    scene = bpy.context.scene
    axe, rubick = (main_rig(scene, name) for name in ('axe', 'rubick'))
    control = bpy.data.objects['DoomsdayArmControls_L']
    control['wrist_axis_mode'] = 'PALM'
    for name, value in recipe['control_properties'].items():
        control[name] = value
    bpy.data.objects[control['target']].location = recipe['target_local']
    bpy.data.objects[control['pole']].location = recipe['pole_local']
    controls.apply_controls(control)
    pose = motion.snapshot(axe)
    for name, relative in recipe['terminal_relative_wrist'].items():
        pose[name] = pose['wrist_' + name[-1]] @ Matrix(relative)
    write_pose(axe, pose)
    return scene, axe, rubick, control


def hinge(pose, names):
    h, k, w = (pose[name].translation for name in names)
    normal = (k - h).cross(w - k)
    if normal.length < 1e-6:
        raise ValueError('Cannot infer an articulated hinge from a straight chain.')
    return normal.normalized()


def build(output):
    recipe = json.loads(Path(__file__).with_name('doomsday_contact_pose.json').read_text(encoding='utf8'))
    scene, axe, rubick, control = contact_pose(recipe)
    base, defender = motion.snapshot(axe), motion.snapshot(rubick)
    source = {name: {n: m.copy() for n, m in pose.items()}
              for name, pose in (('axe', base), ('rubick', defender))}
    left_binding = base['axe_1'].inverted() @ base['wrist_L']
    contact_local = Vector(recipe['contact_weapon_local'])
    contact = base['axe_1'] @ contact_local
    lateral = (base['bicep_R'].translation - base['bicep_L'].translation).normalized()
    elbow_axis = hinge(base, ('bicep_R', 'elbow_R', 'wrist_R'))
    knee_axes = {side: hinge(base, tuple(n + '_' + side for n in ('thigh', 'knee', 'ankle')))
                 for side in ('L', 'R')}
    pole_local = bpy.data.objects[control['pole']].location.copy()
    for obj in (axe, rubick):
        obj.animation_data_clear()
    result = {'axe': [], 'rubick': []}
    samples = []
    for frame in range(80):
        scene.frame_set(frame)
        pose = {n: m.copy() for n, m in base.items()}
        recoil = motion.curve(frame, ((0, 0), (7, 1), (20, 0), (79, 0)))
        drive = motion.curve(frame, ((0, 0), (12, 0), (35, 1), (54, .8), (79, .55)))
        lag = motion.curve(frame, ((0, 0), (12, 1), (31, -.3), (56, .25), (79, .15)))
        # One recoil followed by a sustained drive; no periodic bouncing.
        motion.branch(axe, pose, 'spine1', math.radians(-1 * recoil + 2 * drive), lateral)
        motion.branch(axe, pose, 'spine2', math.radians(.5 * recoil - drive), 'Z')
        motion.branch(axe, pose, 'head', math.radians(3 * recoil - 3 * drive), lateral)
        motion.branch(axe, pose, 'elbow_R', math.radians(-2 * recoil - 2 * drive), elbow_axis)
        for side, amount in (('L', 6), ('R', -9)):
            motion.branch(axe, pose, 'thigh_' + side, math.radians(amount * lag), lateral)
            motion.branch(axe, pose, 'knee_' + side, math.radians((8 if side == 'L' else 12) * lag), knee_axes[side])
        # Keep the actual blade contact point, allowing the weapon to rock about it.
        shift = contact - pose['axe_1'] @ contact_local
        pose = motion.shift(pose, shift)
        write_pose(axe, pose)
        control.matrix_world = controls._space(axe, 'L')
        bpy.context.view_layer.update()
        target = pose['axe_1'] @ left_binding
        bpy.data.objects[control['target']].location = control.matrix_world.inverted() @ target.translation
        bpy.data.objects[control['pole']].location = pole_local
        angles, error = required_hand_angles(control, target.to_quaternion())
        for name, value in angles.items():
            control[name] = value
        controls.apply_controls(control)
        actual = motion.snapshot(axe)
        goal_error = (actual['wrist_L'].translation - target.translation).length
        if goal_error > .001:
            raise ValueError(f'Native hand target unreachable at frame {frame}: {goal_error}')
        result['axe'].append(actual)
        delta = pose['axe_1'] @ base['axe_1'].inverted()
        hand = delta @ defender['wrist_R']
        defender_pose = motion.solve_arm(rubick, defender, 'R', hand,
                                         defender['elbow_R'].translation - defender['bicep_R'].translation)
        result['rubick'].append(defender_pose)
        samples.append({'frame': frame, 'controls_degrees': {n: math.degrees(v) for n, v in angles.items()},
                        'hand_target_error': goal_error, 'orientation_error_degrees': error,
                        'root_translation': list(shift),
                        'contact_error': (actual['axe_1'] @ contact_local - contact).length})
    for name, actor in (('axe', axe), ('rubick', rubick)):
        motion.bake(actor, result[name])
    scene.frame_start, scene.frame_end, scene.render.fps = 0, 79, 30
    scene.frame_set(0)
    camera_target = Vector((.15, -2.35, 2.5))
    scene.camera.location = camera_target + Vector((4, -3.5, .5))
    scene.camera.rotation_euler = (camera_target - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera.data.ortho_scale = 3.7
    effort_camera = scene.camera
    detail = bpy.data.objects.new('NativeContactDetail', bpy.data.cameras.new('NativeContactDetail'))
    scene.collection.objects.link(detail)
    detail.data.type, detail.data.ortho_scale = 'ORTHO', 1.4
    detail.location = contact + Vector((3, -1, 1.8))
    detail.rotation_euler = (contact - detail.location).to_track_quat('-Z', 'Y').to_euler()
    scene.timeline_markers.clear()
    scene.timeline_markers.new('Blade contact', frame=0).camera = detail
    scene.timeline_markers.new('Effort', frame=12).camera = effort_camera
    scene.render.resolution_x, scene.render.resolution_y = 720, 576
    scene.render.resolution_percentage = 100
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene['review_status'] = 'NATIVE PALM PRESSURE STUDY; full motion and surface review pending'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'build_report.json').write_text(json.dumps({'samples': samples,
        'source': recipe['source'], 'scope': '80-frame contact motion only; no artistic PASS'}, indent=2), encoding='utf8')
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'native_pressure.blend'), compress=True)
    return scene


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probes', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    scene = build(args.output.resolve())
    if args.probes:
        for frame in (0, 7, 35, 55, 79):
            scene.frame_set(frame)
            scene.render.filepath = str(args.output.resolve() / f'probe_{frame:03}.png')
            bpy.ops.render.render(write_still=True)
