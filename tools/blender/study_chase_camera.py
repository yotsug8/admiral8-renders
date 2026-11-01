"""Compare a closer chase camera on a prepared scene without saving over it.

Run in Blender with -- --actors actors_cache.json --out NEW_DIRECTORY.
Only a new camera is animated; actor animation and environment remain untouched.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actors', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--shot', action='store_true', help='Render every candidate frame instead of paired stills')
    parser.add_argument('--start', type=int, default=144)
    parser.add_argument('--end', type=int, default=239)
    parser.add_argument('--offset', type=float, nargs=3, default=(2.5, 8, 2.8))
    parser.add_argument('--target-weight', type=float, default=.8,
                        help='Weight of Hoodwink root in the look target (0..1)')
    parser.add_argument('--candidate-only', action='store_true',
                        help='Skip reference renders when they already exist')
    parser.add_argument('--target-height', type=float, default=1.5)
    parser.add_argument('--validate-only', action='store_true', help='Check framing without rendering')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.end < args.start:
        parser.error('--end must be >= --start')
    if not 0 <= args.target_weight <= 1:
        parser.error('--target-weight must be between 0 and 1')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    actors = json.loads(args.actors.read_text(encoding='utf-8'))
    scene = bpy.context.scene
    original = scene.camera
    camera = bpy.data.objects.new('study_chase_close', original.data.copy())
    scene.collection.objects.link(camera)
    camera.data.animation_data_clear()
    camera.data.dof.aperture_fstop = 5.6
    scene.render.resolution_x = 360
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    points_by_frame = {}
    poses = {}
    for frame in range(args.start, args.end + 1):
        scene.frame_set(frame)
        h = bpy.data.objects[actors['hoodwink']['root']].matrix_world.translation.copy()
        k = bpy.data.objects[actors['kunkka']['root']].matrix_world.translation.copy()
        target = h * args.target_weight + k * (1-args.target_weight) + Vector((0, 0, args.target_height))
        position = h + Vector(args.offset)
        poses[frame] = (position, target)
        dg = bpy.context.evaluated_depsgraph_get()
        points = []
        for actor in actors.values():
            for name in actor['objs']:
                obj = bpy.data.objects[name]
                if obj.type != 'MESH' or any(s in name.lower() for s in ('physics', 'hitbox', 'blob')):
                    continue
                evaluated = obj.evaluated_get(dg)
                points.extend(evaluated.matrix_world @ Vector(v) for v in evaluated.bound_box)
        points_by_frame[frame] = points
    # A single lens for the whole shot avoids per-frame zoom pumping.
    chosen = None
    for lens in range(32, 9, -1):
        camera.data.lens = lens
        fits = True
        for frame, (position, target) in poses.items():
            camera.location = position
            camera.rotation_euler = (target-position).to_track_quat('-Z', 'Y').to_euler()
            bpy.context.view_layer.update()
            uv = [world_to_camera_view(scene, camera, p) for p in points_by_frame[frame]]
            if not all(.065 <= p.x <= .87 and .19 <= p.y <= .92 and p.z > .1 for p in uv):
                fits = False
                break
        if fits:
            chosen = lens
            break
    if chosen is None:
        raise ValueError('Candidate cannot contain both characters in safe framing: '+str((frame, tuple(h), tuple(k), [(min(getattr(p,a) for p in uv),max(getattr(p,a) for p in uv)) for a in ('x','y','z')])))
    for frame, (position, target) in poses.items():
        camera.location = position
        camera.rotation_euler = (target-position).to_track_quat('-Z', 'Y').to_euler()
        camera.keyframe_insert('location', frame=frame)
        camera.keyframe_insert('rotation_euler', frame=frame)
        camera.data.dof.focus_distance = (target-position).length
        camera.data.dof.keyframe_insert('focus_distance', frame=frame)
    for owner in (camera, camera.data):
        for layer in owner.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
    report = {'lens': chosen, 'range': [args.start, args.end], 'offset': list(args.offset),
              'target_weight': args.target_weight,
              'target_height': args.target_height,
              'frames': list(range(args.start, args.end + 1)) if args.shot else sorted({args.start, (args.start + args.end + 1)//2, args.end}),
              'limits': 'Camera-only candidate. Bounding boxes are not an occlusion or artistic-quality test. Source is not saved.'}
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if args.validate_only:
        return
    if args.shot:
        scene.camera = camera
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'camera_candidate.blend'), copy=True)
    for frame in report['frames']:
        scene.frame_set(frame)
        pairs = ([('f', camera)] if args.shot else [('after_', camera)] if args.candidate_only
                 else [('before_', original), ('after_', camera)])
        for label, cam in pairs:
            scene.camera = cam
            scene.render.filepath = str(out/f'{label}{frame:04d}.png')
            bpy.ops.render.render(write_still=True)
    scene.camera = original


if __name__ == '__main__':
    main()
