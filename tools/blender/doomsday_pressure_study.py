"""Experimental contact-pressure study, using an independently reviewed grip scene.

Blender -b --python this.py -- --source v11.blend --grip candidate.blend
    --output study --no-render
This does not certify the input grip or publish a finished movie.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doomsday_performance as motion
from doomsday_weapon_clearance import FINGER
from doomsday_grip import load_recipe
from doomsday_rubick_stop import correct_pose, WITHDRAWAL_LOCAL, INDEX_ROTATION_LOCAL


def main_rig(scene, actor):
    suffix = actor + '.vmdl_c'
    return next(o for o in scene.objects if o.type == 'ARMATURE'
                and o.name.endswith(suffix) and o.parent
                and o.parent.name == actor + '_root')


def face_values(scene):
    return {o.name: {k.name: float(k.value) for k in o.data.shape_keys.key_blocks[1:]}
            for o in scene.objects if o.type == 'MESH' and o.data.shape_keys}


def build(source, grip, output, first=279, last=358):
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    actors = {name: main_rig(scene, name) for name in ('axe', 'rubick')}
    bank = {name: [] for name in actors}
    for frame in range(first, last + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for name, rig in actors.items():
            bank[name].append(motion.snapshot(rig))

    bpy.ops.wm.open_mainfile(filepath=str(grip))
    scene = bpy.context.scene
    if scene.frame_current != 318:
        raise ValueError('Grip source must be saved at the authored pose, frame 318')
    actors = {name: main_rig(scene, name) for name in ('axe', 'rubick')}
    template = motion.snapshot(actors['axe'])
    inverse_weapon = template['axe_1'].inverted()
    binds = {side: inverse_weapon @ template['wrist_' + side] for side in ('L', 'R')}
    # Roll the lower palm around the shaft so its thumb base does not cross the
    # chest; moving only the elbow cannot fix that contact. The small axial
    # shift keeps the elbow bent without changing either arm's segment lengths.
    section = load_recipe()['shaft_section']
    shaft_axis = (inverse_weapon.to_3x3() @ Vector(section['axis_world'])).normalized()
    shaft_center = inverse_weapon @ Vector(section['centers_world']['R'])
    binds['R'] = motion.around(binds['R'], shaft_center, 25, shaft_axis)
    binds['R'].translation += shaft_axis * (.24 / (template['axe_1'].to_3x3() @ shaft_axis).length)
    fingers = {side: {b.name: template['wrist_' + side].inverted() @ template[b.name]
                     for b in actors['axe'].pose.bones
                     if FINGER.fullmatch(b.name) and b.name.endswith('_' + side)}
               for side in ('L', 'R')}
    faces = []
    for frame in range(first, last + 1):
        scene.frame_set(frame)
        faces.append(face_values(scene))
    scene.frame_set(318)
    for obj in scene.objects:
        if obj not in actors.values():
            obj.animation_data_clear()
    for obj in list(scene.objects):
        if obj.name.startswith('GripDiagnostic'):
            bpy.data.objects.remove(obj, do_unlink=True)

    result = {name: [] for name in actors}
    grip_drift = 0.0
    for i, frame in enumerate(range(first, last + 1)):
        pose = bank['axe'][i]
        weapon = Matrix.Translation((.8, 0, 0)) @ pose['axe_1']
        # Preserve room for the ribcage beneath the fixed weapon at peak effort.
        # This changes the body's approach, rather than hiding a wrist collision
        # with a different elbow pole or a camera cut.
        retreat = motion.curve(frame, ((279, 0), (312, 0), (324, .12),
                                      (332, .12), (345, 0), (358, 0)))
        pose = motion.shift(pose, Vector((0, max(0.0, retreat), 0)))
        load = motion.curve(frame, ((279, .10), (287, 0), (304, .60),
                                   (318, 1), (337, .72), (358, .42)))
        load = max(0.0, min(1.0, load))
        drive = motion.curve(frame, ((279, 0), (304, 0), (318, .75),
                                     (329, 1), (343, .6), (358, .4)))
        drive = max(0.0, min(1.0, drive))
        # Establish a readable torso direction before adding the pressure phrase.
        motion.branch(actors['axe'], pose, 'spine1', math.radians(25), 'Z')
        motion.branch(actors['axe'], pose, 'head', math.radians(-25), 'Z')
        motion.branch(actors['axe'], pose, 'spine1', math.radians(12 + 6 * load - 9 * drive), 'X')
        motion.branch(actors['axe'], pose, 'spine2', math.radians(-12 - 8 * drive), 'Z')
        motion.branch(actors['axe'], pose, 'head', math.radians(18 + 8 * drive), 'Z')
        # Counter the thorax pitch: effort is directed at the opponent, not
        # expressed by staring down at the handle throughout the entire shot.
        motion.branch(actors['axe'], pose, 'head', math.radians(-2 - 3 * load), 'X')
        motion.branch(actors['axe'], pose, 'clavicle_R', math.radians(-18), 'Y')
        poles = {
            'R': Vector((-1, -.6, -1.2)).lerp(Vector((-1, -.75, -1.2)), load),
            'L': Vector((1, 0, -.6)).lerp(Vector((1, -.5, .65)), load),
        }
        for side in ('R', 'L'):
            target = weapon @ binds[side]
            try:
                pose = motion.solve_arm(actors['axe'], pose, side, target, poles[side])
            except ValueError as exc:
                h, k, w = (pose[n + '_' + side].translation for n in ('bicep', 'elbow', 'wrist'))
                raise ValueError(f'Frame {frame}, {side}: target distance {(target.translation-h).length:.5f}; '
                                 f'arm length {(k-h).length+(w-k).length:.5f}') from exc
            for name, local in fingers[side].items():
                pose[name] = target @ local
            grip_drift = max(grip_drift, (weapon.inverted() @ pose['wrist_' + side]
                                         - binds[side]).to_translation().length)
        pose['axe_1'] = weapon  # The weapon is a wrist descendant; set it last.
        for side in ('L', 'R'):
            foot = pose['ankle_' + side].copy()
            if side == 'L':
                offset = Vector((.338,
                    motion.curve(frame, ((279, .10), (292, .44), (318, .312), (358, .37))),
                    motion.curve(frame, ((279, -.45), (292, -.65), (318, -.583), (358, -.61)))))
            else:
                offset = Vector((-.242,
                    motion.curve(frame, ((279, .50), (296, .72), (318, .712), (358, .62))),
                    motion.curve(frame, ((279, -.70), (296, -.82), (318, -.863), (358, -.84)))))
            foot.translation = pose['root'].translation + offset
            pose, _ = motion.solve(actors['axe'], pose,
                                   tuple(n + '_' + side for n in ('thigh', 'knee', 'ankle')),
                                   foot, None)
        result['axe'].append(pose)
        defender = motion.shift(bank['rubick'][i], Vector((.8, 0, 0)))
        staff_hand = defender['wrist_L'].copy()
        staff_hand.translation.x -= .20
        pole = defender['elbow_L'].translation - defender['bicep_L'].translation
        defender = motion.solve_arm(actors['rubick'], defender, 'L', staff_hand, pole)
        defender = correct_pose(actors['rubick'], defender, weapon,
                                WITHDRAWAL_LOCAL, INDEX_ROTATION_LOCAL)
        result['rubick'].append(defender)

    for name, rig in actors.items():
        motion.bake(rig, result[name])
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
    for i, state in enumerate(faces):
        for name, values in state.items():
            obj = scene.objects.get(name)
            if obj and obj.type == 'MESH' and obj.data.shape_keys:
                for key, value in values.items():
                    block = obj.data.shape_keys.key_blocks.get(key)
                    if block:
                        block.value = value
                        block.keyframe_insert('value', frame=i)
    scene.frame_start = 0
    scene.frame_end = last - first
    scene.render.fps = 30
    scene.frame_set(318 - first)
    # A fixed working shot; never inherit an isolated grip inspection camera.
    bpy.context.view_layer.update()
    target = (actors['axe'].matrix_world @ actors['axe'].pose.bones['head'].head
              + Vector((.15, -.05, -.2)))
    scene.camera.data.type = 'PERSP'
    scene.camera.data.lens = 45
    scene.camera.location = target + Vector((-2.7, -2.5, .3))
    scene.camera.rotation_euler = (target - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
    effort_camera = scene.camera
    contact_camera = bpy.data.objects.new('v12_contact_working', bpy.data.cameras.new('v12_contact_working'))
    scene.collection.objects.link(contact_camera)
    contact_camera.data.type = 'ORTHO'
    contact_camera.data.ortho_scale = 1.25
    contact_camera.data.clip_start = .01
    contact_camera.location = Vector((-2.22517072, -4.94930679, 5.60395810))
    contact_target = Vector((-.81682985, -3.43153016, 3.35164149))
    contact_camera.rotation_euler = (contact_target - contact_camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.timeline_markers.clear()
    scene.timeline_markers.new('Contact surface', frame=0).camera = contact_camera
    scene.timeline_markers.new('Directed effort', frame=18).camera = effort_camera
    for obj in scene.objects:
        root = obj
        while root.parent:
            root = root.parent
        if obj.type == 'MESH':
            obj.hide_render = root.name not in ('axe_root', 'rubick_root')
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = 640, 360
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene['review_status'] = 'EXPERIMENTAL; grip, surfaces, image and motion require independent review'
    output.mkdir(parents=True, exist_ok=True)
    report = {'source': source.name, 'grip_source': grip.name, 'source_frames': [first, last],
              'frames': last - first + 1, 'fps': 30,
              'wrist_binding_position_drift': grip_drift,
              'limits': ['Binding stability does not certify a correct grip.',
                         'Only contact-pressure excerpt; jump and complete editing are not checked.',
                         'No surface or artistic pass is implied by successful baking.']}
    (output / 'build_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    previous = bpy.context.preferences.filepaths.save_version
    try:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(output / 'pressure_study.blend'), compress=True)
    finally:
        bpy.context.preferences.filepaths.save_version = previous
    return scene


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--grip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-render', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    scene = build(args.source.resolve(), args.grip.resolve(), args.output.resolve())
    if not args.no_render:
        scene.render.filepath = str(args.output.resolve() / 'frames' / '') + '/'
        bpy.ops.render.render(animation=True)
