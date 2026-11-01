"""Compare a fixed world-space soft fill on prepared scene frames.

Source scene is never saved; no camera-following light or animation edits.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--actor', required=True)
    p.add_argument('--anchor', type=int, default=30)
    p.add_argument('--frames', type=int, nargs='+', default=[30, 90, 360])
    p.add_argument('--energy', type=float, default=400)
    p.add_argument('--kind', choices=['AREA', 'SPOT'], default='AREA')
    p.add_argument('--cone', type=float, default=35)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    scene = bpy.context.scene
    actor = bpy.data.objects.get(args.actor)
    if actor is None or args.energy < 0:
        raise ValueError('Actor missing or negative light energy')
    if not 1 <= args.cone <= 179:
        raise ValueError('Cone must be between 1 and 179 degrees')
    if any(f < scene.frame_start or f > scene.frame_end for f in [args.anchor]+args.frames):
        raise ValueError('Frame outside prepared scene')
    args.out.mkdir(parents=True, exist_ok=False)
    scene.frame_set(args.anchor)
    target = actor.matrix_world.translation + Vector((0, 0, 1.7))
    camera = scene.camera.matrix_world
    towards = (camera.translation-target).normalized()
    right = camera.to_quaternion() @ Vector((1, 0, 0))
    position = target + towards*4 + right*2 + Vector((0, 0, 2))
    data = bpy.data.lights.new('study_fixed_fill', args.kind)
    data.energy = args.energy
    if args.kind == 'AREA':
        data.shape, data.size = 'DISK', 4
    else:
        data.spot_size = math.radians(args.cone)
        data.spot_blend = .65
        data.shadow_soft_size = .6
    data.color = (1, .94, .85)
    fill = bpy.data.objects.new('study_fixed_fill', data)
    scene.collection.objects.link(fill)
    fill.location = position
    fill.rotation_euler = (target-position).to_track_quat('-Z', 'Y').to_euler()
    scene.render.resolution_x, scene.render.resolution_y = 360, 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    for frame in args.frames:
        scene.frame_set(frame)
        for label, hidden in [('before', True), ('fill', False)]:
            fill.hide_render = hidden
            scene.render.filepath = str(args.out/f'{label}_{frame:04d}.png')
            bpy.ops.render.render(write_still=True)
    report = dict(frames=args.frames, energy=args.energy, position=list(position),
                  target=list(target), kind=args.kind, cone=args.cone,
                  size=4 if args.kind == 'AREA' else None, anchor=args.anchor,
                  limits='Still-frame lighting study only. Check shadows and movement before adoption.')
    (args.out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
