"""Render explicit half-open ranges from an already prepared scene.

blender -b scene.blend --disable-autoexec --python-exit-code 2
        -P tools/blender/render_study_frames.py -- --out PATH --range 144:336
No scene preparation, animation edits, or implicit frame-rate conversion.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--range', action='append', required=True, dest='ranges')
    parser.add_argument('--size', nargs=2, type=int, default=[360, 640])
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--camera', help='Named diagnostic camera in the prepared scene')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    scene = bpy.context.scene
    if args.camera:
        camera = bpy.data.objects.get(args.camera)
        if camera is None or camera.type != 'CAMERA':
            raise ValueError('Diagnostic camera not found')
        scene.camera = camera
    if abs(scene.render.fps / scene.render.fps_base - args.fps) > 1e-8:
        raise ValueError('Scene cadence differs: rebuild animation instead of retiming it')
    frames = []
    for item in args.ranges:
        first, stop = map(int, item.split(':'))
        if not scene.frame_start <= first < stop <= scene.frame_end+1:
            raise ValueError('Range outside scene timeline')
        frames.extend(range(first, stop))
    if len(set(frames)) != len(frames) or min(args.size) <= 0:
        raise ValueError('Overlapping ranges or invalid dimensions')
    if args.out.exists():
        raise ValueError('Use a new output directory; existing results are preserved')
    args.out.mkdir(parents=True)
    scene.render.resolution_x, scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = str(args.out / f'f{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
    report = dict(scene=Path(bpy.data.filepath).name, frames=frames, fps=args.fps,
                  size=args.size, blender=bpy.app.version_string,
                  limitations='Prepared scene required; rendering is not visual acceptance.')
    (args.out/'render_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
