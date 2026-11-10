"""Render explicit half-open ranges from an already prepared scene.

blender -b scene.blend --disable-autoexec --python-exit-code 2
        -P tools/blender/render_study_frames.py -- --out PATH --range 144:336
No scene preparation, animation edits, or implicit frame-rate conversion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render_storage import cached_file, file_lock


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, data):
    content = json.dumps(data, indent=2, ensure_ascii=False)
    cached_file(path, lambda p: p.write_text(content, encoding='utf-8'),
                lambda p: p.read_text(encoding='utf-8') == content)


def render_frame(scene, number, path):
    scene.frame_set(number)
    scene.render.filepath = str(path)
    if bpy.ops.render.render(write_still=True) != {'FINISHED'}:
        raise RuntimeError(f'Blender не завершил кадр {number}')


def complete_png(path, size):
    with path.open('rb') as source:
        header = source.read(24)
        if len(header) != 24 or header[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            return False
        if struct.unpack('>II', header[16:]) != tuple(size):
            return False
        source.seek(-12, 2)
        return source.read() == b'\x00\x00\x00\x00IEND\xaeB`\x82'


def resume(scene, args, frames, report):
    if not bpy.data.filepath:
        raise ValueError('Сначала сохраните сцену в .blend')
    external = bpy.utils.blend_paths(absolute=True, packed=False)
    if external:
        raise ValueError(f'Для возобновления нужна автономная сцена. Внешняя зависимость: {external[0]}')
    source = Path(bpy.data.filepath)
    identity = dict(schema=1, source=digest(source), renderer=digest(Path(__file__).resolve()),
                    build=bpy.app.build_hash.decode('ascii'), scene=scene.name,
                    size=args.size, fps=args.fps, camera=args.camera)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / 'render_job.json'
    with file_lock(args.out / 'render.lock'):
        if manifest.exists():
            if json.loads(manifest.read_text(encoding='utf-8')) != identity:
                raise ValueError('Сцена, Blender или настройки изменились. Укажите новую папку кадров')
        else:
            if any(p.name not in ('render.lock', 'render_job.json.lock')
                   and not (p.name.startswith('.render_job.') and p.suffix == '.json')
                   for p in args.out.iterdir()):
                raise ValueError('В папке есть кадры без сведений об исходной сцене. Укажите новую папку')
            write_json(manifest, identity)

        reused, rendered = [], []
        for number in frames:
            destination = args.out / f'f{number:04d}.png'
            record = destination.with_suffix('.sha256')

            def verified(path):
                try:
                    return (record.is_file() and path.is_file()
                            and record.read_text(encoding='ascii') == digest(path))
                except (OSError, UnicodeError):
                    return False

            if verified(destination):
                reused.append(number)
                continue
            cached_file(destination, lambda path: render_frame(scene, number, path),
                        lambda path: verified(path) if path == destination else complete_png(path, args.size))
            checksum = digest(destination)
            cached_file(record, lambda p: p.write_text(checksum, encoding='ascii'),
                        lambda p: p.read_text(encoding='ascii') == checksum)
            rendered.append(number)
        if digest(source) != identity['source']:
            raise RuntimeError('Исходная сцена изменена во время рендера. Используйте новую папку кадров')
        write_json(args.out / 'render_report.json', dict(report, reused=reused, rendered=rendered))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--range', action='append', required=True, dest='ranges')
    parser.add_argument('--size', nargs=2, type=int, default=[360, 640])
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--camera', help='Named diagnostic camera in the prepared scene')
    parser.add_argument('--resume', action='store_true', help='Reuse verified frames for an unchanged packed scene')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    scene = bpy.context.scene
    if args.camera:
        camera = scene.objects.get(args.camera)
        if camera is None or camera.type != 'CAMERA':
            raise ValueError('Diagnostic camera not found')
        # frame_set restores the camera from timeline markers. Disable those
        # bindings in this loaded copy so every diagnostic frame uses the override.
        for marker in scene.timeline_markers:
            marker.camera = None
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
    if args.out.exists() and not args.resume:
        raise ValueError('Use a new output directory; existing results are preserved')
    scene.render.resolution_x, scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.use_file_extension = True
    report = dict(scene=Path(bpy.data.filepath).name, frames=frames, fps=args.fps,
                  size=args.size, blender=bpy.app.version_string,
                  limitations='Prepared scene required; rendering is not visual acceptance.')
    if args.resume:
        resume(scene, args, frames, report)
        return
    args.out.mkdir(parents=True)
    for frame in frames:
        render_frame(scene, frame, args.out / f'f{frame:04d}.png')
    (args.out/'render_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
