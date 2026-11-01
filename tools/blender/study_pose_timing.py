"""Isolated shoulder-led gesture: preparation, indicate, hold, return.

Uses the same world-direction rotation as skit_talk. Optional --reach uses the
existing two-bone solver from contact_reaction, preserving the wrist orientation.
Run inside a prepared static hero scene with --out NEW_DIRECTORY.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector


def smooth(t):
    t = max(0., min(1., t))
    return t*t*t*(10+t*(-15+6*t))


def rotation(frame, prep, point):
    keys = [(0, Quaternion()), (6, Quaternion()), (21, prep),
            (39, point), (57, point), (75, Quaternion()), (84, Quaternion())]
    for (a, qa), (b, qb) in zip(keys, keys[1:]):
        if a <= frame <= b:
            return qa.slerp(qb, smooth((frame-a)/(b-a)))
    raise ValueError('Frame outside study')


def position(frame, start, prep, target):
    keys = [(0, start), (6, start), (21, prep), (39, target),
            (57, target), (75, start), (84, start)]
    for (a, pa), (b, pb) in zip(keys, keys[1:]):
        if a <= frame <= b:
            return pa.lerp(pb, smooth((frame-a)/(b-a)))
    raise ValueError('Frame outside study')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--actor', choices=('pudge', 'sniper'), default='pudge')
    parser.add_argument('--max-angle', type=float, default=15., help='Maximum shoulder excursion in degrees')
    parser.add_argument('--reach', action='store_true', help='Solve shoulder/elbow/wrist toward a bounded target')
    parser.add_argument('--reach-ratio', type=float, default=.94, help='Final shoulder-to-wrist distance / arm length')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not 0 < args.max_angle <= 30:
        raise ValueError('Initial shoulder study supports excursions up to 30 degrees')
    if not .8 <= args.reach_ratio <= .97:
        raise ValueError('Keep a visible elbow bend: reach ratio must be .8 to .97')
    if args.out.exists():
        raise ValueError('Use a new study directory')
    args.out.mkdir(parents=True)
    sc = bpy.context.scene
    sc.frame_set(0)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from contact_metrics import resolve
    _, arm, members = resolve(args.actor, list(sc.objects))
    shoulder, elbow, wrist = [arm.pose.bones[n] for n in ('bicep_L', 'elbow_L', 'wrist_L')]
    if any(b.constraints for b in (shoulder, elbow, wrist)):
        raise ValueError('Study requires an unconstrained arm')
    base = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
    base_pose = {b.name: b.matrix.copy() for b in arm.pose.bones}
    world = arm.matrix_world.copy()
    origin = (world @ shoulder.matrix).translation
    vector = (world @ wrist.matrix).translation-origin
    original_shoulder = world @ shoulder.matrix
    base_world = {n: world @ m for n, m in base_pose.items()}
    start = base_world[wrist.name].translation.copy()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from contact_reaction import _solve_leg, _basis
    protected = [b for b in arm.pose.bones if b.name not in
                 {shoulder.name, *[c.name for c in shoulder.children_recursive]}]
    protected_base = {b.name: (world @ b.matrix).copy() for b in protected}
    original_lengths = [((world @ a.matrix).translation-(world @ b.matrix).translation).length
                        for a, b in ((shoulder, elbow), (elbow, wrist))]
    for obj in sc.objects:
        name = obj.name.lower()
        other_actor = 'sniper' if args.actor == 'pudge' else 'pudge'
        if (other_actor in name or (obj in members and
                ('leftweapon' in name or (args.actor == 'sniper' and 'weapon' in name)))):
            obj.hide_render = True
    # Neutral diagnostic floor; the prepared map patch is not a study backdrop.
    ground = bpy.data.objects.get('Plane')
    floor_z = ground.location.z if ground else 0.
    if ground:
        ground.hide_render = True
    mesh = bpy.data.meshes.new('study_floor')
    mesh.from_pydata([(-200, -200, floor_z), (200, -200, floor_z),
                     (200, 200, floor_z), (-200, 200, floor_z)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new('study_floor', mesh)
    sc.collection.objects.link(floor)
    material = bpy.data.materials.new('study_floor')
    material.diffuse_color = (.18, .2, .23, 1.)
    mesh.materials.append(material)
    if arm.animation_data:
        arm.animation_data.action = None
        for track in arm.animation_data.nla_tracks:
            track.mute = True
    for b in arm.pose.bones:
        b.matrix_basis = base[b.name]
        b.keyframe_insert('location', frame=0)
        b.keyframe_insert('rotation_quaternion' if b.rotation_mode == 'QUATERNION' else 'rotation_euler', frame=0)
        b.keyframe_insert('scale', frame=0)
    seed = arm.animation_data.action
    reports = []
    for name, local_direction in [('A', (.65, -1, .2)), ('B', (.95, -.8, .2))]:
        action = seed.copy()
        action.name = 'study_point_'+name
        arm.animation_data.action = action
        prep_vector = vector + world.to_3x3() @ Vector((.08, 0, -.04))
        prep = vector.rotation_difference(prep_vector)
        direction = world.to_3x3() @ Vector(local_direction)
        point = vector.rotation_difference(direction)
        point = Quaternion().slerp(point, min(1., math.radians(args.max_angle)/max(point.angle, 1e-9)))
        prep_position = origin + prep_vector
        target_position = origin + (point @ vector).normalized() * (sum(original_lengths)*args.reach_ratio)
        last_q = {}
        pole = None
        corrected = (shoulder, elbow, wrist) if args.reach else (shoulder,)
        for i in range(337):
            frame = i/4
            for b in arm.pose.bones:
                b.matrix_basis = base[b.name]
            bpy.context.view_layer.update()
            if args.reach:
                desired = {}
                target = base_world[wrist.name].copy()
                target.translation = position(frame, start, prep_position, target_position)
                pole = _solve_leg(base_world, desired, (shoulder.name, elbow.name, wrist.name),
                                  Vector((0, 0, 0)), pole, world.to_3x3() @ Vector((1, 0, 0)), target)
                for b in corrected:
                    pose = world.inverted() @ desired[b.name]
                    parent = world.inverted() @ desired[b.parent.name] if b.parent.name in desired else base_pose[b.parent.name]
                    b.matrix_basis = _basis(b, pose, parent)
            else:
                q = rotation(frame, prep, point)
                shoulder.matrix = world.inverted() @ (Matrix.Translation(origin) @
                    q.to_matrix().to_4x4() @ Matrix.Translation(-origin) @ original_shoulder)
            bpy.context.view_layer.update()
            for b in corrected:
                if b.name in last_q and b.rotation_quaternion.dot(last_q[b.name]) < 0:
                    b.rotation_quaternion.negate()
                last_q[b.name] = b.rotation_quaternion.copy()
                b.keyframe_insert('rotation_quaternion', frame=frame)
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
        max_protected = max_length = max_target = max_wrist_angle = 0.
        wrist_positions, endpoint_matrices, elbow_angles = [], [], []
        for i in range(673):
            frame = i/8
            sc.frame_set(int(frame), subframe=frame % 1)
            bpy.context.view_layer.update()
            wrist_positions.append((world @ wrist.matrix).translation.copy())
            if i in (0, 672):
                endpoint_matrices.append({b.name: (world @ b.matrix).copy() for b in corrected})
            upper = (world @ elbow.matrix).translation-(world @ shoulder.matrix).translation
            lower = (world @ wrist.matrix).translation-(world @ elbow.matrix).translation
            elbow_angles.append(math.degrees(upper.angle(lower)))
            for b in protected:
                m = world @ b.matrix
                max_protected = max(max_protected, max(abs(m[r][c]-protected_base[b.name][r][c])
                                                       for r in range(4) for c in range(4)))
            for j, (a, b) in enumerate(((shoulder, elbow), (elbow, wrist))):
                length = ((world @ a.matrix).translation-(world @ b.matrix).translation).length
                max_length = max(max_length, abs(length-original_lengths[j]))
            if args.reach:
                actual = world @ wrist.matrix
                max_target = max(max_target, (actual.translation-position(frame, start, prep_position, target_position)).length)
                max_wrist_angle = max(max_wrist_angle, actual.to_quaternion().rotation_difference(base_world[wrist.name].to_quaternion()).angle)
        if max_protected > 1e-5 or max_length > .001:
            raise ValueError(f'Protected pose/arm length changed: {max_protected}, {max_length}')
        if args.reach and (max_target > .001 or max_wrist_angle > .003):
            raise ValueError(f'Reach playback mismatch: position {max_target}, rotation {max_wrist_angle}')
        endpoint_error = max(abs(endpoint_matrices[0][n][r][c]-endpoint_matrices[1][n][r][c])
                             for n in endpoint_matrices[0] for r in range(4) for c in range(4))
        if endpoint_error > 1e-5 or min(elbow_angles) < 5.:
            raise ValueError('Gesture does not return to baseline or locks the elbow')
        velocities = [(b-a)*240 for a, b in zip(wrist_positions, wrist_positions[1:])]
        accelerations = [(b-a)*240 for a, b in zip(velocities, velocities[1:])]
        from bpy_extras.object_utils import world_to_camera_view
        points = []
        for frame in range(85):
            sc.frame_set(frame)
            dg = bpy.context.evaluated_depsgraph_get()
            for obj in sc.objects:
                if (obj.type == 'MESH' and obj in members and not obj.hide_render
                        and not any(tag in obj.name.lower() for tag in ('blob', 'hitbox', 'physics'))):
                    ev = obj.evaluated_get(dg)
                    points.extend(ev.matrix_world @ Vector(v) for v in ev.bound_box)
        if not points:
            raise ValueError('No visible actor mesh bounds')
        lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center = (lo+hi)/2
        sc.render.resolution_x, sc.render.resolution_y = 360, 640
        sc.render.resolution_percentage = 100
        for label, offset in [('front', (3, -10, 2)), ('side', (10, -3, 2))]:
            cname = 'study_'+label
            camera = bpy.data.objects.get(cname)
            if camera is None:
                camera = bpy.data.objects.new(cname, bpy.data.cameras.new(cname))
                sc.collection.objects.link(camera)
            camera.location = center + world.to_3x3() @ (Vector(offset)*3)
            camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
            camera.data.type = 'ORTHO'
            camera.data.clip_end = 1000.
            camera.data.ortho_scale = (hi-lo).length
            camera.data.dof.use_dof = False
            bpy.context.view_layer.update()
            for _ in range(50):
                uv = [world_to_camera_view(sc, camera, p) for p in points]
                if all(.05 <= p.x <= .95 and .05 <= p.y <= .95 and p.z > 0 for p in uv):
                    break
                camera.data.ortho_scale *= 1.05
            else:
                raise ValueError('Cannot fit the complete gesture')
        sc.camera = bpy.data.objects['study_front']
        sc.frame_start, sc.frame_end = 0, 84
        sc.render.fps, sc.render.fps_base = 30, 1.
        sc.frame_set(0)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.out/f'point_{name}.blend'))
        reports.append(dict(actor=args.actor, variant=name, samples=673, max_protected_matrix_error=max_protected,
                            max_segment_length_error_m=max_length, direction=list(local_direction),
                            direction_excursion_degrees=math.degrees(point.angle), reach=args.reach,
                            target_error_m=max_target if args.reach else None,
                            wrist_orientation_error_rad=max_wrist_angle if args.reach else None,
                            reach_ratio=args.reach_ratio if args.reach else None,
                            endpoint_matrix_error=endpoint_error,
                            elbow_bend_degrees=[min(elbow_angles), max(elbow_angles)],
                            wrist_peak_speed_m_s=max(v.length for v in velocities),
                            wrist_peak_acceleration_m_s2=max(a.length for a in accelerations)))
    (args.out/'pose_qa.json').write_text(json.dumps(dict(cases=reports,
        limits='Skeleton witnesses only. Reach target is the wrist bone origin, not palm surface contact; surfaces, camera, and artistic result still need review.'), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
