"""Measure encoded picture levels and export representative review frames.

Metrics flag areas for inspection, not artistic quality or proof of clipping.
Intentional black tails are excluded by the explicit picture-frame count.
"""
import argparse
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw
from fractions import Fraction
from grade import video_timing


def levels(rgb):
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or rgb.dtype != np.uint8:
        raise ValueError('Expected uint8 RGB image')
    luma = rgb.astype(float) @ np.array([.2126, .7152, .0722])
    return dict(mean=float(luma.mean()), p05=float(np.percentile(luma, 5)),
                p95=float(np.percentile(luma, 95)),
                dark_fraction=float((luma <= 8).mean()),
                bright_fraction=float((luma >= 247).mean()),
                channel_limit_fraction=float((rgb >= 254).any(axis=2).mean()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    count, fps = recipe['picture_frames'], recipe['fps']
    if count <= 0 or fps <= 0:
        raise ValueError('Positive frame count and fps required')
    timing = video_timing(args.video)
    if timing['fps'] != Fraction(str(fps)) or count > timing['count']:
        raise ValueError('Recipe FPS/picture count differs from encoded video')
    args.out.mkdir(parents=True, exist_ok=False)
    width, height = recipe['size']
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(args.video),
           '-frames:v', str(count), '-vf', f'scale={width}:{height}', '-an',
           '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    if len(raw) != count * width * height * 3:
        raise ValueError('Missing decoded picture frames')
    frames = np.frombuffer(raw, np.uint8).reshape(count, height, width, 3)
    rows = [dict(frame=i, **levels(frame)) for i, frame in enumerate(frames)]
    boundaries = sorted({r['start'] for r in recipe['ranges'] if r['start'] > 0})
    if any(not 0 < f < count for f in boundaries):
        raise ValueError('Cut outside picture range')
    selected = set(range(0, count, max(1, round(fps)))) | {count-1}
    for key in ('dark_fraction', 'bright_fraction', 'channel_limit_fraction'):
        selected.add(max(rows, key=lambda row: row[key])['frame'])
    selected.update(f for cut in boundaries for f in (cut-1, cut))
    ids = sorted(selected)
    thumb_w = 180
    thumb_h = round(height * thumb_w / width)
    sheet = Image.new('RGB', (thumb_w*4, (thumb_h+20)*((len(ids)+3)//4)), '#202020')
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(ids):
        x, y = i % 4 * thumb_w, i // 4 * (thumb_h+20)
        sheet.paste(Image.fromarray(frames[f]).resize((thumb_w, thumb_h)), (x, y+20))
        draw.text((x+2, y+2), f'{f} / {f/fps:.2f}s', fill='white')
    sheet.save(args.out/'review.jpg', quality=92)
    cuts = [dict(frame=f, mean_change=rows[f]['mean']-rows[f-1]['mean']) for f in boundaries]
    report = dict(frames=rows, cuts=cuts, selected=ids,
                  limits='Display-encoded luma, not scene-linear exposure. Bright/saturated '
                         'pixels may be intentional. Cuts change content; differences are '
                         'not exposure errors by themselves. No artistic pass is inferred.')
    (args.out/'levels.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(picture_frames=count, review_frames=len(ids), cuts=cuts)))


if __name__ == '__main__':
    main()
