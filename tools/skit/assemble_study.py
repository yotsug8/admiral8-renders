"""Assemble explicit shot ranges with one fixed look; no local-script dependency.

Paths in the recipe are relative to --assets. Outputs must be a new directory.
This consumes rendered frames and a mixed WAV; it does not generate game assets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
from PIL import Image

from chase_look import ChaseLook

ROOT = Path(__file__).resolve().parents[2]


def asset(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Recipe asset must stay inside --assets')
    return path


def sources(recipe, root):
    count = recipe['picture_frames']
    result = [None] * count
    for entry in recipe['ranges']:
        first, stop = entry['start'], entry['stop']
        if not 0 <= first < stop <= count:
            raise ValueError('Invalid half-open frame range')
        for frame in range(first, stop):
            if result[frame] is not None:
                raise ValueError(f'Overlapping source ranges at {frame}')
            result[frame] = asset(root, entry['folder']) / f'f{frame:04d}.png'
    if any(p is None or not p.is_file() for p in result):
        raise ValueError('Missing source frames or uncovered range')
    return result


def decoded_qa(video, recipe):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    raw = subprocess.run([ff, '-v', 'error', '-i', str(video), '-vf', 'scale=90:160',
                          '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape((-1, 160, 90, 3))
    count = recipe['picture_frames']
    if len(frames) != round(recipe['duration'] * recipe['fps']):
        raise ValueError('Decoded frame count mismatch')
    minimum = float(frames[:count].mean(axis=(1, 2, 3)).min())
    tail = int(frames[count:].max())
    if minimum <= 8 or tail != 0:
        raise ValueError('Unexpected dark picture or nonblack end pause')
    motion = []
    for first, stop in recipe.get('moving_ranges', []):
        if not 0 <= first < stop - 1 <= count - 1:
            raise ValueError('Invalid motion-check interval')
        diff = np.abs(frames[first+1:stop].astype(np.int16) -
                      frames[first:stop-1].astype(np.int16)).mean(axis=(1, 2, 3))
        if diff.min() <= 0:
            raise ValueError('Repeated frame within a moving shot')
        motion.append(float(diff.min()))
    raw = subprocess.run([ff, '-v', 'error', '-i', str(video), '-vn', '-ac', '2',
                          '-ar', '48000', '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.float32).reshape((-1, 2))
    start, stop = recipe['silent_check']
    pause = audio[round(start*48000):round(stop*48000)]
    if len(pause) != round(stop*48000)-round(start*48000) or abs(pause).max() >= 1e-5:
        raise ValueError('End pause is missing or contains sound')
    return dict(frames=len(frames), picture_min_mean=minimum, black_tail_max=tail,
                motion_min_differences=motion, silent_peak=float(abs(pause).max()),
                video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                limitations='No listening or artistic approval; inspect review sheets separately.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    root = args.assets.resolve()
    paths = sources(recipe, root)
    audio = asset(root, recipe['audio'])
    if not audio.is_file():
        raise ValueError('Missing explicit WAV')
    fps, count = recipe['fps'], recipe['picture_frames']
    if fps <= 0 or count <= 0 or not count < recipe['duration']*fps:
        raise ValueError('Invalid picture duration or black tail')
    if any(not 0 <= f < count for f in recipe['look_samples']):
        raise ValueError('Look sample outside pictures')
    for path in paths:
        with Image.open(path) as im:
            im.verify()
    if args.validate_only:
        print(f'Validated {count} source images and explicit WAV path; no render or assembly.')
        return
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Use a new output directory to avoid stale or overwritten results')
    out.mkdir(parents=True)
    frames = out / 'frames'
    frames.mkdir()
    samples = []
    for f in recipe['look_samples']:
        with Image.open(paths[f]) as im:
            samples.append(np.asarray(im.convert('RGB').resize((270, 480))))
    look = ChaseLook(np.stack(samples))
    hashes = []
    for frame, path in enumerate(paths):
        hashes.append(dict(frame=frame, source=path.relative_to(root).as_posix(),
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        with Image.open(path) as im:
            rgb = np.asarray(im.convert('RGB').resize(tuple(recipe['size']), Image.Resampling.LANCZOS))
        Image.fromarray(look(rgb)).save(frames / f'f{frame:04d}.png')
    subprocess.run([sys.executable, str(ROOT/'tools/blender/finish_chase.py'),
                    '--folder', str(out), '--frames', str(frames), '--audio', str(audio),
                    '--width', str(recipe['size'][0]), '--height', str(recipe['size'][1]),
                    '--frame-count', str(count), '--fps', str(fps), '--source-fps', str(fps),
                    '--black-start', str(count/fps), '--duration', str(recipe['duration'])], check=True)
    report = decoded_qa(out/'kunkka_hoodwink_chase.mp4', recipe)
    report['recipe'] = recipe
    report['source_frames'] = hashes
    report['audio_sha256'] = hashlib.sha256(audio.read_bytes()).hexdigest()
    (out/'assembly_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('recipe', 'source_frames')}))


if __name__ == '__main__':
    main()
