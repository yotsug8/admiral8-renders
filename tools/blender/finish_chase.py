"""CPU assembly without frame-rate conversion or implicit audio selection.

Legacy timing: --audio audio/chase_mix.wav (279 source / 288 total frames).
New timing: --audio NEW.wav --black-start 12.5 --duration 12.8
            --frame-count 375 --fps 30 --source-fps 30
PNG sequences must contain exactly frame-count images, starting at f0000.png.
--source-fps declares their render cadence; PNGs do not store timestamps.
"""
import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw


def probe(path, executable='ffprobe'):
    result = subprocess.run([executable, '-v', 'error', '-count_frames',
                             '-show_streams', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)['streams']


def frame_number(seconds, fps):
    value = seconds * fps
    if not math.isfinite(value) or abs(value-round(value)) > 1e-6:
        raise ValueError('Timeline boundaries must lie on exact frame boundaries')
    return round(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True, help='Explicit WAV, relative to cwd')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--frames', type=Path)
    source.add_argument('--video', type=Path, help='Native CFR source; no fps conversion')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--source-fps', type=int, default=30, help='Actual PNG render cadence')
    parser.add_argument('--width', type=int, default=1080)
    parser.add_argument('--height', type=int, default=1920)
    parser.add_argument('--frame-count', type=int, help='Source frames, excluding black tail')
    parser.add_argument('--duration', type=float, default=9.6)
    parser.add_argument('--black-start', type=float, default=9.3)
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--skip-preview', action='store_true')
    args = parser.parse_args()
    folder = args.folder.resolve()
    frames = args.frames or folder/'frames_full'
    if args.fps <= 0 or min(args.width, args.height) <= 0 or args.width % 2 or args.height % 2:
        raise ValueError('Positive fps and even positive dimensions required')
    if not 0 < args.black_start < args.duration:
        raise ValueError('Require 0 < black-start < duration')
    count = frame_number(args.black_start, args.fps)
    total = frame_number(args.duration, args.fps)
    if args.frame_count is not None and args.frame_count != count:
        raise ValueError('frame-count must equal black-start * fps')
    if args.audio.suffix.lower() != '.wav':
        raise ValueError('Supply the explicit new WAV')
    audio = probe(args.audio, args.ffprobe)
    audio = [s for s in audio if s['codec_type'] == 'audio']
    if len(audio) != 1 or audio[0]['channels'] != 2:
        raise ValueError('WAV must have exactly one stereo stream')
    if abs(float(audio[0]['duration'])-args.duration) > 1/int(audio[0]['sample_rate']) + 1e-6:
        raise ValueError('WAV duration differs from timeline; no padding or stretching allowed')
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    stats = []
    if args.video:
        streams = probe(args.video, args.ffprobe)
        videos = [s for s in streams if s['codec_type'] == 'video']
        if len(videos) != 1:
            raise ValueError('Require one video stream')
        v = videos[0]
        if any(Fraction(v[k]) != args.fps for k in ('avg_frame_rate', 'r_frame_rate')):
            raise ValueError('Source fps mismatch; 15fps repetition/stretching forbidden')
        if (v['width'], v['height']) != (args.width, args.height) or int(v['nb_read_frames']) != count:
            raise ValueError('Source dimensions/frame count mismatch')
        # Check actual presentation timestamps, not just rounded stream metadata.
        result = subprocess.run([args.ffprobe, '-v', 'error', '-select_streams', 'v:0',
                                 '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time',
                                 '-of', 'json', str(args.video)], capture_output=True, text=True, check=True)
        pts = [float(f['best_effort_timestamp_time']) for f in json.loads(result.stdout)['frames']]
        if len(pts) != count or any(abs(t-pts[0]-i/args.fps) > 2e-5 for i, t in enumerate(pts)):
            raise ValueError('Nonuniform video timestamps; no implicit resampling')
        inputs = ['-i', str(args.video)]
    else:
        if args.source_fps != args.fps:
            raise ValueError('PNG source fps mismatch; re-render at target fps')
        expected = {f'f{i:04d}.png' for i in range(count)}
        if {p.name for p in frames.glob('f*.png')} != expected:
            raise ValueError('Missing or extra source frames; no implicit repetition/truncation')
        for i in range(count):
            with Image.open(frames/f'f{i:04d}.png') as image:
                if image.size != (args.width, args.height):
                    raise ValueError(f'Wrong resolution at {i}')
                mean = float(np.asarray(image.convert('RGB').resize((90, 160)), dtype=float).mean())
                if mean < 8:
                    raise ValueError(f'Unexpected dark/empty frame {i}: {mean}')
                stats.append(dict(frame=i, mean_rgb=mean))
        inputs = ['-framerate', str(args.fps), '-start_number', '0', '-i', str(frames/'f%04d.png')]
    folder.mkdir(parents=True, exist_ok=True)
    output = folder/'kunkka_hoodwink_chase.mp4'
    if output.resolve() in [args.audio.resolve(), args.video.resolve() if args.video else None]:
        raise ValueError('Output must not overwrite an input')
    subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', *inputs,
                    '-i', str(args.audio), '-map', '0:v:0', '-map', '1:a:0',
                    '-vf', (f'settb=expr=1/{args.fps},setpts=N,'
                            f'tpad=stop_mode=add:stop={total-count}:color=black,setpts=N,'
                            f'fps={args.fps}'),
                    '-fps_mode', 'passthrough',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-ac', '2', '-b:a', '192k', '-movflags', '+faststart', str(output)], check=True)
    streams = probe(output, args.ffprobe)
    v = next(s for s in streams if s['codec_type'] == 'video')
    a = next(s for s in streams if s['codec_type'] == 'audio')
    if int(v['nb_read_frames']) != total or Fraction(v['avg_frame_rate']) != args.fps or a['channels'] != 2:
        raise ValueError('Encoded output failed frame/fps/stereo checks')
    if abs(float(a['duration'])-args.duration) > .025:
        raise ValueError('Encoded audio duration mismatch')
    if not args.skip_preview:
        # Extract the encoded result, including black tail, for manual review.
        review = folder/'encoded_review'
        review.mkdir(exist_ok=True)
        subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(output),
                        '-vf', 'fps=1,scale=270:-1', str(review/'s%03d.png')], check=True)
        paths = sorted(review.glob('s*.png'))[:math.ceil(args.duration)]
        for page, start in enumerate(range(0, len(paths), 8)):
            selected = paths[start:start+8]
            sheet = Image.new('RGB', (270*len(selected), 505))
            draw = ImageDraw.Draw(sheet)
            for col, path in enumerate(selected):
                with Image.open(path) as image:
                    sheet.paste(image.convert('RGB').resize((270, 480)), (col*270, 25))
                draw.text((col*270+6, 6), f'sample {start+col}', fill='white')
            sheet.save(folder/f'review_{page}.jpg', quality=92)
    report = dict(fps=args.fps, source_frames=count, total_frames=total,
                  black_start=args.black_start, duration=args.duration, channels=a['channels'],
                  audio=str(args.audio), frames=stats,
                  limitations=['PNG cadence is declared, not recoverable from image metadata.',
                               'Pre-duplicated or pre-retimed sources cannot be identified reliably.',
                               'No listening or artistic validation; review encoded frames separately.'])
    (folder/'frame_review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
