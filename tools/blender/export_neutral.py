"""Export a specified BVH frame as world matrices; no scene save or render."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bvh', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--frame', type=int, default=1, help='One-based BVH sample')
    parser.add_argument('--fps', type=int, default=60)
    parser.add_argument('--scale', type=float, default=0.0254/0.45)
    parser.add_argument('--axis-forward', default='-Z')
    parser.add_argument('--axis-up', default='Y')
    parser.add_argument('--bones', nargs='+', default=[
        'Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck', 'Neck1', 'Head'])
    parser.add_argument('--expected-sha256', help='Optional exact input-byte check')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.output.exists():
        parser.error('Output already exists; choose a new file')
    if not args.bvh.is_file() or args.frame < 1 or args.fps < 1 or args.scale <= 0:
        parser.error('Input must exist; frame, FPS and scale must be positive')
    source_hash = hashlib.sha256(args.bvh.read_bytes()).hexdigest()
    if args.expected_sha256 and source_hash != args.expected_sha256.lower():
        parser.error('Input SHA256 differs from expected value')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.fps = args.fps
    scene.render.fps_base = 1
    result = bpy.ops.import_anim.bvh(
        filepath=str(args.bvh.resolve()), target='ARMATURE', global_scale=args.scale,
        frame_start=1, use_fps_scale=False, update_scene_fps=False,
        update_scene_duration=False, rotate_mode='NATIVE',
        axis_forward=args.axis_forward, axis_up=args.axis_up,
    )
    if result != {'FINISHED'}:
        raise RuntimeError('BVH import failed')
    rig = bpy.context.object
    if args.frame > rig.animation_data.action.frame_range[1]:
        parser.error('Requested frame is outside the imported action')
    missing = set(args.bones) - set(rig.pose.bones.keys())
    if missing:
        parser.error('Missing bones: '+', '.join(sorted(missing)))
    scene.frame_set(args.frame)
    matrices = {name: [list(row) for row in rig.matrix_world @ rig.pose.bones[name].matrix]
                for name in args.bones}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as file:
        json.dump(matrices, file, indent=2, allow_nan=False)
        file.write('\n')
    print(json.dumps({'bones': len(matrices), 'source_frame': args.frame,
                      'source_sha256': source_hash, 'scene_saved': False}))


if __name__ == '__main__':
    main()
