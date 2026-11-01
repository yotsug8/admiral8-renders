"""Isolated shoulder-led gesture: preparation, indicate, hold, return.

Uses the same world-direction rotation as skit_talk. This first exercise keeps
the elbow bend fixed; it is not the two-bone reaching proposal in POSE_TIMING.md.
Run inside a prepared static Pudge scene with --out NEW_DIRECTORY.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-angle', type=float, default=15., help='Maximum shoulder excursion in degrees')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not 0 < args.max_angle <= 30:
        raise ValueError('Initial shoulder study supports excursions up to 30 degrees')
    if args.out.exists():
        raise ValueError('Use a new study directory')
    args.out.mkdir(parents=True)
    sc = bpy.context.scene
    sc.frame_set(0)
    arm = next(o for o in sc.objects if o.type == 'ARMATURE' and o.name.endswith('pudge.vmdl_c'))
    shoulder, elbow, wrist = [arm.pose.bones[n] for n in ('bicep_L', 'elbow_L', 'wrist_L')]
    if any(b.constraints for b in (shoulder, elbow, wrist)):
        raise ValueError('Study requires an unconstrained arm')
    base = {b.name: b.matrix_basis.copy() for b in arm.pose.bones}
    world = arm.matrix_world.copy()
    origin = (world @ shoulder.matrix).translation
    vector = (world @ wrist.matrix).translation-origin
    original_shoulder = world @ shoulder.matrix
    protected = [b for b in arm.pose.bones if b.name not in
                 {shoulder.name, *[c.name for c in shoulder.children_recursive]}]
    protected_base = {b.name: (world @ b.matrix).copy() for b in protected}
    original_lengths = [((world @ a.matrix).translation-(world @ b.matrix).translation).length
                        for a, b in ((shoulder, elbow), (elbow, wrist))]
    for obj in sc.objects:
        if 'leftweapon' in obj.name.lower() or 'sniper' in obj.name.lower():
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
        last_q = None
        for i in range(337):
            frame = i/4
            for b in arm.pose.bones:
                b.matrix_basis = base[b.name]
            bpy.context.view_layer.update()
            q = rotation(frame, prep, point)
            shoulder.matrix = world.inverted() @ (Matrix.Translation(origin) @
                q.to_matrix().to_4x4() @ Matrix.Translation(-origin) @ original_shoulder)
            bpy.context.view_layer.update()
            if last_q is not None and shoulder.rotation_quaternion.dot(last_q) < 0:
                shoulder.rotation_quaternion.negate()
            last_q = shoulder.rotation_quaternion.copy()
            shoulder.keyframe_insert('rotation_quaternion', frame=frame)
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
        max_protected = max_length = 0.
        for i in range(673):
            frame = i/8
            sc.frame_set(int(frame), subframe=frame % 1)
            bpy.context.view_layer.update()
            for b in protected:
                m = world @ b.matrix
                max_protected = max(max_protected, max(abs(m[r][c]-protected_base[b.name][r][c])
                                                       for r in range(4) for c in range(4)))
            for j, (a, b) in enumerate(((shoulder, elbow), (elbow, wrist))):
                length = ((world @ a.matrix).translation-(world @ b.matrix).translation).length
                max_length = max(max_length, abs(length-original_lengths[j]))
        if max_protected > 1e-5 or max_length > .001:
            raise ValueError(f'Protected pose/arm length changed: {max_protected}, {max_length}')
        from bpy_extras.object_utils import world_to_camera_view
        points = []
        for frame in range(85):
            sc.frame_set(frame)
            dg = bpy.context.evaluated_depsgraph_get()
            for obj in sc.objects:
                if (obj.type == 'MESH' and 'pudge' in obj.name.lower() and not obj.hide_render
                        and not any(tag in obj.name.lower() for tag in ('blob', 'hitbox', 'physics'))):
                    ev = obj.evaluated_get(dg)
                    points.extend(ev.matrix_world @ Vector(v) for v in ev.bound_box)
        if not points:
            raise ValueError('No visible Pudge mesh bounds')
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
            camera.location = center + world.to_3x3() @ Vector(offset)
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
        reports.append(dict(variant=name, samples=673, max_protected_matrix_error=max_protected,
                            max_segment_length_error_m=max_length, direction=list(local_direction),
                            shoulder_excursion_degrees=math.degrees(point.angle)))
    (args.out/'pose_qa.json').write_text(json.dumps(dict(cases=reports,
        limits='Skeleton witnesses only. Shoulder-led gesture with fixed elbow bend; surfaces, camera, and artistic result still need review.'), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
