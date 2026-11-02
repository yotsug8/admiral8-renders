"""Assemble unchanged performance frames and make timed review sheets.

Normal delivery is exactly 14 seconds at 15 or 30 fps. Sparse probes may
only be assembled as an explicitly labelled short technical test.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw


def sheet(frames, indices, fps, output):
    """Read only selected frames; keep no duplicate full-size image files."""
    if not indices:
        return None
    cell_w, cell_h, columns = 144, 278, 6
    canvas = Image.new('RGB', (columns * cell_w, math.ceil(len(indices) / columns) * cell_h), '#181818')
    draw = ImageDraw.Draw(canvas)
    for slot, index in enumerate(indices):
        x, y = slot % columns * cell_w, slot // columns * cell_h
        with Image.open(frames[index]) as source:
            thumb = source.convert('RGB')
            thumb.thumbnail((132, 242), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (x + (cell_w - thumb.width) // 2, y))
        draw.text((x + 5, y + 245), f'{index / fps:.2f}s / {frames[index].stem}', fill='white')
    canvas.save(output, quality=91)
    return output.name


def assemble(args):
    frames = list(args.frames.glob('*.png'))
    if not frames or any(not path.stem.isdecimal() for path in frames):
        raise ValueError('Input directory must contain numerically named PNG frames')
    frames.sort(key=lambda path: int(path.stem))
    numbers = [int(path.stem) for path in frames]
    if len(set(numbers)) != len(numbers):
        raise ValueError('Duplicate numeric frame identifiers')
    duration = len(frames) / args.fps
    if not args.allow_short_test:
        if len(frames) != 14 * args.fps:
            raise ValueError(f'Expected {14 * args.fps} frames for 14 s, found {len(frames)}; sparse probes require --allow-short-test')
        steps = {right - left for left, right in zip(numbers, numbers[1:])}
        if len(steps) != 1:
            raise ValueError('Nonuniform source frame spacing: possible missing frames')
    if args.audio is not None and not args.audio.is_file():
        raise ValueError(f'Audio file does not exist: {args.audio}')
    if args.output.suffix.lower() != '.mp4':
        raise ValueError('--output must name an MP4 file')
    with Image.open(frames[0]) as source:
        size = source.size
    if any(value % 2 for value in size):
        raise ValueError('H.264 yuv420p requires even image dimensions')
    # Validate sizes before opening an output, rather than failing mid-encode.
    for path in frames:
        with Image.open(path) as source:
            if source.size != size:
                raise ValueError(f'Inconsistent frame size: {path.name}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{size[0]}x{size[1]}',
               '-r', str(args.fps), '-i', 'pipe:0']
    if args.audio:
        command += ['-i', str(args.audio), '-map', '0:v:0', '-map', '1:a:0',
                    '-af', f'apad,atrim=duration={duration:.9f}',
                    '-c:a', 'aac', '-b:a', '192k']
    else:
        command += ['-an']
    command += ['-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-t', f'{duration:.9f}', '-movflags', '+faststart', str(args.output)]
    hashes = []
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        try:
            for path in frames:
                hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
                with Image.open(path) as source:
                    process.stdin.write(source.convert('RGB').tobytes())
        finally:
            process.stdin.close()
        if process.wait():
            raise RuntimeError('Video encoding failed')
    decode = subprocess.run([ffmpeg, '-hide_banner', '-v', 'error', '-i', str(args.output),
                             '-map', '0:v:0', '-an', '-progress', 'pipe:1', '-nostats',
                             '-f', 'null', '-'], capture_output=True, text=True, check=True)
    decoded = [int(line.partition('=')[2]) for line in decode.stdout.splitlines() if line.startswith('frame=')]
    if not decoded or decoded[-1] != len(frames):
        raise RuntimeError(f'Decoded frame count mismatch: {decoded[-1:]}, expected {len(frames)}')
    prefix = args.output.with_suffix('')
    seconds = list(range(0, len(frames), args.fps))
    jump = sorted({round(t * args.fps / 10) for t in range(75, 101)
                   if round(t * args.fps / 10) < len(frames)})
    sheets = [sheet(frames, seconds, args.fps, prefix.with_name(prefix.name + '_seconds.jpg'))]
    if jump:
        sheets.append(sheet(frames, jump, args.fps, prefix.with_name(prefix.name + '_jump.jpg')))
    if args.allow_short_test:
        sheets.append(sheet(frames, list(range(len(frames))), args.fps,
                            prefix.with_name(prefix.name + '_test_frames.jpg')))
    report = {'frames': len(frames), 'fps': args.fps, 'duration_seconds': duration,
              'dimensions': list(size), 'decoded_frames': decoded[-1],
              'mode': 'short_technical_test' if args.allow_short_test else ('motion' if args.fps == 15 else 'draft'),
              'source_frames': numbers, 'frame_sha256': hashes,
              'audio': args.audio.name if args.audio else None,
              'audio_sha256': hashlib.sha256(args.audio.read_bytes()).hexdigest() if args.audio else None,
              'audio_processing': 'pad or trim to video duration; AAC encoding only' if args.audio else None,
              'grade_or_bloom_added': False, 'sheets': sheets,
              'video_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
              'review_status': 'Technical assembly only; full visual review and listening not performed by this script.'}
    prefix.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'frames': len(frames), 'fps': args.fps,
                      'duration_seconds': duration, 'mode': report['mode'], 'sheets': sheets}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=Path, required=True, help='Directory of numeric PNG frame names')
    parser.add_argument('--fps', type=int, choices=(15, 30), required=True)
    parser.add_argument('--audio', type=Path, help='Optional prepared WAV; no loudness or creative processing')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-short-test', action='store_true',
                        help='Treat sparse probes as consecutive test frames, not as a 14-second delivery')
    assemble(parser.parse_args())


if __name__ == '__main__':
    main()
